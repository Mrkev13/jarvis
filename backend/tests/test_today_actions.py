"""Roadmap 4H: akce z režimu Dnes – metadata, připomínky (hotovo/odložit), úkoly přes pending akce, zdroj, stale, undo."""
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

import ai  # noqa: E402
import auth_service  # noqa: E402
import main  # noqa: E402
import mutation_service  # noqa: E402
import reminder_service as rs  # noqa: E402
import today_service as ts  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, Assignment, Exam, PendingAction, Reminder, Subject  # noqa: E402
from time_utils import local_to_utc  # noqa: E402

NOW = datetime(2026, 10, 10, 12, 0)  # so 14:00 Praha


def utc(y, mo, d, h, mi=0):
    return local_to_utc(datetime(y, mo, d, h, mi))


class ActionMetadataTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(Subject(id=1, name="Fyzika"))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_actions_only_where_semantics_exist(self):
        self.db.add_all([
            Reminder(id=1, title="Jednorázová", due_at=utc(2026, 10, 10, 17), status="scheduled"),
            Reminder(id=2, title="Zazněla", due_at=utc(2026, 10, 10, 11), status="fired"),
            Reminder(id=3, title="Opakovaná", due_at=utc(2026, 10, 10, 18), status="scheduled", recurrence="daily", local_time="18:00"),
            Reminder(id=4, title="Hotová", due_at=utc(2026, 10, 10, 9), status="done"),
            Reminder(id=5, title="Stará", due_at=utc(2026, 10, 9, 9), status="fired"),
            Reminder(id=6, title="Zítra", due_at=utc(2026, 10, 11, 9), status="scheduled"),
            Assignment(id=1, title="Dnešní úkol", subject_id=1, due_date=date(2026, 10, 10), status="todo"),
            Assignment(id=2, title="Hotový", subject_id=1, due_date=date(2026, 10, 10), status="done"),
            Assignment(id=3, title="Po termínu", subject_id=1, due_date=date(2026, 10, 1), status="todo"),
            Exam(id=1, title="Proběhlá", subject_id=1, exam_date=date(2026, 10, 1), status="upcoming"),
        ])
        self.db.commit()
        out = ts.build_today(self.db, now_utc=NOW)
        acts = {it["id"]: it["actions"] for k in ("timeline", "attention", "priorities", "upcoming") for it in out[k]}
        # Regrese 4H: „+N min" se počítá od teď – budoucí připomínku by „odložení" přiblížilo → jen Hotovo
        self.assertEqual(acts["reminder:1"], ["complete"], "budoucí připomínka: odložit až po zaznění")
        self.assertEqual(acts["reminder:2"], ["complete", "snooze"])
        self.assertEqual(acts["reminder:3"], [], "opakovaná: hotovo by výskyt neposunulo")
        self.assertEqual(acts["reminder:4"], [])
        self.assertEqual(acts["reminder:5"], ["complete", "snooze"], "nevyřízená z dřívějška v Pozornosti")
        self.assertEqual(acts["reminder:6"], [], "Potom zůstává bez akcí")
        self.assertEqual(acts["assignment:1"], ["complete"])
        self.assertEqual(acts["assignment:2"], [])
        self.assertEqual(acts["assignment:3"], ["complete"])
        self.assertEqual(acts["exam:1"], ["record_result"], "výsledek zkoušky se zapisuje ve Škole")

    def test_snooze_options_prague(self):
        opts = {o["id"]: o for o in ts.build_today(self.db, now_utc=NOW)["snooze_options"]}
        self.assertEqual([opts[k].get("minutes") for k in ("15m", "1h", "3h")], [15, 60, 180])
        self.assertEqual(opts["tomorrow"]["until_local"], "2026-10-11T08:00")
        # 23:30 UTC 10. 10. = 01:30 Praha 11. 10. → „zítra" je 12. 10.
        late = {o["id"]: o for o in ts.build_today(self.db, now_utc=datetime(2026, 10, 10, 23, 30))["snooze_options"]}
        self.assertEqual(late["tomorrow"]["until_local"], "2026-10-12T08:00")
        dst = {o["id"]: o for o in ts.build_today(self.db, now_utc=datetime(2026, 10, 25, 10, 0))["snooze_options"]}
        self.assertEqual(dst["tomorrow"]["until_local"], "2026-10-26T08:00")


