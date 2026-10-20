"""Phase G: Týdenní přehled – hranice týdne, snímek a metriky, grounding, LLM request, scheduler, API, push.
Falešné hodiny i LLM (případně lokální fake HTTP za OpenAI SDK) – žádný reálný Groq."""
import json
import os
import sys
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
import delivery_service as ds  # noqa: E402
import main  # noqa: E402
import reminder_service as rs  # noqa: E402
import scheduler_service  # noqa: E402
import weekly_review_service as wr  # noqa: E402
import weekly_snapshot as wsn  # noqa: E402
from database import Base  # noqa: E402
from models import (  # noqa: E402
    ActivityLog, Assignment, Delivery, Exam, FinanceTransaction, Goal, GoalProgressHistory, Notification, Reminder,
    Subject, WeeklyReview, WorkSession,
)
from tests.fakes import FakeGroq, FakeProvider, completion, groq_error  # noqa: E402

W = date(2026, 10, 5)  # pondělí; týden 5.–11. 10. 2026 (SELČ, UTC+2)
SUN19 = datetime(2026, 10, 11, 17, 0)  # neděle 19:00 Praha
MON_NEXT = datetime(2026, 10, 12, 6, 0)  # pondělí 8:00 Praha (další týden)


def answer(**over):
    data = {
        "headline": "Dokončený úkol, nižší výdělek",
        "summary": "Tento týden jsi dokončil jeden úkol a cíl se posunul. Výdělek byl nižší než minulý týden.",
        "wins": [{"ref": "metric:assignments_completed", "text": "Dokončen 1 úkol"},
                 {"ref": "goal:1", "text": "Cíl spoření se posunul z 6 % na 10 %"}],
        "concerns": [{"ref": "metric:work_income", "text": "Výdělek 1 400 Kč, minulý týden 2 200 Kč"},
                     {"ref": "assignment:1", "text": "Sada je stále po termínu"}],
        "comparisons": [{"ref": "metric:work_hours", "text": "Práce 7 h místo 11 h"},
                        {"ref": "metric:work_income", "text": "Výdělek −800 Kč"}],
        "next_week": [{"ref": "assignment:3", "text": "Projekt v úterý 13. 10."},
                      {"ref": "metric:next_week_deadlines", "text": "4 termíny, nejvíc ve středu"}],
        "forecasts": [{"ref": "forecast:deadline_load", "statement": "Příští týden může být náročnější: 4 termíny."}],
        "focus": [{"ref": "assignment:1", "text": "Dodělat Sadu"}],
    }
    data.update(over)
    return json.dumps(data, ensure_ascii=False)


class FakeLLM:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, messages, max_tokens):
        self.calls.append({"messages": messages, "max_tokens": max_tokens})
        a = self.answers.pop(0) if self.answers else answer()
        if isinstance(a, Exception):
            raise a
        return a, {"model": "fake", "prompt_tokens": 1500, "completion_tokens": 600, "total_tokens": 2100,
                   "latency_ms": 20}


class WeeklyTestBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self._env = patch.dict(os.environ, {"WEEKLY_REVIEW_ENABLED": "true", "WEEKLY_REVIEW_TIME": "19:00",
                                            "WEEKLY_REVIEW_DAY": "SUN", "WEEKLY_REVIEW_PUSH": "true"})
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

    def add(self, *objs):
        def go(db):
            db.add_all(objs)
            db.commit()
        self.q(go)

    def seed_normal(self):
        """Týden W: 1 dokončený úkol, 1 po termínu, práce 7 h (minulý týden 11 h), výdaje 1 500 vs 400 Kč,
        cíl 6 % → 10 %, příští týden 3 úkoly + 1 zkouška."""
        def go(db):
            s = Subject(name="Matematika")
            db.add(s)
            db.flush()
            for title, due, st in [("Sada", date(2026, 10, 2), "todo"), ("Esej", date(2026, 10, 8), "done"),
                                   ("Projekt", date(2026, 10, 13), "todo"), ("Referát", date(2026, 10, 14), "todo"),
                                   ("Laboratoř", date(2026, 10, 14), "todo")]:
                db.add(Assignment(title=title, subject_id=s.id, status=st, due_date=due))
            db.add(Exam(title="Zkouška fyzika", subject_id=s.id, status="upcoming", exam_date=date(2026, 10, 15)))
            db.flush()
            db.add(ActivityLog(timestamp=SUN19 - timedelta(days=3), area="school", action_type="complete",
                               entity_type="Assignment", entity_id=2, summary="Dokončeno (AI): Esej",
                               delta_json=json.dumps({"status": {"old": "todo", "new": "done"}}), dedupe_key="a1"))
            for d, h in [(date(2026, 10, 6), 4), (date(2026, 10, 8), 3), (date(2026, 9, 29), 6), (date(2026, 9, 30), 5)]:
                db.add(WorkSession(date=d, hours=h, hourly_rate=200))
            for days, amount, kind, cat in [(2, 1200, "expense", "Jídlo"), (3, 300, "expense", "Doprava"),
                                            (9, 400, "expense", "Jídlo"), (4, 1400, "income", "Práce")]:
                db.add(FinanceTransaction(amount=amount, category=cat, transaction_type=kind,
                                          created_at=SUN19 - timedelta(days=days)))
            g = Goal(area="finance", title="Našetřit 150 000 Kč", status="active", priority="high", progress=10,
                     target_date=date(2026, 10, 30), created_at=SUN19 - timedelta(days=60))
            db.add(g)
            db.flush()
            for days, p in [(40, 2), (20, 6), (5, 10)]:
                db.add(GoalProgressHistory(goal_id=g.id, progress=p, recorded_at=SUN19 - timedelta(days=days)))
            db.commit()
        self.q(go)

    def snap(self, ws=W, cutoff=SUN19, **kw):
        return self.q(lambda db: wsn.build_weekly_snapshot(db, ws, cutoff, **kw))

    def row(self, ws=W):
        return self.q(lambda db: db.query(WeeklyReview).filter_by(week_start=ws).one())

    def notes(self):
        return self.q(lambda db: db.query(Notification).filter_by(notification_type="weekly_review").all())


