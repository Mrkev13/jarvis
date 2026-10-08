"""MRK-19: doménové události – transakční outbox, projekce do Aktivity, after-commit dispatch, SSE stream,
Last-Event-ID replay, reset, retence. SQLite v paměti, žádná síť ani Groq."""
import asyncio
import json
import os
import re
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import bcrypt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import auth_service  # noqa: E402
import domain_events as de  # noqa: E402
import event_stream as es  # noqa: E402
import main  # noqa: E402
import module_registry as mr  # noqa: E402
import school_service  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, Assignment, DomainEvent, Exam, Subject  # noqa: E402
from modules.habits import service as habits  # noqa: E402
from modules.habits.models import HabitEntry  # noqa: E402

MODULE_ENV = [m.env_name for m in mr.MODULES]
T0 = datetime(2026, 10, 8, 12, 0, 0)
WIRE_KEYS = {"id", "type", "module_id", "aggregate_type", "aggregate_id", "occurred_at", "payload"}


def _clean_env():
    return {k: v for k, v in os.environ.items() if k not in MODULE_ENV and k != "DOMAIN_EVENTS_RETENTION_DAYS"}


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self._patches = [
            patch.object(mr, "SessionLocal", self.Session),
            patch.object(es, "SessionLocal", self.Session),
            patch.dict(os.environ, _clean_env(), clear=True),
        ]
        for p in self._patches:
            p.start()
        mr.invalidate_cache()
        with self.Session() as db:
            db.add(Subject(id=1, name="Matematika"))
            db.add(Assignment(id=1, subject_id=1, title="Sada", status="todo"))
            db.add(Exam(id=1, subject_id=1, title="Písemka", status="upcoming"))
            db.commit()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        mr.invalidate_cache()
        self.engine.dispose()

    def events(self):
        with self.Session() as db:
            return [(e.id, e.event_type, e.module_id, e.aggregate_id) for e in db.query(DomainEvent).order_by(DomainEvent.id)]

    def activity(self, area="school"):
        with self.Session() as db:
            return [(a.action_type, a.summary) for a in db.query(ActivityLog).filter_by(area=area).order_by(ActivityLog.id)]


class TransactionalOutboxTestCase(_DbCase):
    def test_commit_keeps_business_write_event_and_activity_together(self):
        with self.Session() as db:
            school_service.complete_assignment(db, 1, now=T0)
            db.commit()
        with self.Session() as db:
            self.assertEqual(db.get(Assignment, 1).status, "done")
        self.assertEqual([e[1:] for e in self.events()], [("school.assignment.completed", "school", "1")])
        self.assertEqual(self.activity(), [("complete", "Úkol splněn: Sada")])

    def test_rollback_removes_business_write_event_and_activity(self):
        with self.Session() as db:
            school_service.complete_assignment(db, 1, now=T0)
            db.rollback()
        with self.Session() as db:
            self.assertEqual(db.get(Assignment, 1).status, "todo")
        self.assertEqual((self.events(), self.activity()), ([], []))

    def test_direct_business_plus_event_rollback(self):
        with self.Session() as db:
            db.get(Assignment, 1).title = "Změna"
            de.append_domain_event(db, event_type="system.module.enabled", aggregate_type="module", aggregate_id="mff")
            db.rollback()
        with self.Session() as db:
            self.assertEqual(db.get(Assignment, 1).title, "Sada")
        self.assertEqual(self.events(), [])

    def test_all_school_transitions_ordered_with_minimal_payloads(self):
        with self.Session() as db:
            school_service.complete_assignment(db, 1, now=T0)
            school_service.reopen_assignment(db, 1)
            school_service.close_exam(db, 1, {"outcome": "passed", "result_type": "grade", "result_value": "1"}, now=T0)
            school_service.reopen_exam(db, 1)
            db.commit()
            payloads = [de.snapshot(r).payload for r in db.query(DomainEvent).order_by(DomainEvent.id)]
        ids = [e[0] for e in self.events()]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), 4)
        self.assertEqual([e[1] for e in self.events()], ["school.assignment.completed", "school.assignment.reopened",
                                                         "school.exam.closed", "school.exam.reopened"])
        self.assertEqual(payloads[0], {"assignment_id": 1, "subject_id": 1, "completed_at": "2026-10-08T12:00:00Z"})
        self.assertEqual(payloads[2]["outcome"], "passed")
        for p in payloads:
            self.assertNotIn("Sada", json.dumps(p), "žádné názvy v přenosové události")
            self.assertNotIn("Písemka", json.dumps(p))

    def test_repeated_cycles_each_get_exactly_one_activity_row(self):
        with self.Session() as db:
            for _ in range(2):
                school_service.complete_assignment(db, 1, now=T0)
                db.commit()
                school_service.reopen_assignment(db, 1)
                db.commit()
        self.assertEqual(len(self.events()), 4)
        self.assertEqual([a[0] for a in self.activity()], ["complete", "update", "complete", "update"])


