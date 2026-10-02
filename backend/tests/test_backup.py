import os
import sys
import unittest
import tempfile
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models as _all_models
from database import Base


class BackupTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = Session()
        self.TestSession = Session

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_01_backup_sqlite_success_and_verify(self):
        import backup_service

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir).resolve()
            tmpdb = tmpdir_path / "test.db"

            conn = sqlite3.connect(str(tmpdb))
            conn.execute("CREATE TABLE x (id INTEGER PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO x (value) VALUES (?)", ("test",))
            conn.commit()
            conn.close()

            self.assertTrue(tmpdb.exists(), "Test SQLite DB file should exist")

            with patch.object(backup_service, "_DATABASE_URL", f"sqlite+pysqlite:///{tmpdb}"), \
                 patch.object(backup_service, "BACKUP_ENABLED", True), \
                 patch.object(backup_service, "BACKUP_DIR", str(tmpdir_path)), \
                 patch.object(backup_service, "BACKUP_RETENTION_DAYS", 30), \
                 patch.object(backup_service, "SessionLocal", self.TestSession):

                backup_id = backup_service.run_backup(db_session=self.db)
                self.assertGreaterEqual(backup_id, 1, f"run_backup returned invalid id: {backup_id}")

                log = self.db.query(_all_models.BackupLog).filter(_all_models.BackupLog.id == backup_id).first()
                self.assertIsNotNone(log, "BackupLog should exist")
                self.assertEqual(log.status, "success", f"Backup status should be success, got: {log.status}. Error: {log.error_message}")
                self.assertIsNotNone(log.size_bytes, "size_bytes should be set")
                self.assertGreater(log.size_bytes, 0, "size_bytes should be > 0")
                self.assertIsNotNone(log.checksum, "checksum should be set")
                self.assertTrue(len(log.checksum) > 0, "checksum should not be empty")
                self.assertIsNotNone(log.filename, "filename should be set")
                backup_path = Path(log.filename)
                self.assertTrue(backup_path.exists(), f"Backup file should exist: {log.filename}")
                self.assertTrue(str(backup_path).endswith(".sqlite.gz"), f"Backup file should be .sqlite.gz, got: {backup_path}")

    def test_02_retention_deletes_old_logs_and_files(self):
        import backup_service

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir).resolve()

            old_filename = tmpdir_path / "old_backup.sqlite.gz"
            old_filename.write_bytes(b"fake backup data")
            self.assertTrue(old_filename.exists())

            recent_filename = tmpdir_path / "recent_backup.sqlite.gz"
            recent_filename.write_bytes(b"recent backup data")
            self.assertTrue(recent_filename.exists())

            now = datetime.utcnow()
            old_log = _all_models.BackupLog(
                started_at=now - timedelta(days=60),
                finished_at=now - timedelta(days=60),
                status="success",
                filename=str(old_filename),
                size_bytes=100,
                checksum="abc123",
                duration_seconds=1.0,
                retention_days=30,
            )
            recent_log = _all_models.BackupLog(
                started_at=now - timedelta(days=1),
                finished_at=now - timedelta(days=1),
                status="success",
                filename=str(recent_filename),
                size_bytes=200,
                checksum="def456",
                duration_seconds=1.0,
                retention_days=30,
            )
            self.db.add(old_log)
            self.db.add(recent_log)
            self.db.commit()

            old_log_id = old_log.id
            recent_log_id = recent_log.id

            with patch.object(backup_service, "BACKUP_RETENTION_DAYS", 30):
                deleted = backup_service._apply_retention(self.db)
                self.assertEqual(deleted, 1, f"Should delete exactly 1 old log, got: {deleted}")

            self.db.expire_all()

            old_after = self.db.query(_all_models.BackupLog).filter(_all_models.BackupLog.id == old_log_id).first()
            self.assertIsNone(old_after, "Old BackupLog should be deleted")

            recent_after = self.db.query(_all_models.BackupLog).filter(_all_models.BackupLog.id == recent_log_id).first()
            self.assertIsNotNone(recent_after, "Recent BackupLog should still exist")

            self.assertFalse(old_filename.exists(), "Old backup file should be deleted")
            self.assertTrue(recent_filename.exists(), "Recent backup file should still exist")

    def test_03_should_run_backup_daily_once_per_day(self):
        import backup_service

        now = datetime.utcnow()
        today_3_05 = datetime(now.year, now.month, now.day, 3, 5, 0)

        existing_log = _all_models.BackupLog(
            started_at=today_3_05,
            finished_at=today_3_05 + timedelta(minutes=1),
            status="success",
            filename="/tmp/dummy.sqlite.gz",
            size_bytes=100,
            checksum="abc",
            duration_seconds=1.0,
            retention_days=30,
        )
        self.db.add(existing_log)
        self.db.commit()

        with patch.object(backup_service, "SessionLocal", self.TestSession), \
             patch.object(backup_service, "datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(now.year, now.month, now.day, 4, 0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result1 = backup_service.should_run_backup_daily(hour_of_day=3)
            self.assertFalse(result1, "should_run_backup_daily should be False when already ran today")

        self.db.delete(existing_log)
        self.db.commit()

        with patch.object(backup_service, "SessionLocal", self.TestSession), \
             patch.object(backup_service, "datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(now.year, now.month, now.day, 4, 0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result2 = backup_service.should_run_backup_daily(hour_of_day=3)
            self.assertTrue(result2, "should_run_backup_daily should be True when not ran today")


if __name__ == "__main__":
    unittest.main()