# ===== hranice týdne =====

class WeekBoundaryTestCase(unittest.TestCase):
    def test_monday_start_and_sunday_end(self):
        for d in (date(2026, 10, 5), date(2026, 10, 8), date(2026, 10, 11)):
            self.assertEqual(wsn.week_start_for(d), date(2026, 10, 5))
        self.assertEqual(wsn.week_start_for(date(2026, 10, 12)), date(2026, 10, 12))
        start, end = wsn.week_bounds_utc(date(2026, 10, 5))
        self.assertEqual((start, end), (datetime(2026, 10, 4, 22, 0), datetime(2026, 10, 11, 22, 0)))

    def test_dst_spring_and_autumn_weeks(self):
        start, end = wsn.week_bounds_utc(date(2026, 3, 23))  # 29. 3. jarní posun
        self.assertEqual((start, end), (datetime(2026, 3, 22, 23, 0), datetime(2026, 3, 29, 22, 0)))
        self.assertEqual(end - start, timedelta(hours=167))
        start, end = wsn.week_bounds_utc(date(2026, 10, 19))  # 25. 10. podzimní posun
        self.assertEqual((start, end), (datetime(2026, 10, 18, 22, 0), datetime(2026, 10, 25, 23, 0)))
        self.assertEqual(end - start, timedelta(hours=169))
        self.assertEqual(wr.scheduled_at(date(2026, 3, 23)), datetime(2026, 3, 29, 17, 0))  # 19:00 SELČ
        self.assertEqual(wr.scheduled_at(date(2026, 10, 19)), datetime(2026, 10, 25, 18, 0))  # 19:00 SEČ

    def test_year_and_iso_week_boundary(self):
        self.assertEqual(wsn.week_start_for(date(2027, 1, 1)), date(2026, 12, 28))
        self.assertEqual(wsn.week_start_for(date(2027, 1, 3)), date(2026, 12, 28))
        self.assertEqual(date(2027, 1, 1).isocalendar()[:2], (2026, 53))  # ISO týden 53 = tentýž týden
        self.assertEqual(wsn.week_label(date(2026, 12, 28)), "28. 12. 2026 – 3. 1. 2027")
        self.assertEqual(wsn.week_label(date(2026, 9, 28)), "28. 9. – 4. 10. 2026")
        self.assertEqual(wsn.week_label(date(2026, 10, 5)), "5.–11. 10. 2026")
        start, _ = wsn.week_bounds_utc(date(2026, 12, 28))
        self.assertEqual(start, datetime(2026, 12, 27, 23, 0))

    def test_due_week_never_next_week_early(self):
        with patch.dict(os.environ, {"WEEKLY_REVIEW_DAY": "SUN", "WEEKLY_REVIEW_TIME": "19:00"}):
            self.assertEqual(wr.due_week(SUN19 - timedelta(minutes=1)), date(2026, 9, 28))
            self.assertEqual(wr.due_week(SUN19), W)
            self.assertEqual(wr.due_week(datetime(2026, 10, 11, 21, 59)), W)  # ne 23:59 Praha
            self.assertEqual(wr.due_week(datetime(2026, 10, 11, 22, 0)), W)  # po 00:00: pořád minulý týden
            self.assertEqual(wr.due_week(MON_NEXT + timedelta(days=6)), W)  # ne 18. 10. 8:00

    def test_like_for_like_previous_period(self):
        cur, prev = wsn._period(W, SUN19)
        self.assertEqual((cur.start, cur.end, cur.last_day), (datetime(2026, 10, 4, 22, 0), SUN19, date(2026, 10, 11)))
        self.assertEqual((prev.start, prev.end), (datetime(2026, 9, 27, 22, 0), datetime(2026, 10, 4, 17, 0)))
        # přes podzimní DST: neděle 1. 11. 19:00 SEČ (18:00Z) vs 25. 10. 19:00 SEČ (18:00Z)
        cur, prev = wsn._period(date(2026, 10, 26), datetime(2026, 11, 1, 18, 0))
        self.assertEqual(prev.end, datetime(2026, 10, 25, 18, 0))
        self.assertEqual(prev.start, datetime(2026, 10, 18, 22, 0))
        # celý týden (catch-up): konec = pondělí 00:00, poslední den = neděle
        cur, _ = wsn._period(W, datetime(2026, 10, 20))
        self.assertEqual((cur.end, cur.last_day), (datetime(2026, 10, 11, 22, 0), date(2026, 10, 11)))


# ===== snímek a metriky =====