class HabitsEventsTestCase(_DbCase):
    def test_done_and_skipped_emit_events_with_single_activity_rows(self):
        today = date(2026, 10, 8)
        with self.Session() as db:
            h = habits.create_habit(db, "Rehab kolene")
            db.commit()
            hid = h.id
        with self.Session() as db, patch.object(habits, "created_day", lambda _h: today - timedelta(days=3)):
            habits.set_entry(db, hid, "done", day=today, today=today, user_context="manual")
            habits.set_entry(db, hid, "skipped", day=today - timedelta(days=1), today=today, user_context="manual")
            habits.set_entry(db, hid, "done", day=today, today=today, user_context="manual")  # beze změny → nic
            db.commit()
            payloads = [de.snapshot(r).payload for r in db.query(DomainEvent).order_by(DomainEvent.id)]
            entries = db.query(HabitEntry).count()
        self.assertEqual([e[1:3] for e in self.events()], [("habits.entry.done", "habits"), ("habits.entry.skipped", "habits")])
        self.assertEqual(entries, 2)
        self.assertEqual(set(payloads[0]), {"habit_id", "entry_id", "date", "state", "previous_state"})
        self.assertNotIn("Rehab", json.dumps(payloads), "název návyku do události nepatří")
        rows = [a for a in self.activity("habits") if a[0] in ("check", "update")]
        self.assertEqual(len(rows), 2, "právě jeden viditelný řádek Aktivity na změnu")

    def test_note_or_value_edit_without_state_change_is_history_not_a_new_fact(self):
        today = date(2026, 10, 8)
        with self.Session() as db:
            hid = habits.create_habit(db, "Kroky").id
            db.commit()
        with self.Session() as db, patch.object(habits, "created_day", lambda _h: today):
            habits.set_entry(db, hid, "done", day=today, today=today)
            habits.set_entry(db, hid, "done", day=today, today=today, note="po obědě")
            db.commit()
        self.assertEqual([e[1] for e in self.events()], ["habits.entry.done"], "stejný stav = žádný další fakt")
        rows = [a for a in self.activity("habits") if a[0] in ("check", "update")]
        self.assertEqual(len(rows), 2, "úprava poznámky zůstává v historii (Aktivita)")

    def test_habit_rollback_drops_entry_and_event(self):
        today = date(2026, 10, 8)
        with self.Session() as db:
            hid = habits.create_habit(db, "Voda").id
            db.commit()
        with self.Session() as db, patch.object(habits, "created_day", lambda _h: today):
            habits.set_entry(db, hid, "done", day=today, today=today)
            db.rollback()
        with self.Session() as db:
            self.assertEqual(db.query(HabitEntry).count(), 0)
        self.assertEqual(self.events(), [])


