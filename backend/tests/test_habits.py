"""MRK-21: Návyky – model, stavy (done / skipped / odvozené missed), historie, REST, feature flag a příspěvky
do vyhledávání, Dnes, GET /dashboard a AI kontextu přes rámec modulů. Žádný reálný Groq."""
import json
import os
import sys
import unittest
from datetime import date, datetime, timedelta
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
import search_service as ss  # noqa: E402
import today_service as ts  # noqa: E402
from context_service import build_current_context  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, Habit, HabitEntry  # noqa: E402
from module_registry import ModuleAccess  # noqa: E402
from modules.habits import service  # noqa: E402

TODAY = date(2026, 10, 7)
NOW_UTC = datetime(2026, 10, 7, 8, 0)  # 10:00 Praha
CREATED = datetime(2026, 10, 3, 8, 0)  # založeno 3. 10.
MODULE_ENV = [m.env_name for m in mr.MODULES]


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine, autocommit=False, autoflush=False)


class HabitServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.engine, Session = _session()
        self.db = Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _habit(self, name="Rehab", **kw):
        h = service.create_habit(self.db, name, **kw)
        h.created_at = CREATED
        self.db.commit()
        return h

    def test_create_and_validation(self):
        h = self._habit("  Pitný   režim ", kind="count", target_value="2", unit="l")
        self.assertEqual((h.name, h.kind, h.target_value, h.unit, h.active), ("Pitný režim", "count", 2.0, "l", True))
        self.assertEqual(service.target_label(h), "2 l")
        for bad in [dict(name=""), dict(name="x" * 200), dict(name="A", kind="streak"), dict(name="A", target_value="x"),
                    dict(name="A", target_value=-1)]:
            with self.subTest(bad=bad), self.assertRaises(service.HabitError):
                service.create_habit(self.db, **bad)
        log = self.db.query(ActivityLog).filter_by(area="habits", action_type="create").one()
        self.assertEqual(log.entity_type, "habit")

    def test_done_skipped_and_inferred_missed(self):
        h = self._habit()
        service.set_entry(self.db, h.id, "done", day=TODAY - timedelta(days=2), today=TODAY)
        service.set_entry(self.db, h.id, "skipped", day=TODAY - timedelta(days=1), today=TODAY)
        self.db.commit()
        item = service.list_habits(self.db, TODAY)["active"][0]
        states = {d["date"]: d["state"] for d in item["history"]}
        self.assertEqual(states["2026-10-01"], None, "před založením se nic nečeká")
        self.assertEqual(states["2026-10-03"], "missed", "minulý den bez záznamu = vynecháno (odvozené)")
        self.assertEqual(states["2026-10-04"], "missed")
        self.assertEqual(states["2026-10-05"], "done")
        self.assertEqual(states["2026-10-06"], "skipped")
        self.assertEqual(states["2026-10-07"], "open", "dnešek bez záznamu ještě čeká")
        self.assertEqual(self.db.query(HabitEntry).count(), 2, "missed se neukládá")
        s = service.summary(self.db, TODAY)
        self.assertEqual((s["total"], s["done"], s["open"]), (1, 0, 1))
        self.assertEqual((s["week_done"], s["week_expected"]), (1, 3), "3. a 4. vynecháno, 5. splněno; přeskočení se nepočítá")

    def test_write_rules(self):
        h = self._habit()
        with self.assertRaises(service.HabitError):
            service.set_entry(self.db, h.id, "missed", today=TODAY)  # missed se nezapisuje ručně
        with self.assertRaises(service.HabitError):
            service.set_entry(self.db, h.id, "done", day=TODAY + timedelta(days=1), today=TODAY)
        with self.assertRaises(service.HabitError):
            service.set_entry(self.db, h.id, "done", day=date(2026, 10, 1), today=TODAY)
        with self.assertRaises(service.HabitError) as ctx:
            service.set_entry(self.db, 999, "done", today=TODAY)
        self.assertEqual(ctx.exception.status, 404)
        with self.assertRaises(service.HabitError):
            service.set_entry(self.db, h.id, "done", value="nic", today=TODAY)

    def test_history_preserved_and_changes_are_traced(self):
        h = self._habit("Čtení", kind="duration", target_value=20, unit="min")
        service.set_entry(self.db, h.id, "done", day=TODAY - timedelta(days=1), duration_minutes=25, today=TODAY)
        service.set_entry(self.db, h.id, "done", day=TODAY, duration_minutes=10, today=TODAY)
        self.db.commit()
        # změna dnešního stavu nezmění včerejšek a zanechá stopu v Aktivitě
        service.set_entry(self.db, h.id, "skipped", day=TODAY, note="nemoc", today=TODAY)
        self.db.commit()
        rows = {e.date: e for e in self.db.query(HabitEntry).all()}
        self.assertEqual((rows[TODAY - timedelta(days=1)].state, rows[TODAY - timedelta(days=1)].duration_minutes), ("done", 25))
        self.assertEqual((rows[TODAY].state, rows[TODAY].note), ("skipped", "nemoc"))
        change = self.db.query(ActivityLog).filter_by(area="habits", action_type="update").one()
        self.assertEqual(json.loads(change.delta_json)["state"], {"old": "done", "new": "skipped"})
        # stejný stav znovu = žádný nový záznam v Aktivitě
        before = self.db.query(ActivityLog).count()
        service.set_entry(self.db, h.id, "skipped", day=TODAY, note="nemoc", today=TODAY)
        self.assertEqual(self.db.query(ActivityLog).count(), before)

    def test_archive_keeps_entries_and_restore_returns_them(self):
        h = self._habit()
        service.set_entry(self.db, h.id, "done", day=TODAY - timedelta(days=1), today=TODAY)
        service.set_active(self.db, h.id, False)
        self.db.commit()
        self.assertEqual(self.db.query(HabitEntry).count(), 1)
        data = service.list_habits(self.db, TODAY)
        self.assertEqual((data["active"], [a["id"] for a in data["archived"]]), ([], [h.id]))
        self.assertIsNotNone(data["archived"][0]["archived_at"])
        self.assertEqual(service.summary(self.db, TODAY)["total"], 0)
        with self.assertRaises(service.HabitError) as ctx:
            service.set_entry(self.db, h.id, "done", today=TODAY)
        self.assertEqual(ctx.exception.status, 409)
        service.set_active(self.db, h.id, True)
        self.db.commit()
        hist = {d["date"]: d["state"] for d in service.list_habits(self.db, TODAY)["active"][0]["history"]}
        self.assertEqual(hist["2026-10-06"], "done", "historie se vrátila s návykem")

    def test_archived_days_are_never_inferred_as_missed(self):
        h = self._habit()  # založeno 3. 10.; 3. 10. splněno, 4. 10. archivováno, 7. 10. obnoveno
        service.set_entry(self.db, h.id, "done", day=date(2026, 10, 3), today=TODAY)
        with patch.object(service, "utc_now", return_value=datetime(2026, 10, 4, 8, 0)):
            service.set_active(self.db, h.id, False)
        self.db.commit()
        archived = {d["date"]: d["state"] for d in service.list_habits(self.db, TODAY)["archived"][0]["history"]}
        self.assertEqual([archived[f"2026-10-0{d}"] for d in range(3, 8)], ["done", None, None, None, None],
                         "archivovaný návyk nic nevynechává")
        with patch.object(service, "today_local", return_value=TODAY):
            service.set_active(self.db, h.id, True)
        self.db.commit()
        restored = service.list_habits(self.db, TODAY)["active"][0]
        hist = {d["date"]: d["state"] for d in restored["history"]}
        self.assertEqual([hist[f"2026-10-0{d}"] for d in range(3, 8)], ["done", None, None, None, "open"],
                         "dny archivace se po obnovení nepočítají jako vynechané")
        self.assertEqual(service.summary(self.db, TODAY)["week_expected"], 1)
        self.assertEqual(service.summary(self.db, TODAY + timedelta(days=1))["week_expected"], 2, "od obnovení se zase počítá")

    def test_same_day_archive_and_restore_keeps_inference(self):
        h = self._habit()
        with patch.object(service, "utc_now", return_value=NOW_UTC):
            service.set_active(self.db, h.id, False)
        with patch.object(service, "today_local", return_value=TODAY):
            service.set_active(self.db, h.id, True)
        self.db.commit()
        hist = {d["date"]: d["state"] for d in service.list_habits(self.db, TODAY)["active"][0]["history"]}
        self.assertEqual(hist["2026-10-04"], "missed")

    def test_entries_cannot_be_deleted_by_cascade(self):
        h = self._habit()
        service.set_entry(self.db, h.id, "done", today=TODAY)
        self.db.commit()
        self.assertIn(Habit.entries.property.passive_deletes, ("all", True))
        fk = next(iter(HabitEntry.__table__.c.habit_id.foreign_keys))
        self.assertEqual(fk.ondelete, "RESTRICT")