class SnapshotTestCase(WeeklyTestBase):
    def test_quiet_week_threshold(self):
        snap = self.snap()
        self.assertTrue(snap.is_quiet)
        self.assertEqual(snap.signals, 0)
        self.assertIn("ODHADY: žádné", snap.render())
        self.add(*[ActivityLog(timestamp=SUN19 - timedelta(hours=i + 1), area="school", action_type="create",
                               summary=f"Úkol {i}", dedupe_key=f"q{i}") for i in range(wsn.QUIET_MIN_SIGNALS - 1)])
        # MRK-60: změny ve Finance se do týdenního přehledu (vstup LLM) nepočítají ani jako datový bod
        self.add(*[ActivityLog(timestamp=SUN19 - timedelta(minutes=i + 1), area="finance", action_type="create",
                               summary=f"Výdaj {i} Kč", dedupe_key=f"f{i}") for i in range(5)])
        self.assertTrue(self.snap().is_quiet, "3 datové body = pořád málo dat")
        self.add(ActivityLog(timestamp=SUN19 - timedelta(hours=9), area="work", action_type="create",
                             summary="Práce", dedupe_key="q9"))
        self.assertFalse(self.snap().is_quiet)

    def test_normal_week_metrics_and_comparisons(self):
        self.seed_normal()
        snap = self.snap()
        m = {x.key: x for x in snap.metrics}
        self.assertEqual((m["assignments_completed"].cur, m["assignments_completed"].prev,
                          m["assignments_completed"].trend), (1, 0, "better"))
        self.assertEqual((m["work_hours"].cur, m["work_hours"].prev, m["work_hours"].delta), (7, 11, -4))
        self.assertEqual(m["work_hours"].pct, -36)
        self.assertEqual(m["work_hours"].trend, "down", "hodiny nemají polaritu dobré/špatné")
        self.assertEqual((m["work_income"].cur, m["work_income"].prev), (1400, 2200))
        # MRK-60: seed má transakce ve Finance, ale týdenní snímek (vstup LLM) z nich nic nepočítá
        self.assertFalse({k for k in m if k.startswith(("finance", "expense", "month_expense"))}, sorted(m))
        self.assertNotIn("1 500", snap.render())
        self.assertEqual((m["goals_progressed"].cur, m["goals_progressed"].prev), (1, 0))
        self.assertEqual((m["next_week_deadlines"].cur, m["next_week_deadlines"].prev), (4, 1))
        self.assertIn("nejvíc středa 14. 10. (2)", m["next_week_deadlines"].note)
        refs = {k: [i.ref for i in v] for k, v in snap.sections.items()}
        self.assertEqual(refs["school"], ["assignment:2", "assignment:1"])
        self.assertEqual(refs["goals"], ["goal:1"])
        self.assertEqual(refs["next_week"], ["assignment:3", "assignment:4", "assignment:5", "exam:1"])
        text = snap.render()
        self.assertIn("[goal:1] Našetřit 150 000 Kč · 6 % → 10 % · +4 %", text)
        self.assertIn("Srovnání = předchozí týden ve stejném rozsahu", text)
        self.assertFalse(snap.is_quiet)

    def test_previous_week_comparison_is_like_for_like(self):
        prev_cut = SUN19 - timedelta(days=7)

        def created(at, entity_id):
            return ActivityLog(timestamp=at, area="school", action_type="create", entity_type="Assignment",
                               entity_id=entity_id, summary=f"Úkol přidán {entity_id}", dedupe_key=f"c{entity_id}")
        self.add(created(prev_cut - timedelta(hours=1), 1),
                 created(prev_cut + timedelta(hours=1), 2),  # minulá neděle po 19:00
                 created(SUN19 - timedelta(hours=2), 3))
        m = {x.key: x for x in self.snap().metrics}
        self.assertEqual((m["assignments_created"].cur, m["assignments_created"].prev), (1, 1))
        m = {x.key: x for x in self.snap(cutoff=datetime(2026, 10, 13)).metrics}  # celý týden (catch-up)
        self.assertEqual(m["assignments_created"].prev, 2)

    def test_technical_activity_is_filtered(self):
        noise = [dict(area="goals", action_type="snapshot", summary="Snapshot"),
                 dict(area="finance", action_type="sync", summary="Sync"),
                 dict(area="system", action_type="error", summary="Chyba"),
                 dict(area="school", action_type="update", summary="Úprava", user_context="unit_test"),
                 dict(area="school", action_type="create", summary="Úkol [TEST]"),
                 dict(area="school", action_type="create", summary="Dočasný", entity_type="Assignment", entity_id=50),
                 dict(area="school", action_type="delete", summary="Dočasný", entity_type="Assignment", entity_id=50)]
        keep = [dict(area="school", action_type="create", summary="Úkol přidán: Protokol", entity_type="Assignment",
                     entity_id=51),
                dict(area="reminders", action_type="complete", summary="Připomínka hotová: fyzio")]
        self.add(*[ActivityLog(timestamp=SUN19 - timedelta(hours=i + 1), dedupe_key=f"n{i}", **kw)
                   for i, kw in enumerate(noise + keep)])
        snap = self.snap()
        self.assertEqual(sorted(snap.activity_summary.split(" (")[0].split(", ")), ["1× reminders", "1× school"])
        labels = " ".join(i.label for i in snap.sections["activity"])
        for word in ("Snapshot", "Sync", "Chyba", "Úprava", "[TEST]", "Dočasný"):
            self.assertNotIn(word, labels)
        self.assertEqual({x.key: x for x in snap.metrics}["assignments_created"].cur, 1)

    def test_no_double_counting(self):
        self.seed_normal()
        logs = [  # dvojí záznam téže dokončené Eseje + dokončení, které bylo vráceno (úkol 3 je dnes todo)
            ActivityLog(timestamp=SUN19 - timedelta(days=2), area="school", action_type="update", entity_type="Assignment",
                        entity_id=2, summary="Upraveno (AI): Esej", delta_json=json.dumps({"status": {"new": "completed"}}),
                        dedupe_key="dup"),
            ActivityLog(timestamp=SUN19 - timedelta(days=2), area="school", action_type="complete",
                        entity_type="Assignment", entity_id=3, summary="Dokončeno (AI): Projekt", dedupe_key="undone"),
        ]
        self.add(*logs)

        def link_work_income(db):
            tx = db.query(FinanceTransaction).filter_by(transaction_type="income").one()
            db.query(WorkSession).filter_by(date=date(2026, 10, 6)).one().finance_transaction_id = tx.id
            db.commit()
        self.q(link_work_income)
        m = {x.key: x for x in self.snap().metrics}
        self.assertEqual(m["assignments_completed"].cur, 1)
        self.assertNotIn("finance_income", m, "MRK-60: Finance do týdenního přehledu nejde")
        self.assertEqual(m["work_income"].cur, 1400, "výdělek z práce jen jednou, z práce")

    def test_next_week_contains_only_known_open_commitments(self):
        self.seed_normal()

        def extra(db):
            db.add(Assignment(title="Hotový", subject_id=1, status="done", due_date=date(2026, 10, 13)))
            db.add(Exam(title="Složená", subject_id=1, status="passed", exam_date=date(2026, 10, 13)))
            db.add(Reminder(title="Jednorázová", due_at=datetime(2026, 10, 14, 8, 0), status="scheduled",
                            recurrence="none"))
            db.add(Reminder(title="Pozdější", due_at=datetime(2026, 10, 21, 8, 0), status="scheduled",
                            recurrence="none"))
            db.add(Reminder(title="Denní", due_at=datetime(2026, 10, 12, 8, 0), status="scheduled",
                            recurrence="daily", local_time="10:00"))
            db.commit()
        self.q(extra)
        labels = [i.label for i in self.snap().sections["next_week"]]
        self.assertIn("Jednorázová", labels)
        for name in ("Hotový", "Složená", "Pozdější", "Denní"):
            self.assertNotIn(name, labels)

    def test_backlog_delta(self):
        def go(db):
            subject = Subject(name="Dějepis")
            db.add(subject)
            db.flush()
            sid = subject.id
            for i, st in enumerate(("done", "done", "todo")):
                db.add(Assignment(id=10 + i, title=f"Starý {i}", subject_id=sid, status=st, due_date=date(2026, 9, 20)))
            db.add(Assignment(id=20, title="Zpětně zadaný", subject_id=sid, status="todo", due_date=date(2026, 9, 30)))
            db.flush()
            for i in (10, 11):
                db.add(ActivityLog(timestamp=SUN19 - timedelta(days=1), area="school", action_type="complete",
                                   entity_type="Assignment", entity_id=i, summary=f"Dokončeno {i}", dedupe_key=f"c{i}"))
            db.add(ActivityLog(timestamp=SUN19 - timedelta(days=1), area="school", action_type="create",
                               entity_type="Assignment", entity_id=20, summary="Úkol přidán", dedupe_key="c20"))
            db.commit()
        self.q(go)
        m = {x.key: x for x in self.snap().metrics}["overdue_backlog"]
        self.assertEqual((m.prev, m.cur, m.trend), (3, 2, "better"))

    def test_small_money_changes_are_not_trends(self):
        self.add(WorkSession(date=date(2026, 10, 10), hours=2, hourly_rate=200),
                 WorkSession(date=date(2026, 10, 3), hours=1.5, hourly_rate=200))
        snap = self.snap()
        m = {x.key: x for x in snap.metrics}
        self.assertEqual((m["work_income"].cur, m["work_income"].prev), (400, 300))
        self.assertEqual(m["work_income"].trend, "same")
        self.assertIsNone(m["work_income"].pct, "procenta jen nad rozumným základem")

    def test_goal_stagnation_and_forecast_rules(self):
        def go(db):
            g = Goal(area="school", title="Přečíst 10 knih", status="active", progress=30,
                     created_at=SUN19 - timedelta(days=90), target_date=date(2026, 12, 31))
            db.add(g)
            db.flush()
            for days in (40, 30, 20):
                db.add(GoalProgressHistory(goal_id=g.id, progress=30, recorded_at=SUN19 - timedelta(days=days)))
            db.commit()
        self.q(go)
        snap = self.snap()
        [item] = snap.sections["goals"]
        self.assertIn("beze změny", item.when)
        self.assertEqual(wr._tone(snap, item.ref), "negative")
        self.assertEqual(snap.forecasts, [], "bez podložených dat žádný odhad")

    def test_work_trend_forecast_and_no_spending_pace(self):
        def go(db):
            for d, h in [(date(2026, 9, 22), 12), (date(2026, 9, 29), 8), (date(2026, 10, 6), 5)]:
                db.add(WorkSession(date=d, hours=h, hourly_rate=0))
            db.add(FinanceTransaction(amount=6000, category="Nájem", transaction_type="expense",
                                      created_at=datetime(2026, 9, 10)))
            db.add(FinanceTransaction(amount=5000, category="Jídlo", transaction_type="expense",
                                      created_at=datetime(2026, 10, 6)))
            db.commit()
        self.q(go)
        snap = self.snap()
        f = {x.key: x for x in snap.forecasts}
        self.assertEqual(f["work_trend_down"].confidence, "low")
        self.assertIn("12 h → 8 h → 5 h", f["work_trend_down"].statement)
        # MRK-60: tempo výdajů je Finance agregát → žádný odhad ani metrika, i když transakce existují
        self.assertNotIn("spending_pace", f)
        self.assertNotIn("month_expense_pace", {x.key for x in snap.metrics})
        for fc in snap.forecasts:
            self.assertIsNone(wr._BANNED_RE.search(fc.statement))

    def test_token_budget_quiet_normal_busy_worst(self):
        quiet = self.snap()
        self.seed_normal()
        normal = self.snap()

        def busy(db):
            for i in range(12):
                db.add(Assignment(title=f"Úkol {i}", subject_id=1, status="todo", due_date=date(2026, 10, 1 + i)))
                db.add(FinanceTransaction(amount=300 + 100 * i, category=f"Kat {i % 4}", transaction_type="expense",
                                          created_at=SUN19 - timedelta(days=i % 9, hours=i)))
                db.add(ActivityLog(timestamp=SUN19 - timedelta(hours=i + 2), area="school", action_type="create",
                                   summary=f"Úkol přidán {i}", dedupe_key=f"b{i}"))
            db.commit()
        self.q(busy)
        busy_snap = self.snap()

        def flood(db):
            for i in range(300):
                db.add(Assignment(title=f"Velmi dlouhý název úkolu {i} " + "x" * 120, subject_id=1, status="todo",
                                  due_date=date(2026, 9, 1) + timedelta(days=i % 50)))
                db.add(ActivityLog(timestamp=SUN19 - timedelta(minutes=i + 1), area="school", action_type="create",
                                   summary="Změna " + "y" * 200, dedupe_key=f"f{i}"))
                db.add(Goal(area="school", title=f"Cíl {i} " + "z" * 100, status="active", priority="high",
                            target_date=date(2026, 10, 1) + timedelta(days=i % 20)))
                db.add(FinanceTransaction(amount=1000 + i, category=f"Kategorie {i % 40} " + "k" * 30,
                                          transaction_type="expense", created_at=SUN19 - timedelta(days=i % 14)))
                db.add(Reminder(title=f"Připomínka {i} " + "r" * 80, due_at=SUN19 - timedelta(days=1), status="fired"))
            db.commit()
        self.q(flood)
        worst = self.snap()
        self.assertLess(normal.tokens, 1500)
        self.assertLessEqual(worst.tokens, wsn.MAX_SNAPSHOT_TOKENS)
        for s in (normal, busy_snap, worst):
            self.assertLess(wr.estimate_request_tokens(s), 6000, "pohodlně pod 8k TPM")
        print(f"\n[weekly budget] quiet snapshot={quiet.tokens} (bez LLM); "
              f"normal snapshot={normal.tokens} request≈{wr.estimate_request_tokens(normal)}; "
              f"busy snapshot={busy_snap.tokens} request≈{wr.estimate_request_tokens(busy_snap)}; "
              f"worst snapshot={worst.tokens} request≈{wr.estimate_request_tokens(worst)}; "
              f"schema≈{wr.estimate_tokens(json.dumps(wr.RESPONSE_SCHEMA))} system≈{wr.estimate_tokens(wr.SYSTEM_PROMPT)}")


