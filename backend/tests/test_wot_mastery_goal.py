"""MRK-82: automatic goal source `wot_ace_mastery_count` – every "Mistr" (ace) record counts, repeated ones on the same
tank too; the goal follows milestone create/update/delete in the same transaction."""
import os
import sys
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import wot_service as ws  # noqa: E402
from database import Base  # noqa: E402
from goal_history_service import WOT_ACE_MASTERY_SOURCE, compute_goal_progress_and_value  # noqa: E402
from models import ActivityLog, Goal, GoalProgressHistory  # noqa: E402


class WotMasteryGoalTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.goal = Goal(area="wot", title="dosáhnout 50 M-ek", tracking_type="automatic",
                         source=WOT_ACE_MASTERY_SOURCE, target_value=50, status="active")
        self.db.add(self.goal)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _add(self, tank, mastery="ace"):
        m = ws.create_milestone(self.db, {"tank": tank, "mastery": mastery})
        self.db.commit()
        return m

    def _value(self):
        return compute_goal_progress_and_value(self.db, self.goal)

    def test_every_ace_record_counts_including_repeats_on_one_tank(self):
        self._add("Kranvagn")
        self._add("Kranvagn")        # second M on the same tank counts (decision 2026-10-25)
        self._add("Škoda T 56")
        self._add("IS-7", "first")   # not a Mistr badge
        self._add("T-62A", None)     # memorable battle without a badge
        self.assertEqual(self._value(), (6, 3.0))  # 3 / 50 = 6 %

    def test_goal_follows_create_update_and_delete(self):
        first = self._add("Kranvagn")
        second = self._add("Progetto 65")
        self.assertEqual(self._value()[1], 2.0)

        ws.update_milestone(self.db, second.id, {"mastery": "first"})
        self.db.commit()
        self.assertEqual(self._value()[1], 1.0)

        ws.delete_milestone(self.db, first.id)
        self.db.commit()
        self.assertEqual(self._value()[1], 0.0)

        values = [h.current_value for h in self.db.query(GoalProgressHistory).order_by(GoalProgressHistory.id)]
        self.assertEqual(values, [1.0, 2.0, 1.0, 0.0], "a snapshot per change, in the same transaction")
        snapshots = self.db.query(ActivityLog).filter_by(area="goals", action_type="snapshot").count()
        self.assertEqual(snapshots, 4, "every change moved the percentage by 2 %")

    def test_manual_goal_is_not_touched(self):
        manual = Goal(area="wot", title="ruční", tracking_type="manual", progress=92, status="active")
        self.db.add(manual)
        self.db.commit()
        self._add("Kranvagn")
        self.assertEqual(self.db.query(GoalProgressHistory).filter_by(goal_id=manual.id).count(), 0)
        self.assertEqual(self.db.get(Goal, manual.id).progress, 92)


if __name__ == "__main__":
    unittest.main()
