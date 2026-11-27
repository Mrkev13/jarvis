"""MRK-155: Jarvis na PC – párování, token zařízení (scope jen /device/agent/*), heartbeat, fronta příkazů s krátkou
platností, výsledek, odvolání a audit. Žádný reálný Groq ani síť."""
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("GROQ_API_KEY", "x")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import bcrypt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import auth_service  # noqa: E402
import database  # noqa: E402
import main  # noqa: E402
import module_registry as mr  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, Device, DeviceCommand, DevicePairingCode, DomainEvent  # noqa: E402
from modules.computer import router as computer_router  # noqa: E402
from modules.computer import service  # noqa: E402

NOW = datetime(2026, 11, 27, 18, 0)
MODULE_ENV = [m.env_name for m in mr.MODULES]
APPS = [{"id": "wot", "name": "World of Tanks"}, {"id": "discord", "name": "Discord"}]


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine, autocommit=False, autoflush=False)


class DeviceServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.engine, Session = _session()
        self.db = Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _paired(self, now=NOW):
        code = service.create_pairing_code(self.db, now)["code"]
        device, token = service.pair(self.db, code, "Herní PC", "windows", "0.1.0", now)
        service.heartbeat(self.db, device, {"cpu_percent": 12}, APPS, now=now)
        self.db.commit()
        return device, token

    def test_pairing_code_is_hashed_single_use_and_expires(self):
        out = service.create_pairing_code(self.db, NOW)
        code = out["code"]
        self.assertRegex(code, r"^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")
        row = self.db.query(DevicePairingCode).one()
        self.assertNotIn(service.normalize_code(code), row.code_hash, "v DB jen hash")
        # expirace
        with self.assertRaises(service.DeviceError) as ctx:
            service.pair(self.db, code, "PC", now=NOW + service.PAIRING_TTL)
        self.assertEqual(ctx.exception.status, 401)
        # platný – i s malými písmeny a bez pomlčky
        device, token = service.pair(self.db, code.replace("-", "").lower(), "PC", now=NOW + timedelta(minutes=1))
        self.assertEqual(service.authenticate(self.db, token).id, device.id)
        self.assertNotEqual(device.token_hash, token)
        # podruhé ne
        with self.assertRaises(service.DeviceError):
            service.pair(self.db, code, "PC 2", now=NOW + timedelta(minutes=2))

    def test_new_code_invalidates_previous(self):
        first = service.create_pairing_code(self.db, NOW)["code"]
        second = service.create_pairing_code(self.db, NOW + timedelta(seconds=5))["code"]
        with self.assertRaises(service.DeviceError):
            service.pair(self.db, first, "PC", now=NOW + timedelta(seconds=10))
        self.assertIsNotNone(service.pair(self.db, second, "PC", now=NOW + timedelta(seconds=10))[0].id)

    def test_device_limit(self):
        for _ in range(service.MAX_ACTIVE_DEVICES):
            self._paired()
        with self.assertRaises(service.DeviceError) as ctx:
            service.create_pairing_code(self.db, NOW)
        self.assertEqual(ctx.exception.status, 409)

    def test_heartbeat_keeps_only_known_fields(self):
        device, _ = self._paired()
        service.heartbeat(self.db, device, {
            "cpu_percent": 250, "ram_percent": "41.26", "uptime_minutes": 95,
            "disks": [{"name": "C:", "free_gb": 120.55, "total_gb": 476}, {"name": "", "free_gb": 1, "total_gb": 2}, "x"],
            "running": ["wot", "notepad"], "secret": "nope",
        }, APPS + [{"id": "Bad Id!", "name": "x"}, {"id": "wot", "name": "dup"}, {"id": "steam"}], now=NOW)
        self.assertEqual(device.status, {"cpu_percent": None, "ram_percent": 41.3, "uptime_minutes": 95,
                                         "disks": [{"name": "C:", "free_gb": 120.5, "total_gb": 476.0}],
                                         "running": ["wot"]})
        self.assertEqual(device.apps, APPS)
        self.assertEqual(self.db.query(ActivityLog).filter_by(action_type="heartbeat").count(), 0, "telemetrie bez Aktivity")

    def test_command_lifecycle_and_audit(self):
        device, _ = self._paired()
        cmd = service.create_command(self.db, device.id, "launch_app", {"app_id": "WOT"}, now=NOW)
        self.assertEqual((cmd.status, cmd.payload), ("queued", {"app_id": "wot", "app_name": "World of Tanks"}))
        taken = service.take_commands(self.db, device, NOW + timedelta(seconds=5))
        self.assertEqual([c["id"] for c in taken], [cmd.id])
        self.assertEqual(service.take_commands(self.db, device, NOW + timedelta(seconds=6)), [], "jen jednou")
        service.complete_command(self.db, device, cmd.id, True, None, NOW + timedelta(seconds=8))
        self.db.commit()
        self.assertEqual(cmd.status, "succeeded")
        with self.assertRaises(service.DeviceError) as ctx:
            service.complete_command(self.db, device, cmd.id, False, "x", NOW + timedelta(seconds=9))
        self.assertEqual(ctx.exception.status, 409)
        actions = [a.action_type for a in self.db.query(ActivityLog).filter_by(area="computer").order_by(ActivityLog.id)]
        self.assertEqual(actions, ["pairing_code", "device_paired", "command_queued", "command_done"])
        types = [e.event_type for e in self.db.query(DomainEvent).order_by(DomainEvent.id)]
        self.assertEqual(types, ["computer.device.paired", "computer.command.completed"])
        done = self.db.query(ActivityLog).filter_by(action_type="command_done").one()
        self.assertEqual(done.summary, "Počítač „Herní PC“: spustit World of Tanks – hotovo")

    def test_command_validation(self):
        device, _ = self._paired()
        bad = [("launch_app", {"app_id": "steam"}), ("launch_app", {}), ("power", {"action": "format"}),
               ("power", {"action": "shutdown", "delay_seconds": service.MAX_DELAY_SECONDS + 1}),
               ("power", {"action": "shutdown", "delay_seconds": "x"}), ("shell", {"cmd": "rm -rf /"})]
        for kind, payload in bad:
            with self.assertRaises(service.DeviceError, msg=(kind, payload)) as ctx:
                service.create_command(self.db, device.id, kind, payload, now=NOW)
            self.assertEqual(ctx.exception.status, 422)
        cmd = service.create_command(self.db, device.id, "power", {"action": "shutdown", "delay_seconds": 3600, "extra": 1}, now=NOW)
        self.assertEqual(cmd.payload, {"action": "shutdown", "delay_seconds": 3600}, "jen povolená pole")
        self.assertEqual(service.command_label(cmd.kind, cmd.payload, device), "vypnout za 60 min")

    def test_offline_device_gets_no_command(self):
        device, _ = self._paired()
        with self.assertRaises(service.DeviceError) as ctx:
            service.create_command(self.db, device.id, "power", {"action": "lock"},
                                   now=NOW + service.ONLINE_WINDOW + timedelta(seconds=1))
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(self.db.query(DeviceCommand).count(), 0)

    def test_command_expires_and_is_never_delivered_late(self):
        device, _ = self._paired()
        cmd = service.create_command(self.db, device.id, "power", {"action": "shutdown"}, now=NOW)
        later = NOW + service.COMMAND_TTL + timedelta(seconds=1)
        self.assertEqual(service.take_commands(self.db, device, later), [])
        self.assertEqual(cmd.status, "expired")
        self.assertEqual(cmd.result_message, "PC příkaz nevyzvedlo včas.")
        self.assertEqual(self.db.query(DomainEvent).filter_by(event_type="computer.command.expired").count(), 1)

    def test_delivered_without_result_expires(self):
        device, _ = self._paired()
        cmd = service.create_command(self.db, device.id, "power", {"action": "sleep"}, now=NOW)
        service.take_commands(self.db, device, NOW)
        self.assertEqual(service.expire_stale(self.db, NOW + service.DELIVERED_TIMEOUT - timedelta(seconds=1)), 0)
        self.assertEqual(service.expire_stale(self.db, NOW + service.DELIVERED_TIMEOUT), 1)
        self.assertEqual((cmd.status, cmd.result_message), ("expired", "PC nepotvrdilo provedení."))

    def test_revoke_invalidates_token_and_pending_commands(self):
        device, token = self._paired()
        cmd = service.create_command(self.db, device.id, "power", {"action": "lock"}, now=NOW)
        service.revoke(self.db, device.id, NOW + timedelta(seconds=3))
        self.db.commit()
        self.assertIsNone(service.authenticate(self.db, token))
        self.assertEqual(cmd.status, "expired")
        self.assertEqual(service.list_devices(self.db, NOW), [])
        self.assertIsNotNone(self.db.get(Device, device.id), "řádek zůstává kvůli historii")
        with self.assertRaises(service.DeviceError):
            service.revoke(self.db, device.id)

    def test_other_device_cannot_report_result(self):
        a, _ = self._paired()
        b, _ = self._paired()
        cmd = service.create_command(self.db, a.id, "power", {"action": "lock"}, now=NOW)
        service.take_commands(self.db, a, NOW)
        with self.assertRaises(service.DeviceError) as ctx:
            service.complete_command(self.db, b, cmd.id, True, now=NOW)
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(service.take_commands(self.db, b, NOW), [], "cizí příkazy nevidí")