# ===== grounding a generování =====

class GenerateTestCase(WeeklyTestBase):
    def gen(self, llm, now=SUN19, trigger="scheduler", regenerate=False):
        return self.q(lambda db: wr.generate(db, trigger=trigger, now=now, regenerate=regenerate, llm=llm))

    def content(self):
        return json.loads(self.row().content)

    def test_valid_review_is_grounded_persisted_and_notified(self):
        self.seed_normal()
        llm = FakeLLM()
        self.gen(llm)
        row = self.row()
        self.assertEqual((row.status, row.trigger, row.attempts, row.total_tokens, row.grounding_fixes),
                         ("ready", "scheduler", 1, 2100, 0))
        self.assertEqual(row.period_end, SUN19)
        c = self.content()
        self.assertEqual([w["ref"] for w in c["wins"]], ["metric:assignments_completed", "goal:1"])
        self.assertEqual([x["ref"] for x in c["concerns"]], ["metric:work_income", "assignment:1"])
        self.assertEqual(c["comparisons"][0]["metric"]["delta_text"], "−4 h (−36 %)")
        [fc] = c["forecasts"]
        self.assertEqual((fc["confidence"], fc["confidence_text"], fc["kind"]), ("high", "vysoká", "forecast"))
        self.assertEqual(len(fc["basis_labels"]), 4)
        self.assertEqual((c["partial"], c["quiet"], c["week_start"]), (True, False, "2026-10-05"))
        self.assertEqual([m["role"] for m in llm.calls[0]["messages"]], ["system", "user"])
        self.assertEqual(llm.calls[0]["max_tokens"], wr.MAX_OUTPUT_TOKENS)
        [n] = self.notes()
        self.assertEqual((n.title, n.action_url, n.dedupe_key), ("📅 Týdenní přehled", "/review",
                                                                 "weekly_review:2026-10-05"))

    def test_unknown_duplicate_and_wrong_tone_refs_are_dropped(self):
        self.seed_normal()
        self.gen(FakeLLM(answer(
            wins=[{"ref": "metric:work_income", "text": "Výdělek"},  # horší ≠ úspěch
                  {"ref": "assignment:999", "text": "Vymyšlený úkol"},
                  {"ref": "metric:assignments_completed", "text": "Dokončen 1 úkol"},
                  {"ref": "metric:assignments_completed", "text": "Znovu"}],
            concerns=[{"ref": "metric:assignments_completed", "text": "I starost?"},  # už je úspěch
                      {"ref": "assignment:1", "text": "Sada po termínu"}],
        )))
        c = self.content()
        self.assertEqual([w["ref"] for w in c["wins"]], ["metric:assignments_completed"])
        self.assertEqual([x["ref"] for x in c["concerns"]], ["assignment:1"])
        self.assertGreaterEqual(self.row().grounding_fixes, 4)

    def test_invented_dates_money_causality_and_refs_are_removed(self):
        self.seed_normal()
        self.gen(FakeLLM(answer(
            summary="Výdaje vzrostly kvůli nákupům na 9 999 Kč.",
            wins=[{"ref": "goal:1", "text": "Cíl se posunul (goal:1) díky šetření"}],
            concerns=[{"ref": "assignment:1", "text": "Sada měla termín 20. 10."},
                      {"ref": "metric:work_income", "text": "Výdělek 5 000 Kč (metric:work_income)"}],
            next_week=[{"ref": "assignment:3", "text": "Projekt [assignment:3] v úterý 13. 10."}],
        )))
        c = self.content()
        dump = json.dumps({k: c[k] for k in ("summary", "wins", "concerns", "next_week")}, ensure_ascii=False)
        for bad in ("kvůli", "9 999", "díky", "20. 10.", "5 000"):
            self.assertNotIn(bad, dump)
        self.assertEqual(c["summary"], wr.deterministic_summary(self.snap()))
        self.assertEqual(c["concerns"][0]["text"], "Sada · po termínu od 2. 10.")
        self.assertEqual(c["next_week"][0]["text"], "Projekt v úterý 13. 10.", "ref vyčištěn, zbytek platí")
        for item in c["wins"] + c["concerns"] + c["next_week"]:
            self.assertNotRegex(item["text"], r"(metric|goal|assignment):")

    def test_forecasts_must_be_candidates_and_hedged(self):
        self.seed_normal()
        self.gen(FakeLLM(answer(forecasts=[
            {"ref": "forecast:exam_success", "statement": "Zkoušku z fyziky nejspíš složíš."},
            {"ref": "metric:work_hours", "statement": "Budeš pracovat méně."},
            {"ref": "forecast:deadline_load", "statement": "Příští týden určitě nezvládneš 4 termíny."},
        ])))
        [fc] = self.content()["forecasts"]
        self.assertEqual(fc["ref"], "forecast:deadline_load")
        self.assertEqual(fc["statement"], self.snap().forecasts[0].statement, "jistota → deterministický text")
        self.gen(FakeLLM(answer(forecasts=[{"ref": "forecast:deadline_load",
                                            "statement": "Kvůli stresu a nízké motivaci bude týden těžký."}])),
                 now=SUN19 + timedelta(minutes=5), trigger="manual", regenerate=True)
        [fc] = self.content()["forecasts"]
        self.assertNotRegex(fc["statement"], "stres|motivac")

    def test_mostly_hallucinated_answer_is_rejected(self):
        self.seed_normal()
        bad = [{"ref": f"assignment:{900 + i}", "text": "x"} for i in range(4)]
        self.gen(FakeLLM(answer(wins=bad, concerns=bad, comparisons=[], next_week=[], forecasts=[], focus=[])))
        row = self.row()
        self.assertEqual((row.status, row.error_category), ("failed", "grounding_rejected"))
        self.assertIsNone(row.content)
        self.assertEqual(self.notes(), [])

    def test_malformed_json_is_invalid_response(self):
        self.seed_normal()
        for text in ("not json", '{"headline": 1}', '{"headline":"a","summary":"b","wins":"x"}'):
            with self.subTest(text=text):
                self.q(lambda db: (db.query(WeeklyReview).delete(), db.commit()))
                self.gen(FakeLLM(text))
                self.assertEqual(self.row().error_category, "invalid_response")

    def test_quiet_week_is_deterministic_without_llm(self):
        llm = FakeLLM()
        self.gen(llm)
        self.assertEqual(llm.calls, [])
        row = self.row()
        c = self.content()
        self.assertEqual((row.status, row.model, c["quiet"], c["headline"]), ("ready", "deterministic", True,
                                                                             "Klidný týden – málo dat"))
        self.assertEqual(c["forecasts"], [])
        self.assertIn("málo záznamů", c["summary"])

    def test_manual_regeneration_and_failure_keeps_previous(self):
        self.seed_normal()
        self.gen(FakeLLM(), trigger="manual")
        self.assertEqual(self.notes(), [], "ruční generování bez notifikace")
        before = self.row().content
        self.gen(FakeLLM(wr.WeeklyReviewError("output_limit")), now=SUN19 + timedelta(hours=1), trigger="manual",
                 regenerate=True)
        row = self.row()
        self.assertEqual((row.status, row.error_category, row.content), ("ready", "regenerate_failed:output_limit",
                                                                         before))
        self.gen(FakeLLM(answer(headline="Nový titulek týdne")), now=SUN19 + timedelta(hours=2), trigger="manual",
                 regenerate=True)
        row = self.row()
        self.assertEqual((row.regenerated_count, row.attempts), (1, 3))
        self.assertEqual(json.loads(row.content)["headline"], "Nový titulek týdne")


