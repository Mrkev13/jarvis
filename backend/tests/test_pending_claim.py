"""Roadmap 3.5: claim potvrzení se commitne před spuštěním executoru; audit id je stabilní."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

import ai  # noqa: E402
from database import Base  # noqa: E402
from models import PendingAction  # noqa: E402


class PendingClaimTestCase(unittest.TestCase):
    def setUp(self):
        # Souborová DB a samostatná spojení: jiná session vidí jen commitnutá data (jako executor v produkci).
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.path = Path(path)
        self.engine = create_engine(f"sqlite+pysqlite:///{path}", poolclass=NullPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()
        self.path.unlink(missing_ok=True)

    def test_claim_is_committed_before_execution(self):
        db = self.Session()
        action_id = ai._store_pending_action(db, "add_finance_transaction", {"amount": 1}, ttl_minutes=30)
        stored = ai._confirm_pending_action_atomically(db, action_id)
        self.assertEqual(stored["status"], "executing")
        other = self.Session()  # např. executor nebo druhé potvrzení
        try:
            self.assertEqual(other.get(PendingAction, int(action_id)).status, "executing")
            with self.assertRaises(Exception):  # druhé potvrzení téže akce = 409
                ai._confirm_pending_action_atomically(other, action_id)
        finally:
            other.close()
            db.close()

    def test_audit_entity_id_is_stable(self):
        self.assertEqual(ai._audit_entity_id("42"), 42)
        self.assertEqual(ai._audit_entity_id("abc"), ai._audit_entity_id("abc"))
        self.assertLess(ai._audit_entity_id("abc"), 10**8)


if __name__ == "__main__":
    unittest.main()
