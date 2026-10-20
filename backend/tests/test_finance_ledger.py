"""MRK-61: Finance ledger – integer money, legacy bridge, void instead of delete, accounts and categories.
Synthetic data only (no real bank values)."""
import os
import re
import sys
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import finance_integrations  # noqa: E402
import goal_history_service  # noqa: E402
import main  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, FinanceTransaction, Goal, WorkSession  # noqa: E402
from modules.finance import money  # noqa: E402
from modules.finance import service as fs  # noqa: E402
from modules.finance.categories import BUILTIN_CATEGORIES, legacy_category_key  # noqa: E402
from modules.finance.models import FinanceAccount, FinanceCategory  # noqa: E402


class LedgerTestBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = self.Session()
        self._patches = [patch.object(main, "SessionLocal", self.Session), patch.object(tools, "SessionLocal", self.Session)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.db.close()
        self.engine.dispose()

    def fresh(self):
        self.db.close()
        self.db = self.Session()
        return self.db

    def category_key(self, tx):
        return self.db.get(FinanceCategory, tx.effective_category_id).key


class MoneyTestCase(unittest.TestCase):
    def test_parse_minor_uses_decimal_text(self):
        self.assertEqual(money.parse_minor("1 234,50"), 123450)
        self.assertEqual(money.parse_minor("0.1"), 10)
        self.assertEqual(money.parse_minor(Decimal("2437.505")), 243751)  # half up
        self.assertEqual(money.parse_minor(5), 500)
        for bad in (0, -5, "abc", None, True, "NaN", "Infinity", 0.5):
            with self.subTest(bad=bad), self.assertRaises(money.MoneyError):
                money.parse_minor(bad)
        self.assertEqual(money.signed_minor(500, "out"), -500)
        self.assertEqual(money.check_currency(" czk "), "CZK")
        with self.assertRaises(money.MoneyError):
            money.check_currency("BTC")

    def test_no_float_in_finance_business_logic(self):
        """Float smí jen legacy most (legacy_compat.py); ostatní moduly/finance pracují s int/Decimal."""
        folder = BACKEND_DIR / "modules" / "finance"
        for path in folder.glob("*.py"):
            if path.name == "legacy_compat.py":
                continue
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                code = re.search(r"\bfloat\(|\bFloat\(|:\s*float\b|->\s*float\b", text)
                self.assertIsNone(code, f"{path.name} používá float")


class LegacyBridgeTestCase(LedgerTestBase):
    def test_legacy_insert_fills_ledger_columns(self):
        self.db.add_all([
            FinanceTransaction(amount=189.9, category="Jídlo", transaction_type="expense", description="oběd",
                               created_at=datetime(2026, 10, 31, 23, 30)),  # v Praze už 1. 11.
            FinanceTransaction(amount=9000, category="Výplata", transaction_type="income"),
            FinanceTransaction(amount=50, category="něco svého", transaction_type="income"),
        ])
        self.db.commit()
        lunch, salary, other_income = self.db.query(FinanceTransaction).order_by(FinanceTransaction.id).all()
        self.assertEqual((lunch.amount_minor, lunch.direction, lunch.currency, lunch.source),
                         (-18990, "out", "CZK", "manual"))
        self.assertEqual(lunch.booked_on, date(2026, 11, 1))
        self.assertEqual(self.db.get(FinanceAccount, lunch.account_id).key, "manual_cash")
        self.assertEqual((self.category_key(lunch), lunch.category_source), ("restaurants", "legacy"))
        self.assertEqual(self.category_key(salary), "salary")
        self.assertEqual(self.category_key(other_income), "income_other", "neznámý příjem → ostatní příjmy")
        self.assertEqual(lunch.search_text, "obed jidlo restaurace a jidlo")
        self.assertEqual(self.db.query(FinanceCategory).count(), len(BUILTIN_CATEGORIES))

    def test_legacy_updates_keep_columns_in_sync(self):
        tx = FinanceTransaction(amount=100, category="Doprava", transaction_type="expense",
                                created_at=datetime(2026, 10, 2, 10))
        self.db.add(tx)
        self.db.commit()
        tx.amount = 150.5  # legacy undo vazby z práce mění jen amount
        self.db.commit()
        self.assertEqual(tx.amount_minor, -15050)
        tx.created_at = datetime(2026, 9, 30, 22, 30)  # test fixture posune den vzniku
        self.db.commit()
        self.assertEqual(tx.booked_on, date(2026, 10, 1))
        tx.transaction_type = "income"
        self.db.commit()
        self.assertEqual((tx.amount_minor, tx.direction, self.category_key(tx)), (15050, "in", "income_other"))

    def test_float_sums_match_integer_sums(self):
        for amount in (0.1, 0.2, 0.3, 1250.55, 33.33):
            self.db.add(FinanceTransaction(amount=amount, category="Ostatní", transaction_type="expense"))
        self.db.commit()
        self.assertEqual(fs.totals_minor(self.db)["expenses_minor"], 10 + 20 + 30 + 125055 + 3333)

    def test_legacy_category_mapping(self):
        self.assertEqual(legacy_category_key("Potraviny", "out"), "food")
        self.assertEqual(legacy_category_key("work", "in"), "salary")
        self.assertEqual(legacy_category_key("Doprava", "in"), "income_other")
        self.assertEqual(legacy_category_key("", "out"), "other")


class TransactionServiceTestCase(LedgerTestBase):
    def test_manual_transaction_is_integer_and_audited_in_same_session(self):
        tx = fs.create_manual_transaction(self.db, amount_minor=18990, direction="out", category="Jídlo",
                                          description="oběd")
        self.db.rollback()  # bez commitu volajícího nic nezůstane – ani audit
        self.assertEqual(self.fresh().query(FinanceTransaction).count(), 0)
        self.assertEqual(self.db.query(ActivityLog).count(), 0)
        tx = fs.create_manual_transaction(self.db, amount_minor=18990, direction="out", category="Jídlo",
                                          description="oběd")
        self.db.commit()
        self.assertEqual((tx.amount_minor, tx.amount, tx.category_source), (-18990, 189.9, "manual"))
        [log] = self.db.query(ActivityLog).all()
        self.assertEqual((log.area, log.action_type, log.entity_id), ("finance", "create", tx.id))
        self.assertIn("189,90", log.summary)
        for amount, direction in ((0, "out"), (-5, "out"), (100, "sideways")):
            with self.subTest(amount=amount, direction=direction), self.assertRaises(fs.FinanceError):
                fs.create_manual_transaction(self.db, amount_minor=amount, direction=direction, category="x")
        with self.assertRaises(fs.FinanceError):
            fs.create_manual_transaction(self.db, amount_minor=1.5, direction="out", category="x")

    def test_void_hides_row_everywhere_but_keeps_history(self):
        keep = fs.create_manual_transaction(self.db, amount_minor=100000, direction="in", category="Výplata")
        gone = fs.create_manual_transaction(self.db, amount_minor=30000, direction="out", category="Jídlo",
                                            description="zrušit mě")
        self.db.add(Goal(area="finance", title="Rezerva", status="active", tracking_type="automatic",
                         source="finance_balance", target_value=10000))
        self.db.commit()
        keep_id, gone_id = keep.id, gone.id
        fs.void_transaction(self.db, gone_id, reason="duplicitní zápis")
        self.db.commit()
        db = self.fresh()
        self.assertIsNotNone(db.get(FinanceTransaction, gone_id).voided_at, "řádek v DB zůstává")
        self.assertEqual(fs.totals_minor(db), {"income_minor": 100000, "expenses_minor": 0, "count": 1})
        self.assertEqual([t["id"] for t in fs.list_transactions(db)], [keep_id])
        self.assertEqual([r[1] for r in finance_integrations.search_finance(db, "")], [keep_id])
        dash = finance_integrations.get_finance_with_goal(db, today=date(2026, 10, 15))
        self.assertEqual((dash["balance"], dash["expenses"], dash["transactions_count"]), (1000.0, 0.0, 1))
        self.assertEqual(goal_history_service.compute_automatic_goal_current_value_with_ok(db, "finance_balance"),
                         (1000.0, True))
        with self.assertRaises(fs.FinanceError) as ctx:
            fs.void_transaction(db, gone_id)
        self.assertEqual(ctx.exception.status, 404)

    def test_imported_rows_cannot_be_voided(self):
        tx = fs.create_manual_transaction(self.db, amount_minor=500, direction="out", category="x")
        tx.source = "import"
        self.db.commit()
        with self.assertRaises(fs.FinanceError) as ctx:
            fs.void_transaction(self.db, tx.id)
        self.assertEqual(ctx.exception.status, 409)
        self.assertIsNone(tx.voided_at)

    def test_month_totals_use_prague_booking_day(self):
        self.db.add_all([
            FinanceTransaction(amount=10, category="x", transaction_type="expense",
                               created_at=datetime(2026, 9, 30, 22, 30)),  # Praha: 1. 10.
            FinanceTransaction(amount=20, category="x", transaction_type="expense",
                               created_at=datetime(2026, 10, 31, 23, 30)),  # Praha: 1. 11.
        ])
        self.db.commit()
        self.assertEqual(fs.month_totals_minor(self.db, date(2026, 10, 5))["expenses_minor"], 1000)
        self.assertEqual(fs.month_totals_minor(self.db, date(2026, 11, 5))["expenses_minor"], 2000)
        self.assertEqual(fs.month_totals_minor(self.db, date(2026, 12, 5))["expenses_minor"], 0)

    def test_work_link_survives_void(self):
        tx = FinanceTransaction(amount=400, category="work", transaction_type="income")
        self.db.add(tx)
        self.db.flush()
        self.db.add(WorkSession(date=date(2026, 9, 7), hours=2, hourly_rate=200, finance_transaction_id=tx.id))
        self.db.commit()
        tx_id = tx.id
        fs.void_transaction(self.db, tx_id)
        self.db.commit()
        self.assertEqual(self.fresh().query(WorkSession).one().finance_transaction_id, tx_id)


class LegacyApiTestCase(LedgerTestBase):
    def test_rest_create_list_summary_and_delete(self):
        result = main.add_finance_transaction(main.FinanceTransactionRequest(
            amount=189.9, category="Jídlo", description="oběd", transaction_type="expense"))
        main.add_finance_transaction(main.FinanceTransactionRequest(
            amount=1000, category="Výplata", transaction_type="income"))
        rows = main.finance_transactions()
        self.assertEqual({r["amount_minor"] for r in rows}, {-18990, 100000})
        lunch = next(r for r in rows if r["id"] == result["id"])
        self.assertEqual((lunch["amount"], lunch["category"], lunch["transaction_type"], lunch["currency"]),
                         (189.9, "Jídlo", "expense", "CZK"))
        self.assertEqual(main.finance_summary(), {"income": 1000.0, "expenses": 189.9, "balance": 810.1,
                                                  "transactions_count": 2})
        main.delete_finance_transaction(result["id"])
        self.assertEqual(main.finance_summary()["expenses"], 0.0)
        with self.assertRaises(main.HTTPException) as ctx:
            main.add_finance_transaction(main.FinanceTransactionRequest(amount=-5, category="x",
                                                                        transaction_type="expense"))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_quick_add_executor_writes_through_service(self):
        out = tools.add_finance_transaction(amount=120.5, category="Doprava", transaction_type="expense",
                                            description="vlak", user_context="quick_add")
        self.assertEqual((out["amount_minor"], out["amount"], out["source"]), (-12050, 120.5, "manual"))
        log = self.fresh().query(ActivityLog).one()
        self.assertEqual((log.user_context, log.area), ("quick_add", "finance"))


class AccountsAndCategoriesTestCase(LedgerTestBase):
    def test_account_identifier_is_masked_and_hashed_only(self):
        account = fs.create_account(self.db, name="Běžný účet", kind="current", institution="Banka",
                                    identifier="123456789/0100")
        self.db.commit()
        self.assertEqual(account.masked_identifier, "…0100")
        self.assertEqual(len(account.identifier_hash), 64)
        self.assertNotIn("123456789", str(fs.account_dict(account)))
        with self.assertRaises(fs.FinanceError) as ctx:
            fs.create_account(self.db, name="Znovu", identifier="123456789 / 0100")
        self.assertEqual(ctx.exception.status, 409)
        for bad in ({"name": " "}, {"name": "x", "kind": "crypto"}, {"name": "x", "currency": "BTC"}):
            with self.subTest(bad=bad), self.assertRaises(fs.FinanceError):
                fs.create_account(self.db, **bad)

    def test_accounts_update_archive_and_builtin(self):
        names = [a["name"] for a in fs.list_accounts(self.db)]
        self.assertEqual(names, ["Ruční / hotovost"], "vestavěný účet existuje vždy")
        manual = self.db.query(FinanceAccount).one()
        with self.assertRaises(fs.FinanceError):
            fs.archive_account(self.db, manual.id)
        account = fs.create_account(self.db, name="Spoření", kind="savings")
        fs.update_account(self.db, account.id, name="Spořicí účet")
        fs.archive_account(self.db, account.id)
        self.db.commit()
        self.assertEqual([a["name"] for a in fs.list_accounts(self.db)], ["Ruční / hotovost"])
        self.assertEqual(len(fs.list_accounts(self.db, include_archived=True)), 2)
        actions = [lg.action_type for lg in self.db.query(ActivityLog).order_by(ActivityLog.id)]
        self.assertEqual(actions, ["create", "update", "archive"])

    def test_categories_builtins_depth_and_archive(self):
        fs.ensure_builtin_categories(self.db)
        fs.ensure_builtin_categories(self.db)  # idempotentní
        self.assertEqual(self.db.query(FinanceCategory).count(), len(BUILTIN_CATEGORIES))
        income = self.db.query(FinanceCategory).filter_by(key="income").one()
        salary = self.db.query(FinanceCategory).filter_by(key="salary").one()
        self.assertEqual(salary.parent_id, income.id)
        child = fs.create_category(self.db, name="Brigády", kind="income", parent_id=income.id)
        with self.assertRaises(fs.FinanceError):
            fs.create_category(self.db, name="Třetí úroveň", kind="income", parent_id=child.id)
        with self.assertRaises(fs.FinanceError):
            fs.create_category(self.db, name="Jiný druh", kind="expense", parent_id=income.id)
        with self.assertRaises(fs.FinanceError):
            fs.create_category(self.db, name="Systém", kind="system")
        with self.assertRaises(fs.FinanceError):
            fs.archive_category(self.db, income.id)  # vestavěná
        parent = fs.create_category(self.db, name="Koníčky", kind="expense")
        fs.create_category(self.db, name="Kola", kind="expense", parent_id=parent.id)
        with self.assertRaises(fs.FinanceError):
            fs.archive_category(self.db, parent.id)  # aktivní podkategorie
        fs.rename_category(self.db, child.id, "Brigády a výpomoc")
        fs.archive_category(self.db, child.id)
        self.db.commit()
        names = {c["name"] for c in fs.list_categories(self.db)}
        self.assertNotIn("Brigády a výpomoc", names)
        self.assertIn("Kola", names)


if __name__ == "__main__":
    unittest.main()