class StructuredRequestTestCase(WeeklyTestBase):
    """Reálná cesta přes structured_llm → ai._llm_create_with_retry → OpenAI SDK → lokální fake HTTP."""

    def run_with(self, fake, now=SUN19):
        with patch.object(ai, "client", fake.client()), patch("time.sleep", lambda s: None):
            return self.q(lambda db: wr.generate(db, trigger="scheduler", now=now))

    def test_strict_schema_low_reasoning_cap_no_tools_no_history(self):
        self.seed_normal()
        fake = FakeGroq((200, completion(answer())))
        with self.assertLogs("standa_hub.weekly_review", "INFO") as logs:
            self.run_with(fake)
        [body] = fake.requests
        self.assertEqual((body["reasoning_effort"], body["max_completion_tokens"]), ("low", 1600))
        for key in ("max_tokens", "tools", "tool_choice"):
            self.assertNotIn(key, body)
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        fmt = body["response_format"]
        self.assertEqual((fmt["type"], fmt["json_schema"]["name"], fmt["json_schema"]["strict"]),
                         ("json_schema", "weekly_review", True))
        schema = fmt["json_schema"]["schema"]
        self.assertEqual(schema, wr.RESPONSE_SCHEMA)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(sorted(schema["required"]), sorted(schema["properties"]))
        row = self.row()
        self.assertEqual((row.status, row.prompt_tokens, row.completion_tokens, row.total_tokens),
                         ("ready", 900, 400, 1300))
        out = "\n".join(logs.output)
        self.assertIn("reasoning_tokens=150", out)
        for private in ("Sada", "Našetřit", "SNAPSHOT", "Matematika"):
            self.assertNotIn(private, out, "log bez obsahu promptu/snímku")

    def test_output_limit_and_schema_errors(self):
        self.seed_normal()
        for response, category, delay in [
            ((200, completion('{"headline":"x', finish="length")), "output_limit", timedelta(hours=6)),
            (groq_error(400, "Failed to generate JSON", "json_validate_failed"), "schema_error", timedelta(hours=1)),
        ]:
            with self.subTest(category=category):
                self.q(lambda db: (db.query(WeeklyReview).delete(), db.commit()))
                self.run_with(FakeGroq(response))
                row = self.row()
                self.assertEqual((row.status, row.error_category, row.next_retry_at), ("failed", category, SUN19 + delay))


