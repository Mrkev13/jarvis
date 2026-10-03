"""A3 server-side context prefetch: deterministický výběr, rozpočet, Praha data, a méně tool kol v ask_ai."""
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

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import ai  # noqa: E402
import time_utils  # noqa: E402
import tools  # noqa: E402
from context_service import (  # noqa: E402
    CONTEXT_MAX_TOKENS,
    CONTEXT_TARGET_TOKENS,
    build_current_context,
    classify_areas,
)
from database import Base  # noqa: E402
from llm_budget import estimate_tokens  # noqa: E402
from models import Assignment, Exam, FinanceTransaction, Goal, Memory, Notification, Subject, WorkSession, WotGrind, WotResource  # noqa: E402
from planner_guard import find_planner_block  # noqa: E402

# 2. 10. 2026 00:30 Praha (pátek) = 1. 10. 22:30 UTC – UTC datum by bylo o den dřív.
NOW_UTC = datetime(2026, 10, 1, 22, 30)


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _seed_basic(db):
    subject = Subject(name="Foundations of Law", active=True)
    db.add(subject)
    db.flush()
    db.add_all([
        Assignment(title="Esej o ústavě", subject_id=subject.id, due_date=date(2026, 10, 3), status="todo"),
        WorkSession(date=date(2026, 9, 10), hours=7.5, project="Servind", hourly_rate=325, sync_to_finance=False),
        FinanceTransaction(amount=9000, category="work", description="", transaction_type="income",
                           created_at=datetime(2026, 9, 15, 10, 0)),
        Goal(area="finance", title="Našetřit 150 000 Kč", status="active", priority="high", progress=6,
             tracking_type="manual", target_value=150000, target_date=date(2027, 8, 31)),
        WotResource(resource="credits", amount=3082152),
        WotGrind(tank="VZ.55", xp_remaining=205988, priority="high", status="active"),
        Memory(area="wot", category="plan", content="Po VZ.55 chci začít CS linii.", importance=7, active=True),
    ])
    db.commit()


class AreaSelectionTestCase(unittest.TestCase):
    def test_keyword_areas(self):
        self.assertEqual(classify_areas("co mám zítra"), {"school", "goals", "notifications"})
        self.assertEqual(classify_areas("kolik jsem utratil za jídlo"), {"finance", "goals"})
        self.assertEqual(classify_areas("kolik mám kreditů ve WoT?"), {"wot"})
        self.assertEqual(classify_areas("ahoj"), set())
        self.assertIn("work", classify_areas("jak jde Servind", project_names=["Servind"]))
        self.assertEqual(classify_areas("jak jde Servind", project_names=["Servind"]), {"work", "finance", "goals"})
        self.assertIn("wot", classify_areas("kolik zbývá na VZ.55", tank_names=["VZ.55"]))

    def test_planning_questions_include_work_and_finance(self):
        # Regrese (live A3 C): planner priority řadí finance a práci, ale kontext je nenesl →
        # každý týdenní plán potřeboval extra kolo get_finance_summary + get_work_summary (a 429 TPM).
        for question in ("co mám dělat tento týden", "co mám dneska dělat", "naplánuj mi zítřek", "jaké mám priority"):
            self.assertTrue({"work", "finance", "school", "goals", "notifications"} <= classify_areas(question), question)
        # Čistě časový dotaz bez plánovacího záměru zůstává úzký.
        self.assertEqual(classify_areas("co mám zítra"), {"school", "goals", "notifications"})

    def test_weekly_plan_context_covers_planner_reads_within_budget(self):
        engine, Session = _session()
        db = Session()
        try:
            _seed_basic(db)
            ctx = build_current_context(db, "co mám dělat tento týden", now_utc=NOW_UTC)
            self.assertTrue({"get_work_summary", "get_finance_summary"} <= ctx.covered_tools)
            self.assertIn("work", ctx.sections)
            self.assertIn("finance", ctx.sections)
            self.assertLessEqual(ctx.estimated_tokens, CONTEXT_TARGET_TOKENS)
        finally:
            db.close()
            engine.dispose()

    def test_context_contains_only_selected_areas(self):
        engine, Session = _session()
        db = Session()
        try:
            _seed_basic(db)
            school = build_current_context(db, "co mám zítra", now_utc=NOW_UTC)
            self.assertIn("Esej o ústavě", school.text)
            self.assertNotIn("WoT zdroje", school.text)
            self.assertNotIn("Finance tento měsíc", school.text)
            self.assertIn("get_school_assignments", school.covered_tools)

            wot = build_current_context(db, "kolik mám kreditů ve WoT?", now_utc=NOW_UTC)
            self.assertIn("credits 3 082 152", wot.text)
            self.assertIn("Po VZ.55 chci začít CS linii.", wot.text)
            self.assertNotIn("Esej", wot.text)

            general = build_current_context(db, "ahoj", now_utc=NOW_UTC)
            self.assertEqual(general.sections, ("date",))
            self.assertEqual(general.covered_tools, frozenset())
        finally:
            db.close()
            engine.dispose()


