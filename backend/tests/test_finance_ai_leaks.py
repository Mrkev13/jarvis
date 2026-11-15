"""MRK-71: remaining Finance → AI leak paths.

- Activity rows about Finance-computed goals are logged under area "goals" ("Cíl 'Rezerva' 40% → 45%"), so the area
  filter alone let them into the AI activity tool, the daily briefing and the weekly review.
- The chat planner answer is stored in the conversation and sent to the LLM later → no Finance goals there.
- A failed Quick Add Finance write (error text can carry amounts) is logged under Finance, not "system".
"""
import json
import os
import sys
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import ai  # noqa: E402
from briefing_snapshot import build_snapshot  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, Goal  # noqa: E402
from planner_service import generate_plan  # noqa: E402
from read_queries import query_recent_activity  # noqa: E402
from weekly_snapshot import build_weekly_snapshot  # noqa: E402

NOW = datetime(2026, 10, 22, 6, 0)  # Thursday 8:00 Prague
TODAY = date(2026, 10, 22)


class FinanceAiLeaksTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = self.Session()
        soon = TODAY + timedelta(days=2)
        finance = Goal(area="finance", title="Rezerva 150 000", tracking_type="automatic", source="finance_balance",
                       target_value=150000, status="active", target_date=soon)
        manual = Goal(area="personal", title="Naučit se vařit", status="active", progress=40, target_date=soon)
        self.db.add_all([finance, manual])
        self.db.flush()
        self.finance_id, self.manual_id = finance.id, manual.id
        for i, (goal, title) in enumerate(((finance, "Rezerva 150 000"), (manual, "Naučit se vařit"))):
            self.db.add(ActivityLog(timestamp=NOW - timedelta(hours=1 + i), area="goals", action_type="update",
                                    summary=f"Cíl '{title}' 40% → 45%", entity_type="Goal", entity_id=goal.id))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_recent_activity_hides_finance_goal_rows(self):
        out = query_recent_activity(self.db, days=7, now_utc=NOW)
        self.assertEqual([i["entity_id"] for i in out["items"]], [self.manual_id])
        self.assertEqual(out["total"], 1)
        self.assertNotIn("Rezerva", json.dumps(out, ensure_ascii=False))

    def test_briefing_and_weekly_hide_finance_goal_rows(self):
        briefing = build_snapshot(self.db, NOW)
        self.assertNotIn("Rezerva", briefing.render())
        self.assertIn("goals", briefing.changes_summary, "the ordinary goal row still counts")
        weekly = build_weekly_snapshot(self.db, TODAY, NOW).render()
        self.assertNotIn("Rezerva", weekly)

    def test_chat_planner_leaves_out_finance_goals_but_page_keeps_them(self):
        for mode in ("daily", "weekly", "goal_review"):
            chat = json.dumps(generate_plan(self.db, mode, today=TODAY, exclude_finance=True), ensure_ascii=False,
                              default=str)
            self.assertNotIn("Rezerva", chat, mode)
            self.assertIn("Naučit se vařit", chat, mode)
        page = json.dumps(generate_plan(self.db, "daily", today=TODAY), ensure_ascii=False, default=str)
        self.assertIn("Rezerva", page, "the /planner page has no LLM and still shows Finance goals")

    def test_failed_quick_add_finance_write_is_logged_under_finance(self):
        with patch.object(ai, "SessionLocal", self.Session):
            pending = ai.prepare_write_action(self.db, "add_finance_transaction",
                                              {"type": "expense", "amount": 1234, "category": "jídlo"},
                                              source=ai.QUICK_ADD_SOURCE)
            self.db.commit()

            def boom(**_kwargs):
                raise ValueError("Částka 1234 Kč nejde uložit")

            with patch.dict(ai.MANUAL_ONLY_TOOL_FUNCTIONS, {"add_finance_transaction": boom}):
                result = ai.execute_confirm_action(pending["id"])
        self.assertFalse(result["ok"])
        self.db.expire_all()
        row = self.db.query(ActivityLog).filter(ActivityLog.summary.like("%1234%")).one()
        self.assertEqual((row.area, row.action_type), ("finance", "error"))
        self.assertNotIn("1234", json.dumps(query_recent_activity(self.db, days=7), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