# ===== scheduler =====

class SchedulerTestCase(WeeklyTestBase):
    def tick(self, now, llm):
        return self.q(lambda db: wr.run_scheduled(db, now=now, llm=llm))

    def setUp(self):
        super().setUp()
        self.seed_normal()
        self.add(WeeklyReview(week_start=date(2026, 9, 28), status="ready", trigger="scheduler", attempts=1,
                              grounding_fixes=0, regenerated_count=0, content="{}", generated_at=SUN19 - timedelta(days=7),
                              created_at=SUN19, updated_at=SUN19))

    def test_sunday_generation_once_and_no_duplicates(self):
        llm = FakeLLM()
        self.assertEqual(self.tick(SUN19 - timedelta(minutes=1), llm), "exists")  # minulý týden už je
        self.assertEqual(self.tick(SUN19, llm), "generated")
        for minutes in (15, 30, 60 * 5):
            self.assertEqual(self.tick(SUN19 + timedelta(minutes=minutes), llm), "exists")
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(self.row().trigger, "scheduler")
        self.assertEqual(len(self.notes()), 1)

    def test_restart_catch_up_covers_full_previous_week(self):
        llm = FakeLLM()
        self.assertEqual(self.tick(MON_NEXT, llm), "generated")
        row = self.row()
        self.assertEqual((row.trigger, row.period_end), ("catchup", datetime(2026, 10, 11, 22, 0)))
        self.assertFalse(json.loads(row.content)["partial"])
        self.assertEqual(self.q(lambda db: db.query(WeeklyReview).count()), 2)

    def test_next_week_is_never_generated_early(self):
        llm = FakeLLM()
        self.tick(SUN19, llm)
        for days in range(1, 7):
            self.assertEqual(self.tick(SUN19 + timedelta(days=days) - timedelta(minutes=1), llm), "exists")
        self.assertEqual(self.q(lambda db: db.query(WeeklyReview).count()), 2)
        self.assertEqual(self.tick(SUN19 + timedelta(days=7), llm), "generated")
        self.assertEqual(self.row(date(2026, 10, 12)).week_start, date(2026, 10, 12))

    def test_retry_bounds_and_daily_limit(self):
        llm = FakeLLM(*[wr.WeeklyReviewError("daily_limit")] * 10)
        self.tick(SUN19, llm)
        self.assertEqual(self.row().next_retry_at, SUN19 + timedelta(hours=3))
        self.assertEqual(self.tick(SUN19 + timedelta(hours=1), llm), "waiting")
        t = SUN19
        for _ in range(3):
            t += timedelta(hours=3, minutes=1)
            self.assertEqual(self.tick(t, llm), "retried")
        self.assertEqual(self.tick(t + timedelta(hours=4), llm), "gave_up")
        self.assertEqual(len(llm.calls), 4)

    def test_stuck_generation_recovers(self):
        self.add(WeeklyReview(week_start=W, status="generating", trigger="scheduler", attempts=1, grounding_fixes=0,
                              regenerated_count=0, created_at=SUN19, updated_at=SUN19))
        llm = FakeLLM()
        self.assertEqual(self.tick(SUN19 + timedelta(minutes=5), llm), "in_progress")
        self.assertEqual(self.tick(SUN19 + timedelta(minutes=11), llm), "retried")
        self.assertEqual((self.row().status, self.row().attempts), ("ready", 2))

    def test_custom_day_time_and_disabled(self):
        with patch.dict(os.environ, {"WEEKLY_REVIEW_DAY": "SAT", "WEEKLY_REVIEW_TIME": "10:00"}):
            self.assertEqual(wr.scheduled_at(W), datetime(2026, 10, 10, 8, 0))
            self.assertEqual(self.tick(datetime(2026, 10, 10, 8, 0), FakeLLM()), "generated")
        with patch.dict(os.environ, {"WEEKLY_REVIEW_ENABLED": "false"}):
            self.assertEqual(self.tick(SUN19 + timedelta(days=7), FakeLLM()), "disabled")

    def test_failure_is_isolated_from_reminders_and_briefing(self):
        import briefing_service as bs

        def go(db):
            rs.create_from_spec(db, rs.build_spec("fyzio", in_minutes=1, now=datetime(2020, 1, 1)))
            db.commit()
        self.q(go)

        def boom(db, now=None, llm=None):
            raise RuntimeError("Groq down")

        briefing_calls = []
        with patch.object(scheduler_service, "SessionLocal", self.Session), \
                patch.object(wr, "run_scheduled", boom), \
                patch.object(bs, "run_scheduled", lambda db, now=None, llm=None: briefing_calls.append(1) or "exists"):
            scheduler_service._run_weekly_review_job()  # nesmí vyhodit
            scheduler_service._run_reminders_job()
            scheduler_service._run_briefing_job()
        self.assertEqual(self.q(lambda db: db.query(Reminder).one().status), "fired")
        self.assertEqual(briefing_calls, [1])


