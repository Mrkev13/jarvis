"""MRK-86: stav zápočtu, souhrn zkoušek, týdenní docházka a počítání absencí (deterministicky, bez LLM)."""
import os
import sys
import unittest
from datetime import date, datetime
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
import today_service  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, DomainEvent, Exam, Subject  # noqa: E402
from module_contracts import ContextRequest  # noqa: E402
from module_registry import ModuleAccess  # noqa: E402
from modules.school import progress  # noqa: E402
from modules.school.models import SchoolAttendance  # noqa: E402
from school_integrations import context_school  # noqa: E402

PIN = "4821"
TODAY = date(2026, 11, 11)          # středa
WEEK = date(2026, 11, 9)            # pondělí tohoto týdne
NOW_UTC = datetime(2026, 11, 11, 9, 0)


class SchoolProgressTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self._patches = [patch.object(m, "SessionLocal", self.Session) for m in (auth_service, main, database)]
        self._patches += [patch.object(auth_service, "_failed_attempts", {}),
                          patch.object(auth_service, "AUTH_PIN_HASH",
                                       bcrypt.hashpw(PIN.encode(), bcrypt.gensalt(rounds=4)).decode()),
                          patch.object(progress, "today_local", lambda *a: TODAY)]
        for p in self._patches:
            p.start()
        self.client = TestClient(main.app)
        self.assertEqual(self.client.post("/auth/login", json={"pin": PIN}).status_code, 200)
        db = self.Session()
        try:
            law = Subject(name="Právo", code="PRA", semester="ZS", credits=5, active=True, absence_limit=2)
            ait = Subject(name="Angličtina v IT", code="EIT", semester="ZS", credits=3, active=True)
            old = Subject(name="Starý předmět", active=False)
            db.add_all([law, ait, old])
            db.flush()
            db.add_all([
                Exam(title="Test 1", subject_id=law.id, exam_date=date(2026, 10, 20), status="passed",
                     result_type="percent", result_value="85 %"),
                Exam(title="Test 2", subject_id=law.id, exam_date=date(2026, 11, 3), status="failed",
                     result_type="pass_fail", result_value="nesloženo"),
                Exam(title="Zkouška", subject_id=law.id, exam_date=date(2026, 12, 15), status="upcoming"),
            ])
            db.commit()
            self.law, self.ait, self.old = law.id, ait.id, old.id
        finally:
            db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def q(self, fn):
        db = self.Session()
        try:
            return fn(db)
        finally:
            db.close()

    def attend(self, subject_id, week, present):
        return self.client.put(f"/school/subject/{subject_id}/attendance",
                               json={"week_start": week.isoformat(), "present": present})

    def progress(self, subject_id):
        data = self.client.get("/school/progress").json()
        return next(s for s in data["subjects"] if s["id"] == subject_id)

    # ---------- výpočet ----------

    def test_absence_levels(self):
        cases = [(None, 3, None), (3, 1, "ok"), (2, 1, "last"), (2, 2, "exhausted"), (2, 3, "exceeded"), (0, 0, "exhausted")]
        for limit, absent, level in cases:
            a = progress.Absences(present=4, absent=absent, limit=limit)
            self.assertEqual(a.level, level, (limit, absent))
        self.assertEqual(progress.Absences(5, 1, 2).text(), "byl 5 z 6, absence 1 z max. 2 (zbývá poslední)")
        self.assertEqual(progress.Absences(4, 3, 2).text(), "byl 4 z 7, absence 3 z max. 2 (limit překročen o 1)")
        self.assertEqual(progress.Absences(0, 0, None).text(), "docházka zatím nezapsaná")
        self.assertEqual(progress.week_start(TODAY), WEEK)
        self.assertEqual(progress.week_start(date(2026, 11, 15)), WEEK, "neděle patří k pondělí před ní")

    def test_progress_overview(self):
        data = self.client.get("/school/progress").json()
        self.assertEqual(data["week_start"], WEEK.isoformat())
        self.assertEqual(data["previous_week_start"], "2026-11-02")
        self.assertEqual([s["name"] for s in data["subjects"]], ["Angličtina v IT", "Právo"], "archivovaný ne")
        law = self.progress(self.law)
        self.assertEqual(law["credit"], {"status": "pending", "label": "nesplněn", "date": None})
        self.assertEqual({k: law["exams"][k] for k in ("open", "closed", "passed", "failed")},
                         {"open": 1, "closed": 2, "passed": 1, "failed": 1})
        self.assertEqual([(r["title"], r["result"], r["outcome_label"]) for r in law["exams"]["results"]],
                         [("Test 2", None, "nesloženo"), ("Test 1", "85 %", "složeno")])
        self.assertEqual(law["attendance"]["this_week"], None)
        self.assertEqual(law["attendance"]["text"], "docházka zatím nezapsaná, absence 0 z max. 2 (zbývá 2)")

    # ---------- docházka ----------

    def test_one_tap_attendance_counts_and_audit(self):
        r = self.attend(self.law, WEEK, True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["attendance"]["this_week"], True)
        self.attend(self.law, date(2026, 11, 2), False)
        self.attend(self.law, date(2026, 10, 26), True)
        a = self.progress(self.law)["attendance"]
        self.assertEqual((a["present"], a["absent"], a["recorded"], a["remaining"], a["level"]), (2, 1, 3, 1, "last"))
        self.assertEqual([w["week_start"] for w in a["weeks"]], ["2026-11-09", "2026-11-02", "2026-10-26"])
        # oprava týdne = úprava řádku, ne nový
        self.attend(self.law, WEEK, False)
        self.assertEqual(self.q(lambda db: db.query(SchoolAttendance).count()), 3)
        self.assertEqual(self.progress(self.law)["attendance"]["level"], "exhausted")
        # smazání záznamu
        self.attend(self.law, WEEK, None)
        self.assertEqual(self.progress(self.law)["attendance"]["this_week"], None)
        logs = self.q(lambda db: [l.summary for l in db.query(ActivityLog).filter_by(entity_type="Subject").order_by(ActivityLog.id)])
        self.assertEqual(len(logs), 5, "každý zápis = Aktivita")
        self.assertEqual(logs[0], "Docházka Právo, týden od 9. 11.: byl")
        self.assertEqual(logs[-1], "Docházka Právo, týden od 9. 11.: nezapsáno")
        # stejný zápis znovu = nic
        self.attend(self.law, date(2026, 11, 2), False)
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).filter_by(entity_type="Subject").count()), 5)

    def test_attendance_validation(self):
        self.assertEqual(self.attend(self.law, date(2026, 11, 10), True).status_code, 422, "úterý není začátek týdne")
        self.assertEqual(self.attend(self.law, date(2026, 11, 16), True).status_code, 422, "budoucí týden")
        self.assertEqual(self.attend(self.old, WEEK, True).status_code, 409, "archivovaný předmět")
        self.assertEqual(self.attend(999, WEEK, True).status_code, 404)
        self.assertEqual(self.q(lambda db: (db.query(SchoolAttendance).count(), db.query(ActivityLog).count())), (0, 0))

    # ---------- zápočet ----------

    def test_credit_change_is_a_domain_event_with_activity(self):
        r = self.client.put(f"/school/subject/{self.law}/credit", json={"status": "passed"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["credit"], {"status": "passed", "label": "splněn", "date": TODAY.isoformat()})
        ev = self.q(lambda db: db.query(DomainEvent).one())
        self.assertEqual(ev.event_type, "school.subject.credit_changed")
        self.assertEqual(ev.payload, {"subject_id": self.law, "credit_status": "passed", "previous_status": "pending",
                                      "credit_date": TODAY.isoformat()})
        log = self.q(lambda db: db.query(ActivityLog).one())
        self.assertEqual((log.summary, log.entity_type, log.entity_id), ("Zápočet splněn: Právo", "Subject", self.law))
        # beze změny = nic; zpět na nesplněn smaže datum
        self.client.put(f"/school/subject/{self.law}/credit", json={"status": "passed", "date": TODAY.isoformat()})
        self.assertEqual(self.q(lambda db: db.query(DomainEvent).count()), 1)
        r = self.client.put(f"/school/subject/{self.law}/credit", json={"status": "pending"})
        self.assertEqual(r.json()["credit"], {"status": "pending", "label": "nesplněn", "date": None})
        self.assertEqual(self.q(lambda db: db.query(DomainEvent).count()), 2)

    def test_credit_validation(self):
        self.assertEqual(self.client.put(f"/school/subject/{self.law}/credit", json={"status": "maybe"}).status_code, 422)
        self.assertEqual(self.client.put(f"/school/subject/{self.law}/credit",
                                         json={"status": "failed", "date": "2026-12-01"}).status_code, 422)
        self.assertEqual(self.client.put("/school/subject/999/credit", json={"status": "passed"}).status_code, 404)
        self.assertEqual(self.q(lambda db: db.query(DomainEvent).count()), 0)

    def test_absence_limit_via_subject_patch(self):
        self.assertEqual(self.client.patch(f"/school/subject/{self.ait}", json={"absence_limit": 3}).json()["absence_limit"], 3)
        self.assertEqual(self.client.patch(f"/school/subject/{self.ait}", json={"absence_limit": None}).json()["absence_limit"], None)
        for bad in (-1, 53):
            self.assertEqual(self.client.patch(f"/school/subject/{self.ait}", json={"absence_limit": bad}).status_code, 422)

    # ---------- Dnes a AI ----------

    def _attention(self):
        db = self.Session()
        try:
            return [it for it in today_service.build_today(db, NOW_UTC, access=ModuleAccess({}))["attention"]
                    if it["type"] == "subject"]
        finally:
            db.close()

    def test_warning_in_today_attention(self):
        self.assertEqual(self._attention(), [], "bez absencí nic")
        self.attend(self.law, date(2026, 11, 2), False)
        items = self._attention()
        self.assertEqual([(i["id"], i["severity"]) for i in items], [(f"subject:{self.law}", "warning")])
        self.assertIn("zbývá poslední", items[0]["subtitle"])
        self.attend(self.law, date(2026, 10, 26), False)
        self.attend(self.law, WEEK, False)
        self.assertEqual(self._attention()[0]["severity"], "important", "překročeno")
        # splněný zápočet = absence už nevadí
        self.client.put(f"/school/subject/{self.law}/credit", json={"status": "passed"})
        self.assertEqual(self._attention(), [])
        # modul Škola vypnutý → nic
        self.client.put(f"/school/subject/{self.law}/credit", json={"status": "pending"})
        db = self.Session()
        try:
            off = today_service.build_today(db, NOW_UTC, access=ModuleAccess({"school": False}))["attention"]
        finally:
            db.close()
        self.assertFalse([i for i in off if i["type"] == "subject"])

    def test_ai_context_gets_only_computed_results(self):
        self.attend(self.law, WEEK, True)
        self.attend(self.law, date(2026, 11, 2), False)
        self.client.put(f"/school/subject/{self.ait}/credit", json={"status": "passed", "date": "2026-11-05"})
        text = "\n".join(self.q(lambda db: context_school(ContextRequest(db, TODAY, NOW_UTC))))
        self.assertIn("Zápočty: Angličtina v IT splněn (2026-11-05); Právo nesplněn; zkoušky uzavřené 2 (složeno 1, nesloženo 1)", text)
        self.assertIn("Test 1: 85 %", text)
        self.assertIn("Docházka (týdny): Právo: byl 1 z 2, absence 1 z max. 2 (zbývá poslední)", text)
        self.assertIn("Varování absencí: Právo: zbývá poslední povolená absence (1 z max. 2)", text)
        self.assertNotIn("Starý předmět", text)


if __name__ == "__main__":
    unittest.main()