class AppendValidationTestCase(_DbCase):
    def append(self, event_type="system.module.enabled", **kw):
        kw.setdefault("aggregate_type", "module")
        with self.Session() as db:
            row = de.append_domain_event(db, event_type=event_type, **kw)
            rid = row.id
            db.commit()
            return rid

    def test_undeclared_or_badly_named_type_is_rejected(self):
        for bad in ("school.assignment.deleted", "System.Module.Enabled", "module.enabled", "a.b.c.d", "", None):
            with self.subTest(bad=bad), self.assertRaises(de.DomainEventError):
                self.append(bad)
        self.assertEqual(self.events(), [])

    def test_event_type_is_keyword_only(self):
        with self.Session() as db, self.assertRaises(TypeError):
            de.append_domain_event(db, "system.module.enabled", aggregate_type="module")  # noqa

    def test_module_id_is_derived_and_must_match(self):
        with self.assertRaises(de.DomainEventError):
            self.append("school.exam.closed", aggregate_type="exam", module_id="wot")
        self.append("school.exam.closed", aggregate_type="exam", aggregate_id=1)
        self.append("system.module.enabled", aggregate_id="wot")
        self.assertEqual([(e[1], e[2]) for e in self.events()], [("school.exam.closed", "school"), ("system.module.enabled", None)])

    def test_malformed_payload_is_rejected(self):
        for bad in ([1, 2], {"when": datetime(2026, 1, 1)}, {"x": float("nan")}, {"a": {"b": {"c": {"d": 1}}}},
                    {"blob": "x" * 5000}, {1: "non-string key"}, {"obj": object()}):
            with self.subTest(bad=str(bad)[:40]), self.assertRaises(de.DomainEventError):
                self.append(payload=bad)
        with self.assertRaises(de.DomainEventError):
            self.append(aggregate_type="Bad Type")
        self.assertEqual(self.events(), [])

    def test_every_declared_type_follows_the_convention_and_used_types_are_declared(self):
        declared = de.declared_types()
        for t, owner in declared.items():
            self.assertRegex(t, de.EVENT_TYPE_RE)
            self.assertEqual(t.split(".")[0], owner or "system")
        used = set()
        for path in list(Path(BACKEND_DIR).glob("*.py")) + list(Path(BACKEND_DIR).glob("modules/*/*.py")):
            text = path.read_text(encoding="utf-8")
            used |= set(re.findall(r'event_type="([a-z0-9_.]+)"', text))
        used |= {"habits.entry.done", "habits.entry.skipped", "system.module.enabled", "system.module.disabled"}
        self.assertEqual(used - set(declared), set())

    def test_occurred_at_is_utc(self):
        rid = self.append()
        with self.Session() as db:
            snap = de.snapshot(db.get(DomainEvent, rid))
        self.assertTrue(snap.occurred_at.endswith("Z"))