# ===== notifikace / Web Push =====

class PushTestCase(WeeklyTestBase):
    def test_one_notification_and_push_via_phase_e_queue(self):
        self.seed_normal()
        self.q(lambda db: wr.run_scheduled(db, now=SUN19, llm=FakeLLM()))
        self.q(lambda db: wr.run_scheduled(db, now=SUN19 + timedelta(minutes=20), llm=FakeLLM()))
        self.assertEqual(len(self.notes()), 1)
        p = FakeProvider()
        for minutes in (1, 2, 3):
            self.q(lambda db: ds.run_delivery_cycle(db, [p], now=SUN19 + timedelta(minutes=minutes)))
        calls = [c for c in p.calls if c[1]["title"] == "📅 Týdenní přehled"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["url"], "/review")
        self.assertEqual(self.q(lambda db: db.query(Delivery).filter(Delivery.dedupe_key.like("weekly_review:%"))
                                .count()), 1)

    def test_push_disabled_keeps_internal_notification(self):
        self.seed_normal()
        self.q(lambda db: wr.run_scheduled(db, now=SUN19, llm=FakeLLM()))
        with patch.dict(os.environ, {"WEEKLY_REVIEW_PUSH": "false"}):
            self.assertNotIn("weekly_review", ds.deliverable_types())
            p = FakeProvider()
            self.q(lambda db: ds.run_delivery_cycle(db, [p], now=SUN19 + timedelta(minutes=1)))
        self.assertFalse([c for c in p.calls if c[1]["title"] == "📅 Týdenní přehled"])
        self.assertEqual(len(self.notes()), 1)
        self.assertIn("daily_briefing", ds.deliverable_types(), "ostatní typy beze změny")


