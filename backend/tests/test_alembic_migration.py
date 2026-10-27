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
STEP_0009_EXTRA = {"reminders"}
STEP_0010_EXTRA = {"push_subscriptions", "deliveries"}
STEP_0011_EXTRA = {"daily_briefings"}
STEP_0012_EXTRA = {"weekly_reviews"}
STEP_0013_EXTRA = {"wot_grind_completions", "wot_milestones", "wot_milestone_screenshots"}
STEP_0014_EXTRA = {"wot_replays"}
STEP_0016_EXTRA = {"module_settings"}  # MRK-18 A2
STEP_0017_EXTRA = {"habits", "habit_entries"}  # MRK-21 Návyky
STEP_0018_EXTRA = {"domain_events"}  # MRK-19
STEP_0019_EXTRA = {"calendar_sources", "calendar_events"}  # MRK-30/MRK-31
STEP_0021_EXTRA = {"study_courses", "study_materials"}  # MRK-42
STEP_0022_EXTRA = {"fitness_exercises", "fitness_workouts", "fitness_workout_sets", "fitness_rehab_exercises", "fitness_rehab_sessions", "fitness_rehab_entries"}  # MRK-33
STEP_0024_EXTRA = {"offsite_backup_runs"}  # MRK-57 off-machine backup history
STEP_0025_EXTRA = {"finance_accounts", "finance_categories", "finance_imports", "finance_import_issues",
                   "finance_rules", "finance_transaction_revisions"}  # MRK-61 Finance ledger


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


class _TempSqliteAlembicMixin:
    """Dočasná souborová SQLite DB + Alembic config (sdílí migrační test třídy)."""

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


class AlembicMigrationTestCase(_TempSqliteAlembicMixin, unittest.TestCase):
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
        self.assertEqual(tables_first, BASELINE_TABLES | STEP_0006_EXTRA | STEP_0009_EXTRA | STEP_0010_EXTRA | STEP_0011_EXTRA | STEP_0012_EXTRA | STEP_0013_EXTRA | STEP_0014_EXTRA | STEP_0016_EXTRA | STEP_0017_EXTRA | STEP_0018_EXTRA | STEP_0019_EXTRA | STEP_0021_EXTRA | STEP_0022_EXTRA | STEP_0024_EXTRA | STEP_0025_EXTRA)

        alembic_cmd.upgrade(self.cfg, "head")
        tables_second = _sqlite_tables(self.conn)
        self.assertEqual(tables_second, tables_first)