class AfterCommitTestCase(_DbCase):
    def test_consumers_run_only_after_commit(self):
        seen = []
        unregister = de.register_after_commit(lambda evs: seen.extend(e.type for e in evs))
        try:
            with self.Session() as db:
                school_service.complete_assignment(db, 1, now=T0)
                self.assertEqual(seen, [], "nic před commitem")
                db.rollback()
            self.assertEqual(seen, [], "rollback nic nepošle")
            with self.Session() as db:
                school_service.complete_assignment(db, 1, now=T0)
                db.commit()
            self.assertEqual(seen, ["school.assignment.completed"])
        finally:
            unregister()

    def test_savepoint_rollback_keeps_outer_pending_and_close_discards(self):
        seen = []
        unregister = de.register_after_commit(lambda evs: seen.extend(e.type for e in evs))
        try:
            with self.Session() as db:
                school_service.complete_assignment(db, 1, now=T0)
                sp = db.begin_nested()
                sp.rollback()
                db.commit()
            self.assertEqual(seen, ["school.assignment.completed"], "rollback savepointu nezahodí vnější událost")
            db = self.Session()
            school_service.reopen_assignment(db, 1)
            db.close()  # bez commitu → transakce končí, čekající snapshot se zahodí
            self.assertNotIn(de._PENDING_KEY, db.info)
            db.commit()
            db.close()
            self.assertEqual(seen, ["school.assignment.completed"])
        finally:
            unregister()

    def test_sqlite_ids_are_never_reused_after_retention_empties_the_table(self):
        with self.Session() as db:
            first = de.append_domain_event(db, event_type="system.module.enabled", aggregate_type="module",
                                           aggregate_id="mff").id
            db.commit()
            db.query(DomainEvent).delete()
            db.commit()
            second = de.append_domain_event(db, event_type="system.module.enabled", aggregate_type="module",
                                            aggregate_id="mff").id
            db.commit()
        self.assertGreater(second, first, "dedupe_key event:<id> nesmí kolidovat se starší projekcí")

    def test_failing_consumer_does_not_undo_committed_write_or_leak_payload(self):
        def broken(_events):
            raise RuntimeError("secret-payload-Sada")
        unregister = de.register_after_commit(broken)
        try:
            with self.assertLogs("domain_events", level="WARNING") as logs, self.Session() as db:
                school_service.complete_assignment(db, 1, now=T0)
                db.commit()
        finally:
            unregister()
        self.assertEqual(len(self.events()), 1)
        with self.Session() as db:
            self.assertEqual(db.get(Assignment, 1).status, "done")
        self.assertNotIn("secret-payload", "\n".join(logs.output))
        self.assertIn("RuntimeError", "\n".join(logs.output))


def _collect(cursor, *, until, modules=None, types=None, max_frames=50, timeout=5.0):
    frames: list[str] = []
    state = {"stop": False}

    async def run():
        gen = es.stream_events(lambda: state["stop"], cursor, modules=modules, types=types)
        async for chunk in gen:
            frames.append(chunk)
            if until(frames) or len(frames) >= max_frames:
                state["stop"] = True
                await gen.aclose()
                break

    asyncio.run(asyncio.wait_for(run(), timeout))
    return frames


def _events_of(frames, kind="domain_event"):
    out = []
    for f in frames:
        m = re.match(r"(?:id: (\d+)\n)?event: (\w+)\ndata: (.*)\n\n", f, re.S)
        if m and m.group(2) == kind:
            out.append((int(m.group(1)) if m.group(1) else None, json.loads(m.group(3))))
    return out