# ===== API =====

class WeeklyApiTestCase(WeeklyTestBase):
    def setUp(self):
        super().setUp()
        self.llm = FakeLLM()
        self.now = SUN19
        self._patches = [
            patch.object(main, "SessionLocal", self.Session),
            patch.object(auth_service, "SessionLocal", self.Session),
            patch.object(auth_service, "_failed_attempts", {}),
            patch.object(auth_service, "AUTH_PIN_HASH", bcrypt.hashpw(b"4821", bcrypt.gensalt(rounds=4)).decode()),
            patch.object(wr, "_call_llm", lambda snap, llm=None: self.llm(wr.build_messages(snap), wr.MAX_OUTPUT_TOKENS)),
            patch.object(wr, "utc_now", lambda: self.now),
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
        for method, path in (("get", "/weekly-review"), ("get", "/weekly-review/history"),
                             ("get", "/weekly-review/week/2026-10-05"), ("post", "/weekly-review/generate")):
            self.assertEqual(getattr(self.client, method)(path).status_code, 401, path)
        self.assertEqual(self.llm.calls, [])

    def test_current_generate_regenerate_and_history(self):
        self.seed_normal()
        self.login()
        body = self.client.get("/weekly-review").json()
        self.assertEqual((body["status"], body["week_start"], body["week_label"], body["schedule_label"]),
                         ("missing", "2026-10-05", "5.–11. 10. 2026", "neděle 19:00"))
        self.assertTrue(body["can_generate"])
        self.assertTrue(body["fallback"]["next_week"])
        body = self.client.post("/weekly-review/generate", json={}).json()
        self.assertEqual((body["status"], body["trigger"], body["generated_label"], body["period_end_label"]),
                         ("ready", "manual", "neděle 11. 10. 19:00", "neděle 11. 10. 19:00"))
        self.assertIsNone(body["fallback"])
        self.client.post("/weekly-review/generate", json={})
        self.assertEqual(len(self.llm.calls), 1)
        body = self.client.post("/weekly-review/generate", json={"regenerate": True}).json()
        self.assertEqual((body["regenerated_count"], len(self.llm.calls)), (1, 2))
        items = self.client.get("/weekly-review/history").json()["items"]
        self.assertEqual([(i["week_start"], i["status"]) for i in items], [("2026-10-05", "ready")])
        self.assertEqual(items[0]["headline"], "Dokončený úkol, nižší výdělek")
        # historický týden: čtení ano, generování ne (endpoint generuje jen aktuální týden)
        self.now = SUN19 + timedelta(days=7)
        old = self.client.get("/weekly-review/week/2026-10-05").json()
        self.assertEqual((old["status"], old["is_current"], old["can_generate"]), ("ready", False, False))
        body = self.client.post("/weekly-review/generate", json={}).json()
        self.assertEqual(body["week_start"], "2026-10-12")

    def test_week_endpoint_validation(self):
        self.login()
        self.assertEqual(self.client.get("/weekly-review/week/2026-10-06").status_code, 422)
        self.assertEqual(self.client.get("/weekly-review/week/2025-01-06").status_code, 404)

    def test_in_progress_is_409_and_failed_state(self):
        self.seed_normal()
        self.login()
        self.add(WeeklyReview(week_start=W, status="generating", trigger="scheduler", attempts=1, grounding_fixes=0,
                              regenerated_count=0, created_at=SUN19, updated_at=SUN19))
        self.assertEqual(self.client.post("/weekly-review/generate", json={}).status_code, 409)
        self.now = SUN19 + timedelta(minutes=30)
        self.llm.answers = [wr.WeeklyReviewError("daily_limit")]
        body = self.client.post("/weekly-review/generate", json={}).json()
        self.assertEqual(body["status"], "failed")
        self.assertIn("denní limit", body["error_text"])
        self.assertTrue(body["fallback"]["comparisons"])


if __name__ == "__main__":
    unittest.main()
