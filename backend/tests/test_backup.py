import os
import sys
import json
import hashlib
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
            media_dir = tmpdir_path / "live-media"
            media_dir.mkdir()

            self.assertTrue(tmpdb.exists(), "Test SQLite DB file should exist")

            with patch.object(backup_service, "_DATABASE_URL", f"sqlite+pysqlite:///{tmpdb}"), \
                 patch.object(backup_service, "BACKUP_ENABLED", True), \
                 patch.object(backup_service, "BACKUP_DIR", str(tmpdir_path)), \
                 patch.object(backup_service, "MEDIA_DIR", str(media_dir)), \
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
                run_files = list((tmpdir_path / "runs").glob("backup_*.json"))
                self.assertEqual(len(run_files), 1)
                run = json.loads(run_files[0].read_text(encoding="utf-8"))
                self.assertEqual(run["status"], "success")
                self.assertEqual(run["database"]["sha256"], log.checksum)
                self.assertEqual(run["media"]["file_count"], 0)

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

    def test_04_backup_hour_is_prague_local_time(self):
        import backup_service

        with patch.object(backup_service, "SessionLocal", self.TestSession):
            # léto (CEST = UTC+2): 00:30 UTC = 02:30 Praha, 01:30 UTC = 03:30 Praha
            self.assertFalse(backup_service.should_run_backup_daily(3, now_utc=datetime(2026, 10, 2, 0, 30)))
            self.assertTrue(backup_service.should_run_backup_daily(3, now_utc=datetime(2026, 10, 2, 1, 30)))
            # zima (CET = UTC+1): 01:30 UTC = 02:30 Praha, 02:00 UTC = 03:00 Praha
            self.assertFalse(backup_service.should_run_backup_daily(3, now_utc=datetime(2026, 12, 2, 1, 30)))
            self.assertTrue(backup_service.should_run_backup_daily(3, now_utc=datetime(2026, 12, 2, 2, 0)))

    def test_05_already_ran_today_uses_prague_day(self):
        import backup_service

        # 2. 10. 00:30 Praha = 1. 10. 22:30 UTC → je to záloha z pražského „dnes" (2. 10.)
        self.db.add(_all_models.BackupLog(
            started_at=datetime(2026, 10, 1, 22, 30),
            finished_at=datetime(2026, 10, 1, 22, 31),
            status="success",
            filename="/tmp/dummy.sqlite.gz",
            size_bytes=100,
            checksum="abc",
            duration_seconds=1.0,
            retention_days=30,
        ))
        self.db.commit()

        with patch.object(backup_service, "SessionLocal", self.TestSession):
            # 2. 10. 03:30 Praha → dnes už proběhla → nespouštět
            self.assertFalse(backup_service.should_run_backup_daily(3, now_utc=datetime(2026, 10, 2, 1, 30)))
            # 3. 10. 03:30 Praha → nový den → spustit
            self.assertTrue(backup_service.should_run_backup_daily(3, now_utc=datetime(2026, 10, 3, 1, 30)))

    def test_06_pg_dump_explicit_path_wins(self):
        import backup_service

        with tempfile.TemporaryDirectory() as tmpdir:
            executable = Path(tmpdir) / "pg_dump.exe"
            executable.write_bytes(b"stub")
            with patch.dict(os.environ, {"PG_DUMP_PATH": str(executable)}), \
                 patch.object(backup_service.shutil, "which") as which:
                self.assertEqual(backup_service.find_pg_dump(), str(executable))
                which.assert_not_called()

    def test_07_pg_dump_uses_path_fallback(self):
        import backup_service

        with patch.dict(os.environ, {"PG_DUMP_PATH": ""}), \
             patch.object(backup_service.shutil, "which", return_value="C:/tools/pg_dump.exe"):
            self.assertEqual(backup_service.find_pg_dump(), "C:/tools/pg_dump.exe")

    def test_08_pg_dump_not_found_is_actionable(self):
        import backup_service

        with patch.dict(os.environ, {"PG_DUMP_PATH": ""}), \
             patch.object(backup_service.shutil, "which", return_value=None), \
             patch.object(backup_service.os, "name", "posix"):
            with self.assertRaisesRegex(backup_service.PgDumpNotFound, "PG_DUMP_PATH"):
                backup_service.find_pg_dump()

    def test_09_media_new_unchanged_nested_and_manifest(self):
        import backup_service

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            media = root / "media-source"
            backup = root / "backup"
            nested = media / "wot-replays" / "nested" / "battle.wotreplay"
            nested.parent.mkdir(parents=True)
            nested.write_bytes(b"replay-content")
            expected_hash = hashlib.sha256(b"replay-content").hexdigest()

            with patch.object(backup_service, "MEDIA_DIR", str(media)):
                first = backup_service.sync_media_archive(backup, "first")
                second = backup_service.sync_media_archive(backup, "second")

            self.assertEqual(first["copied"], 1)
            self.assertEqual(second["copied"], 0)
            self.assertEqual(second["skipped"], 1)
            manifest = json.loads(second["manifest_path"].read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["files"][0]["relative_path"], "wot-replays/nested/battle.wotreplay")
            self.assertEqual(manifest["files"][0]["sha256"], expected_hash)
            archived = backup / manifest["files"][0]["archive_path"]
            self.assertEqual(hashlib.sha256(archived.read_bytes()).hexdigest(), expected_hash)

    def test_10_changed_media_is_versioned_without_overwrite(self):
        import backup_service

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            media = root / "source"
            backup = root / "backup"
            source = media / "photos" / "same.jpg"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"old")
            with patch.object(backup_service, "MEDIA_DIR", str(media)):
                first = backup_service.sync_media_archive(backup, "first")
                source.write_bytes(b"new")
                second = backup_service.sync_media_archive(backup, "second")

            first_manifest = json.loads(first["manifest_path"].read_text(encoding="utf-8"))
            second_manifest = json.loads(second["manifest_path"].read_text(encoding="utf-8"))
            first_archive = backup / first_manifest["files"][0]["archive_path"]
            second_archive = backup / second_manifest["files"][0]["archive_path"]
            self.assertEqual(first_archive.read_bytes(), b"old")
            self.assertEqual(second_archive.read_bytes(), b"new")
            self.assertNotEqual(first_archive, second_archive)
            self.assertIn(".versions", second_archive.parts)

    def test_11_deleted_source_is_retained(self):
        import backup_service

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            media = root / "source"
            backup = root / "backup"
            source = media / "wot-replays" / "keep.wotreplay"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"keep-me")
            with patch.object(backup_service, "MEDIA_DIR", str(media)):
                first = backup_service.sync_media_archive(backup, "first")
                source.unlink()
                second = backup_service.sync_media_archive(backup, "second")
            first_manifest = json.loads(first["manifest_path"].read_text(encoding="utf-8"))
            archived = backup / first_manifest["files"][0]["archive_path"]
            self.assertTrue(archived.exists())
            self.assertEqual(second["file_count"], 0)

    def test_12_path_traversal_and_outside_symlink_are_rejected(self):
        import backup_service

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            safe_root = root / "safe"
            safe_root.mkdir()
            outside = root / "outside.bin"
            outside.write_bytes(b"outside")
            with self.assertRaises(backup_service.MediaBackupError):
                backup_service._safe_relative_file(outside, safe_root)
            with self.assertRaises(backup_service.MediaBackupError):
                backup_service._safe_archive_path(safe_root, Path("../escape.bin"))

    def test_13_media_failure_marks_whole_backup_failed(self):
        import backup_service

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tmpdb = root / "test.db"
            sqlite3.connect(str(tmpdb)).close()
            media = root / "media"
            media.mkdir()
            with patch.object(backup_service, "_DATABASE_URL", f"sqlite+pysqlite:///{tmpdb}"), \
                 patch.object(backup_service, "BACKUP_ENABLED", True), \
                 patch.object(backup_service, "BACKUP_DIR", str(root / "backups")), \
                 patch.object(backup_service, "MEDIA_DIR", str(media)), \
                 patch.object(backup_service, "SessionLocal", self.TestSession), \
                 patch.object(backup_service, "sync_media_archive", side_effect=backup_service.MediaBackupError("boom")):
                backup_id = backup_service.run_backup(db_session=self.db)
            log = self.db.get(_all_models.BackupLog, backup_id)
            self.assertEqual(log.status, "failed")
            self.assertIn("media backup failed", log.error_message)

    def test_14_archive_commit_never_overwrites_racing_destination(self):
        import backup_service

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source.wotreplay"
            target = root / "archive" / "battle.wotreplay"
            source.write_bytes(b"source-content")
            expected_hash = hashlib.sha256(b"source-content").hexdigest()
            original_copyfileobj = backup_service.shutil.copyfileobj

            def copy_then_occupy(source_handle, target_handle, length=0):
                original_copyfileobj(source_handle, target_handle, length=length)
                target.write_bytes(b"racing-writer-content")

            with patch.object(backup_service.shutil, "copyfileobj", side_effect=copy_then_occupy):
                with self.assertRaisesRegex(backup_service.MediaBackupError, "obsazen"):
                    backup_service._copy_verified(source, target, expected_hash)

            self.assertEqual(target.read_bytes(), b"racing-writer-content")
            self.assertFalse(target.with_name(f".{target.name}.tmp").exists())


if __name__ == "__main__":
    unittest.main()
