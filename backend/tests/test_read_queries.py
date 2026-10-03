import json
import os
import sys
import types
import unittest
from datetime import date, datetime

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from unittest.mock import patch  # noqa: E402

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import ai  # noqa: E402
import read_queries as rq  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, Assignment, Exam, FinanceTransaction, Goal, Subject, WorkSession  # noqa: E402


class ReadQueriesTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _finance(self):
        rows = [
            FinanceTransaction(amount=100 + i, category="Jídlo" if i % 2 else "Doprava", description=f"t{i}",
                               transaction_type="expense", created_at=datetime(2026, 9, 1 + i, 10, 0))
            for i in range(25)
        ]
        rows.append(FinanceTransaction(amount=9000, category="work", description="výplata",
                                       transaction_type="income", created_at=datetime(2026, 9, 30, 10, 0)))
        self.db.add_all(rows)
        self.db.commit()

    def test_finance_default_cap_newest_first_and_envelope(self):
        self._finance()
        r = rq.query_finance_transactions(self.db)
        self.assertEqual(r["total"], 26)
        self.assertEqual(r["returned"], rq.DEFAULT_LIMIT)
        self.assertTrue(r["truncated"])
        self.assertEqual(r["items"][0]["amount"], 9000)
        dates = [i["created_at"] for i in r["items"]]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertEqual(set(r["items"][0]), {"id", "amount", "category", "description", "transaction_type", "created_at"})

    def test_finance_filters(self):
        self._finance()
        r = rq.query_finance_transactions(self.db, transaction_type="income")
        self.assertEqual([i["amount"] for i in r["items"]], [9000])
        self.assertFalse(r["truncated"])
        r = rq.query_finance_transactions(self.db, category="jídlo", limit=500)
        self.assertEqual(r["total"], 12)
        self.assertTrue(all(i["category"] == "Jídlo" for i in r["items"]))
        self.assertEqual(r["filters"]["limit"], rq.MAX_LIMIT)
        # Pražské kalendářní dny: 2026-09-03 10:00 UTC patří do 3. 9.
        r = rq.query_finance_transactions(self.db, date_from="2026-09-03", date_to="2026-09-04")
        self.assertEqual(sorted(i["description"] for i in r["items"]), ["t2", "t3"])

    def test_invalid_date_raises_readable_error(self):
        with self.assertRaises(ValueError):
            rq.query_finance_transactions(self.db, date_from="zítra")

    def test_work_sessions_filters(self):
        self.db.add_all([
            WorkSession(date=date(2026, 9, d), hours=4, project="Servind" if d % 2 else "Jiný", hourly_rate=300)
            for d in range(1, 11)
        ])
        self.db.commit()
        r = rq.query_work_sessions(self.db, project="servind", limit=3)
        self.assertEqual(r["total"], 5)
        self.assertEqual([i["date"] for i in r["items"]], ["2026-09-09", "2026-09-07", "2026-09-05"])
        self.assertEqual(r["items"][0]["earnings"], 1200)
        r = rq.query_work_sessions(self.db, date_from="2026-09-08")
        self.assertEqual(r["total"], 3)

    def test_school_assignments_open_by_default(self):
        s = Subject(name="Matematika")
        self.db.add(s)
        self.db.flush()
        self.db.add_all([
            Assignment(title="Hotový", subject_id=s.id, status="done", due_date=date(2026, 9, 1)),
            Assignment(title="Esej", subject_id=s.id, status="todo", due_date=date(2026, 10, 3)),
            Assignment(title="Bez termínu", subject_id=s.id, status="in_progress"),
        ])
        self.db.commit()
        r = rq.query_school_assignments(self.db)
        self.assertEqual([i["title"] for i in r["items"]], ["Esej", "Bez termínu"])
        self.assertEqual(r["items"][0]["subject_name"], "Matematika")
        self.assertEqual(rq.query_school_assignments(self.db, status="all")["total"], 3)
        self.assertEqual([i["title"] for i in rq.query_school_assignments(self.db, status="done")["items"]], ["Hotový"])

    def test_school_exams_open_by_default(self):
        s = Subject(name="Fyzika")
        self.db.add(s)
        self.db.flush()
        self.db.add_all([
            Exam(title="Zápočet", subject_id=s.id, status="passed", exam_date=date(2026, 6, 1)),
            Exam(title="Zkouška", subject_id=s.id, status="upcoming", exam_date=date(2027, 1, 10)),
        ])
        self.db.commit()
        r = rq.query_school_exams(self.db)
        self.assertEqual([i["title"] for i in r["items"]], ["Zkouška"])
        self.assertEqual(r["items"][0]["subject_name"], "Fyzika")
        self.assertEqual(rq.query_school_exams(self.db, status="all")["total"], 2)

    def test_goals_reuse_rest_logic_and_filter(self):
        self.db.add_all([
            Goal(area="finance", title="Spořit", status="active", priority="high", progress=10),
            Goal(area="school", title="Zkouška", status="completed", priority="low", progress=100),
        ])
        self.db.commit()
        with patch.object(tools, "SessionLocal", self.Session):
            full = tools.get_goals()
            r = rq.query_goals(self.db)
            self.assertEqual(r["items"], full)  # stejný tvar položek jako REST /goals
            self.assertEqual([g["title"] for g in rq.query_goals(self.db, status="open")["items"]], ["Spořit"])
            self.assertEqual([g["title"] for g in rq.query_goals(self.db, area="school")["items"]], ["Zkouška"])

    def test_recent_activity_window_and_area(self):
        now = datetime(2026, 10, 3, 12, 0)
        self.db.add_all([
            ActivityLog(timestamp=datetime(2026, 10, 2, 9, 0), area="finance", action_type="create", summary="Výdaj"),
            ActivityLog(timestamp=datetime(2026, 10, 1, 9, 0), area="work", action_type="create", summary="Směna",
                        delta_json='{"x": 1}'),
            ActivityLog(timestamp=datetime(2026, 8, 1, 9, 0), area="finance", action_type="create", summary="Stará"),
        ])
        self.db.commit()
        r = rq.query_recent_activity(self.db, now_utc=now)
        self.assertEqual([i["summary"] for i in r["items"]], ["Výdaj", "Směna"])
        self.assertNotIn("delta_json", r["items"][0])
        r = rq.query_recent_activity(self.db, area="finance", days=90, now_utc=now)
        self.assertEqual([i["summary"] for i in r["items"]], ["Výdaj", "Stará"])
        self.assertEqual(rq.query_recent_activity(self.db, days=1000, now_utc=now)["filters"]["days"], rq.MAX_ACTIVITY_DAYS)


    def test_ai_tool_call_runs_filtered_query_on_request_session(self):
        """get_finance_transactions z LLM běží přes read_queries se session AI requestu a s filtry."""
        self._finance()
        call = types.SimpleNamespace(id="c1", function=types.SimpleNamespace(
            name="get_finance_transactions", arguments=json.dumps({"transaction_type": "income", "limit": 5}),
        ))
        tool_messages, pending = ai._run_tool_calls(self.db, [call])
        self.assertEqual(pending, [])
        result = json.loads(tool_messages[0]["content"])
        self.assertEqual([i["amount"] for i in result["items"]], [9000])
        self.assertEqual(result["filters"]["limit"], 5)

    def test_bad_filter_value_becomes_tool_error_not_crash(self):
        call = types.SimpleNamespace(id="c1", function=types.SimpleNamespace(
            name="get_work_sessions", arguments=json.dumps({"date_from": "minulý týden"}),
        ))
        tool_messages, _ = ai._run_tool_calls(self.db, [call])
        self.assertEqual(json.loads(tool_messages[0]["content"])["error"], "tool_execution_failed")


if __name__ == "__main__":
    unittest.main()