class TodayActionsApiTestCase(unittest.TestCase):
    PIN = "4821"

    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        db = self.Session()
        db.add_all([
            Subject(id=1, name="Fyzika"),
            Reminder(id=1, title="Fyzio", due_at=NOW + timedelta(hours=3), status="scheduled"),
            Reminder(id=2, title="Prádlo", due_at=NOW - timedelta(minutes=10), status="fired"),
            Assignment(id=1, title="Sada", subject_id=1, due_date=date(2026, 10, 2), status="todo"),
            Assignment(id=2, title="Esej", subject_id=1, due_date=date(2026, 10, 10), status="todo"),
            Assignment(id=3, title="Hotová", subject_id=1, due_date=date(2026, 10, 10), status="done"),
        ])
        db.commit()
        db.close()
        self._patches = [
            patch.object(auth_service, "SessionLocal", self.Session),
            patch.object(main, "SessionLocal", self.Session),
            patch.object(ai, "SessionLocal", self.Session),
            patch.object(tools, "SessionLocal", self.Session),
            patch.object(mutation_service, "SessionLocal", self.Session),
            patch.object(rs, "utc_now", lambda: NOW),
            patch.object(auth_service, "_failed_attempts", {}),
            patch.object(auth_service, "AUTH_PIN_HASH", bcrypt.hashpw(self.PIN.encode(), bcrypt.gensalt(rounds=4)).decode()),
            patch.object(ai, "_llm_create_with_retry", side_effect=AssertionError("Dnes nesmí volat LLM")),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def login(self):
        self.assertEqual(self.client.post("/auth/login", json={"pin": self.PIN}).status_code, 200)

    def q(self, fn):
        db = self.Session()
        try:
            return fn(db)
        finally:
            db.close()

    def logs(self, area=None):
        return self.q(lambda db: [(lg.area, lg.action_type, lg.user_context) for lg in db.query(ActivityLog).order_by(ActivityLog.id)
                                  if area is None or lg.area == area])

    # ---- auth ----
    def test_mutations_require_session(self):
        self.assertEqual(self.client.post("/reminders/1/done?source=today").status_code, 401)
        self.assertEqual(self.client.post("/reminders/1/snooze?source=today", json={"minutes": 15}).status_code, 401)
        self.assertEqual(self.client.post("/today/actions/prepare", json={"action": "complete", "ref": "assignment:1"}).status_code, 401)
        self.assertEqual(self.q(lambda db: db.get(Reminder, 1).status), "scheduled")
        self.assertEqual(self.q(lambda db: db.query(PendingAction).count()), 0)

    # ---- připomínky ----
    def test_reminder_complete_from_today_once(self):
        self.login()
        r = self.client.post("/reminders/2/done?source=today")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "done")
        self.assertEqual(self.logs("reminders"), [("reminders", "complete", "today")])
        again = self.client.post("/reminders/2/done?source=today")
        self.assertEqual(again.status_code, 400, "už hotová = zastaralý stav, žádná druhá změna")
        self.assertIn("už je hotová", again.json()["detail"])
        self.assertEqual(len(self.logs("reminders")), 1, "žádný duplicitní záznam v Aktivitě")
        out = self.q(lambda db: ts.build_today(db, now_utc=NOW))
        row = next(it for it in out["timeline"] if it["id"] == "reminder:2")
        self.assertEqual((row["status"], row["actions"]), ("done", []))

    def test_unknown_source_is_manual(self):
        self.login()
        self.client.post("/reminders/1/done?source=ai_confirm")
        self.assertEqual(self.logs("reminders"), [("reminders", "complete", "manual")], "zdroj nejde podstrčit")

    def test_reminder_snooze_minutes_and_tomorrow(self):
        self.login()
        r = self.client.post("/reminders/2/snooze?source=today", json={"minutes": 15})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.q(lambda db: db.get(Reminder, 2).due_at), NOW + timedelta(minutes=15))
        self.assertEqual(self.q(lambda db: db.get(Reminder, 2).status), "scheduled")
        self.client.post("/reminders/1/snooze?source=today", json={"minutes": 60})
        self.assertEqual(self.q(lambda db: db.get(Reminder, 1).due_at), NOW + timedelta(minutes=60))
        r = self.client.post("/reminders/1/snooze?source=today", json={"until_local": "2026-10-11T08:00"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.q(lambda db: db.get(Reminder, 1).due_at), datetime(2026, 10, 11, 6, 0), "08:00 CEST = 06:00 UTC")
        self.assertEqual([c for _, a, c in self.logs("reminders") if a == "snooze"], ["today"] * 3)
        out = self.q(lambda db: ts.build_today(db, now_utc=NOW))
        self.assertNotIn("reminder:1", [it["id"] for it in out["timeline"]], "odložená na zítra zmizí z dneška")
        self.assertIn("reminder:1", [it["id"] for it in out["upcoming"]])

    def test_snooze_across_dst(self):
        self.login()
        with patch.object(rs, "utc_now", lambda: datetime(2026, 10, 24, 21, 0)):
            self.client.post("/reminders/1/snooze?source=today", json={"until_local": "2026-10-25T08:00"})
        self.assertEqual(self.q(lambda db: db.get(Reminder, 1).due_at), datetime(2026, 10, 25, 7, 0), "po přechodu na CET = UTC+1")
        with patch.object(rs, "utc_now", lambda: datetime(2026, 10, 24, 22, 30)):  # 00:30 CEST 25. 10.
            r = self.client.post("/reminders/2/snooze?source=today", json={"minutes": 180})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.q(lambda db: db.get(Reminder, 2).due_at), datetime(2026, 10, 25, 1, 30), "minuty počítané v UTC – přes DST bez skoku")

    def test_snooze_stale_and_invalid(self):
        self.login()
        self.client.post("/reminders/1/done?source=today")
        r = self.client.post("/reminders/1/snooze?source=today", json={"minutes": 15})
        self.assertEqual(r.status_code, 400, "hotovou nejde odložit")
        self.assertEqual(self.client.post("/reminders/2/snooze?source=today", json={"until_local": "2026-10-09T08:00"}).status_code, 400)
        self.assertEqual(self.client.post("/reminders/99/done?source=today").status_code, 404)

    # ---- úkoly přes pending akce ----
    def prepare(self, ref, action="complete"):
        return self.client.post("/today/actions/prepare", json={"action": action, "ref": ref})

    def test_assignment_complete_via_pending_action(self):
        self.login()
        r = self.prepare("assignment:1")
        self.assertEqual(r.status_code, 200, r.text)
        pending = r.json()["pending_action"]
        self.assertEqual(pending["tool"], "modify_records")
        self.assertEqual(pending["arguments"]["_source"], "today")
        self.assertEqual(self.q(lambda db: db.get(Assignment, 1).status), "todo", "příprava nic nezapisuje")
        c = self.client.post("/actions/confirm", json={"action_id": pending["id"]}).json()
        self.assertTrue(c["ok"], c)
        self.assertTrue(c["result"]["undo_available"])
        self.assertEqual(self.q(lambda db: db.get(Assignment, 1).status), "done")
        logs = self.logs()
        self.assertEqual([(a, t, ctx) for a, t, ctx in logs if a == "school"], [("school", "complete", "today")])
        self.assertFalse(any(a == "ai" for a, _, _ in logs), "akce z Dnes není akce AI")
        out = self.q(lambda db: ts.build_today(db, now_utc=NOW))
        everywhere = [it["id"] for k in ("timeline", "attention", "priorities", "upcoming") for it in out[k]]
        self.assertNotIn("assignment:1", everywhere, "hotový úkol po termínu zmizí z aktivních sekcí")

    def test_assignment_due_today_moves_to_done(self):
        self.login()
        pending = self.prepare("assignment:2").json()["pending_action"]
        self.client.post("/actions/confirm", json={"action_id": pending["id"]})
        out = self.q(lambda db: ts.build_today(db, now_utc=NOW))
        row = next(it for it in out["timeline"] if it["id"] == "assignment:2")
        self.assertEqual((row["status"], row["actions"]), ("done", []))

    def test_assignment_already_done_is_stale(self):
        self.login()
        r = self.prepare("assignment:3")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["error"], "no_change")
        self.assertEqual(self.q(lambda db: db.query(PendingAction).count()), 0)

    def test_assignment_changed_between_prepare_and_confirm(self):
        self.login()
        pending = self.prepare("assignment:2").json()["pending_action"]
        db = self.Session()
        db.get(Assignment, 2).title = "Esej (upraveno v jiné záložce)"
        db.commit()
        db.close()
        c = self.client.post("/actions/confirm", json={"action_id": pending["id"]}).json()
        self.assertFalse(c["ok"])
        self.assertEqual(c["error"], "execution_failed")
        self.assertIn("změnil", c["detail"])
        self.assertEqual(self.q(lambda db: db.get(Assignment, 2).status), "todo")
        again = self.client.post("/actions/confirm", json={"action_id": pending["id"]}).json()
        self.assertEqual(again["error"], "action_already_processed", "žádné druhé provedení")
        failure = [ctx for a, t, ctx in self.logs() if a == "system"]
        self.assertEqual(failure, ["today", "today"], "selhání i odmítnuté opakování připsané Dnes, ne AI")

    def test_undo_keeps_today_source(self):
        self.login()
        pending = self.prepare("assignment:1").json()["pending_action"]
        self.client.post("/actions/confirm", json={"action_id": pending["id"]})
        u = self.client.post("/actions/undo", json={"action_id": pending["id"]}).json()
        self.assertTrue(u["ok"], u)
        self.assertEqual(u["pending_action"]["arguments"].get("_source"), "today")
        c = self.client.post("/actions/confirm", json={"action_id": u["pending_action"]["id"]}).json()
        self.assertTrue(c["ok"], c)
        self.assertEqual(self.q(lambda db: db.get(Assignment, 1).status), "todo")
        self.assertFalse(any(a == "ai" for a, _, _ in self.logs()))
        self.assertTrue(all(ctx == "today" for a, _, ctx in self.logs() if a == "school"), self.logs())

    def test_prepare_rejects_unsupported(self):
        self.login()
        for body in ({"action": "delete", "ref": "assignment:1"}, {"action": "complete", "ref": "reminder:1"},
                     {"action": "complete", "ref": "exam:1"}, {"action": "complete", "ref": "assignment:abc"}, {"action": "complete", "ref": ""}):
            self.assertEqual(self.client.post("/today/actions/prepare", json=body).status_code, 422, body)
        self.assertEqual(self.prepare("assignment:99").status_code, 409, "neexistující = zastaralé")
        self.assertEqual(self.q(lambda db: db.query(PendingAction).count()), 0)

    def test_ai_actions_unchanged(self):
        """AI pending akce bez zdroje dál = ai_confirm + záznam „schváleno"; argument _source od modelu se zahodí."""
        db = self.Session()
        item = ai.prepare_write_action(db, "modify_records", {"entity": "school_assignment", "action": "complete",
                                                               "target": {"id": 1}, "_source": "today"})
        db.close()
        self.assertNotIn("_source", item["arguments"])
        self.login()
        self.client.post("/actions/confirm", json={"action_id": item["id"]})
        ctxs = {(a, ctx) for a, _, ctx in self.logs()}
        self.assertIn(("school", "ai_confirm"), ctxs)
        self.assertIn(("ai", "ai_confirm"), ctxs)
        stored = self.q(lambda db: json.loads(db.get(PendingAction, int(item["id"])).arguments))
        self.assertNotIn("_source", stored)


if __name__ == "__main__":
    unittest.main()
