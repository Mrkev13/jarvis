import os
import sys
import unittest
import json as _json
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import HTTPException

from database import Base
from models import PendingAction


class PendingActionModelTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_01_model_structure_via_migration(self):
        rows = self.db.execute(text("PRAGMA table_info(pending_actions)")).fetchall()
        insp_cols = {r[1] for r in rows}
        for expected in ["id", "tool", "arguments", "status", "created_at", "expires_at"]:
            self.assertIn(expected, insp_cols, f"Column {expected} missing in pending_actions")

        created = datetime(2026, 9, 20, 10, 0, 0)
        expires = created + timedelta(minutes=10)
        pa = PendingAction(
            tool="add_work_session",
            arguments=_json.dumps({"date_value": "2026-09-20", "hours": 5}),
            created_at=created,
            expires_at=expires,
        )
        self.db.add(pa)
        self.db.commit()
        got = self.db.query(PendingAction).filter(PendingAction.id == pa.id).first()
        self.assertIsNotNone(got)
        self.assertEqual(got.status, "pending")
        self.assertEqual(got.tool, "add_work_session")
        self.assertGreater(got.expires_at, got.created_at)
        args = _json.loads(got.arguments)
        self.assertEqual(args["hours"], 5)


class FSMTransitionTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = Session()
        from ai import _finalize_pending_status, _confirm_pending_action_atomically, reject_pending, _check_pending_expired
        self._finalize = _finalize_pending_status
        self._atomic_confirm = _confirm_pending_action_atomically
        self._reject = reject_pending
        self._check_expired = _check_pending_expired

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _make_pending(self, tool="x", status="pending", created=None, expires=None, args=None):
        created = created or datetime.utcnow()
        expires = expires or (created + timedelta(minutes=10))
        pa = PendingAction(
            tool=tool,
            arguments=_json.dumps(args or {"a": 1}, ensure_ascii=False),
            status=status,
            created_at=created,
            expires_at=expires,
        )
        self.db.add(pa)
        self.db.commit()
        self.db.refresh(pa)
        return str(pa.id)

    def test_02_fsm_transitions(self):
        pid_1 = self._make_pending(tool="t1")
        conf = self._atomic_confirm(self.db, pid_1)
        self.assertEqual(conf["status"], "executing")
        self._finalize(self.db, pid_1, "executed")
        got = self.db.query(PendingAction).filter(PendingAction.id == int(pid_1)).first()
        self.assertEqual(got.status, "executed")

        pid_2 = self._make_pending(tool="t2")
        self._reject(self.db, pid_2)
        got2 = self.db.query(PendingAction).filter(PendingAction.id == int(pid_2)).first()
        self.assertEqual(got2.status, "rejected")

        pid_3_id = self._make_pending(
            tool="t3",
            created=datetime.utcnow() - timedelta(minutes=60),
            expires=datetime.utcnow() - timedelta(minutes=30),
        )
        expired_count = self._check_expired(self.db)
        self.assertGreaterEqual(expired_count, 1)
        got3 = self.db.query(PendingAction).filter(PendingAction.id == int(pid_3_id)).first()
        self.assertEqual(got3.status, "expired")


class AtomicConfirmTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = Session()
        from ai import _confirm_pending_action_atomically
        self._atomic_confirm = _confirm_pending_action_atomically

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_03_atomic_confirm_double_click_1_write(self):
        created = datetime.utcnow()
        pa = PendingAction(
            tool="double_click_tool",
            arguments=_json.dumps({"x": 1}),
            status="pending",
            created_at=created,
            expires_at=created + timedelta(minutes=10),
        )
        self.db.add(pa)
        self.db.commit()
        pid = str(pa.id)

        first = self._atomic_confirm(self.db, pid)
        self.assertEqual(first["status"], "executing")

        with self.assertRaises(HTTPException) as ctx:
            self._atomic_confirm(self.db, pid)
        self.assertEqual(ctx.exception.status_code, 409)

        executing_count = (
            self.db.query(PendingAction)
            .filter(PendingAction.id == int(pid))
            .filter(PendingAction.status == "executing")
            .count()
        )
        self.assertEqual(executing_count, 1)


class RecoveryExpiredTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = Session()
        from ai import _check_pending_expired
        self._check_expired = _check_pending_expired

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_04_startup_recovery_expired(self):
        base = datetime.utcnow()
        pa_already = PendingAction(
            tool="ok_tool",
            arguments=_json.dumps({"ok": True}),
            status="pending",
            created_at=base - timedelta(minutes=5),
            expires_at=base + timedelta(minutes=25),
        )
        pa_expired_1 = PendingAction(
            tool="exp_tool_1",
            arguments=_json.dumps({"e": 1}),
            status="pending",
            created_at=base - timedelta(hours=2),
            expires_at=base - timedelta(hours=1),
        )
        pa_expired_2 = PendingAction(
            tool="exp_tool_2",
            arguments=_json.dumps({"e": 2}),
            status="pending",
            created_at=base - timedelta(hours=3),
            expires_at=base - timedelta(minutes=1),
        )
        pa_done = PendingAction(
            tool="done_tool",
            arguments=_json.dumps({}),
            status="executed",
            created_at=base - timedelta(days=1),
            expires_at=base - timedelta(hours=23),
        )
        self.db.add_all([pa_already, pa_expired_1, pa_expired_2, pa_done])
        self.db.commit()

        expired_count = self._check_expired(self.db)
        self.assertEqual(expired_count, 2)

        pending_stati = {
            p.id: p.status
            for p in self.db.query(PendingAction).all()
        }
        self.assertEqual(pending_stati[pa_already.id], "pending")
        self.assertEqual(pending_stati[pa_expired_1.id], "expired")
        self.assertEqual(pending_stati[pa_expired_2.id], "expired")
        self.assertEqual(pending_stati[pa_done.id], "executed")


class PendingEndpointFiltersTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = Session()
        # Endpoint filtry testujeme bez auth; vynucení auth pokrývá test_auth_enforcement.py.
        # Bez toho by výsledek závisel na AUTH_PIN_HASH v lokálním backend/.env.
        import auth_service
        self._orig_auth_pin_hash = auth_service.AUTH_PIN_HASH
        auth_service.AUTH_PIN_HASH = ""
        from main import app
        from fastapi.testclient import TestClient
        self.client = TestClient(app)
        from database import SessionLocal as _SL
        _SL.configure(bind=self.engine)

    def tearDown(self):
        import auth_service
        auth_service.AUTH_PIN_HASH = self._orig_auth_pin_hash
        self.db.close()
        self.engine.dispose()

    def _insert_many(self):
        statuses = ["pending", "pending", "pending", "pending",
                    "executing", "executed", "executed",
                    "failed", "rejected", "rejected",
                    "expired", "expired"]
        base = datetime.utcnow()
        for i, s in enumerate(statuses):
            created = base - timedelta(minutes=i)
            expires = created + timedelta(minutes=10)
            pa = PendingAction(
                tool=f"tool_{i}_{s}",
                arguments=_json.dumps({"i": i, "s": s}),
                status=s,
                created_at=created,
                expires_at=expires,
            )
            self.db.add(pa)
        self.db.commit()

    def test_05_get_pending_endpoint_filters(self):
        self._insert_many()

        r_all = self.client.get("/pending")
        self.assertEqual(r_all.status_code, 200)
        data_all = r_all.json()
        self.assertEqual(len(data_all["items"]), 12)

        r_pending = self.client.get("/pending", params={"status": "pending"})
        self.assertEqual(r_pending.status_code, 200)
        data_pending = r_pending.json()
        self.assertEqual(len(data_pending["items"]), 4)
        for it in data_pending["items"]:
            self.assertEqual(it["status"], "pending")

        r_limit = self.client.get("/pending", params={"limit": 3})
        self.assertEqual(r_limit.status_code, 200)
        data_limit = r_limit.json()
        self.assertEqual(len(data_limit["items"]), 3)


class RejectEndpointTestCase(unittest.TestCase):
    """/ai/reject mění stav → musí být POST; GET nesmí pending zamítnout."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        import auth_service
        import main
        self._orig_auth_pin_hash = auth_service.AUTH_PIN_HASH
        self._orig_main_session_local = main.SessionLocal
        auth_service.AUTH_PIN_HASH = ""
        main.SessionLocal = self.Session
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

        db = self.Session()
        now = datetime.utcnow()
        pa = PendingAction(
            tool="add_work_session",
            arguments=_json.dumps({"hours": 8}),
            status="pending",
            created_at=now,
            expires_at=now + timedelta(minutes=30),
        )
        db.add(pa)
        db.commit()
        self.pending_id = pa.id
        db.close()

    def tearDown(self):
        import auth_service
        import main
        auth_service.AUTH_PIN_HASH = self._orig_auth_pin_hash
        main.SessionLocal = self._orig_main_session_local
        self.engine.dispose()

    def _status(self) -> str:
        db = self.Session()
        try:
            return db.query(PendingAction).filter(PendingAction.id == self.pending_id).one().status
        finally:
            db.close()

    def test_post_rejects_pending_action(self):
        r = self.client.post(f"/ai/reject/{self.pending_id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "rejected")
        self.assertEqual(self._status(), "rejected")

        r_again = self.client.post(f"/ai/reject/{self.pending_id}")
        self.assertEqual(r_again.status_code, 409)

    def test_get_is_not_allowed_and_leaves_state_untouched(self):
        r = self.client.get(f"/ai/reject/{self.pending_id}")
        self.assertEqual(r.status_code, 405)
        self.assertEqual(self._status(), "pending")


if __name__ == "__main__":
    unittest.main()
