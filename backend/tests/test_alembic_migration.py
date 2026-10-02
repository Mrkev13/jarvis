import os
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


if __name__ == "__main__":
    unittest.main()