class SseStreamTestCase(_DbCase):
    def setUp(self):
        super().setUp()
        self._sse = [patch.object(es, "POLL_SECONDS", 0.05), patch.object(es, "WAKE_STEP_SECONDS", 0.01)]
        for p in self._sse:
            p.start()

    def tearDown(self):
        for p in self._sse:
            p.stop()
        super().tearDown()

    def seed(self, n=3):
        with self.Session() as db:
            for _ in range(n):
                de.append_domain_event(db, event_type="system.module.disabled", aggregate_type="module",
                                       aggregate_id="mff", payload={"module_id": "mff"}, now=T0)
            db.commit()
        return [e[0] for e in self.events()]

    def test_format_and_replay_after_last_event_id(self):
        ids = self.seed(3)
        frames = _collect(ids[0], until=lambda f: len(_events_of(f)) >= 2)
        self.assertTrue(frames[0].startswith("retry: "))
        got = _events_of(frames)
        self.assertEqual([i for i, _ in got], ids[1:])
        self.assertEqual(set(got[0][1]), WIRE_KEYS, "stabilní minimální tvar")
        self.assertEqual(got[0][1]["id"], ids[1], "SSE id == domain_events.id")

    def test_without_cursor_only_new_events_are_streamed(self):
        self.seed(2)

        def until(frames):
            if frames[-1].startswith(": keepalive") and not getattr(until, "added", False):
                until.added = True
                with self.Session() as db:
                    de.append_domain_event(db, event_type="system.module.enabled", aggregate_type="module", aggregate_id="mff")
                    db.commit()
            return len(_events_of(frames)) >= 1
        with patch.object(es, "HEARTBEAT_SECONDS", 0.05):
            frames = _collect(None, until=until)
        self.assertEqual([e["type"] for _, e in _events_of(frames)], ["system.module.enabled"])

    def test_one_and_multiple_missed_then_live_without_gap_or_duplicate(self):
        ids = self.seed(4)
        one = _collect(ids[2], until=lambda f: len(_events_of(f)) >= 1)
        self.assertEqual([i for i, _ in _events_of(one)], [ids[3]], "jedna zmeškaná")

        def until(frames):
            got = _events_of(frames)
            if len(got) == 3 and not getattr(until, "added", False):
                until.added = True  # replay hotový → živá událost
                with self.Session() as db:
                    de.append_domain_event(db, event_type="system.module.enabled", aggregate_type="module", aggregate_id="mff")
                    db.commit()
            return len(got) >= 4
        multi = _collect(ids[0], until=until)
        streamed = [i for i, _ in _events_of(multi)]
        self.assertEqual(streamed[:3], ids[1:], "více zmeškaných ve správném pořadí")
        self.assertEqual(len(streamed), len(set(streamed)), "žádná duplicita na předělu replay → živě")
        self.assertEqual(streamed[3], ids[3] + 1, "žádná mezera")

    def test_ready_frame_carries_the_position_before_any_event(self):
        frames = _collect(None, until=lambda f: bool(_events_of(f, "ready")))
        self.assertEqual(_events_of(frames, "ready"), [(0, {"latest_id": 0})], "prázdná tabulka = pozice 0")
        ids = self.seed(2)
        frames = _collect(None, until=lambda f: bool(_events_of(f, "ready")))
        self.assertEqual(_events_of(frames, "ready"), [(ids[-1], {"latest_id": ids[-1]})])
        frames = _collect(ids[0], until=lambda f: len(_events_of(f)) >= 1)
        self.assertEqual(_events_of(frames, "ready")[0][0], ids[0], "s kurzorem = kurzor")
        frames = _collect(ids[-1] + 100, until=lambda f: bool(_events_of(f, "reset")))
        self.assertEqual(_events_of(frames, "ready"), [], "reset místo ready")

    def test_stream_ends_when_the_session_is_no_longer_valid(self):
        checks = []

        def authorized():
            checks.append(1)
            return len(checks) < 2

        async def run():
            out = []
            async for chunk in es.stream_events(lambda: False, None, authorized=authorized):
                out.append(chunk)
            return out
        with patch.object(es, "HEARTBEAT_SECONDS", 0.05):
            frames = asyncio.run(asyncio.wait_for(run(), 5))
        self.assertEqual(len(checks), 2, "druhá kontrola session stream ukončí sama")
        self.assertTrue(frames[0].startswith("retry: "))

    def test_reconnect_resumes_without_duplicates(self):
        ids = self.seed(4)
        first = _collect(ids[0], until=lambda f: len(_events_of(f)) >= 1)
        last_seen = _events_of(first)[-1][0]
        second = _collect(last_seen, until=lambda f: len(_events_of(f)) >= 2)
        replayed = [i for i, _ in _events_of(second)]
        self.assertEqual(replayed, [i for i in ids if i > last_seen])

    def test_reset_when_cursor_is_older_than_retention(self):
        ids = self.seed(5)
        with self.Session() as db:
            db.query(DomainEvent).filter(DomainEvent.id <= ids[2]).delete()
            db.commit()
        frames = _collect(ids[0], until=lambda f: bool(_events_of(f, "reset")))
        (reset_id, reset), = _events_of(frames, "reset")
        self.assertEqual(reset, {"reason": "retention", "latest_id": ids[-1]})
        self.assertEqual(reset_id, ids[-1])

    def test_reset_on_overflow_and_unknown_cursor(self):
        ids = self.seed(5)
        with patch.object(es, "REPLAY_MAX", 3):
            frames = _collect(0, until=lambda f: bool(_events_of(f, "reset")))
        self.assertEqual(_events_of(frames, "reset")[0][1]["reason"], "overflow")
        frames = _collect(ids[-1] + 100, until=lambda f: bool(_events_of(f, "reset")))
        self.assertEqual(_events_of(frames, "reset")[0][1]["reason"], "unknown_cursor")

    def test_disabled_module_events_are_never_streamed_and_filters_apply(self):
        with self.Session() as db:
            school_service.complete_assignment(db, 1, now=T0)
            de.append_domain_event(db, event_type="system.module.enabled", aggregate_type="module", aggregate_id="mff")
            db.commit()
        os.environ["MODULE_SCHOOL_ENABLED"] = "false"
        frames = _collect(0, until=lambda f: len(_events_of(f)) >= 1)
        self.assertEqual([e["type"] for _, e in _events_of(frames)], ["system.module.enabled"])
        del os.environ["MODULE_SCHOOL_ENABLED"]
        frames = _collect(0, until=lambda f: len(_events_of(f)) >= 1, types=frozenset({"school.assignment.completed"}))
        self.assertEqual([e["type"] for _, e in _events_of(frames)], ["school.assignment.completed"])
        frames = _collect(0, until=lambda f: len(_events_of(f)) >= 1, modules=frozenset({"system"}))
        self.assertEqual([e["type"] for _, e in _events_of(frames)], ["system.module.enabled"])

    def test_heartbeat_when_idle(self):
        with patch.object(es, "HEARTBEAT_SECONDS", 0.05):
            frames = _collect(None, until=lambda f: any(x.startswith(": keepalive") for x in f))
        self.assertIn(": keepalive\n\n", frames)

    def test_cursor_parsing(self):
        self.assertEqual(es.parse_cursor("12", None), 12)
        self.assertEqual(es.parse_cursor(None, "7"), 7)
        self.assertEqual(es.parse_cursor("12", "7"), 12, "hlavička má přednost")
        for bad in ("-1", "abc", "1.5", "", str(2 ** 64)):
            self.assertIsNone(es.parse_cursor(bad, None), bad)


