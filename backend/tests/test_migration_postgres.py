"""Opt-in migrace proti skutečnému PostgreSQL (SQLite reflexe některé rozdíly nevidí).

Spuštění jen s TEST_POSTGRES_URL na JEDNORÁZOVOU databázi, jejíž název obsahuje
"test" – typicky:
  * prázdná DB  → ověří čistý řetězec 0001 → head,
  * obnovená kopie produkční DB (pg_dump) stampnutá na 0006 → ověří reálný upgrade.
Test DB upgraduje na head (mění ji), proto odmítne produkční DATABASE_URL.
"""
import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL", "")


@unittest.skipUnless(TEST_POSTGRES_URL, "TEST_POSTGRES_URL není nastaven – PostgreSQL migrace přeskočena")
class PostgresMigrationTestCase(unittest.TestCase):
    def setUp(self):
        from sqlalchemy.engine import make_url
        url = make_url(TEST_POSTGRES_URL)
        if url.get_backend_name() != "postgresql" or "test" not in (url.database or ""):
            self.fail("TEST_POSTGRES_URL musí mířit na PostgreSQL DB s 'test' v názvu")
        self._orig_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = TEST_POSTGRES_URL  # čte alembic/env.py

    def tearDown(self):
        if self._orig_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = self._orig_database_url

    def test_upgrade_to_head_has_no_drift(self):
        from alembic.config import Config
        from alembic import command
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine

        if str(BACKEND_DIR) not in sys.path:
            sys.path.append(str(BACKEND_DIR))
        from database import Base
        import models  # noqa: F401

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        cfg.set_main_option("version_locations", str(BACKEND_DIR / "alembic" / "versions"))
        command.upgrade(cfg, "head")

        engine = create_engine(TEST_POSTGRES_URL)
        try:
            with engine.connect() as conn:
                ctx = MigrationContext.configure(conn)
                self.assertEqual(ctx.get_current_revision(), ScriptDirectory.from_config(cfg).get_current_head())
                diffs = compare_metadata(ctx, Base.metadata)
            self.assertEqual(diffs, [], msg=f"PostgreSQL drift po upgrade head: {diffs}")
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
