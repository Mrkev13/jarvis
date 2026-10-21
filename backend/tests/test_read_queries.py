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

    def test_finance_has_no_ai_read_query(self):
        """MRK-60: Finance transakce AI nečte – žádný read dotaz pro AI tooly neexistuje."""
        self.assertFalse(hasattr(rq, "query_finance_transactions"))

    def test_default_cap_and_envelope(self):
        self.db.add_all([WorkSession(date=date(2026, 9, 1 + i), hours=1, project=f"p{i}", hourly_rate=100)
                         for i in range(25)])
        self.db.commit()
        r = rq.query_work_sessions(self.db)
        self.assertEqual(r["total"], 25)
        self.assertEqual(r["returned"], rq.DEFAULT_LIMIT)
        self.assertTrue(r["truncated"])
        self.assertEqual(rq.query_work_sessions(self.db, limit=500)["filters"]["limit"], rq.MAX_LIMIT)

    def test_invalid_date_raises_readable_error(self):
        with self.assertRaises(ValueError):
            rq.query_work_sessions(self.db, date_from="zítra")

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

    def test_work_sessions_hide_finance_link(self):
        """MRK-60: AI vidí výdělek z práce, ale ne vazbu na Finance ani starý příznak synchronizace."""
        self._finance()
        tx = self.db.query(FinanceTransaction).filter_by(transaction_type="income").one()
        self.db.add(WorkSession(date=date(2026, 9, 30), hours=4, project="Servind", hourly_rate=300,
                                finance_transaction_id=tx.id, sync_to_finance=True))
        self.db.commit()
        [item] = rq.query_work_sessions(self.db)["items"]
        self.assertEqual(item["earnings"], 1200)
        self.assertNotIn("finance_transaction_id", item)
        self.assertNotIn("sync_to_finance", item)

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

    def test_goals_computed_from_finance_are_hidden(self):
        """MRK-60: automatický cíl počítaný z Finance (bilance) je Finance agregát → AI ho nevidí."""
        self._finance()
        self.db.add_all([
            Goal(area="finance", title="Rezerva", status="active", tracking_type="automatic",
                 source="finance_balance", target_value=100000),
            Goal(area="finance", title="Ruční cíl", status="active", progress=10),
        ])
        self.db.commit()
        with patch.object(tools, "SessionLocal", self.Session):
            items = rq.query_goals(self.db)["items"]
        self.assertEqual([g["title"] for g in items], ["Ruční cíl"])

    def test_recent_activity_window_and_area(self):
        now = datetime(2026, 10, 3, 12, 0)
        self.db.add_all([
            ActivityLog(timestamp=datetime(2026, 10, 2, 9, 0), area="school", action_type="create", summary="Úkol"),
            ActivityLog(timestamp=datetime(2026, 10, 1, 9, 0), area="work", action_type="create", summary="Směna",
                        delta_json='{"x": 1}'),
            ActivityLog(timestamp=datetime(2026, 8, 1, 9, 0), area="school", action_type="create", summary="Stará"),
        ])
        self.db.commit()
        r = rq.query_recent_activity(self.db, now_utc=now)
        self.assertEqual([i["summary"] for i in r["items"]], ["Úkol", "Směna"])
        self.assertNotIn("delta_json", r["items"][0])
        r = rq.query_recent_activity(self.db, area="school", days=90, now_utc=now)
        self.assertEqual([i["summary"] for i in r["items"]], ["Úkol", "Stará"])
        self.assertEqual(rq.query_recent_activity(self.db, days=1000, now_utc=now)["filters"]["days"], rq.MAX_ACTIVITY_DAYS)

    def test_recent_activity_never_returns_finance_rows(self):
        """MRK-60: souhrny Finance v Aktivitě nesou částky → AI je nedostane (ani s filtrem area=finance)."""
        now = datetime(2026, 10, 3, 12, 0)
        self.db.add_all([
            ActivityLog(timestamp=datetime(2026, 10, 2, 9, 0), area="finance", action_type="create",
                        summary="Výdaj 120 Kč"),
            ActivityLog(timestamp=datetime(2026, 10, 2, 9, 5), area="work", action_type="sync",
                        entity_type="FinanceTransaction", entity_id=1, summary="Zapsáno z Práce: příjem 1 200 Kč"),
            ActivityLog(timestamp=datetime(2026, 10, 2, 9, 10), area="work", action_type="create", summary="Směna"),
        ])
        self.db.commit()
        self.assertEqual([i["summary"] for i in rq.query_recent_activity(self.db, now_utc=now)["items"]], ["Směna"])
        r = rq.query_recent_activity(self.db, area="finance", now_utc=now)
        self.assertEqual((r["items"], r["total"]), ([], 0))


    def test_timestamps_are_prague_local_with_offset(self):
        """Follow-up z A5: AI ukazovala UTC (05:12) místo pražského času (07:12)."""
        self.db.add_all([
            ActivityLog(timestamp=datetime(2026, 10, 3, 5, 12), area="school", action_type="create", summary="X"),  # SELČ
            ActivityLog(timestamp=datetime(2026, 12, 3, 6, 0), area="school", action_type="create", summary="Y"),  # SEČ
        ])
        self.db.commit()
        stamps = sorted(i["timestamp"] for i in rq.query_recent_activity(
            self.db, days=90, now_utc=datetime(2026, 12, 3, 12, 0))["items"])
        self.assertEqual(stamps, ["2026-10-03T07:12:00+02:00", "2026-12-03T07:00:00+01:00"])

    def test_ai_tool_call_runs_filtered_query_on_request_session(self):
        """get_work_sessions z LLM běží přes read_queries se session AI requestu a s filtry."""
        self.db.add_all([WorkSession(date=date(2026, 9, d), hours=2, project="Servind" if d % 2 else "Jiný",
                                     hourly_rate=300) for d in range(1, 5)])
        self.db.commit()
        call = types.SimpleNamespace(id="c1", function=types.SimpleNamespace(
            name="get_work_sessions", arguments=json.dumps({"project": "servind", "limit": 5}),
        ))
        tool_messages, pending = ai._run_tool_calls(self.db, [call])
        self.assertEqual(pending, [])
        result = json.loads(tool_messages[0]["content"])
        self.assertEqual([i["date"] for i in result["items"]], ["2026-09-03", "2026-09-01"])
        self.assertEqual(result["filters"]["limit"], 5)

    def test_ai_finance_read_call_is_unknown_and_returns_no_data(self):
        """MRK-60: vymyšlené volání bývalého Finance toolu skončí jako unknown_tool, bez dat."""
        self._finance()
        tool_messages = []
        for i, name in enumerate(("get_finance_transactions", "get_finance_summary")):
            call = types.SimpleNamespace(id=f"c{i}", function=types.SimpleNamespace(name=name, arguments="{}"))
            msgs, pending = ai._run_tool_calls(self.db, [call])
            self.assertEqual(pending, [])
            tool_messages += msgs
        for msg in tool_messages:
            self.assertEqual(json.loads(msg["content"])["error"], "unknown_tool")
            self.assertNotIn("9000", msg["content"])

    def test_bad_filter_value_becomes_tool_error_not_crash(self):
        call = types.SimpleNamespace(id="c1", function=types.SimpleNamespace(
            name="get_work_sessions", arguments=json.dumps({"date_from": "minulý týden"}),
        ))
        tool_messages, _ = ai._run_tool_calls(self.db, [call])
        self.assertEqual(json.loads(tool_messages[0]["content"])["error"], "tool_execution_failed")


if __name__ == "__main__":
    unittest.main()
