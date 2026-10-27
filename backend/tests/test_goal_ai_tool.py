"""MRK-72: AI `upsert_goal` with an id edits only the given fields (modify_records plan: diff preview, stale check,
undo); without an id it still creates a goal. Regression: an edit used to reset every field the model did not send."""
import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import ai  # noqa: E402
import mutation_service  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from models import Goal  # noqa: E402
from mutation_service import MutationRefused  # noqa: E402


class GoalAiToolTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        db = self.Session()
        goal = Goal(area="personal", title="Naučit se vařit", description="10 nových receptů", status="in_progress",
                    priority="high", progress=40, target_date=date(2026, 11, 1))
        finance = Goal(area="finance", title="Rezerva", tracking_type="automatic", source="finance_balance",
                       target_value=50000, progress=30)
        db.add_all([goal, finance])
        db.commit()
        self.goal_id, self.finance_id = goal.id, finance.id
        db.close()
        self._patches = [patch.object(m, "SessionLocal", self.Session) for m in (ai, tools, mutation_service)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def _prepare(self, **arguments):
        db = self.Session()
        try:
            return ai.prepare_write_action(db, "upsert_goal", arguments)
        finally:
            db.close()

    def _goal(self, goal_id=None):
        db = self.Session()
        try:
            g = db.get(Goal, goal_id or self.goal_id)
            return {k: getattr(g, k) for k in ("area", "title", "description", "status", "priority", "progress",
                                               "target_date")}
        finally:
            db.close()

    def test_editing_only_the_date_keeps_every_other_field(self):
        pending = self._prepare(area="personal", title="Naučit se vařit", id=self.goal_id, target_date="2026-12-01")
        self.assertIn("plan", pending["arguments"], "edit goes through the modify_records plan")
        changes = pending["preview"]["items"][0]["changes"]
        self.assertEqual([c["field"] for c in changes], ["target_date"], "unchanged title is not a change")
        self.assertEqual(self._goal()["target_date"], date(2026, 11, 1), "nothing changes before confirmation")

        result = ai.execute_confirm_action(pending["id"])
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["result"].get("undo_available"))
        self.assertEqual(self._goal(), {
            "area": "personal", "title": "Naučit se vařit", "description": "10 nových receptů",
            "status": "in_progress", "priority": "high", "progress": 40, "target_date": date(2026, 12, 1),
        })

    def test_empty_or_missing_values_never_clear_a_field(self):
        pending = self._prepare(area="personal", title="Naučit se vařit", id=self.goal_id, description="",
                                progress=55, target_date=None)
        self.assertEqual([c["field"] for c in pending["preview"]["items"][0]["changes"]], ["progress"])
        self.assertTrue(ai.execute_confirm_action(pending["id"])["ok"])
        goal = self._goal()
        self.assertEqual((goal["progress"], goal["description"], goal["target_date"]),
                         (55, "10 nových receptů", date(2026, 11, 1)))

    def test_no_real_change_prepares_nothing(self):
        with self.assertRaises(MutationRefused) as ctx:
            self._prepare(area="personal", title="Naučit se vařit", id=self.goal_id, priority="high", description="")
        self.assertEqual(ctx.exception.code, "no_change")

    def test_goal_changed_after_the_proposal_is_not_overwritten(self):
        pending = self._prepare(area="personal", title="Naučit se vařit", id=self.goal_id, progress=60)
        db = self.Session()
        try:
            db.get(Goal, self.goal_id).progress = 45   # edited in the app between proposal and confirmation
            db.commit()
        finally:
            db.close()
        result = ai.execute_confirm_action(pending["id"])
        self.assertFalse(result["ok"])
        self.assertEqual(self._goal()["progress"], 45)

    def test_finance_goal_cannot_be_edited_by_ai(self):
        # MRK-60: the goal entity hides finance goals from the AI, so an id from anywhere finds nothing.
        with self.assertRaises(MutationRefused):
            self._prepare(area="finance", title="Rezerva", id=self.finance_id, priority="low")
        self.assertEqual(self._goal(self.finance_id)["priority"], "medium")

    def test_create_without_id_is_unchanged(self):
        pending = self._prepare(area="hobby", title="Dokončit model", progress=10)
        self.assertNotIn("plan", pending["arguments"])
        self.assertNotIn("preview", pending)
        result = ai.execute_confirm_action(pending["id"])
        self.assertTrue(result["ok"], result)
        db = self.Session()
        try:
            created = db.query(Goal).filter_by(title="Dokončit model").one()
            self.assertEqual((created.area, created.progress, created.status), ("hobby", 10, "active"))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
