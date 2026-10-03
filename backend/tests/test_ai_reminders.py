"""Phase D: AI tooly připomínek přes pending akce (fake LLM, bez Groq)."""
import json
import os
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import ai  # noqa: E402
import context_service  # noqa: E402
import main  # noqa: E402
import reminder_actions  # noqa: E402
import reminder_service as rs  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from models import PendingAction, Reminder  # noqa: E402
from tool_router import route_tools  # noqa: E402

NOW = datetime(2026, 10, 4, 12, 0)  # neděle 14:00 Praha


def _message(content=None, tool_calls=None):
    msg = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None)


def _call(name, args):
    return types.SimpleNamespace(id="c1", function=types.SimpleNamespace(name=name, arguments=json.dumps(args)))


class AiReminderTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.clock = [NOW]
        self.script: list = []
        self.calls: list = []

        def fake_llm(api_messages, **kwargs):
            self.calls.append({"messages": [dict(m) for m in api_messages], **kwargs})
            return self.script.pop(0)

        self._patches = [
            patch.object(ai, "SessionLocal", self.Session),
            patch.object(tools, "SessionLocal", self.Session),
            patch.object(reminder_actions, "SessionLocal", self.Session),
            patch.object(ai, "_llm_create_with_retry", fake_llm),
            patch.object(ai, "_build_context_safely", lambda db, message: None),
            patch.object(rs, "utc_now", lambda: self.clock[0]),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def q(self, fn):
        db = self.Session()
        try:
            return fn(db)
        finally:
            db.close()

    def ask(self, text, tool, args, answer="Připraveno."):
        self.script = [_message(tool_calls=[_call(tool, args)]), _message(content=answer)]
        result = ai.ask_ai([{"role": "user", "content": text}])
        self.assertEqual(self.script, [])
        return result

    def last_tool_result(self):
        return json.loads(self.calls[-1]["messages"][-1]["content"])

    def reminders(self):
        return self.q(lambda db: db.query(Reminder).order_by(Reminder.id).all())

    def seed(self, **kw):
        def go(db):
            r = rs.create_from_spec(db, rs.build_spec(now=self.clock[0], **kw))
            db.commit()
            return r.id
        return self.q(go)

    # ---- vytvoření ----
    def test_create_tomorrow_at_8_is_pending_then_confirmed(self):
        result = self.ask("připomeň mi zítra v 8 fyzio", "add_reminder",
                          {"title": "fyzio", "due_local": "2026-10-05T08:00"})
        [pending] = result["pending_actions"]
        self.assertEqual(pending["preview"]["kind"], "create")
        self.assertEqual(pending["preview"]["items"][0]["changes"][0]["new"], "po 5. 10. 2026 08:00")
        self.assertEqual(self.reminders(), [], "nic se nevytvoří před potvrzením")
        self.assertEqual(self.calls[0]["tools"] and {t["function"]["name"] for t in self.calls[0]["tools"]}
                         & {"add_reminder", "add_work_session", "manage_reminder"}, {"add_reminder"})
        outcome = ai.execute_confirm_action(pending["id"])
        self.assertTrue(outcome["ok"], outcome)
        [r] = self.reminders()
        self.assertEqual((r.title, r.due_at, r.status), ("fyzio", datetime(2026, 10, 5, 6, 0), "scheduled"))
        again = ai.execute_confirm_action(pending["id"])
        self.assertFalse(again["ok"])
        self.assertEqual(len(self.reminders()), 1, "opakované potvrzení nevytvoří druhou připomínku")

    def test_relative_time_is_captured_at_proposal(self):
        result = self.ask("připomeň mi za 2 hodiny rotoped", "add_reminder", {"title": "rotoped", "in_minutes": 120})
        self.clock[0] = NOW + timedelta(minutes=20)  # potvrzeno o 20 minut později
        self.assertTrue(ai.execute_confirm_action(result["pending_actions"][0]["id"])["ok"])
        self.assertEqual(self.reminders()[0].due_at, NOW + timedelta(hours=2))

    def test_weekly_reminder(self):
        result = self.ask("připomeň mi každou neděli v 19:00 WoT plán", "add_reminder",
                          {"title": "WoT plán", "recurrence": "weekly", "weekdays": "6", "time_local": "19:00"})
        ai.execute_confirm_action(result["pending_actions"][0]["id"])
        [r] = self.reminders()
        self.assertEqual((r.recurrence, r.weekdays, r.local_time, r.due_at),
                         ("weekly", "6", "19:00", datetime(2026, 10, 4, 17, 0)))

    def test_rejected_create_does_nothing(self):
        result = self.ask("připomeň mi zítra v 8 fyzio", "add_reminder",
                          {"title": "fyzio", "due_local": "2026-10-05T08:00"})
        self.q(lambda db: ai.reject_pending(db, result["pending_actions"][0]["id"]))
        self.assertEqual(self.reminders(), [])
        self.assertFalse(ai.execute_confirm_action(result["pending_actions"][0]["id"])["ok"])
        self.assertEqual(self.reminders(), [])

    def test_invalid_create_is_not_prepared(self):
        result = self.ask("připomeň mi včera fyzio", "add_reminder",
                          {"title": "fyzio", "due_local": "2026-10-03T08:00"}, answer="Ten čas už byl.")
        self.assertEqual(result["pending_actions"], [])
        self.assertEqual(self.last_tool_result()["status"], "not_prepared")
        self.assertEqual(self.q(lambda db: db.query(PendingAction).count()), 0)

    # ---- úpravy ----
    def test_shift_by_an_hour(self):
        rid = self.seed(title="rotoped", in_minutes=120)
        result = self.ask("posuň tu připomínku o hodinu", "manage_reminder",
                          {"action": "update", "target": {"text": "rotoped"}, "shift_minutes": 60})
        pending = result["pending_actions"][0]
        change = pending["preview"]["items"][0]["changes"][0]
        self.assertEqual((change["old"], change["new"]), ("ne 4. 10. 2026 16:00", "ne 4. 10. 2026 17:00"))
        self.assertEqual(self.q(lambda db: db.get(Reminder, rid).due_at), NOW + timedelta(hours=2))
        self.assertTrue(ai.execute_confirm_action(pending["id"])["ok"])
        self.assertEqual(self.q(lambda db: db.get(Reminder, rid).due_at), NOW + timedelta(hours=3))

    def test_cancel_snooze_and_complete(self):
        rotoped = self.seed(title="rotoped", in_minutes=30)
        fyzio = self.seed(title="fyzio", in_minutes=10)
        result = self.ask("zruš připomínku na rotoped", "manage_reminder",
                          {"action": "cancel", "target": {"text": "rotoped"}})
        ai.execute_confirm_action(result["pending_actions"][0]["id"])
        self.assertEqual(self.q(lambda db: db.get(Reminder, rotoped).status), "cancelled")

        self.clock[0] = NOW + timedelta(minutes=11)
        self.q(lambda db: rs.process_due_reminders(db))
        result = self.ask("odlož připomínku fyzio o 15 minut", "manage_reminder",
                          {"action": "snooze", "target": {"text": "fyzio"}, "snooze_minutes": 15})
        ai.execute_confirm_action(result["pending_actions"][0]["id"])
        r = self.q(lambda db: db.get(Reminder, fyzio))
        self.assertEqual((r.status, r.due_at), ("scheduled", NOW + timedelta(minutes=26)))

        result = self.ask("fyzio je hotové", "manage_reminder", {"action": "complete", "target": {"text": "fyzio"}})
        ai.execute_confirm_action(result["pending_actions"][0]["id"])
        self.assertEqual(self.q(lambda db: db.get(Reminder, fyzio).status), "done")

    def test_ambiguous_target_asks_instead_of_pending(self):
        self.seed(title="rotoped", in_minutes=30)
        self.seed(title="fyzio", in_minutes=60)
        result = self.ask("zruš tu připomínku", "manage_reminder", {"action": "cancel", "target": {}},
                          answer="Kterou připomínku?")
        self.assertEqual(result["pending_actions"], [])
        self.assertEqual(self.last_tool_result()["error"], "ambiguous_target")
        result = self.ask("zruš připomínku", "manage_reminder",
                          {"action": "cancel", "target": {"text": "připomínka"}}, answer="Kterou?")
        self.assertEqual(result["pending_actions"], [])
        self.assertEqual(self.q(lambda db: db.query(PendingAction).count()), 0)
        self.assertEqual({r.status for r in self.reminders()}, {"scheduled"})

    def test_stale_target_fails_safely(self):
        rid = self.seed(title="fyzio", in_minutes=10)
        result = self.ask("posuň připomínku fyzio o hodinu", "manage_reminder",
                          {"action": "update", "target": {"text": "fyzio"}, "shift_minutes": 60})
        self.clock[0] = NOW + timedelta(minutes=11)
        self.q(lambda db: rs.process_due_reminders(db))  # mezitím zazněla
        outcome = ai.execute_confirm_action(result["pending_actions"][0]["id"])
        self.assertFalse(outcome["ok"])
        r = self.q(lambda db: db.get(Reminder, rid))
        self.assertEqual((r.status, r.due_at), ("fired", NOW + timedelta(minutes=10)))

    def test_read_tool(self):
        self.seed(title="fyzio", due_local="2026-10-05T08:00")
        result = reminder_actions.query_reminders(self.Session())
        self.assertEqual(result["items"][0]["next_label"], "po 5. 10. 2026 08:00")
        self.assertEqual(result["timezone"], "Europe/Prague")


class ReminderRoutingTestCase(unittest.TestCase):
    def names(self, msg):
        return set(route_tools([msg]).names)

    def test_create_phrases_expose_only_add_reminder(self):
        for msg in ("připomeň mi zítra v 8 fyzio", "připomeň mi za 2 hodiny rotoped",
                    "připomeň mi každou neděli v 19:00 WoT plán"):
            with self.subTest(msg):
                writes = {n for n in self.names(msg) if not n.startswith("get_")}
                self.assertEqual(writes, {"add_reminder"})

    def test_mutation_phrases_expose_manage_reminder(self):
        for msg in ("posuň tu připomínku o hodinu", "zruš připomínku na rotoped", "odlož připomínku o 15 minut",
                    "zruš tu připomínku"):
            with self.subTest(msg):
                writes = {n for n in self.names(msg) if not n.startswith("get_")}
                self.assertEqual(writes, {"manage_reminder"})

    def test_known_gap_reminder_not_named(self):
        # Známá mezera: bez slova „připomínka" ukazuje „o hodinu" na práci → manage_reminder není v sadě.
        # Model pak dostane write_not_available / Groq fallback rozšíří sadu; zdokumentováno jako riziko.
        self.assertNotIn("manage_reminder", self.names("posuň fyzio o hodinu"))
        self.assertIn("manage_reminder", self.names("posuň připomínku fyzio o hodinu"))

    def test_questions_are_read_only(self):
        for msg in ("co mám připomenout dnes", "jaké mám aktivní připomínky"):
            with self.subTest(msg):
                names = self.names(msg)
                self.assertIn("get_reminders", names)
                self.assertFalse({n for n in names if not n.startswith("get_")})

    def test_planner_fast_path_skips_reminder_questions(self):
        self.assertIsNone(main.detect_planner_intent("co mám připomenout dnes"))
        self.assertIsNone(main.detect_planner_intent("připomeň mi zítra v 8 fyzio"))
        self.assertIsNotNone(main.detect_planner_intent("co mám dělat dnes"))


class ReminderContextTestCase(unittest.TestCase):
    def test_current_state_lists_due_and_upcoming_reminders(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine)()
        try:
            for spec in (rs.build_spec("fyzio", due_local="2026-10-05T08:00", now=NOW),
                         rs.build_spec("za týden", due_local="2026-10-11T08:00", now=NOW)):
                rs.create_from_spec(db, spec)
            db.commit()
            ctx = context_service.build_current_context(db, "co mám zítra", now_utc=NOW)
            self.assertIn("Připomínky:", ctx.text)
            self.assertIn("fyzio po 05.10. 08:00", ctx.text)
            self.assertNotIn("za týden", ctx.text)
            self.assertIn("get_reminders", ctx.covered_tools)
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
