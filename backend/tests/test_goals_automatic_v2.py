import os
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import (
    Assignment,
    Exam,
    FinanceTransaction,
    Goal,
    Subject,
    WorkSession,
    MffCharacter,
)

from goal_history_service import (
    compute_automatic_goal_current_value_with_ok as compute_automatic_goal_current_value,
    compute_goal_progress_and_value,
)


class GoalsAutomaticV2TestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = Session()

        subj = Subject(name="TestSubject", code="TST", semester="", credits=0, active=True)
        self.db.add(subj)
        self.db.commit()
        self.subject_id = subj.id

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_01_finance_month_income_expenses_year_month(self):
        today_sep_2026 = date(2026, 9, 26)

        sep_inc_50k = FinanceTransaction(
            amount=50000, category="plat", description="září 2026 plat",
            transaction_type="income",
            created_at=datetime(2026, 9, 15, 10, 0, 0),
        )
        sep_exp_15k = FinanceTransaction(
            amount=15000, category="nájem", description="září 2026 nájem",
            transaction_type="expense",
            created_at=datetime(2026, 9, 1, 8, 0, 0),
        )
        aug_inc_30k = FinanceTransaction(
            amount=30000, category="plat", description="srpen 2026 plat",
            transaction_type="income",
            created_at=datetime(2026, 8, 15, 10, 0, 0),
        )
        sep_2025_inc_20k = FinanceTransaction(
            amount=20000, category="plat", description="září 2025 plat (jiný rok)",
            transaction_type="income",
            created_at=datetime(2025, 9, 15, 10, 0, 0),
        )

        self.db.add_all([sep_inc_50k, sep_exp_15k, aug_inc_30k, sep_2025_inc_20k])
        self.db.commit()

        inc_val, inc_ok = compute_automatic_goal_current_value(
            self.db, "finance_month_income", today=today_sep_2026
        )
        self.assertTrue(inc_ok)
        self.assertEqual(inc_val, 50000.0)

        exp_val, exp_ok = compute_automatic_goal_current_value(
            self.db, "finance_month_expenses", today=today_sep_2026
        )
        self.assertTrue(exp_ok)
        self.assertEqual(exp_val, 15000.0)

    def test_02_school_open_assignments_null_counts_as_open(self):
        today = date(2026, 9, 26)

        a_completed = Assignment(
            title="Dokončený úkol", description="",
            due_date=None, priority="medium", status="completed",
            subject_id=self.subject_id,
        )
        a_todo = Assignment(
            title="Rozdělaný úkol", description="",
            due_date=None, priority="medium", status="todo",
            subject_id=self.subject_id,
        )
        a_null = Assignment(
            title="Úkol bez statusu", description="",
            due_date=None, priority="medium", status=None,
            subject_id=self.subject_id,
        )
        a_done = Assignment(
            title="Hotový úkol", description="",
            due_date=None, priority="medium", status="done",
            subject_id=self.subject_id,
        )

        self.db.add_all([a_completed, a_todo, a_null, a_done])
        self.db.commit()

        completed_val, completed_ok = compute_automatic_goal_current_value(
            self.db, "school_completed_assignments", today=today
        )
        self.assertTrue(completed_ok)
        self.assertEqual(completed_val, 2.0)

        open_val, open_ok = compute_automatic_goal_current_value(
            self.db, "school_open_assignments", today=today
        )
        self.assertTrue(open_ok)
        self.assertEqual(open_val, 2.0)

    def test_03_same_result_goal_history_and_tools_same_truth(self):
        today = date(2026, 9, 26)

        s1 = WorkSession(
            date=date(2026, 9, 10), hours=10.0, project="X",
            description="", hourly_rate=500, sync_to_finance=False,
        )
        s2 = WorkSession(
            date=date(2026, 9, 20), hours=6.5, project="Y",
            description="", hourly_rate=500, sync_to_finance=False,
        )
        self.db.add_all([s1, s2])

        fin1 = FinanceTransaction(
            amount=75000, category="plat", description="",
            transaction_type="income",
            created_at=datetime(2026, 9, 5, 9, 0, 0),
        )
        self.db.add(fin1)

        ass1 = Assignment(
            title="Úkol A", description="",
            due_date=None, priority="high", status="todo",
            subject_id=self.subject_id,
        )
        ass2 = Assignment(
            title="Úkol B", description="",
            due_date=None, priority="medium", status=None,
            subject_id=self.subject_id,
        )
        ass3 = Assignment(
            title="Úkol C", description="",
            due_date=None, priority="low", status="completed",
            subject_id=self.subject_id,
        )
        self.db.add_all([ass1, ass2, ass3])

        m1 = MffCharacter(
            name="Thor", tier="T4", level=80, priority="high", status="built",
            uniform="u", ctp="ctp", artifact="a",
            uru_slots_total=20, uru_slots_filled=20, odin_blessings_count=8,
            iso8_set="iso", team_supports="s1",
        )
        m2 = MffCharacter(
            name="Iron Man", tier="T4", level=80, priority="medium", status="built",
            uniform="u", ctp="", artifact="",
            uru_slots_total=20, uru_slots_filled=0, odin_blessings_count=0,
            iso8_set="", team_supports="",
        )
        m3 = MffCharacter(
            name="Hulk", tier="T3", level=80, priority="medium", status="in_progress",
            uniform="", ctp="", artifact="",
            uru_slots_total=20, uru_slots_filled=0, odin_blessings_count=0,
            iso8_set="", team_supports="",
        )
        self.db.add_all([m1, m2, m3])

        self.db.commit()

        sources_to_test = [
            ("work_month_hours", 100.0),
            ("finance_month_income", 200000.0),
            ("school_open_assignments", 5.0),
            ("mff_t4_count", 10.0),
        ]

        for source, target_value in sources_to_test:
            a_cv, a_ok = compute_automatic_goal_current_value(self.db, source, today=today)
            self.assertTrue(a_ok, f"source {source} not ok")

            b_progress = 0
            if float(target_value) > 0:
                b_progress = min(
                    100,
                    max(0, int(round(float(a_cv) / float(target_value) * 100))),
                )
            b_current_value = float(a_cv)

            goal = Goal(
                area="test",
                title=f"Test {source}",
                status="active",
                priority="medium",
                progress=0,
                tracking_type="automatic",
                source=source,
                target_value=target_value,
            )
            self.db.add(goal)
            self.db.flush()

            c_progress, c_current_value = compute_goal_progress_and_value(
                self.db, goal, today=today
            )

            self.assertEqual(
                b_progress,
                c_progress,
                f"progress mismatch source={source}: tools-like={b_progress}, compute_goal={c_progress}",
            )
            self.assertAlmostEqual(
                b_current_value,
                c_current_value if c_current_value is not None else 0.0,
                places=6,
                msg=f"current_value mismatch source={source}: tools-like={b_current_value}, compute_goal={c_current_value}",
            )


if __name__ == "__main__":
    unittest.main()
