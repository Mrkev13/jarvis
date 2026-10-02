import os
import sys
import unittest
from datetime import date, datetime

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from goal_history_service import compute_automatic_goal_current_value
from main import _get_finance_with_goal
from models import FinanceTransaction


class FinancePragueMonthTestCase(unittest.TestCase):
    """created_at je naive UTC; měsíční součty se počítají v pražském kalendáři."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)()
        self.db.add_all([
            # 1. 10. 2026 00:30 Praha (CEST) = 30. 9. 22:30 UTC → patří do ŘÍJNA
            FinanceTransaction(amount=1000, category="plat", description="",
                               transaction_type="income", created_at=datetime(2026, 9, 30, 22, 30)),
            # 30. 9. 2026 23:30 Praha = 21:30 UTC → patří do ZÁŘÍ
            FinanceTransaction(amount=200, category="plat", description="",
                               transaction_type="income", created_at=datetime(2026, 9, 30, 21, 30)),
            # 1. 11. 2026 00:30 Praha (CET) = 31. 10. 23:30 UTC → patří do LISTOPADU
            FinanceTransaction(amount=50, category="jídlo", description="",
                               transaction_type="expense", created_at=datetime(2026, 10, 31, 23, 30)),
            # 31. 10. 2026 23:30 Praha = 22:30 UTC → patří do ŘÍJNA
            FinanceTransaction(amount=70, category="jídlo", description="",
                               transaction_type="expense", created_at=datetime(2026, 10, 31, 22, 30)),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_goal_sources_use_prague_month(self):
        october = date(2026, 10, 15)
        september = date(2026, 9, 15)
        self.assertEqual(compute_automatic_goal_current_value(self.db, "finance_month_income", today=october), 1000.0)
        self.assertEqual(compute_automatic_goal_current_value(self.db, "finance_month_income", today=september), 200.0)
        self.assertEqual(compute_automatic_goal_current_value(self.db, "finance_month_expenses", today=october), 70.0)
        self.assertEqual(
            compute_automatic_goal_current_value(self.db, "finance_month_expenses", today=date(2026, 11, 2)), 50.0
        )

    def test_dashboard_month_totals_use_prague_month(self):
        fin = _get_finance_with_goal(self.db, today=date(2026, 10, 1))
        self.assertEqual(fin["this_month_income"], 1000.0)
        self.assertEqual(fin["this_month_expenses"], 70.0)
        self.assertEqual(fin["income"], 1200.0)
        self.assertEqual(fin["expenses"], 120.0)


if __name__ == "__main__":
    unittest.main()