class SseEndpointTestCase(_DbCase):
    PIN = "4821"

    def setUp(self):
        super().setUp()
        self._orig = (auth_service.SessionLocal, main.SessionLocal, tools.SessionLocal, auth_service.AUTH_PIN_HASH,
                      auth_service._failed_attempts)
        auth_service.SessionLocal = main.SessionLocal = tools.SessionLocal = self.Session
        auth_service._failed_attempts = {}
        auth_service.AUTH_PIN_HASH = bcrypt.hashpw(self.PIN.encode(), bcrypt.gensalt(rounds=4)).decode()
        self._sse = [patch.object(es, "POLL_SECONDS", 0.05), patch.object(es, "WAKE_STEP_SECONDS", 0.01)]
        for p in self._sse:
            p.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self._sse:
            p.stop()
        (auth_service.SessionLocal, main.SessionLocal, tools.SessionLocal, auth_service.AUTH_PIN_HASH,
         auth_service._failed_attempts) = self._orig
        super().tearDown()

    def login(self):
        self.assertEqual(self.client.post("/auth/login", json={"pin": self.PIN}).status_code, 200)

    def test_stream_requires_auth(self):
        self.assertEqual(self.client.get("/events/stream").status_code, 401)

    def test_module_toggle_produces_event_and_single_activity_row(self):
        self.login()
        self.assertEqual(self.client.put("/modules/mff", json={"enabled": False}).status_code, 200)
        self.assertEqual([e[1] for e in self.events()], ["system.module.disabled"])
        self.assertEqual([a[0] for a in self.activity("system")], ["module.disabled"])
        self.client.put("/modules/mff", json={"enabled": True})
        self.client.put("/modules/mff", json={"enabled": False})
        self.assertEqual([a[0] for a in self.activity("system")], ["module.disabled", "module.enabled", "module.disabled"])

    def test_authenticated_stream_replays_with_last_event_id_header(self):
        self.login()
        self.client.put("/modules/mff", json={"enabled": False})
        self.client.put("/modules/mff", json={"enabled": True})
        first_id = self.events()[0][0]
        real = es.stream_events
        seen_cursor = {}

        async def finite(is_disconnected, cursor, **kw):
            # TestClient nedoručí odpojení u nekonečného streamu → skutečný generátor, ukončený po 1. události
            seen_cursor["value"] = cursor
            async for chunk in real(is_disconnected, cursor, **kw):
                yield chunk
                if chunk.startswith("id: ") and "event: domain_event" in chunk:
                    return
        with patch.object(es, "stream_events", finite), \
                self.client.stream("GET", "/events/stream", headers={"Last-Event-ID": str(first_id)}) as resp:
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.headers["content-type"].startswith("text/event-stream"))
            body = "".join(resp.iter_text())
        self.assertIn(f"id: {first_id + 1}\nevent: domain_event", body)
        self.assertIn('"type":"system.module.enabled"', body)
        self.assertIn(f"id: {first_id}\nevent: ready\n", body, "ready nese pozici klienta")
        self.assertNotIn(f"id: {first_id}\nevent: domain_event", body)
        self.assertEqual(seen_cursor["value"], first_id)
        for secret in ("AUTH_PIN_HASH", self.PIN, "GROQ"):
            self.assertNotIn(secret, body)


