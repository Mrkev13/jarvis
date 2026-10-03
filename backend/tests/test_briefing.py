"""Phase F: Denní přehled – snímek, grounding, perzistence, scheduler, selhání, notifikace, API (fake LLM)."""
import json
import os
import sys
import types
import unittest
from datetime import date, datetime, timedelta
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

import ai  # noqa: E402
import auth_service  # noqa: E402
import briefing_service as bs  # noqa: E402
import delivery_service as ds  # noqa: E402
import main  # noqa: E402
import reminder_service as rs  # noqa: E402
import scheduler_service  # noqa: E402
from briefing_snapshot import MAX_SNAPSHOT_TOKENS, build_snapshot  # noqa: E402
from database import Base  # noqa: E402
from llm_usage import LLMCallRecord  # noqa: E402
from models import (  # noqa: E402
    ActivityLog, Assignment, DailyBriefing, Delivery, Exam, Goal, Notification, Reminder, Subject,
)
from tests.test_delivery import FakeProvider  # noqa: E402

# Úterý 6. 10. 2026; 07:00 Praha (SELČ) = 05:00 UTC
SEVEN = datetime(2026, 10, 6, 5, 0)


def good_answer(**over):
    data = {
        "summary": "Dnes odevzdáváš esej a blíží se zkouška z fyziky.",
        "priorities": [{"ref": "assignment:2", "title": "Odevzdat esej o ústavě", "why": "Termín je dnes."},
                       {"ref": "assignment:1", "title": "Dohnat sadu příkladů", "why": "Je po termínu."}],
        "watch": [{"ref": "reminder:1", "text": "Fyzio připomínka dnes"}],
        "upcoming": [{"ref": "exam:1", "text": "Zkouška z fyziky"}],
        "note": None,
    }
    data.update(over)
    return json.dumps(data, ensure_ascii=False)


class FakeLLM:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, messages, max_tokens):
        self.calls.append({"messages": messages, "max_tokens": max_tokens})
        a = self.answers.pop(0) if self.answers else good_answer()
        if isinstance(a, Exception):
            raise a
        return a, {"model": "fake", "prompt_tokens": 900, "completion_tokens": 150, "total_tokens": 1050,
                   "latency_ms": 12}


class BriefingTestBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self._env = patch.dict(os.environ, {"DAILY_BRIEFING_ENABLED": "true", "DAILY_BRIEFING_TIME": "07:00",
                                            "DAILY_BRIEFING_PUSH": "true"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.engine.dispose()

    def q(self, fn):
        db = self.Session()
        try:
            return fn(db)
        finally:
            db.close()

    def seed_busy(self):
        def go(db):
            law, phys = Subject(name="Matematika"), Subject(name="Fyzika")
            db.add_all([law, phys])
            db.flush()
            db.add_all([
                Assignment(title="Sada příkladů", subject_id=law.id, status="todo", due_date=date(2026, 10, 4)),
                Assignment(title="Esej o ústavě", subject_id=law.id, status="todo", priority="high",
                           due_date=date(2026, 10, 6)),
                Assignment(title="Hotový úkol", subject_id=law.id, status="done", due_date=date(2026, 10, 6)),
                Assignment(title="Projekt", subject_id=law.id, status="todo", due_date=date(2026, 10, 9)),
                Exam(title="Zkouška", subject_id=phys.id, status="upcoming", exam_date=date(2026, 10, 12)),
                Goal(area="finance", title="Našetřit 150 000 Kč", status="active", priority="high", progress=6,
                     tracking_type="manual"),
            ])
            db.commit()
            rs.create_from_spec(db, rs.build_spec("fyzio", due_local="2026-10-06T18:00", now=SEVEN))
            db.add(ActivityLog(timestamp=SEVEN - timedelta(hours=2), area="finance", action_type="create",
                               summary="-120 Kč Jídlo"))
            db.commit()
        self.q(go)

    def row(self):
        return self.q(lambda db: db.query(DailyBriefing).one())

    def briefing_notes(self):
        return self.q(lambda db: db.query(Notification).filter_by(notification_type="daily_briefing").all())


class SnapshotTestCase(BriefingTestBase):
    def test_sections_and_refs(self):
        self.seed_busy()
        snap = self.q(lambda db: build_snapshot(db, SEVEN))
        refs = {k: [i.ref for i in v] for k, v in snap.sections.items()}
        self.assertEqual(refs["overdue"], ["assignment:1"])
        self.assertEqual(sorted(refs["today"]), ["assignment:2", "reminder:1"])
        self.assertEqual(refs["soon"], ["assignment:4", "exam:1"])
        self.assertEqual(refs["goals"], ["goal:1"])
        self.assertIn("1× finance", snap.changes_summary)
        text = snap.render()
        self.assertIn("[assignment:2] Esej o ústavě (Matematika) · termín dnes · priorita high", text)
        self.assertNotIn("Hotový úkol", text)
        self.assertFalse(snap.is_quiet)

    def test_new_since_previous_briefing(self):
        self.seed_busy()
        snap = self.q(lambda db: build_snapshot(db, SEVEN, previous_refs={"assignment:1"}))
        flags = {i.ref: i.new for i in snap.items() if i.ref.startswith(("assignment", "exam", "reminder"))}
        self.assertFalse(flags["assignment:1"])
        self.assertTrue(flags["assignment:2"])
        self.assertIn("NOVÉ", snap.render())

    def test_quiet_day(self):
        snap = self.q(lambda db: build_snapshot(db, SEVEN))
        self.assertTrue(snap.is_quiet)
        self.assertIn("Žádné termíny", snap.render())

    def test_token_budget_normal_busy_and_worst_case(self):
        self.seed_busy()
        normal = self.q(lambda db: build_snapshot(db, SEVEN))

        def flood(db):
            s = db.query(Subject).first()
            for i in range(300):
                db.add(Assignment(title=f"Velmi dlouhý název úkolu číslo {i} " + "x" * 120, subject_id=s.id,
                                  status="todo", due_date=date(2026, 10, 1 + i % 12)))
                db.add(ActivityLog(timestamp=SEVEN - timedelta(minutes=i), area="school", action_type="create",
                                   summary="Změna " + "y" * 200, dedupe_key=f"k{i}"))
                db.add(Goal(area="school", title=f"Cíl {i} " + "z" * 100, status="active", priority="high",
                            progress=i % 100, target_date=date(2026, 10, 1 + i % 20)))
            db.commit()
        self.q(flood)
        worst = self.q(lambda db: build_snapshot(db, SEVEN))
        self.assertLessEqual(worst.tokens, MAX_SNAPSHOT_TOKENS)
        self.assertLessEqual(len(worst.items()), 6 + 6 + 6 + 3 + 3 + 1 + 4)
        for snap in (normal, worst):
            self.assertLess(bs.estimate_request_tokens(snap), 3000, "pohodlně pod 8k TPM")
        print(f"\n[budget] normal snapshot={normal.tokens} request≈{bs.estimate_request_tokens(normal)}; "
              f"worst snapshot={worst.tokens} request≈{bs.estimate_request_tokens(worst)}")


class GenerateTestCase(BriefingTestBase):
    def gen(self, llm, now=SEVEN, trigger="scheduler", regenerate=False):
        return self.q(lambda db: bs.generate(db, trigger=trigger, now=now, regenerate=regenerate, llm=llm))

    def test_success_is_grounded_persisted_and_notified_once(self):
        self.seed_busy()
        llm = FakeLLM(good_answer())
        self.gen(llm)
        row = self.row()
        self.assertEqual((row.status, row.trigger, row.attempts, row.total_tokens), ("ready", "scheduler", 1, 1050))
        content = json.loads(row.content)
        self.assertEqual([p["ref"] for p in content["priorities"]], ["assignment:2", "assignment:1"])
        self.assertEqual(content["priorities"][0]["when"], "termín dnes")  # datum ze snímku, ne z LLM
        self.assertEqual(content["priorities"][0]["url"], "/school")
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual([m["role"] for m in llm.calls[0]["messages"]], ["system", "user"])
        self.assertEqual(llm.calls[0]["max_tokens"], bs.MAX_OUTPUT_TOKENS)
        self.assertNotIn("tools", llm.calls[0])
        [n] = self.briefing_notes()
        self.assertEqual((n.title, n.action_url, n.dedupe_key), ("☀️ Denní přehled", "/", "briefing:2026-10-06"))
        self.assertIsNotNone(n.expires_at)

    def test_one_briefing_per_day(self):
        self.seed_busy()
        llm = FakeLLM()
        for minutes in (0, 5, 600):
            self.q(lambda db: bs.run_scheduled(db, now=SEVEN + timedelta(minutes=minutes), llm=llm))
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(self.q(lambda db: db.query(DailyBriefing).count()), 1)
        self.assertEqual(len(self.briefing_notes()), 1)

    def test_quiet_day_skips_llm(self):
        llm = FakeLLM()
        self.gen(llm)
        self.assertEqual(llm.calls, [])
        content = json.loads(self.row().content)
        self.assertTrue(content["quiet"])
        self.assertIn("klidný den", content["summary"])
        self.assertEqual(self.row().model, "deterministic")

    def test_hallucinations_are_removed_or_replaced(self):
        self.seed_busy()
        answer = good_answer(
            summary="Dnes musíš zaplatit nájem 12 500 Kč do 9. 11.",
            priorities=[
                {"ref": "assignment:999", "title": "Vymyšlený úkol", "why": ""},
                {"ref": "assignment:2", "title": "Odevzdej esej a pošli 3 000 Kč Petrovi", "why": "Kvůli Novákovi."},
                {"ref": "activity:1", "title": "Změna", "why": ""},
                {"ref": "[exam:1]", "title": "Připrav se na zkoušku", "why": "Blíží se."},
            ],
            watch=[{"ref": "assignment:2", "text": "duplicitní"}],
            note="Za měsíc ušetříš 40 000 Kč.",
        )
        self.gen(FakeLLM(answer))
        row = self.row()
        content = json.loads(row.content)
        self.assertEqual([p["ref"] for p in content["priorities"]], ["assignment:2", "exam:1"])
        self.assertEqual(content["priorities"][0]["text"], "Esej o ústavě (Matematika)")  # neověřené → štítek
        self.assertEqual(content["priorities"][0]["why"], "")
        self.assertEqual(content["watch"], [])
        self.assertTrue(content["summary"].startswith("Přehled:"))
        self.assertIsNone(content["note"])
        self.assertGreaterEqual(row.grounding_removed, 6)

    def test_everything_ungrounded_is_rejected(self):
        self.seed_busy()
        self.gen(FakeLLM(good_answer(priorities=[{"ref": "x:1", "title": "a"}], watch=[], upcoming=[])))
        row = self.row()
        self.assertEqual((row.status, row.error_category), ("failed", "grounding_rejected"))
        self.assertEqual(row.next_retry_at, SEVEN + timedelta(minutes=30))
        self.assertEqual(self.briefing_notes(), [])

    def test_invalid_structured_response(self):
        self.seed_busy()
        for bad in ("Tady je přehled bez JSONu.", '{"summary": 5}', '{"summary": "x", "priorities": "nope"}'):
            with self.subTest(bad=bad):
                self.q(lambda db: db.query(DailyBriefing).delete() or db.commit())
                self.gen(FakeLLM(bad))
                self.assertEqual((self.row().status, self.row().error_category), ("failed", "invalid_response"))
        self.gen(FakeLLM("```json\n" + good_answer() + "\n```"), trigger="manual")
        self.assertEqual(self.row().status, "ready")

    def test_daily_limit_waits_hours_and_does_not_busy_loop(self):
        self.seed_busy()
        llm = FakeLLM(bs.BriefingError("daily_limit"))
        self.q(lambda db: bs.run_scheduled(db, now=SEVEN, llm=llm))
        row = self.row()
        self.assertEqual((row.status, row.error_category), ("failed", "daily_limit"))
        for minutes in range(1, 180, 5):  # job běží každých 5 min – nic nevolá
            self.assertEqual(self.q(lambda db: bs.run_scheduled(db, now=SEVEN + timedelta(minutes=minutes), llm=llm)),
                             "waiting")
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(self.q(lambda db: bs.run_scheduled(db, now=SEVEN + timedelta(hours=3), llm=llm)), "retried")
        self.assertEqual(self.row().status, "ready")

    def test_bounded_scheduler_attempts(self):
        self.seed_busy()
        llm = FakeLLM(*[bs.BriefingError("provider")] * 10)
        t = SEVEN
        for _ in range(10):
            self.q(lambda db: bs.run_scheduled(db, now=t, llm=llm))
            t += timedelta(hours=1)
        self.assertEqual(len(llm.calls), bs.MAX_SCHEDULER_ATTEMPTS)
        self.assertEqual(self.q(lambda db: bs.run_scheduled(db, now=t, llm=llm)), "gave_up")
        self.gen(FakeLLM(), now=t, trigger="manual")  # ručně jde vždy
        self.assertEqual(self.row().status, "ready")

    def test_real_llm_path_classifies_groq_errors_and_sends_no_tools(self):
        self.seed_busy()
        captured = {}

        def daily(api_messages, **kwargs):
            captured.update(kwargs)
            raise ai.DailyLimitError("denní limit")

        def tpm(api_messages, **kwargs):
            kwargs["call_log"].append(LLMCallRecord(attempt=1, latency_ms=1, rate_limited=True, limit_kind="TPM"))
            raise RuntimeError("AI provider nedisponuje (Rate limit …)")

        def network(api_messages, **kwargs):
            raise RuntimeError("Při volání AI došlo k chybě: ConnectionError")

        def ok(api_messages, **kwargs):
            kwargs["call_log"].append(LLMCallRecord(attempt=1, latency_ms=5, prompt_tokens=800, completion_tokens=120,
                                                    total_tokens=920))
            msg = types.SimpleNamespace(content=good_answer(), tool_calls=None)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

        expected = [(daily, "daily_limit"), (tpm, "rate_limit"), (network, "provider")]
        for fake, category in expected:
            with self.subTest(category=category), patch.object(ai, "_llm_create_with_retry", fake):
                self.q(lambda db: db.query(DailyBriefing).delete() or db.commit())
                self.q(lambda db: bs.generate(db, trigger="scheduler", now=SEVEN))
                self.assertEqual(self.row().error_category, category)
        self.assertIsNone(captured["tools"])
        self.assertEqual(captured["max_tokens"], bs.MAX_OUTPUT_TOKENS)
        with patch.object(ai, "_llm_create_with_retry", ok):
            self.q(lambda db: db.query(DailyBriefing).delete() or db.commit())
            self.q(lambda db: bs.generate(db, trigger="scheduler", now=SEVEN))
        row = self.row()
        self.assertEqual((row.status, row.prompt_tokens, row.total_tokens), ("ready", 800, 920))

    def test_manual_generation_and_regeneration(self):
        self.seed_busy()
        self.gen(FakeLLM(), trigger="manual")
        self.assertEqual(self.briefing_notes(), [], "ruční generování nepošle notifikaci")
        self.gen(FakeLLM(), now=SEVEN + timedelta(minutes=5), trigger="manual")  # bez regenerate → beze změny
        self.assertEqual(self.row().regenerated_count, 0)
        llm = FakeLLM(good_answer(summary="Nové shrnutí: esej dnes."))
        self.gen(llm, now=SEVEN + timedelta(hours=1), trigger="manual", regenerate=True)
        row = self.row()
        self.assertEqual((row.regenerated_count, row.attempts, row.first_generated_at), (1, 2, SEVEN))
        self.assertEqual(json.loads(row.content)["summary"], "Nové shrnutí: esej dnes.")
        self.assertEqual(self.q(lambda db: db.query(DailyBriefing).count()), 1)

    def test_failed_regeneration_keeps_previous_briefing(self):
        self.seed_busy()
        self.gen(FakeLLM())
        self.gen(FakeLLM(bs.BriefingError("rate_limit")), now=SEVEN + timedelta(hours=1), trigger="manual",
                 regenerate=True)
        row = self.row()
        self.assertEqual((row.status, row.error_category), ("ready", "regenerate_failed:rate_limit"))
        self.assertIn("esej", json.loads(row.content)["summary"])

    def test_in_progress_and_stale_generation(self):
        self.seed_busy()

        def stuck(db):
            db.add(DailyBriefing(briefing_date=date(2026, 10, 6), status="generating", trigger="scheduler",
                                 attempts=1, grounding_removed=0, regenerated_count=0, created_at=SEVEN,
                                 updated_at=SEVEN))
            db.commit()
        self.q(stuck)
        with self.assertRaises(bs.BriefingInProgress):
            self.gen(FakeLLM(), now=SEVEN + timedelta(minutes=2), trigger="manual")
        self.assertEqual(self.q(lambda db: bs.run_scheduled(db, now=SEVEN + timedelta(minutes=2), llm=FakeLLM())),
                         "in_progress")
        self.q(lambda db: bs.run_scheduled(db, now=SEVEN + timedelta(minutes=15), llm=FakeLLM()))
        self.assertEqual(self.row().status, "ready")


class SchedulerTimingTestCase(BriefingTestBase):
    def run_at(self, now, llm):
        return self.q(lambda db: bs.run_scheduled(db, now=now, llm=llm))

    def test_configured_time_and_catch_up(self):
        self.seed_busy()
        llm = FakeLLM()
        self.assertEqual(self.run_at(SEVEN - timedelta(minutes=1), llm), "not_yet")
        self.assertEqual(self.run_at(SEVEN, llm), "generated")
        self.assertEqual(self.row().trigger, "scheduler")

    def test_backend_started_late_catches_up_once(self):
        self.seed_busy()
        llm = FakeLLM()
        self.assertEqual(self.run_at(SEVEN + timedelta(hours=3), llm), "generated")
        self.assertEqual(self.row().trigger, "catchup")
        self.assertEqual(self.run_at(SEVEN + timedelta(hours=3, minutes=5), llm), "exists")

    def test_custom_time_and_disabled(self):
        with patch.dict(os.environ, {"DAILY_BRIEFING_TIME": "06:30"}):
            self.assertEqual(self.run_at(SEVEN - timedelta(minutes=31), FakeLLM()), "not_yet")
            self.assertEqual(self.run_at(SEVEN - timedelta(minutes=30), FakeLLM()), "generated")
        with patch.dict(os.environ, {"DAILY_BRIEFING_ENABLED": "false"}):
            self.assertEqual(self.run_at(SEVEN, FakeLLM()), "disabled")

    def test_dst_days_use_prague_wall_clock(self):
        llm = FakeLLM()
        # 29. 3. 2026 (jarní posun): 07:00 SELČ = 05:00 UTC
        self.assertEqual(self.run_at(datetime(2026, 3, 29, 4, 59), llm), "not_yet")
        self.assertEqual(self.run_at(datetime(2026, 3, 29, 5, 0), llm), "generated")
        # 25. 10. 2026 (podzimní posun): 07:00 SEČ = 06:00 UTC
        self.assertEqual(self.run_at(datetime(2026, 10, 25, 5, 30), llm), "not_yet")
        self.assertEqual(self.run_at(datetime(2026, 10, 25, 6, 0), llm), "generated")
        dates = self.q(lambda db: sorted(r.briefing_date for r in db.query(DailyBriefing).all()))
        self.assertEqual(dates, [date(2026, 3, 29), date(2026, 10, 25)])

    def test_never_generates_tomorrow_early(self):
        llm = FakeLLM()
        self.run_at(SEVEN, llm)
        self.assertEqual(self.run_at(datetime(2026, 10, 6, 21, 50), llm), "exists")  # 23:50 Praha
        self.assertEqual(self.run_at(datetime(2026, 10, 6, 22, 30), llm), "not_yet")  # 00:30 dalšího dne
        self.assertEqual(self.q(lambda db: db.query(DailyBriefing).count()), 1)


class IntegrationTestCase(BriefingTestBase):
    def test_web_push_reuses_phase_e_queue_without_duplicates(self):
        self.seed_busy()
        self.q(lambda db: bs.run_scheduled(db, now=SEVEN, llm=FakeLLM()))
        p = FakeProvider()
        for minutes in (1, 2):
            self.q(lambda db: ds.run_delivery_cycle(db, [p], now=SEVEN + timedelta(minutes=minutes)))
        briefing_calls = [c for c in p.calls if c[1]["title"] == "☀️ Denní přehled"]
        self.assertEqual(len(briefing_calls), 1)
        self.assertEqual(briefing_calls[0][1]["url"], "/")
        self.assertEqual(self.q(lambda db: db.query(Delivery).filter(Delivery.dedupe_key.like("briefing:%")).count()), 1)

    def test_push_can_be_disabled_for_briefings(self):
        self.seed_busy()
        self.q(lambda db: bs.run_scheduled(db, now=SEVEN, llm=FakeLLM()))
        with patch.dict(os.environ, {"DAILY_BRIEFING_PUSH": "false"}):
            p = FakeProvider()
            self.q(lambda db: ds.run_delivery_cycle(db, [p], now=SEVEN + timedelta(minutes=1)))
        self.assertFalse([c for c in p.calls if c[1]["title"] == "☀️ Denní přehled"])
        self.assertEqual(len(self.briefing_notes()), 1, "interní notifikace zůstává")

    def test_briefing_failure_does_not_affect_reminders(self):
        def go(db):
            rs.create_from_spec(db, rs.build_spec("fyzio", in_minutes=1, now=datetime(2020, 1, 1)))
            db.commit()
        self.q(go)

        def boom(db, now=None, llm=None):
            raise RuntimeError("Groq down")

        with patch.object(scheduler_service, "SessionLocal", self.Session), patch.object(bs, "run_scheduled", boom):
            scheduler_service._run_briefing_job()  # nesmí vyhodit
            scheduler_service._run_reminders_job()
        self.assertEqual(self.q(lambda db: db.query(Reminder).one().status), "fired")


class BriefingApiTestCase(BriefingTestBase):
    def setUp(self):
        super().setUp()
        self.llm = FakeLLM()
        self._patches = [
            patch.object(main, "SessionLocal", self.Session),
            patch.object(auth_service, "SessionLocal", self.Session),
            patch.object(auth_service, "_failed_attempts", {}),
            patch.object(auth_service, "AUTH_PIN_HASH", bcrypt.hashpw(b"4821", bcrypt.gensalt(rounds=4)).decode()),
            patch.object(bs, "_call_llm", lambda snap, llm=None: self.llm(bs.build_messages(snap), bs.MAX_OUTPUT_TOKENS)),
            patch.object(bs, "utc_now", lambda: SEVEN),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        super().tearDown()

    def login(self):
        self.assertEqual(self.client.post("/auth/login", json={"pin": "4821"}).status_code, 200)

    def test_requires_session(self):
        self.assertEqual(self.client.get("/briefing/today").status_code, 401)
        self.assertEqual(self.client.post("/briefing/today/generate", json={}).status_code, 401)
        self.assertEqual(self.llm.calls, [])

    def test_missing_then_generate_then_regenerate(self):
        self.seed_busy()
        self.login()
        body = self.client.get("/briefing/today").json()
        self.assertEqual((body["status"], body["date"], body["scheduled_time"]), ("missing", "2026-10-06", "07:00"))
        self.assertEqual([i["ref"] for i in body["fallback"]["overdue"]], ["assignment:1"])
        body = self.client.post("/briefing/today/generate", json={}).json()
        self.assertEqual((body["status"], body["trigger"], body["generated_label"]), ("ready", "manual", "07:00"))
        self.assertEqual(len(body["briefing"]["priorities"]), 2)
        self.assertIsNone(body["fallback"])
        self.client.post("/briefing/today/generate", json={})
        self.assertEqual(len(self.llm.calls), 1, "bez regenerate se nic nepřegeneruje")
        body = self.client.post("/briefing/today/generate", json={"regenerate": True}).json()
        self.assertEqual((body["regenerated_count"], len(self.llm.calls)), (1, 2))

    def test_in_progress_is_409(self):
        self.login()

        def stuck(db):
            db.add(DailyBriefing(briefing_date=date(2026, 10, 6), status="generating", trigger="scheduler",
                                 attempts=1, grounding_removed=0, regenerated_count=0, created_at=SEVEN,
                                 updated_at=SEVEN))
            db.commit()
        self.q(stuck)
        self.assertEqual(self.client.post("/briefing/today/generate", json={}).status_code, 409)

    def test_failed_state_shows_error_and_fallback(self):
        self.seed_busy()
        self.login()
        self.llm.answers = [bs.BriefingError("daily_limit")]
        body = self.client.post("/briefing/today/generate", json={}).json()
        self.assertEqual(body["status"], "failed")
        self.assertIn("denní limit", body["error_text"])
        self.assertTrue(body["fallback"]["today"])


if __name__ == "__main__":
    unittest.main()
