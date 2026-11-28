"""MRK-157: Jarvis na PC – AI tooly (stav, návrh příkazu, zrušení časovače) přes pending akce, routing a kontext.
Fake LLM (bez Groq), bez sítě."""
import json
import os
import sys
import types
import unittest
from datetime import timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import ai  # noqa: E402
import tool_registry as reg  # noqa: E402
import tools  # noqa: E402
from context_service import classify_areas  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, DeviceCommand  # noqa: E402
from module_contracts import ContextRequest  # noqa: E402
from modules.computer import ai_actions, integrations, service  # noqa: E402
from mutation_service import MutationRefused, StaleTarget  # noqa: E402
from time_utils import utc_now  # noqa: E402
from tool_router import route_tools  # noqa: E402

APPS = [{"id": "wot", "name": "World of Tanks"}, {"id": "wgc", "name": "Wargaming Game Center"},
        {"id": "wows", "name": "World of Warships"}, {"id": "discord", "name": "Discord"}]
WRITES = {s.name for s in reg.WRITE_SPECS}


def _message(content=None, tool_calls=None):
    msg = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None)


def _call(name, args):
    return types.SimpleNamespace(id="c1", function=types.SimpleNamespace(name=name, arguments=json.dumps(args)))


class ComputerAiTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.script, self.calls = [], []

        def fake_llm(api_messages, **kwargs):
            self.calls.append({"messages": [dict(m) for m in api_messages], **kwargs})
            return self.script.pop(0)

        self._patches = [
            patch.object(ai, "SessionLocal", self.Session),
            patch.object(tools, "SessionLocal", self.Session),
            patch.object(ai_actions, "SessionLocal", self.Session),
            patch.object(ai, "_llm_create_with_retry", fake_llm),
            patch.object(ai, "_build_context_safely", lambda db, message: None),
        ]
        for p in self._patches:
            p.start()
        self.device_id = self._pair("Herní PC")

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def q(self, fn):
        db = self.Session()
        try:
            out = fn(db)
            db.commit()
            return out
        finally:
            db.close()

    def _pair(self, name, apps=APPS, seen=None):
        def go(db):
            now = utc_now()
            code = service.create_pairing_code(db, now)["code"]
            device, _ = service.pair(db, code, name, now=now)
            service.heartbeat(db, device, {"cpu_percent": 12, "running": ["wot"]}, apps, now=seen or now)
            return device.id
        return self.q(go)

    def commands(self):
        return self.q(lambda db: [(c.kind, c.payload, c.user_context) for c in db.query(DeviceCommand).order_by(DeviceCommand.id)])

    def ask(self, text, tool, args, answer="Připraveno."):
        self.script = [_message(tool_calls=[_call(tool, args)]), _message(content=answer)]
        result = ai.ask_ai([{"role": "user", "content": text}])
        self.assertEqual(self.script, [])
        return result

    # ---- návrh ----
    def test_launch_by_name_or_id(self):
        for app in ("wot", "World of Tanks", "world of tanks", "tanks"):
            plan = self.q(lambda db: ai_actions.propose_control_computer(db, "launch_app", app=app))
            self.assertEqual(plan["command"], {"kind": "launch_app", "payload": {"app_id": "wot"}}, app)
        self.assertEqual(plan["preview"]["items"][0]["label"], "Spustit World of Tanks")

    def test_launch_unknown_or_ambiguous_is_refused(self):
        with self.assertRaises(MutationRefused) as ctx:
            self.q(lambda db: ai_actions.propose_control_computer(db, "launch_app", app="Photoshop"))
        self.assertEqual(ctx.exception.code, "not_found")
        self.assertEqual({c["name"] for c in ctx.exception.candidates}, {a["name"] for a in APPS})
        with self.assertRaises(MutationRefused) as ctx:
            self.q(lambda db: ai_actions.propose_control_computer(db, "launch_app", app="World of"))
        self.assertEqual(ctx.exception.code, "ambiguous_target")
        with self.assertRaises(MutationRefused):
            self.q(lambda db: ai_actions.propose_control_computer(db, "launch_app"))
        with self.assertRaises(MutationRefused):
            self.q(lambda db: ai_actions.propose_control_computer(db, "format_disk"))

    def test_power_with_delay(self):
        plan = self.q(lambda db: ai_actions.propose_control_computer(db, "shutdown", delay_minutes=60))
        self.assertEqual(plan["command"], {"kind": "power", "payload": {"action": "shutdown", "delay_seconds": 3600}})
        self.assertEqual(plan["preview"]["items"][0]["label"], "Vypnout za 60 min")
        self.assertTrue(plan["preview"]["warnings"], "vypnutí varuje před ztrátou neuložené práce")
        for bad in (241, -1, "x"):
            with self.assertRaises(MutationRefused, msg=bad):
                self.q(lambda db: ai_actions.propose_control_computer(db, "sleep", delay_minutes=bad))

    def test_offline_or_missing_pc_is_refused(self):
        self.q(lambda db: service.revoke(db, self.device_id))
        with self.assertRaises(MutationRefused) as ctx:
            self.q(lambda db: ai_actions.propose_control_computer(db, "lock"))
        self.assertIn("Žádný počítač", ctx.exception.detail)
        self._pair("Starý PC", seen=utc_now() - timedelta(minutes=10))
        with self.assertRaises(MutationRefused) as ctx:
            self.q(lambda db: ai_actions.propose_control_computer(db, "lock"))
        self.assertIn("není online", ctx.exception.detail)

    def test_two_pcs_need_a_name(self):
        self._pair("Notebook")
        with self.assertRaises(MutationRefused) as ctx:
            self.q(lambda db: ai_actions.propose_control_computer(db, "lock"))
        self.assertEqual(ctx.exception.code, "ambiguous_target")
        plan = self.q(lambda db: ai_actions.propose_control_computer(db, "lock", device="notebook"))
        self.assertEqual(plan["device_name"], "Notebook")

    # ---- potvrzení ----
    def test_chat_proposes_then_confirm_queues_command(self):
        result = self.ask("pusť na PC WoT", "manage_computer", {"action": "launch_app", "app": "WoT"})
        [pending] = result["pending_actions"]
        self.assertEqual(pending["preview"]["title"], "Počítač „Herní PC“")
        self.assertEqual(self.commands(), [], "nic se nespustí před potvrzením")
        offered = {t["function"]["name"] for t in self.calls[0]["tools"]} & WRITES
        self.assertEqual(offered, {"manage_computer"})
        outcome = ai.execute_confirm_action(pending["id"])
        self.assertTrue(outcome["ok"], outcome)
        self.assertEqual(self.commands(), [("launch_app", {"app_id": "wot", "app_name": "World of Tanks"}, "ai_confirm")])
        self.assertFalse(ai.execute_confirm_action(pending["id"])["ok"], "podruhé ne")
        self.assertEqual(len(self.commands()), 1)
        audit = self.q(lambda db: [a.user_context for a in db.query(ActivityLog).filter_by(area="computer", action_type="command_queued")])
        self.assertEqual(audit, ["ai_confirm"])

    def test_confirm_when_pc_went_offline_fails_without_command(self):
        result = self.ask("vypni počítač za hodinu", "manage_computer", {"action": "shutdown", "delay_minutes": 60})

        def offline(db):
            d = service.get_device(db, self.device_id)
            d.last_seen_at = utc_now() - timedelta(minutes=5)
        self.q(offline)
        outcome = ai.execute_confirm_action(result["pending_actions"][0]["id"])
        self.assertFalse(outcome["ok"])
        self.assertEqual(self.commands(), [])

    def test_executor_maps_device_errors_to_stale(self):
        plan = self.q(lambda db: ai_actions.propose_control_computer(db, "launch_app", app="discord"))

        def drop_app(db):
            d = service.get_device(db, self.device_id)
            d.apps = [a for a in APPS if a["id"] != "discord"]
        self.q(drop_app)
        with self.assertRaises(StaleTarget):
            ai_actions.execute_computer_command(plan)
        self.assertEqual(self.commands(), [])

    def test_cancel_timer(self):
        result = self.ask("zruš vypnutí počítače", "manage_computer", {"action": "cancel_timer"})
        ai.execute_confirm_action(result["pending_actions"][0]["id"])
        self.assertEqual(self.commands(), [("power_cancel", {}, "ai_confirm")])

    # ---- čtení, routing, kontext ----
    def test_status_tool(self):
        out = self.q(ai_actions.query_computer_status)
        [d] = out["devices"]
        self.assertEqual((d["name"], d["online"], d["running"]), ("Herní PC", True, ["World of Tanks"]))
        self.assertIn("Discord", d["apps"])
        self.assertNotIn("token", json.dumps(out))

    def test_routing(self):
        cases = {
            "pusť WoT": {"manage_computer"},
            "vypni počítač za hodinu": {"manage_computer"},
            "zamkni pc": {"manage_computer"},
            "uspi notebook": {"manage_computer"},
            "zruš vypnutí počítače": {"manage_computer"},
            "připomeň mi za hodinu vypnout pc": {"add_reminder"},
        }
        for text, expected in cases.items():
            self.assertEqual(set(route_tools([text]).names) & WRITES, expected, text)
        self.assertIn("add_work_session", route_tools(["zapiš 2 hodiny práce na počítači"]).names)
        status = route_tools(["je PC zapnutý?"])
        self.assertIn("computer", status.areas, "stav PC jde do CURRENT STATE")
        self.assertFalse(set(status.names) & WRITES, "otázka nic nezapisuje")
        self.assertNotIn("computer", classify_areas("kolik mám kreditů ve WoT?"))

    def test_context_lines(self):
        lines = self.q(lambda db: integrations.context_computer(ContextRequest(db=db, today=None, local_now=None)))
        self.assertEqual(len(lines), 1)
        self.assertIn("Počítač „Herní PC“: online", lines[0])
        self.assertIn("běží World of Tanks", lines[0])


if __name__ == "__main__":
    unittest.main()