class HabitContributionsTestCase(unittest.TestCase):
    """Návyky v agregátorech jen přes `ModuleIntegrations` – vypnutý modul nedodá nic, data zůstanou."""

    def setUp(self):
        self.engine, Session = _session()
        self.db = Session()
        self.rehab = service.create_habit(self.db, "Rehab koleno")
        self.voda = service.create_habit(self.db, "Pitný režim", kind="count", target_value=2, unit="l")
        for h in (self.rehab, self.voda):
            h.created_at = CREATED
        service.set_entry(self.db, self.voda.id, "done", value=2.5, today=TODAY, day=TODAY)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_search(self):
        hits = ss.search(self.db, "rehab", access=ModuleAccess({}))["results"]
        self.assertEqual([(r["type"], r["href"]) for r in hits], [("habit", f"/habits?habit={self.rehab.id}")])
        self.assertEqual(ss.search(self.db, "rehab", access=ModuleAccess({"habits": False}))["results"], [])

    def test_today(self):
        with patch.object(ts, "generate_plan", return_value={"actions": []}):
            on = ts.build_today(self.db, now_utc=NOW_UTC, access=ModuleAccess({}))
            off = ts.build_today(self.db, now_utc=NOW_UTC, access=ModuleAccess({"habits": False}))
        items = {it["id"]: it for it in on["timeline"]}
        rehab, voda = items[f"habit:{self.rehab.id}"], items[f"habit:{self.voda.id}"]
        self.assertEqual((rehab["status"], rehab["actions"], rehab["href"]), ("open", ["complete", "skip"], f"/habits?habit={self.rehab.id}"))
        self.assertEqual((voda["status"], voda["actions"]), ("done", []))
        self.assertIn("splněno", voda["subtitle"])
        self.assertIn("2,5 l", voda["subtitle"])
        # globální řazení časové osy: hotové dospod
        self.assertEqual(on["timeline"][-1]["id"], f"habit:{self.voda.id}")
        self.assertFalse(any(it["id"].startswith("habit:") for it in off["timeline"]))
        self.assertEqual(self.db.query(HabitEntry).count(), 1, "vypnutí nic nesmazalo")

    def test_ai_context(self):
        on = build_current_context(self.db, "jak mi jdou návyky", now_utc=NOW_UTC, access=ModuleAccess({}))
        self.assertIn("habits", on.sections)
        self.assertIn("Pitný režim splněno", on.text)
        self.assertIn("Rehab koleno čeká", on.text)
        named = build_current_context(self.db, "co rehab koleno", now_utc=NOW_UTC, access=ModuleAccess({}))
        self.assertIn("habits", named.sections, "název návyku označí oblast")
        off = build_current_context(self.db, "jak mi jdou návyky", now_utc=NOW_UTC, access=ModuleAccess({"habits": False}))
        self.assertNotIn("habits", off.sections)

    def test_registered_only_through_the_registry(self):
        m = mr.ModuleAccess({}).get("habits")
        self.assertTrue(m.implemented)
        self.assertEqual({s.name for s in m.integrations.search}, {"habits"})
        self.assertEqual(len(m.integrations.routers), 1)
        self.assertTrue(all(o != "habits" for o, _ in ModuleAccess({"habits": False}).contributions("today")))


