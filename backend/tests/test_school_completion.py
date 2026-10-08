"""MRK-14: splnění úkolu, uzavření zkoušky s volitelným výsledkem, znovuotevření, historie v Aktivitě."""
import json
import os
import sys
import unittest
from datetime import date, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("GROQ_API_KEY", "x")
TESTS_DIR = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(TESTS_DIR, ".."))
for p in (BACKEND_DIR, TESTS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import school_service as ss  # noqa: E402
from models import ActivityLog, Assignment, Exam, Subject  # noqa: E402
from test_wot_milestones import WotBase  # noqa: E402  (in-memory DB, auth, TestClient)


class SchoolBase(WotBase):
    def setUp(self):
        super().setUp()
        self.login()

        def seed(db):
            db.add(Subject(id=1, name="English in IT", code="EIT", semester="ZS", credits=4, active=True))
            db.add(Assignment(id=1, title="Esej", description="", due_date=date.today() + timedelta(days=3), priority="high", status="todo", subject_id=1))
            db.add(Assignment(id=2, title="Sada 3", description="", due_date=date.today() - timedelta(days=4), priority="medium", status="in_progress", subject_id=1))
            db.add(Exam(id=1, title="test", exam_type="exam", exam_date=date.today() + timedelta(days=5), status="upcoming", notes="", subject_id=1))
            db.add(Exam(id=2, title="Zápočet", exam_type="test", exam_date=date.today() - timedelta(days=2), status="upcoming", notes="", subject_id=1))
            db.commit()
        self.q(seed)

    def events(self, entity_type, entity_id):
        return self.q(lambda db: [(a.action_type, json.loads(a.delta_json or "{}")) for a in
                                  db.query(ActivityLog).filter_by(entity_type=entity_type, entity_id=entity_id).order_by(ActivityLog.id)])

    def assignment(self, aid):
        return next(a for a in self.client.get("/school/assignments").json() if a["id"] == aid)

    def exam(self, eid):
        return next(e for e in self.client.get("/school/exams").json() if e["id"] == eid)


class AssignmentCompletionTestCase(SchoolBase):
    def test_complete_task(self):
        r = self.client.post("/school/assignment/1/complete")
        self.assertEqual(r.status_code, 200, r.text)
        a = self.assignment(1)
        self.assertEqual(a["status"], "done")
        self.assertTrue(a["completed_at"].endswith("Z"))
        self.assertEqual(self.events("Assignment", 1)[-1][0], "complete")

    def test_overdue_task_is_completable(self):
        self.assertEqual(self.client.post("/school/assignment/2/complete").status_code, 200)
        self.assertEqual(self.assignment(2)["status"], "done")

    def test_double_complete_and_missing(self):
        self.client.post("/school/assignment/1/complete")
        r = self.client.post("/school/assignment/1/complete")
        self.assertEqual((r.status_code, r.json()["detail"]["error"]), (409, "already_completed"))
        self.assertEqual(self.client.post("/school/assignment/999/complete").status_code, 404)

    def test_reopen_preserves_history(self):
        self.client.post("/school/assignment/1/complete")
        r = self.client.post("/school/assignment/1/reopen")
        self.assertEqual(r.status_code, 200)
        a = self.assignment(1)
        self.assertEqual((a["status"], a["completed_at"]), ("todo", None))
        ev = self.events("Assignment", 1)
        self.assertEqual([e[0] for e in ev], ["complete", "update"])
        self.assertEqual(ev[1][1]["status"], {"old": "done", "new": "todo"})
        self.assertIsNotNone(ev[1][1]["completed_at"]["old"], "čas původního splnění zůstává v historii")
        self.assertEqual(self.client.post("/school/assignment/1/reopen").json()["detail"]["error"], "not_completed")

    def test_record_is_kept_and_delete_is_separate(self):
        self.client.post("/school/assignment/1/complete")
        self.assertEqual(self.q(lambda db: db.query(Assignment).count()), 2)
        self.assertEqual(self.client.delete("/school/assignment/1").status_code, 200)
        self.assertEqual(self.q(lambda db: db.query(Assignment).count()), 1)


class ExamClosureTestCase(SchoolBase):
    def test_close_without_result(self):
        r = self.client.post("/school/exam/1/close", json={"outcome": "closed"})
        self.assertEqual(r.status_code, 200, r.text)
        e = self.exam(1)
        self.assertEqual((e["status"], e["result_type"], e["result_value"]), ("closed", None, None))
        self.assertIsNotNone(e["completed_at"])

    def test_close_with_optional_results(self):
        cases = [
            ({"outcome": "passed", "result_type": "percent", "result_value": "87,5 %"}, ("passed", "percent", "87,5")),
            ({"outcome": "passed", "result_type": "points", "result_value": "42 / 50"}, ("passed", "points", "42/50")),
            ({"outcome": "failed", "result_type": "grade", "result_value": "f"}, ("failed", "grade", "F")),
            ({"outcome": "passed", "result_type": "grade", "result_value": "2-"}, ("passed", "grade", "2-")),
            ({"outcome": "failed", "result_type": "pass_fail"}, ("failed", "pass_fail", "failed")),
        ]
        for body, expected in cases:
            self.client.post("/school/exam/1/reopen")
            r = self.client.post("/school/exam/1/close", json=body)
            self.assertEqual(r.status_code, 200, (body, r.text))
            e = self.exam(1)
            self.assertEqual((e["status"], e["result_type"], e["result_value"]), expected, body)

    def test_invalid_results(self):
        for body, code in (({"outcome": "maybe"}, "invalid_outcome"),
                           ({"result_type": "percent", "result_value": "120"}, "invalid_result_value"),
                           ({"result_type": "percent", "result_value": "hodně"}, "invalid_result_value"),
                           ({"result_type": "points", "result_value": "42 bodů"}, "invalid_result_value"),
                           ({"result_type": "grade", "result_value": "7"}, "invalid_result_value"),
                           ({"result_type": "grade"}, "invalid_result_value"),
                           ({"result_type": "medal", "result_value": "1"}, "invalid_result_type"),
                           ({"result_value": "1"}, "invalid_result_type"),
                           ({"outcome": "closed", "result_type": "pass_fail"}, "invalid_result_value")):
            r = self.client.post("/school/exam/1/close", json=body)
            self.assertEqual((r.status_code, r.json()["detail"]["error"]), (400, code), body)
        self.assertEqual(self.exam(1)["status"], "upcoming", "neplatný vstup nic nezmění")

    def test_overdue_exam_close_and_double_close(self):
        self.assertEqual(self.client.post("/school/exam/2/close", json={}).json()["item"]["status"], "passed")
        r = self.client.post("/school/exam/2/close", json={})
        self.assertEqual((r.status_code, r.json()["detail"]["error"]), (409, "already_completed"))
        self.assertEqual(self.client.post("/school/exam/999/close", json={}).status_code, 404)

    def test_reopen_clears_result_but_history_keeps_it(self):
        self.client.post("/school/exam/1/close", json={"outcome": "passed", "result_type": "percent", "result_value": "91"})
        self.assertEqual(self.client.post("/school/exam/1/reopen").status_code, 200)
        e = self.exam(1)
        self.assertEqual((e["status"], e["result_type"], e["result_value"], e["completed_at"]), ("upcoming", None, None, None))
        ev = self.events("Exam", 1)
        self.assertEqual([x[0] for x in ev], ["complete", "update"])
        self.assertEqual(ev[0][1]["result_value"], {"old": None, "new": "91"})
        self.assertEqual(ev[1][1]["result_value"], {"old": "91", "new": None})
        self.assertEqual(self.client.post("/school/exam/1/reopen").json()["detail"]["error"], "not_completed")

    def test_requires_auth(self):
        self.client.cookies.clear()
        for url in ("/school/assignment/1/complete", "/school/assignment/1/reopen", "/school/exam/1/close", "/school/exam/1/reopen"):
            self.assertEqual(self.client.post(url, json={}).status_code, 401, url)


class NormalizeResultTestCase(unittest.TestCase):
    def test_empty_result_is_allowed(self):
        self.assertEqual(ss.normalize_result(None, None, "passed"), (None, None))
        self.assertEqual(ss.normalize_result("", "", "closed"), (None, None))

    def test_percent_formats(self):
        self.assertEqual(ss.normalize_result("percent", "100", "passed"), ("percent", "100"))
        self.assertEqual(ss.normalize_result("percent", "0.5", "passed"), ("percent", "0,5"))


if __name__ == "__main__":
    unittest.main()


class MutationPathTestCase(SchoolBase):
    """Splnění přes AI / režim Dnes (mutation_service) nastaví stejný čas dokončení; vrácení ho smaže."""

    def test_complete_and_undo_via_mutation_service(self):
        from unittest.mock import patch

        import mutation_service as ms
        p = patch.object(ms, "SessionLocal", self.Session)
        p.start()
        self.addCleanup(p.stop)

        def run(db):
            plan = ms.resolve_mutation(db, "school_assignment", "complete", {"id": 1})
            ms.apply_mutation_plan(plan, user_context="today")
            return plan
        self.q(run)
        self.assertEqual(self.assignment(1)["status"], "done")
        self.assertIsNotNone(self.assignment(1)["completed_at"])

        def undo(db):
            a = db.get(Assignment, 1)
            after = ms._snapshot(ms.ENTITIES["school_assignment"], a)
            item = {"id": 1, "before": {**after, "status": "todo"}, "after": after}
            ms._undo_item(db, ms.ENTITIES["school_assignment"], "complete", item, apply=True)
            db.commit()
        self.q(undo)
        self.assertEqual((self.assignment(1)["status"], self.assignment(1)["completed_at"]), ("todo", None))