class MemoryAndAuthorityTestCase(unittest.TestCase):
    def setUp(self):
        self.engine, Session = _session()
        self.db = Session()
        _seed_basic(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_inactive_memories_excluded(self):
        self.db.add(Memory(area="wot", category="plan", content="NEAKTIVNI plán na Object 260.", importance=10, active=False))
        self.db.commit()
        ctx = build_current_context(self.db, "co dál ve WoT", now_utc=NOW_UTC)
        self.assertIn("CS linii", ctx.text)
        self.assertNotIn("NEAKTIVNI", ctx.text)

    def test_live_state_precedes_and_outranks_conflicting_memory(self):
        self.db.add(Memory(area="finance", category="context", content="Na účtu mám 50 000 Kč.", importance=9, active=True))
        self.db.commit()
        ctx = build_current_context(self.db, "jaká je moje finanční bilance", now_utc=NOW_UTC)
        state, memory = ctx.text.split("RELEVANT MEMORY")
        self.assertIn("celková bilance 9 000 Kč", state)
        self.assertIn("50 000 Kč", memory)
        self.assertIn("never a source of current numbers", memory)
        self.assertTrue(ctx.text.startswith("CURRENT STATE"))
        self.assertIn("50 000", ctx.memory_text)
        self.assertNotIn("9 000", ctx.memory_text)


class ContextBudgetTestCase(unittest.TestCase):
    def test_typical_context_within_target_and_heavy_context_within_hard_max(self):
        engine, Session = _session()
        db = Session()
        try:
            _seed_basic(db)
            typical = build_current_context(db, "jak jsem na tom", now_utc=NOW_UTC)
            self.assertLessEqual(typical.estimated_tokens, CONTEXT_TARGET_TOKENS)

            subject = db.query(Subject).first()
            long = "Velmi dlouhý název položky s mnoha slovy, který se musí zkrátit " * 3
            for i in range(12):
                db.add_all([
                    Assignment(title=f"{long}{i}", subject_id=subject.id, due_date=date(2026, 9, 20 + i % 5), status="todo"),
                    Assignment(title=f"{long}N{i}", subject_id=subject.id, due_date=date(2026, 10, 3 + i % 6), status="todo"),
                    Exam(title=f"{long}E{i}", subject_id=subject.id, exam_date=date(2026, 10, 4 + i % 5), status="upcoming"),
                    Goal(area="personal", title=f"{long}G{i}", status="active", priority="high", progress=i),
                    Notification(area="school", title=f"{long}U{i}", message="x", severity="important",
                                 notification_type="deadline", source_type="assignment", dedupe_key=f"d{i}"),
                    WotGrind(tank=f"Tank {long[:30]} {i}", xp_remaining=1000 * i, priority="high", status="active"),
                    Memory(area="finance", category="plan", content=f"{long} práce finance škola WoT {i}", importance=8),
                ])
            db.commit()
            heavy_q = "jak jsem na tom s prací, financemi, školou, cíli, upozorněními a WoT tento týden"
            heavy = build_current_context(db, heavy_q, now_utc=NOW_UTC)
            self.assertLessEqual(heavy.estimated_tokens, CONTEXT_MAX_TOKENS)
            self.assertEqual(heavy.estimated_tokens, estimate_tokens(heavy.text))

            tight = build_current_context(db, heavy_q, now_utc=NOW_UTC, target_tokens=150, max_tokens=200)
            self.assertLessEqual(tight.estimated_tokens, 200)
            self.assertLess(len(tight.sections), len(heavy.sections))
        finally:
            db.close()
            engine.dispose()

    def test_configured_maximum_is_the_settings_default(self):
        self.assertEqual(CONTEXT_MAX_TOKENS, ai.LLM_SETTINGS.max_context_tokens)
        self.assertLessEqual(CONTEXT_TARGET_TOKENS, CONTEXT_MAX_TOKENS)
        self.assertLessEqual(CONTEXT_MAX_TOKENS, 600)


class PragueDateWindowTestCase(unittest.TestCase):
    def test_tomorrow_week_and_seven_day_window_use_prague_date(self):
        engine, Session = _session()
        db = Session()
        try:
            subject = Subject(name="Law", active=True)
            db.add(subject)
            db.flush()
            db.add_all([
                Assignment(title="Overdue", subject_id=subject.id, due_date=date(2026, 10, 1), status="todo"),
                Assignment(title="Edge7", subject_id=subject.id, due_date=date(2026, 10, 9), status="todo"),
                Assignment(title="Outside", subject_id=subject.id, due_date=date(2026, 10, 10), status="todo"),
                Assignment(title="Done", subject_id=subject.id, due_date=date(2026, 10, 3), status="done"),
            ])
            db.commit()
            ctx = build_current_context(db, "co mám zítra", now_utc=NOW_UTC)
            self.assertIn("Dnes 2026-10-02 (pá) 00:30; zítra 2026-10-03 (so)", ctx.text)
            self.assertIn("tento týden 2026-09-28 až 2026-10-04", ctx.text)
            overdue_line = next(l for l in ctx.text.splitlines() if l.startswith("Škola po termínu"))
            upcoming_line = next(l for l in ctx.text.splitlines() if l.startswith("Úkoly do 2026-10-09"))
            self.assertIn("Overdue", overdue_line)
            self.assertIn("Edge7", upcoming_line)
            self.assertNotIn("Outside", ctx.text)
            self.assertNotIn("Done", ctx.text)
        finally:
            db.close()
            engine.dispose()


def _message(content=None, tool_calls=None):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
        content=content, tool_calls=tool_calls,
    ))])


