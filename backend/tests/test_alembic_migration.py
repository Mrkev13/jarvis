import os
import subprocess
import sys
import unittest
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

_sys_path_original = sys.path[:]
for key in list(sys.modules.keys()):
    if key.startswith("alembic"):
        del sys.modules[key]

BACKEND_PATH = str(BACKEND_DIR)
if BACKEND_PATH in sys.path:
    sys.path.remove(BACKEND_PATH)

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from alembic.config import Config as AlembicCfg
from alembic import command as alembic_cmd

if BACKEND_PATH not in sys.path:
    sys.path.append(BACKEND_PATH)


ALEMBIC_INI = str(BACKEND_DIR / "alembic.ini")

BASELINE_TABLES = {
    "wot_resources",
    "wot_grinds",
    "finance_transactions",
    "subjects",
    "assignments",
    "exams",
    "work_sessions",
    "mff_characters",
    "goals",
    "memories",
    "conversations",
    "messages",
    "notifications",
    "goal_progress_history",
    "planner_recommendation_history",
}

STEP_0002_EXTRA = {"activity_logs"}
STEP_0003_EXTRA = {"activity_logs", "pending_actions"}
STEP_0004_EXTRA = {"activity_logs", "pending_actions"}
STEP_0005_EXTRA = {"activity_logs", "pending_actions", "backup_logs"}
STEP_0006_EXTRA = {"activity_logs", "pending_actions", "backup_logs", "auth_sessions"}


def _sqlite_tables(conn):
    rows = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'")
    ).fetchall()
    return {r[0] for r in rows}


def _make_cfg_for_memory_engine(engine) -> AlembicCfg:
    cfg = AlembicCfg(ALEMBIC_INI)
    url = str(engine.url)
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("version_locations", str(BACKEND_DIR / "alembic" / "versions"))
    cfg.set_main_option("prepend_sys_path", str(BACKEND_DIR))
    return cfg


class AlembicMigrationTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False, dir=str(BACKEND_DIR)
        )
        self._tmpfile.close()
        self._db_path = Path(self._tmpfile.name)
        db_url = f"sqlite+pysqlite:///{str(self._db_path)}"
        os.environ["DATABASE_URL"] = db_url
        self.engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
        )
        self.cfg = _make_cfg_for_memory_engine(self.engine)
        self.conn = self.engine.connect()

    def tearDown(self):
        self.conn.close()
        self.engine.dispose()
        try:
            if self._db_path.exists():
                self._db_path.unlink()
        except Exception:
            pass

    def test_01_baseline_applies_up_down(self):
        alembic_cmd.stamp(self.cfg, "base")

        alembic_cmd.upgrade(self.cfg, "0001_initial_baseline")
        tables = _sqlite_tables(self.conn)
        self.assertEqual(tables, BASELINE_TABLES)

        alembic_cmd.upgrade(self.cfg, "0002_activity_log")
        tables = _sqlite_tables(self.conn)
        self.assertEqual(tables, BASELINE_TABLES | STEP_0002_EXTRA)

        alembic_cmd.upgrade(self.cfg, "0003_pending_actions")
        tables = _sqlite_tables(self.conn)
        self.assertEqual(tables, BASELINE_TABLES | STEP_0003_EXTRA)

        alembic_cmd.upgrade(self.cfg, "0004_goals_sources")
        tables = _sqlite_tables(self.conn)
        self.assertEqual(tables, BASELINE_TABLES | STEP_0004_EXTRA)

        alembic_cmd.upgrade(self.cfg, "0005_backup_log")
        tables = _sqlite_tables(self.conn)
        self.assertEqual(tables, BASELINE_TABLES | STEP_0005_EXTRA)

        alembic_cmd.upgrade(self.cfg, "0006_auth_sessions")
        tables = _sqlite_tables(self.conn)
        self.assertEqual(tables, BASELINE_TABLES | STEP_0006_EXTRA)

        alembic_cmd.downgrade(self.cfg, "0005_backup_log")
        tables = _sqlite_tables(self.conn)
        self.assertNotIn("auth_sessions", tables)
        self.assertEqual(tables, BASELINE_TABLES | STEP_0005_EXTRA)

        alembic_cmd.downgrade(self.cfg, "0004_goals_sources")
        tables = _sqlite_tables(self.conn)
        self.assertNotIn("backup_logs", tables)
        self.assertEqual(tables, BASELINE_TABLES | STEP_0004_EXTRA)

        alembic_cmd.downgrade(self.cfg, "0003_pending_actions")
        tables = _sqlite_tables(self.conn)
        self.assertEqual(tables, BASELINE_TABLES | STEP_0003_EXTRA)

        alembic_cmd.downgrade(self.cfg, "0002_activity_log")
        tables = _sqlite_tables(self.conn)
        self.assertNotIn("pending_actions", tables)
        self.assertEqual(tables, BASELINE_TABLES | STEP_0002_EXTRA)

        alembic_cmd.downgrade(self.cfg, "0001_initial_baseline")
        tables = _sqlite_tables(self.conn)
        self.assertNotIn("activity_logs", tables)
        self.assertEqual(tables, BASELINE_TABLES)

        alembic_cmd.downgrade(self.cfg, "base")
        tables = _sqlite_tables(self.conn)
        self.assertEqual(tables, set())

    def test_02_startup_upgrade_repeatable(self):
        alembic_cmd.stamp(self.cfg, "base")

        alembic_cmd.upgrade(self.cfg, "head")
        tables_first = _sqlite_tables(self.conn)
        self.assertEqual(tables_first, BASELINE_TABLES | STEP_0006_EXTRA)

        alembic_cmd.upgrade(self.cfg, "head")
        tables_second = _sqlite_tables(self.conn)
        self.assertEqual(tables_second, tables_first)


