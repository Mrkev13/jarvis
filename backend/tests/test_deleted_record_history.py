"""MRK-29: manual deletion keeps historical facts in the existing audit."""
import json
import os
from pathlib import Path
import sys
import unittest
from datetime import date, datetime
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import main  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, FinanceTransaction, MffCharacter, WorkSession  # noqa: E402


class DeletedRecordHistoryTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.patch = patch.object(main, "SessionLocal", self.Session)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.db.close()
        self.engine.dispose()

    def deleted_delta(self, entity, item_id):
        self.db.expire_all()
        event = self.db.query(ActivityLog).filter_by(entity_type=entity, entity_id=item_id, action_type="delete").one()
        return json.loads(event.delta_json)

    def test_built_mff_delete_preserves_final_build(self):
        item = MffCharacter(name="History fixture", tier="T4", level=80, status="built", uniform="Original uniform", ctp="Rage", artifact="Original artifact", notes="Completed build", role="Dealer", team="Original team", uru_state="20/20", iso8_set="Attack", build_completeness=100, roles=["Dealer"], team_supports="Support", uru_slots_total=20, uru_slots_filled=20, odin_blessings_count=4, updated_at=datetime(2026, 10, 7, 10))
        self.db.add(item)
        self.db.commit()
        item_id = item.id
        result = main.delete_mff_character(item_id)
        self.assertTrue(result["deleted"])
        self.db.expire_all()
        self.assertIsNone(self.db.get(MffCharacter, item_id))
        delta = self.deleted_delta("MffCharacter", item_id)
        for key, expected in {"name": "History fixture", "tier": "T4", "status": "built", "build_completeness": 100, "level": 80, "uniform": "Original uniform", "ctp": "Rage", "artifact": "Original artifact", "notes": "Completed build", "role": "Dealer", "team": "Original team", "uru_state": "20/20", "iso8_set": "Attack", "roles": ["Dealer"], "team_supports": "Support", "uru_slots_total": 20, "uru_slots_filled": 20, "odin_blessings_count": 4, "updated_at": "2026-10-07T10:00:00"}.items():
            with self.subTest(field=key):
                self.assertEqual(delta[key], {"old": expected, "new": None})

    def test_finance_delete_preserves_original_date_and_unlinks_work(self):
        tx = FinanceTransaction(amount=400, category="work", transaction_type="income", description="Recorded work", created_at=datetime(2026, 9, 7, 10))
        self.db.add(tx)
        self.db.flush()
        work = WorkSession(date=date(2026, 9, 7), hours=2, hourly_rate=200, finance_transaction_id=tx.id, sync_to_finance=True)
        self.db.add(work)
        self.db.commit()
        tx_id, work_id = tx.id, work.id
        self.assertTrue(main.delete_finance_transaction(tx_id)["deleted"])
        delta = self.deleted_delta("FinanceTransaction", tx_id)
        self.assertEqual(delta["created_at"], {"old": "2026-09-07T10:00:00", "new": None})
        self.assertEqual(delta["amount"]["old"], 400)
        self.assertIsNone(self.db.get(FinanceTransaction, tx_id))
        surviving = self.db.get(WorkSession, work_id)
        self.assertIsNone(surviving.finance_transaction_id)
        self.assertEqual((surviving.date, surviving.hours), (date(2026, 9, 7), 2))

    def test_work_delete_preserves_finance_link_without_deleting_income(self):
        tx = FinanceTransaction(amount=400, category="work", transaction_type="income")
        self.db.add(tx)
        self.db.flush()
        item = WorkSession(date=date(2026, 9, 7), hours=2, hourly_rate=200, finance_transaction_id=tx.id, sync_to_finance=True)
        self.db.add(item)
        self.db.commit()
        item_id, tx_id = item.id, tx.id
        self.assertTrue(main.delete_work_session(item_id)["deleted"])
        delta = self.deleted_delta("WorkSession", item_id)
        self.assertEqual(delta["finance_transaction_id"], {"old": tx_id, "new": None})
        self.assertEqual(delta["sync_to_finance"], {"old": True, "new": None})
        self.assertEqual(delta["date"]["old"], "2026-09-07")
        self.assertIsNone(self.db.get(WorkSession, item_id))
        self.assertEqual(self.db.get(FinanceTransaction, tx_id).amount, 400)

    def test_delete_and_audit_rollback_together_on_failure(self):
        cases = [(MffCharacter(name="Rollback build", status="built"), main.delete_mff_character), (FinanceTransaction(amount=1, category="test", transaction_type="expense"), main.delete_finance_transaction), (WorkSession(date=date(2026, 10, 7), hours=1), main.delete_work_session)]
        original_log = main.log_activity
        def fail_after_audit(*args, **kwargs):
            original_log(*args, **kwargs)
            args[0].flush()  # The audit INSERT has executed before the simulated failure.
            raise RuntimeError("Simulated write failure")
        for obj, delete in cases:
            with self.subTest(record=type(obj).__name__):
                self.db.add(obj)
                self.db.commit()
                item_id = obj.id
                with patch.object(main, "log_activity", side_effect=fail_after_audit):
                    with self.assertRaisesRegex(RuntimeError, "Simulated write failure"):
                        delete(item_id)
                self.db.expire_all()
                self.assertIsNotNone(self.db.get(type(obj), item_id))
                self.assertEqual(self.db.query(ActivityLog).count(), 0)