class DeviceApiTestCase(unittest.TestCase):
    PIN = "4821"

    def setUp(self):
        self.engine, self.Session = _session()
        self._orig = (auth_service.SessionLocal, main.SessionLocal, database.SessionLocal, auth_service.AUTH_PIN_HASH,
                      auth_service._failed_attempts)
        auth_service.SessionLocal = main.SessionLocal = database.SessionLocal = self.Session
        auth_service.AUTH_PIN_HASH = bcrypt.hashpw(self.PIN.encode(), bcrypt.gensalt(rounds=4)).decode()
        auth_service._failed_attempts = {}
        computer_router._pair_failures.clear()
        self._env = patch.dict(os.environ, {k: v for k, v in os.environ.items() if k not in MODULE_ENV}, clear=True)
        self._env.start()
        mr.invalidate_cache()
        self._db_patch = patch.object(mr, "SessionLocal", self.Session)
        self._db_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self._db_patch.stop()
        self._env.stop()
        mr.invalidate_cache()
        (auth_service.SessionLocal, main.SessionLocal, database.SessionLocal, auth_service.AUTH_PIN_HASH,
         auth_service._failed_attempts) = self._orig
        computer_router._pair_failures.clear()
        self.engine.dispose()

    def _login(self):
        r = self.client.post("/auth/login", json={"pin": self.PIN})
        self.assertEqual(r.status_code, 200)

    def _pair(self):
        self._login()
        code = self.client.post("/devices/pairing-code").json()["code"]
        anon = TestClient(main.app)  # agent nemá session cookie
        r = anon.post("/device/agent/pair", json={"code": code, "name": "Herní PC", "agent_version": "0.1.0"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        return anon, body["device_id"], {"Authorization": f"Bearer {body['token']}"}

    def test_user_endpoints_need_session(self):
        self.assertEqual(self.client.get("/devices").status_code, 401)
        self.assertEqual(self.client.post("/devices/pairing-code").status_code, 401)

    def test_agent_flow_end_to_end(self):
        agent, device_id, auth = self._pair()
        hb = agent.post("/device/agent/heartbeat", headers=auth, json={"status": {"cpu_percent": 30}, "apps": APPS})
        self.assertEqual(hb.status_code, 200, hb.text)
        devices = self.client.get("/devices").json()["devices"]
        self.assertEqual([(d["name"], d["online"], [a["id"] for a in d["apps"]]) for d in devices],
                         [("Herní PC", True, ["wot", "discord"])])
        self.assertNotIn("token_hash", devices[0])
        r = self.client.post(f"/devices/{device_id}/commands", json={"kind": "launch_app", "payload": {"app_id": "wot"}})
        self.assertEqual(r.status_code, 200, r.text)
        cmds = agent.get("/device/agent/commands", headers=auth).json()["commands"]
        self.assertEqual([(c["kind"], c["payload"]["app_id"]) for c in cmds], [("launch_app", "wot")])
        res = agent.post(f"/device/agent/commands/{cmds[0]['id']}/result", headers=auth, json={"ok": False, "message": "Nenalezeno"})
        self.assertEqual(res.json()["status"], "failed")
        history = self.client.get(f"/devices/{device_id}/commands").json()["commands"]
        self.assertEqual((history[0]["status"], history[0]["result_message"]), ("failed", "Nenalezeno"))
        self.assertEqual(self.client.post(f"/devices/{device_id}/commands", json={"kind": "shell", "payload": {}}).status_code, 422)

    def test_token_scope(self):
        agent, device_id, auth = self._pair()
        # token zařízení neotevře ostatní API
        for path in ("/devices", "/habits", "/activity", "/dashboard"):
            self.assertEqual(agent.get(path, headers=auth).status_code, 401, path)
        # session cookie nestačí na endpointy agenta
        self.assertEqual(self.client.get("/device/agent/commands").status_code, 401)
        self.assertEqual(self.client.post("/device/agent/heartbeat", json={}).status_code, 401)
        # bez tokenu / se špatným tokenem
        self.assertEqual(agent.get("/device/agent/commands").status_code, 401)
        self.assertEqual(agent.get("/device/agent/commands", headers={"Authorization": "Bearer nope"}).status_code, 401)
        self.assertEqual(agent.get("/device/agent/commands", headers=auth).status_code, 200)

    def test_long_poll_waits_then_returns_empty(self):
        agent, _device_id, auth = self._pair()
        import time
        start = time.monotonic()
        r = agent.get("/device/agent/commands?wait=1", headers=auth)
        self.assertEqual(r.json(), {"commands": []})
        self.assertGreaterEqual(time.monotonic() - start, 0.9)
        self.assertLess(time.monotonic() - start, 5)

    def test_revoke_takes_effect_immediately(self):
        agent, device_id, auth = self._pair()
        self.assertTrue(self.client.post(f"/devices/{device_id}/revoke").json()["revoked"])
        self.assertEqual(agent.post("/device/agent/heartbeat", headers=auth, json={}).status_code, 401)
        self.assertEqual(self.client.get("/devices").json()["devices"], [])

    def test_pairing_rate_limit(self):
        anon = TestClient(main.app)
        for _ in range(computer_router.PAIR_FAILURES_MAX):
            self.assertEqual(anon.post("/device/agent/pair", json={"code": "AAAA-BBBB"}).status_code, 401)
        self.assertEqual(anon.post("/device/agent/pair", json={"code": "AAAA-BBBB"}).status_code, 429)

    def test_module_off_hides_both_surfaces(self):
        agent, _device_id, auth = self._pair()
        self.assertEqual(self.client.put("/modules/computer", json={"enabled": False}).status_code, 200)
        self.assertEqual(self.client.get("/devices").status_code, 404)
        self.assertEqual(agent.get("/device/agent/commands", headers=auth).status_code, 404)

    def test_agent_prefix_matches_router(self):
        self.assertEqual(main.DEVICE_AGENT_PREFIX, computer_router.AGENT_PREFIX + "/")
        agent_paths = [r.path for r in main.app.routes if getattr(r, "path", "").startswith("/device/")]
        self.assertTrue(agent_paths)
        self.assertTrue(all(p.startswith(main.DEVICE_AGENT_PREFIX) for p in agent_paths), agent_paths)
        # require_auth tuhle cestu propouští → každý endpoint agenta kromě párování musí chtít token zařízení
        for route in main.app.routes:
            path = getattr(route, "path", "")
            if path.startswith(main.DEVICE_AGENT_PREFIX) and path != "/device/agent/pair":
                deps = {d.call for d in route.dependant.dependencies}
                self.assertIn(computer_router.require_device, deps, path)


if __name__ == "__main__":
    unittest.main()