class StartupSchemaTestCase(unittest.TestCase):
    """Schéma spravuje výhradně Alembic, spouštěný v lifespan (ne při importu)."""

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False, dir=str(BACKEND_DIR))
        tmp.close()
        self._db_path = Path(tmp.name)
        self.db_url = f"sqlite+pysqlite:///{self._db_path}"
        self._orig_database_url = os.environ.get("DATABASE_URL")

    def tearDown(self):
        if self._orig_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = self._orig_database_url
        try:
            self._db_path.unlink()
        except FileNotFoundError:
            pass

    def _subprocess_env(self) -> dict:
        return dict(
            os.environ,
            DATABASE_URL=self.db_url,
            SCHEDULER_ENABLED="false",
            PYTHONDONTWRITEBYTECODE="1",
        )

    def test_alembic_library_importable_from_backend_dir(self):
        # `python -m uvicorn` z backend/ dává cwd na sys.path[0]; lokální složka
        # alembic/ nesmí zastínit knihovnu (dřív alembic/__init__.py → ModuleNotFoundError).
        r = subprocess.run(
            [sys.executable, "-c", "import alembic.config, alembic.command"],
            cwd=str(BACKEND_DIR), env=self._subprocess_env(),
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_import_main_does_not_touch_schema(self):
        r = subprocess.run(
            [sys.executable, "-c", "import main"],
            cwd=str(BACKEND_DIR), env=self._subprocess_env(),
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        engine = create_engine(self.db_url)
        try:
            with engine.connect() as conn:
                tables = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
            self.assertEqual(tables, [])
        finally:
            engine.dispose()

    def test_lifespan_migrates_fresh_db_to_head_then_seeds(self):
        from sqlalchemy.orm import sessionmaker
        from alembic.script import ScriptDirectory
        from fastapi.testclient import TestClient
        import main
        import scheduler_service
        from models import Subject

        os.environ["DATABASE_URL"] = self.db_url  # čte alembic/env.py
        engine = create_engine(self.db_url)
        orig_session_local = main.SessionLocal
        orig_scheduler_enabled = scheduler_service.SCHEDULER_ENABLED
        main.SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        scheduler_service.SCHEDULER_ENABLED = False
        try:
            with TestClient(main.app):
                pass

            head = ScriptDirectory.from_config(_make_cfg_for_memory_engine(engine)).get_current_head()
            with engine.connect() as conn:
                version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                tables = _sqlite_tables(conn)
            self.assertEqual(version, head)
            self.assertEqual(tables, BASELINE_TABLES | STEP_0006_EXTRA)

            db = main.SessionLocal()
            try:
                self.assertEqual(db.query(Subject).count(), 4)
            finally:
                db.close()
        finally:
            main.SessionLocal = orig_session_local
            scheduler_service.SCHEDULER_ENABLED = orig_scheduler_enabled
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