def _tool_round(name):
    return _message(tool_calls=[types.SimpleNamespace(id="c1", function=types.SimpleNamespace(name=name, arguments="{}"))])


def _plan(summary, actions):
    plan = {"summary": summary, "actions": [
        {"priority": i, "area": a, "title": t, "reason": r} for i, (a, t, r) in enumerate(actions, start=1)
    ]}
    return _message(content="Plán:\n```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```")


class AskAiWithContextTestCase(unittest.TestCase):
    """ask_ai s prefetch kontextem: odpověď bez tool kol, fallback tool volání, grounding."""

    def setUp(self):
        self.engine, Session = _session()
        db = Session()
        _seed_basic(db)
        db.close()
        self.script: list = []
        self.sent: list[list[dict]] = []

        def fake_llm(api_messages, **_kwargs):
            self.sent.append([dict(m) for m in api_messages])
            return self.script.pop(0)

        self._patches = [
            patch.object(ai, "SessionLocal", Session),
            patch.object(tools, "SessionLocal", Session),
            patch.object(ai, "_llm_create_with_retry", fake_llm),
            patch.object(ai, "now_local", lambda: time_utils.now_local(NOW_UTC)),
        ]
        for p in self._patches:
            p.start()
        self._orig_build = ai.build_current_context
        ai.build_current_context = lambda db, message, **kw: self._orig_build(db, message, now_utc=NOW_UTC, **kw)

    def tearDown(self):
        ai.build_current_context = self._orig_build
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def _ask(self, question, script):
        self.script = list(script)
        result = ai.ask_ai([{"role": "user", "content": question}])
        self.assertEqual(self.script, [], msg="nevyužité odpovědi fake modelu")
        return result

    def test_answer_from_context_needs_no_tool_round_and_no_planner_nudge(self):
        with self.assertLogs("standa_hub.llm", "INFO") as logs:
            result = self._ask("co mám dělat tento týden", [
                _plan("Týden", [
                    ("school", "Odevzdat Esej o ústavě do 2026-10-03", "Termín je zítra."),
                    ("wot", "Pokračovat ve VZ.55 před CS linií", "Plán z paměti."),
                ]),
            ])
        self.assertEqual(len(self.sent), 1, msg="jediné LLM volání – žádné read kolo, žádná připomínka")
        context_msg = self.sent[0][1]
        self.assertEqual(context_msg["role"], "system")
        self.assertTrue(context_msg["content"].startswith("CURRENT STATE"))
        self.assertIn("Esej o ústavě", context_msg["content"])
        self.assertEqual(len(find_planner_block(result["answer"]).plan["actions"]), 2)
        summary = next(line for line in logs.output if "request calls=" in line)
        self.assertIn("tool_rounds=0", summary)  # počet LLM volání hlídá len(self.sent) výše (fake obchází call_log)
        self.assertRegex(summary, r"context_tokens=\d+ context_sections=\d+")
        self.assertIn("planner_nudged=False", summary)
        self.assertNotIn("Esej", "\n".join(logs.output), msg="obsah kontextu se nesmí logovat")

    def test_missing_data_still_uses_a_tool(self):
        result = self._ask("Ukaž mi moje poslední finanční transakce.", [
            _tool_round("get_finance_transactions"),
            _message(content="Poslední transakce: příjem 9 000 Kč (work)."),
        ])
        self.assertEqual(len(self.sent), 2)
        self.assertIn("get_finance_transactions", self.sent[1][-2]["tool_calls"][0]["function"]["name"])
        tool_result = self.sent[1][-1]
        self.assertEqual(tool_result["role"], "tool")
        self.assertIn("9000", tool_result["content"].replace(" ", ""))
        self.assertIn("9 000", result["answer"])

    def test_planner_grounding_uses_live_state_not_memory_numbers(self):
        db = ai.SessionLocal()
        db.add(Memory(area="finance", category="context", content="Na účtu mám 50 000 Kč.", importance=9, active=True))
        db.commit()
        db.close()
        result = self._ask("co mám dělat tento týden s financemi", [
            _plan("Finance", [
                ("finance", "Zkontrolovat cíl Našetřit 150 000 Kč", "Bilance je 9 000 Kč."),
                ("finance", "Převést 50 000 Kč na spoření", "Podle paměti je to na účtu."),
                ("finance", "Odložit 3 000 Kč stranou", "Vymyšlená částka."),
            ]),
        ])
        titles = [a["title"] for a in find_planner_block(result["answer"]).plan["actions"]]
        self.assertEqual(titles, ["Zkontrolovat cíl Našetřit 150 000 Kč"])

    def test_context_failure_falls_back_to_plain_request(self):
        def boom(db, message, **kw):
            raise RuntimeError("db down")

        ai.build_current_context = boom
        result = self._ask("co mám zítra", [_message(content="Nevím, načtu data.")])
        self.assertEqual(len(self.sent), 1)
        self.assertFalse(any((m.get("content") or "").startswith("CURRENT STATE") for m in self.sent[0]))
        self.assertEqual(result["answer"], "Nevím, načtu data.")


if __name__ == "__main__":
    unittest.main()