class RetentionTestCase(_DbCase):
    def add(self, when):
        with self.Session() as db:
            de.append_domain_event(db, event_type="system.module.enabled", aggregate_type="module", aggregate_id="mff", now=when)
            db.commit()

    def test_retention_days_default_min_max_and_invalid(self):
        self.assertEqual(de.retention_days(), 180)
        for raw, expected in (("90", 90), ("365", 365), ("30", 90), ("1000", 365), ("abc", 180), ("", 180)):
            with self.subTest(raw=raw), patch.dict(os.environ, {"DOMAIN_EVENTS_RETENTION_DAYS": raw}):
                self.assertEqual(de.retention_days(), expected)

    def test_cleanup_exact_cutoff_and_no_business_or_activity_deletion(self):
        now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        threshold = now - timedelta(days=180)
        self.add(threshold - timedelta(seconds=1))
        self.add(threshold)
        self.add(threshold + timedelta(days=1))
        with self.Session() as db:
            school_service.complete_assignment(db, 1, now=T0)
            db.commit()
            activity_before = db.query(ActivityLog).count()
        with self.Session() as db:
            removed = de.cleanup_domain_events(db, now=now)
            db.commit()
        self.assertEqual(removed, 1)
        with self.Session() as db:
            left = sorted(de.as_utc(e.occurred_at) for e in db.query(DomainEvent).filter_by(event_type="system.module.enabled"))
            self.assertEqual(left, [threshold, threshold + timedelta(days=1)], "přesně na prahu zůstává")
            self.assertEqual(db.query(ActivityLog).count(), activity_before, "Aktivita se retencí nemaže")
            self.assertEqual(db.get(Assignment, 1).status, "done")

    def test_cleanup_is_bounded_and_validates_range(self):
        for i in range(5):
            self.add(datetime(2025, 1, 1, tzinfo=timezone.utc) - timedelta(days=i))
        with self.Session() as db:
            self.assertEqual(de.cleanup_domain_events(db, now=datetime(2026, 10, 8, tzinfo=timezone.utc), batch=2), 2)
            db.commit()
        with self.Session() as db, self.assertRaises(ValueError):
            de.cleanup_domain_events(db, days=30)


if __name__ == "__main__":
    unittest.main()