class HabitApiTestCase(unittest.TestCase):
    PIN = "4821"

    def setUp(self):
        self.engine, self.Session = _session()
        self._orig = (auth_service.SessionLocal, main.SessionLocal, database.SessionLocal, auth_service.AUTH_PIN_HASH,
                      auth_service._failed_attempts)
        auth_service.SessionLocal = main.SessionLocal = database.SessionLocal = self.Session
        auth_service.AUTH_PIN_HASH = ""
        auth_service._failed_attempts = {}
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
        self.engine.dispose()

    def test_crud_flow(self):
        r = self.client.post("/habits", json={"name": "Rehab"})
        self.assertEqual(r.status_code, 200)
        hid = r.json()["id"]
        self.assertEqual(self.client.post("/habits", json={"name": ""}).status_code, 422)
        self.assertEqual(self.client.post(f"/habits/{hid}/entries?source=today", json={"state": "done"}).json()["entry"]["state"], "done")
        self.assertEqual(self.client.post(f"/habits/{hid}/entries", json={"state": "missed"}).status_code, 422)
        body = self.client.get("/habits").json()
        self.assertEqual(body["active"][0]["today"]["state"], "done")
        self.assertEqual(body["summary"]["done"], 1)
        log = self.Session().query(ActivityLog).filter_by(area="habits", action_type="check").one()
        self.assertEqual(log.user_context, "today")
        self.assertTrue(self.client.post(f"/habits/{hid}/archive").json()["ok"])
        self.assertEqual(self.client.post(f"/habits/{hid}/entries", json={"state": "done"}).status_code, 409)
        self.assertEqual(self.client.get("/habits").json()["archived"][0]["id"], hid)
        self.assertEqual(self.client.post("/habits/999/archive").status_code, 404)

    def test_disable_and_reenable_keeps_data(self):
        hid = self.client.post("/habits", json={"name": "Rehab"}).json()["id"]
        self.client.post(f"/habits/{hid}/entries", json={"state": "done"})
        self.assertEqual(self.client.put("/modules/habits", json={"enabled": False}).status_code, 200)
        self.assertEqual(self.client.get("/habits").status_code, 404)
        dash = self.client.get("/dashboard").json()
        self.assertIn("habits", dash)
        self.assertIsNone(dash["habits"], "klíč zůstává, modul nic nepočítá")
        self.assertEqual(self.Session().query(HabitEntry).count(), 1, "data zůstala")
        self.assertEqual(self.client.put("/modules/habits", json={"enabled": True}).status_code, 200)
        body = self.client.get("/habits").json()
        self.assertEqual((body["active"][0]["name"], body["active"][0]["today"]["state"]), ("Rehab", "done"))
        self.assertEqual(self.client.get("/dashboard").json()["habits"]["done"], 1)

    def test_auth_still_applies(self):
        auth_service.AUTH_PIN_HASH = bcrypt.hashpw(self.PIN.encode(), bcrypt.gensalt(rounds=4)).decode()
        self.assertEqual(self.client.get("/habits").status_code, 401)
        self.assertEqual(self.client.post("/habits", json={"name": "X"}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