class SchemaDriftTestCase(_TempSqliteAlembicMixin, unittest.TestCase):
    """Migration head musí přesně odpovídat SQLAlchemy modelům (0007+)."""

    AFFECTED_TABLES = (
        "finance_transactions", "goals", "memories", "mff_characters",
        "auth_sessions", "backup_logs", "pending_actions", "activity_logs",
    )

    def _schema_snapshot(self) -> dict:
        from sqlalchemy import inspect
        insp = inspect(self.conn)
        snap = {}
        for t in self.AFFECTED_TABLES:
            snap[t] = {
                "columns": sorted((c["name"], c["nullable"]) for c in insp.get_columns(t)),
                "indexes": sorted(
                    (ix["name"], tuple(ix["column_names"]), bool(ix["unique"]))
                    for ix in insp.get_indexes(t)
                ),
                "uniques": sorted(tuple(u["column_names"]) for u in insp.get_unique_constraints(t)),
            }
        return snap

    def test_head_matches_models(self):
        from alembic.migration import MigrationContext
        from alembic.autogenerate import compare_metadata
        from database import Base
        import models  # noqa: F401  (registruje tabulky do metadata)

        alembic_cmd.upgrade(self.cfg, "head")
        diffs = compare_metadata(MigrationContext.configure(self.conn), Base.metadata)
        self.assertEqual(diffs, [], msg=f"schema drift mezi migracemi a models.py: {diffs}")

    def test_0007_aborts_on_null_instead_of_inventing_values(self):
        alembic_cmd.upgrade(self.cfg, "0006_auth_sessions")
        self.conn.execute(text(
            "INSERT INTO auth_sessions (token_hash, created_at, expires_at, revoked) "
            "VALUES ('h1', '2026-10-01 10:00:00', '2026-10-02 10:00:00', NULL)"
        ))
        self.conn.commit()

        with self.assertRaises(RuntimeError) as ctx:
            alembic_cmd.upgrade(self.cfg, "head")
        self.assertIn("auth_sessions.revoked: 1 NULL", str(ctx.exception))

        version = self.conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        self.assertEqual(version, "0006_auth_sessions")
        still_null = self.conn.execute(
            text("SELECT COUNT(*) FROM auth_sessions WHERE revoked IS NULL")
        ).scalar()
        self.assertEqual(still_null, 1)

    def test_0008_adds_conversation_summary_columns_and_preserves_rows(self):
        from sqlalchemy import inspect

        alembic_cmd.upgrade(self.cfg, "0007_reconcile_schema_drift")
        self.conn.execute(text("INSERT INTO conversations (title, created_at, updated_at) "
                               "VALUES ('Chat', '2026-10-01 10:00:00', '2026-10-01 10:00:00')"))
        self.conn.commit()

        alembic_cmd.upgrade(self.cfg, "0008_conversation_summary")
        cols = {c["name"]: c["nullable"] for c in inspect(self.conn).get_columns("conversations")}
        self.assertTrue(cols["summary"])
        self.assertTrue(cols["summarized_until_message_id"])
        row = self.conn.execute(text("SELECT title, summary, summarized_until_message_id FROM conversations")).one()
        self.assertEqual(tuple(row), ("Chat", None, None))

        alembic_cmd.downgrade(self.cfg, "0007_reconcile_schema_drift")
        cols = {c["name"] for c in inspect(self.conn).get_columns("conversations")}
        self.assertNotIn("summary", cols)
        self.assertNotIn("summarized_until_message_id", cols)
        self.assertEqual(self.conn.execute(text("SELECT title FROM conversations")).scalar(), "Chat")

    def test_0009_adds_reminders_table_and_downgrades_cleanly(self):
        from sqlalchemy import inspect

        alembic_cmd.upgrade(self.cfg, "0008_conversation_summary")
        self.conn.execute(text("INSERT INTO conversations (title, created_at, updated_at) "
                               "VALUES ('Chat', '2026-10-01 10:00:00', '2026-10-01 10:00:00')"))
        self.conn.commit()
        alembic_cmd.upgrade(self.cfg, "0009_reminders")
        self.assertIn("reminders", _sqlite_tables(self.conn))
        indexes = {ix["name"] for ix in inspect(self.conn).get_indexes("reminders")}
        self.assertIn("ix_reminders_status_due", indexes)
        self.conn.execute(text(
            "INSERT INTO reminders (title, due_at, status, recurrence, fire_count, created_at, updated_at) "
            "VALUES ('fyzio', '2026-10-05 06:00:00', 'scheduled', 'none', 0, "
            "'2026-10-04 10:00:00', '2026-10-04 10:00:00')"))
        self.conn.commit()
        alembic_cmd.downgrade(self.cfg, "0008_conversation_summary")
        self.assertNotIn("reminders", _sqlite_tables(self.conn))
        self.assertEqual(self.conn.execute(text("SELECT title FROM conversations")).scalar(), "Chat")
        alembic_cmd.upgrade(self.cfg, "head")
        self.assertIn("reminders", _sqlite_tables(self.conn))

    def test_0010_adds_delivery_tables_and_downgrades_cleanly(self):
        from sqlalchemy import inspect

        alembic_cmd.upgrade(self.cfg, "0009_reminders")
        self.conn.execute(text(
            "INSERT INTO reminders (title, due_at, status, recurrence, fire_count, created_at, updated_at) "
            "VALUES ('fyzio', '2026-10-05 06:00:00', 'scheduled', 'none', 0, "
            "'2026-10-04 10:00:00', '2026-10-04 10:00:00')"))
        self.conn.commit()
        alembic_cmd.upgrade(self.cfg, "0010_push_delivery")
        self.assertTrue(STEP_0010_EXTRA <= _sqlite_tables(self.conn))
        uniques = {ix["name"] for ix in inspect(self.conn).get_indexes("deliveries") if ix["unique"]}
        self.assertIn("ix_deliveries_dedupe_key", uniques)
        alembic_cmd.downgrade(self.cfg, "0009_reminders")
        self.assertFalse(STEP_0010_EXTRA & _sqlite_tables(self.conn))
        self.assertEqual(self.conn.execute(text("SELECT title FROM reminders")).scalar(), "fyzio")
        alembic_cmd.upgrade(self.cfg, "head")
        self.assertTrue(STEP_0010_EXTRA <= _sqlite_tables(self.conn))

    def test_0011_adds_daily_briefings_and_downgrades_cleanly(self):
        from sqlalchemy import inspect

        alembic_cmd.upgrade(self.cfg, "0010_push_delivery")
        alembic_cmd.upgrade(self.cfg, "0011_daily_briefings")
        uniques = {ix["name"] for ix in inspect(self.conn).get_indexes("daily_briefings") if ix["unique"]}
        self.assertIn("ix_daily_briefings_date", uniques)
        self.conn.execute(text(
            "INSERT INTO daily_briefings (briefing_date, status, \"trigger\", attempts, grounding_removed, "
            "regenerated_count, created_at, updated_at) VALUES ('2026-10-06', 'ready', 'scheduler', 1, 0, 0, "
            "'2026-10-06 05:00:00', '2026-10-06 05:00:00')"))
        self.conn.commit()
        with self.assertRaises(Exception):  # druhý přehled pro stejný den nejde
            self.conn.execute(text(
                "INSERT INTO daily_briefings (briefing_date, status, \"trigger\", attempts, grounding_removed, "
                "regenerated_count, created_at, updated_at) VALUES ('2026-10-06', 'ready', 'manual', 1, 0, 0, "
                "'2026-10-06 06:00:00', '2026-10-06 06:00:00')"))
        self.conn.rollback()
        alembic_cmd.downgrade(self.cfg, "0010_push_delivery")
        self.assertNotIn("daily_briefings", _sqlite_tables(self.conn))
        self.assertTrue(STEP_0010_EXTRA <= _sqlite_tables(self.conn))
        alembic_cmd.upgrade(self.cfg, "head")
        self.assertIn("daily_briefings", _sqlite_tables(self.conn))

    def test_0013_adds_wot_milestones_and_keeps_grinds(self):
        from sqlalchemy import inspect

        alembic_cmd.upgrade(self.cfg, "0012_weekly_reviews")
        self.conn.execute(text("INSERT INTO wot_grinds (tank, xp_remaining, priority, status) VALUES ('Kranvagn', 52000, 'high', 'active')"))
        self.conn.execute(text("INSERT INTO wot_grinds (tank, xp_remaining, priority, status) VALUES ('T-100 LT', 0, 'low', 'completed')"))
        self.conn.commit()
        alembic_cmd.upgrade(self.cfg, "0013_wot_milestones")
        rows = dict(self.conn.execute(text("SELECT tank, xp_start FROM wot_grinds")).fetchall())
        self.assertEqual(rows, {"Kranvagn": 52000.0, "T-100 LT": None}, "průběh aktivních od teď, splněné beze změny")
        self.assertTrue(STEP_0013_EXTRA <= _sqlite_tables(self.conn))
        cols = {c["name"] for c in inspect(self.conn).get_columns("wot_milestone_screenshots")}
        self.assertTrue({"stored_name", "original_name", "content_type", "size_bytes", "caption", "position"} <= cols)
        alembic_cmd.downgrade(self.cfg, "0012_weekly_reviews")
        self.assertFalse(STEP_0013_EXTRA & _sqlite_tables(self.conn))
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM wot_grinds")).scalar(), 2, "grindy přežijí downgrade")
        self.assertNotIn("xp_start", {c["name"] for c in inspect(self.conn).get_columns("wot_grinds")})
        alembic_cmd.upgrade(self.cfg, "head")
        self.assertTrue(STEP_0013_EXTRA <= _sqlite_tables(self.conn))

    def test_0016_adds_module_settings_and_downgrades_cleanly(self):
        alembic_cmd.upgrade(self.cfg, "0015_school_completion")
        self.conn.execute(text("INSERT INTO wot_grinds (tank, xp_remaining, priority, status) VALUES ('Kranvagn', 52000, 'high', 'active')"))
        self.conn.commit()
        alembic_cmd.upgrade(self.cfg, "0016_module_settings")
        self.assertTrue(STEP_0016_EXTRA <= _sqlite_tables(self.conn))
        self.conn.execute(text("INSERT INTO module_settings (module_id, enabled, updated_at) VALUES ('wot', 0, CURRENT_TIMESTAMP)"))
        self.conn.commit()
        alembic_cmd.downgrade(self.cfg, "0015_school_completion")
        self.assertFalse(STEP_0016_EXTRA & _sqlite_tables(self.conn))
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM wot_grinds")).scalar(), 1, "data modulu nedotčena")
        alembic_cmd.upgrade(self.cfg, "head")
        self.assertTrue(STEP_0016_EXTRA <= _sqlite_tables(self.conn))

    def test_0020_adds_calendar_source_presence_without_touching_rows(self):
        from sqlalchemy import inspect

        alembic_cmd.upgrade(self.cfg, "0019_calendar")
        self.conn.execute(text("INSERT INTO calendar_sources (kind, name, enabled, timezone, created_at) "
                               "VALUES ('ics', 'Synthetic', 1, 'Europe/Prague', CURRENT_TIMESTAMP)"))
        self.conn.execute(text("INSERT INTO calendar_events (source_id, external_uid, recurrence_id, title, starts_at, ends_at, "
                               "all_day, timezone, status, sequence, imported_at, created_at, updated_at) VALUES (1, 'u@test', '', "
                               "'Lecture', '2026-10-12 08:00:00', '2026-10-12 09:00:00', 0, 'Europe/Prague', 'active', 0, "
                               "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        self.conn.commit()
        alembic_cmd.upgrade(self.cfg, "0020_calendar_source_presence")
        columns = {c["name"] for c in inspect(self.conn).get_columns("calendar_events")}
        self.assertIn("source_missing_at", columns)
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM calendar_events WHERE source_missing_at IS NULL")).scalar(),
                         1, "existing events stay present")
        alembic_cmd.downgrade(self.cfg, "0019_calendar")
        columns = {c["name"] for c in inspect(self.conn).get_columns("calendar_events")}
        self.assertNotIn("source_missing_at", columns)
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM calendar_events")).scalar(), 1, "no row lost")
        alembic_cmd.upgrade(self.cfg, "head")

    def test_0026_adds_calendar_course_ref_without_touching_rows(self):
        from sqlalchemy import inspect

        alembic_cmd.upgrade(self.cfg, "0025_finance_ledger")
        self.conn.execute(text("INSERT INTO calendar_sources (kind, name, enabled, timezone, created_at) "
                               "VALUES ('ics', 'Synthetic', 1, 'Europe/Prague', CURRENT_TIMESTAMP)"))
        self.conn.execute(text("INSERT INTO calendar_events (source_id, external_uid, recurrence_id, title, starts_at, ends_at, "
                               "all_day, timezone, status, sequence, imported_at, created_at, updated_at) VALUES (1, 'q@test', '', "
                               "'Test closes', '2026-10-12 08:00:00', '2026-10-12 08:00:00', 0, 'Europe/Prague', 'active', 0, "
                               "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        self.conn.commit()
        alembic_cmd.upgrade(self.cfg, "0026_calendar_event_course_ref")
        self.assertIn("course_ref", {c["name"] for c in inspect(self.conn).get_columns("calendar_events")})
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM calendar_events WHERE course_ref IS NULL")).scalar(), 1)
        alembic_cmd.downgrade(self.cfg, "0025_finance_ledger")
        self.assertNotIn("course_ref", {c["name"] for c in inspect(self.conn).get_columns("calendar_events")})
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM calendar_events")).scalar(), 1, "no row lost")
        alembic_cmd.upgrade(self.cfg, "head")

    def test_0021_adds_study_materials_and_downgrades_cleanly(self):
        alembic_cmd.upgrade(self.cfg, "0020_calendar_source_presence")
        self.conn.execute(text("INSERT INTO subjects (name, active) VALUES ('Synthetic subject', 1)"))
        self.conn.commit()
        alembic_cmd.upgrade(self.cfg, "0021_study_materials")
        self.assertTrue(STEP_0021_EXTRA <= _sqlite_tables(self.conn))
        self.conn.execute(text("INSERT INTO study_courses (source, external_id, name, subject_id, created_at, updated_at) "
                               "VALUES ('moodle', '101', 'Synthetic course', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        self.conn.commit()
        alembic_cmd.downgrade(self.cfg, "0020_calendar_source_presence")
        self.assertFalse(STEP_0021_EXTRA & _sqlite_tables(self.conn))
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM subjects")).scalar(), 1, "subjects untouched")
        alembic_cmd.upgrade(self.cfg, "head")
        self.assertTrue(STEP_0021_EXTRA <= _sqlite_tables(self.conn))

    def test_0024_offsite_history_table_round_trip(self):
        from sqlalchemy import inspect
        from sqlalchemy.exc import IntegrityError

        alembic_cmd.upgrade(self.cfg, "0024_offsite_backup_runs")
        insert = ("INSERT INTO offsite_backup_runs (operation, status, outcome, started_at) "
                  "VALUES (:op, :status, 'success', CURRENT_TIMESTAMP)")
        self.conn.execute(text(insert), {"op": "backup", "status": "success"})
        self.conn.commit()
        with self.assertRaises(IntegrityError):
            self.conn.execute(text(insert), {"op": "delete-everything", "status": "success"})
        self.conn.rollback()
        idx = {i["name"] for i in inspect(self.conn).get_indexes("offsite_backup_runs")}
        self.assertEqual(idx, {"ix_offsite_backup_runs_operation_started", "ix_offsite_backup_runs_source_backup_id"})
        alembic_cmd.downgrade(self.cfg, "0023_study_course_export_source")
        self.assertNotIn("offsite_backup_runs", inspect(self.conn).get_table_names())
        alembic_cmd.upgrade(self.cfg, "head")
        self.assertIn("offsite_backup_runs", inspect(self.conn).get_table_names())

    def _seed_legacy_finance(self):
        """Syntetické legacy řádky (žádná reálná data): výdaje, příjem, příjem z práce, prázdný created_at."""
        rows = [  # (amount, category, type, created_at UTC)
            (189.9, "Jídlo", "expense", "2026-10-31 23:30:00"),  # v Praze už 1. 11.
            (1250.5, "Doprava", "expense", "2026-10-02 10:00:00"),
            (9000.0, "Výplata", "income", "2026-10-01 08:00:00"),
            (2437.5, "work", "income", "2026-10-03 09:00:00"),
            (33.33, "něco svého", "expense", None),
        ]
        for amount, category, tx_type, created in rows:
            self.conn.execute(text(
                "INSERT INTO finance_transactions (amount, category, description, transaction_type, created_at) "
                "VALUES (:a, :c, 'syntetický', :t, :d)"), {"a": amount, "c": category, "t": tx_type, "d": created})
        self.conn.execute(text(
            "INSERT INTO work_sessions (date, hours, project, description, hourly_rate, finance_transaction_id, "
            "sync_to_finance) VALUES ('2026-10-03', 6.5, 'Synthetic', '', 375, 4, 1)"))
        self.conn.commit()

    def test_0025_ledger_backfills_legacy_rows_and_keeps_links(self):
        from sqlalchemy import inspect

        alembic_cmd.upgrade(self.cfg, "0024_offsite_backup_runs")
        self._seed_legacy_finance()
        before = self.conn.execute(text(
            "SELECT transaction_type, SUM(amount), COUNT(*) FROM finance_transactions GROUP BY transaction_type")).all()
        alembic_cmd.upgrade(self.cfg, "0025_finance_ledger")
        rows = {r.id: r for r in self.conn.execute(text(
            "SELECT t.id, t.amount, t.category, t.created_at, t.account_id, t.source, t.booked_on, t.amount_minor, "
            "t.currency, t.direction, t.review_flag, c.key AS cat, t.category_source, a.key AS account "
            "FROM finance_transactions t JOIN finance_categories c ON c.id = t.effective_category_id "
            "JOIN finance_accounts a ON a.id = t.account_id")).all()}
        self.assertEqual(len(rows), 5)
        self.assertEqual({r.account for r in rows.values()}, {"manual_cash"})
        self.assertEqual({r.currency for r in rows.values()}, {"CZK"})
        # stejné součty po typu: Σ amount_minor / 100 = původní Σ amount
        for tx_type, total, count in before:
            direction = "in" if tx_type == "income" else "out"
            minor = [r.amount_minor for r in rows.values() if r.direction == direction]
            self.assertEqual(len(minor), count)
            self.assertAlmostEqual(abs(sum(minor)) / 100, total, places=2)
        self.assertEqual((rows[1].amount_minor, rows[1].booked_on, rows[1].cat), (-18990, "2026-11-01", "restaurants"))
        self.assertEqual((rows[2].amount_minor, rows[2].cat), (-125050, "transport"))
        self.assertEqual((rows[3].amount_minor, rows[3].cat, rows[3].source), (900000, "salary", "manual"))
        self.assertEqual((rows[4].cat, rows[4].source), ("salary", "work_sync"), "propojení s prací → work_sync")
        self.assertEqual((rows[5].cat, rows[5].amount_minor, rows[5].created_at), ("other", -3333, None))
        self.assertIsNotNone(rows[5].booked_on, "chybějící created_at → den migrace, created_at zůstává NULL")
        self.assertEqual({r.category_source for r in rows.values()}, {"legacy"})
        self.assertEqual({r.category for r in rows.values()},
                         {"Jídlo", "Doprava", "Výplata", "work", "něco svého"}, "legacy sloupce beze změny")
        self.assertEqual(self.conn.execute(text("SELECT finance_transaction_id FROM work_sessions")).scalar(), 4)
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM finance_categories")).scalar(), 15)
        idx = {i["name"] for i in inspect(self.conn).get_indexes("finance_transactions")}
        self.assertTrue({"ix_finance_transactions_id", "ix_finance_transactions_account_booked",
                         "ix_finance_transactions_booked_on", "ix_finance_transactions_category_booked",
                         "ix_finance_transactions_fingerprint"} <= idx)
        # round trip: bez nových dat jde downgrade čistě a legacy řádky zůstanou
        alembic_cmd.downgrade(self.cfg, "0024_offsite_backup_runs")
        cols = {c["name"] for c in inspect(self.conn).get_columns("finance_transactions")}
        self.assertEqual(cols, {"id", "amount", "category", "description", "transaction_type", "created_at"})
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM finance_transactions")).scalar(), 5)
        self.assertFalse(STEP_0025_EXTRA & set(inspect(self.conn).get_table_names()))
        alembic_cmd.upgrade(self.cfg, "head")
        self.assertEqual(self.conn.execute(text(
            "SELECT COUNT(*) FROM finance_transactions WHERE amount_minor IS NOT NULL")).scalar(), 5)

    def test_0025_constraints_and_downgrade_guard(self):
        from sqlalchemy.exc import IntegrityError

        alembic_cmd.upgrade(self.cfg, "0024_offsite_backup_runs")
        self._seed_legacy_finance()
        alembic_cmd.upgrade(self.cfg, "0025_finance_ledger")
        bad = [  # znaménko neodpovídá směru, neznámý zdroj, chybějící účet
            "UPDATE finance_transactions SET amount_minor = 100 WHERE id = 1",
            "UPDATE finance_transactions SET source = 'scraped' WHERE id = 1",
            "UPDATE finance_transactions SET account_id = NULL WHERE id = 1",
        ]
        for sql in bad:
            with self.subTest(sql=sql), self.assertRaises(IntegrityError):
                self.conn.execute(text(sql))
            self.conn.rollback()
        self.conn.execute(text("UPDATE finance_transactions SET voided_at = CURRENT_TIMESTAMP WHERE id = 2"))
        self.conn.commit()
        with self.assertRaises(Exception) as ctx:
            alembic_cmd.downgrade(self.cfg, "0024_offsite_backup_runs")  # zrušený řádek by po downgrade ožil
        self.assertIn("voided rows", str(ctx.exception))
        self.conn.rollback()
        self.conn.execute(text("UPDATE finance_transactions SET voided_at = NULL WHERE id = 2"))
        self.conn.execute(text(
            "INSERT INTO finance_accounts (name, kind, currency, created_at) VALUES ('Účet', 'current', 'CZK', "
            "CURRENT_TIMESTAMP)"))
        self.conn.commit()
        with self.assertRaises(Exception) as ctx:
            alembic_cmd.downgrade(self.cfg, "0024_offsite_backup_runs")
        self.assertIn("user accounts", str(ctx.exception))
        self.conn.rollback()
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM finance_accounts")).scalar(), 2)

    def test_0023_allows_export_source_keeps_rows_and_guards_downgrade(self):
        from sqlalchemy import inspect
        from sqlalchemy.exc import IntegrityError

        insert = ("INSERT INTO study_courses (source, external_id, name, created_at, updated_at) "
                  "VALUES (:source, :ext, 'Synthetic course', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        alembic_cmd.upgrade(self.cfg, "0022_fitness")
        self.conn.execute(text(insert), {"source": "moodle", "ext": "101"})
        self.conn.commit()
        with self.assertRaises(IntegrityError):
            self.conn.execute(text(insert), {"source": "moodle_export", "ext": "900001"})
        self.conn.rollback()
        alembic_cmd.upgrade(self.cfg, "0023_study_course_export_source")
        self.conn.execute(text(insert), {"source": "moodle_export", "ext": "900001"})
        self.conn.commit()
        with self.assertRaises(IntegrityError):
            self.conn.execute(text(insert), {"source": "scraped", "ext": "1"})
        self.conn.rollback()
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM study_courses")).scalar(), 2, "rows preserved")
        idx = {i["name"] for i in inspect(self.conn).get_indexes("study_courses")}
        self.assertIn("ix_study_courses_subject_id", idx, "batch recreation keeps the index")
        with self.assertRaises(Exception):
            alembic_cmd.downgrade(self.cfg, "0022_fitness")  # refuses while export rows exist
        self.conn.rollback()
        self.conn.execute(text("DELETE FROM study_courses WHERE source = 'moodle_export'"))
        self.conn.commit()
        alembic_cmd.downgrade(self.cfg, "0022_fitness")
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM study_courses")).scalar(), 1)
        alembic_cmd.upgrade(self.cfg, "head")

    def test_0018_adds_domain_events_and_downgrades_cleanly(self):
        from sqlalchemy import inspect

        alembic_cmd.upgrade(self.cfg, "0017_habits")
        self.conn.execute(text("INSERT INTO module_settings (module_id, enabled, updated_at) VALUES ('mff', 0, CURRENT_TIMESTAMP)"))
        self.conn.commit()
        alembic_cmd.upgrade(self.cfg, "0018_domain_events")
        self.assertTrue(STEP_0018_EXTRA <= _sqlite_tables(self.conn))
        idx = {i["name"] for i in inspect(self.conn).get_indexes("domain_events")}
        self.assertTrue({"ix_domain_events_occurred_at", "ix_domain_events_event_type", "ix_domain_events_module_id"} <= idx)
        for _ in (1, 2):
            self.conn.execute(text("INSERT INTO domain_events (event_type, aggregate_type, occurred_at, payload) "
                                   "VALUES ('system.module.disabled', 'module', CURRENT_TIMESTAMP, '{}')"))
        self.conn.commit()
        ids = [r[0] for r in self.conn.execute(text("SELECT id FROM domain_events ORDER BY id"))]
        self.assertEqual(len(set(ids)), 2, "monotónní id")
        alembic_cmd.downgrade(self.cfg, "0017_habits")
        self.assertFalse(STEP_0018_EXTRA & _sqlite_tables(self.conn))
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM module_settings")).scalar(), 1, "data nedotčena")
        alembic_cmd.upgrade(self.cfg, "head")
        self.assertTrue(STEP_0018_EXTRA <= _sqlite_tables(self.conn))

    def test_0017_adds_habits_and_downgrades_cleanly(self):
        alembic_cmd.upgrade(self.cfg, "0016_module_settings")
        self.conn.execute(text("INSERT INTO module_settings (module_id, enabled, updated_at) VALUES ('wot', 0, CURRENT_TIMESTAMP)"))
        self.conn.commit()
        alembic_cmd.upgrade(self.cfg, "0017_habits")
        self.assertTrue(STEP_0017_EXTRA <= _sqlite_tables(self.conn))
        self.conn.execute(text("INSERT INTO habits (name, kind, active, created_at) VALUES ('Rehab', 'check', 1, CURRENT_TIMESTAMP)"))
        self.conn.execute(text("INSERT INTO habit_entries (habit_id, date, state, created_at, updated_at) "
                               "VALUES (1, '2026-10-07', 'done', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        self.conn.commit()
        with self.assertRaises(Exception):  # jeden záznam na návyk a den
            self.conn.execute(text("INSERT INTO habit_entries (habit_id, date, state, created_at, updated_at) "
                                   "VALUES (1, '2026-10-07', 'skipped', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
        self.conn.rollback()
        alembic_cmd.downgrade(self.cfg, "0016_module_settings")
        self.assertFalse(STEP_0017_EXTRA & _sqlite_tables(self.conn))
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM module_settings")).scalar(), 1, "jiná data nedotčena")
        alembic_cmd.upgrade(self.cfg, "head")
        self.assertTrue(STEP_0017_EXTRA <= _sqlite_tables(self.conn))

    def test_0014_adds_wot_replays_and_keeps_milestones(self):
        from sqlalchemy import inspect

        alembic_cmd.upgrade(self.cfg, "0013_wot_milestones")
        self.conn.execute(text("INSERT INTO wot_milestones (milestone_type, tank, favorite, created_at, updated_at) "
                               "VALUES ('mastery', 'Progetto 65', 0, '2026-10-07 18:00:00', '2026-10-07 18:00:00')"))
        self.conn.commit()
        alembic_cmd.upgrade(self.cfg, "0014_wot_replays")
        self.assertIn("wot_replays", _sqlite_tables(self.conn))
        cols = {c["name"] for c in inspect(self.conn).get_columns("wot_replays")}
        self.assertTrue({"stored_filename", "sha256", "file_size", "parser_status", "tags", "linked_milestone_id"} <= cols)
        alembic_cmd.downgrade(self.cfg, "0013_wot_milestones")
        self.assertNotIn("wot_replays", _sqlite_tables(self.conn))
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM wot_milestones")).scalar(), 1, "milníky přežijí downgrade")
        alembic_cmd.upgrade(self.cfg, "head")
        self.assertIn("wot_replays", _sqlite_tables(self.conn))

    def test_0015_adds_school_completion_columns_and_keeps_data(self):
        from sqlalchemy import inspect

        alembic_cmd.upgrade(self.cfg, "0014_wot_replays")
        self.conn.execute(text("INSERT INTO subjects (name, code, semester, credits, active) VALUES ('Fyzika', 'F1', 'ZS', 5, 1)"))
        self.conn.execute(text("INSERT INTO assignments (title, description, priority, status, subject_id) VALUES ('Sada', '', 'high', 'done', 1)"))
        self.conn.execute(text("INSERT INTO exams (title, exam_type, status, notes, subject_id) VALUES ('Zápočet', 'test', 'passed', '', 1)"))
        self.conn.commit()
        alembic_cmd.upgrade(self.cfg, "0015_school_completion")
        self.assertTrue({"completed_at"} <= {c["name"] for c in inspect(self.conn).get_columns("assignments")})
        self.assertTrue({"completed_at", "result_type", "result_value"} <= {c["name"] for c in inspect(self.conn).get_columns("exams")})
        self.assertEqual(self.conn.execute(text("SELECT status, completed_at FROM assignments")).fetchone(), ("done", None),
                         "starší hotové položky zůstanou hotové, jen bez času")
        alembic_cmd.downgrade(self.cfg, "0014_wot_replays")
        self.assertNotIn("result_type", {c["name"] for c in inspect(self.conn).get_columns("exams")})
        self.assertEqual(self.conn.execute(text("SELECT COUNT(*) FROM exams")).scalar(), 1)
        alembic_cmd.upgrade(self.cfg, "head")

    def test_0012_adds_weekly_reviews_and_downgrades_cleanly(self):
        from sqlalchemy import inspect

        alembic_cmd.upgrade(self.cfg, "0011_daily_briefings")
        alembic_cmd.upgrade(self.cfg, "0012_weekly_reviews")
        uniques = {ix["name"] for ix in inspect(self.conn).get_indexes("weekly_reviews") if ix["unique"]}
        self.assertIn("ix_weekly_reviews_week_start", uniques)
        insert = ("INSERT INTO weekly_reviews (week_start, status, \"trigger\", attempts, grounding_fixes, "
                  "regenerated_count, created_at, updated_at) VALUES ('2026-10-05', 'ready', '{t}', 1, 0, 0, "
                  "'2026-10-11 17:00:00', '2026-10-11 17:00:00')")
        self.conn.execute(text(insert.format(t="scheduler")))
        self.conn.commit()
        with self.assertRaises(Exception):  # druhý přehled pro stejný týden nejde
            self.conn.execute(text(insert.format(t="manual")))
        self.conn.rollback()
        alembic_cmd.downgrade(self.cfg, "0011_daily_briefings")
        self.assertNotIn("weekly_reviews", _sqlite_tables(self.conn))
        self.assertIn("daily_briefings", _sqlite_tables(self.conn))
        alembic_cmd.upgrade(self.cfg, "head")
        self.assertIn("weekly_reviews", _sqlite_tables(self.conn))

    def test_0007_downgrade_restores_0006_shape(self):
        alembic_cmd.upgrade(self.cfg, "0006_auth_sessions")
        before = self._schema_snapshot()

        alembic_cmd.upgrade(self.cfg, "0007_reconcile_schema_drift")
        self.assertNotEqual(self._schema_snapshot(), before)

        alembic_cmd.downgrade(self.cfg, "0006_auth_sessions")
        self.assertEqual(self._schema_snapshot(), before)


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
            self.assertEqual(tables, BASELINE_TABLES | STEP_0006_EXTRA | STEP_0009_EXTRA | STEP_0010_EXTRA | STEP_0011_EXTRA | STEP_0012_EXTRA | STEP_0013_EXTRA | STEP_0014_EXTRA | STEP_0016_EXTRA | STEP_0017_EXTRA | STEP_0018_EXTRA | STEP_0019_EXTRA | STEP_0021_EXTRA | STEP_0022_EXTRA | STEP_0024_EXTRA | STEP_0025_EXTRA)

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
