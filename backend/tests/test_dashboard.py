import os
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import (
    Assignment,
    Exam,
    FinanceTransaction,
    Goal,
    Notification,
    Subject,
    WorkSession,
    WotGrind,
    MffCharacter,
)
from main import (
    _top_active_goals,
    _get_work_with_goal,
    _get_finance_with_goal,
    _get_upcoming,
    _get_notifications_preview,
    _get_wot_quick_status,
    _get_mff_quick_status,
)


def _now():
    return datetime(2026, 9, 11, 9, 0, 0)


def _today():
    return date(2026, 9, 11)


def _make_notification(
    db,
    dedupe_key,
    severity,
    area,
    title,
    message,
    read=False,
    created_at=None,
    action_url=None,
):
    now = created_at or _now()
    n = Notification(
        area=area,
        title=title,
        message=message,
        severity=severity,
        read=read,
        created_at=now,
        expires_at=now + timedelta(days=7),
        notification_type="deadline",
        source_type="assignment",
        source_id=None,
        dedupe_key=dedupe_key,
        last_triggered_at=now,
        resolved=False,
        action_url=action_url,
    )
    db.add(n)
    db.flush()
    return n


class DashboardTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = Session()

        subj = Subject(name="Test", code="", semester="", credits=0, active=True)
        self.db.add(subj)
        self.db.commit()
        self.subject_id = subj.id

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_empty_db_returns_empty_shapes(self):
        goals = _top_active_goals(self.db, limit=3)
        self.assertEqual(goals, [])

        work = _get_work_with_goal(self.db)
        self.assertEqual(work["this_month_hours"], 0.0)
        self.assertEqual(work["this_month_earnings"], 0.0)
        self.assertIsNone(work["goal"])

        finance = _get_finance_with_goal(self.db)
        self.assertEqual(finance["balance"], 0.0)
        self.assertEqual(finance["income"], 0.0)
        self.assertEqual(finance["expenses"], 0.0)
        self.assertIsNone(finance["goal"])

        upcoming = _get_upcoming(self.db, limit=5)
        self.assertEqual(upcoming, [])

        notifs = _get_notifications_preview(self.db, limit=3)
        self.assertEqual(notifs, [])

        wot = _get_wot_quick_status(self.db, limit=2)
        self.assertEqual(wot["top_grinds"], [])

        mff = _get_mff_quick_status(self.db)
        self.assertEqual(mff["tracked_characters"], 0)
        self.assertEqual(mff["t4_count"], 0)

    def test_high_priority_goal_selection(self):
        today = _today()
        g1 = Goal(
            area="finance", title="Našetřit 150k", status="active", priority="medium",
            progress=9, tracking_type="manual", target_value=150000,
            target_date=today + timedelta(days=355),
        )
        g2 = Goal(
            area="mff", title="10 T4 postav", status="active", priority="high",
            progress=60, tracking_type="automatic", source="mff_t4_count",
            target_value=10, target_date=today + timedelta(days=90),
        )
        g3 = Goal(
            area="work", title="Work 100h měsíčně", status="active", priority="high",
            progress=0, tracking_type="automatic", source="work_month_hours",
            target_value=100, target_date=today + timedelta(days=19),
        )
        g4 = Goal(
            area="school", title="Splnit zkoušky", status="paused", priority="high",
            progress=50, target_date=today + timedelta(days=20),
        )
        for g in [g1, g2, g3, g4]:
            self.db.add(g)
        self.db.commit()

        top = _top_active_goals(self.db, limit=3)
        titles = [g["title"] for g in top]
        self.assertNotIn("Splnit zkoušky", titles)
        self.assertEqual(len(top), 3)
        self.assertEqual(top[0]["priority"].lower(), "high")
        self.assertEqual(top[1]["priority"].lower(), "high")
        high_titles = [t for t in titles if t in ("Work 100h měsíčně", "10 T4 postav")]
        self.assertEqual(len(high_titles), 2)
        self.assertLess(titles.index("Work 100h měsíčně"), titles.index("10 T4 postav"))

    def test_upcoming_sorting_overdue_first(self):
        today = _today()
        ass_overdue = Assignment(
            title="Assignment XYZ", description="",
            due_date=today - timedelta(days=2), priority="high", status="todo",
            subject_id=self.subject_id,
        )
        exam_3d = Exam(
            title="Zkouška z práva", exam_type="exam",
            exam_date=today + timedelta(days=3), status="upcoming",
            subject_id=self.subject_id, notes="",
        )
        ass_7d = Assignment(
            title="Úkol 7d", description="",
            due_date=today + timedelta(days=7), priority="medium", status="todo",
            subject_id=self.subject_id,
        )
        goal_14d = Goal(
            area="general", title="Cíl za 14d", status="active",
            target_date=today + timedelta(days=14),
        )
        ass_completed = Assignment(
            title="Vyřešené", description="",
            due_date=today + timedelta(days=1), priority="low", status="completed",
            subject_id=self.subject_id,
        )
        for item in [ass_overdue, exam_3d, ass_7d, goal_14d, ass_completed]:
            self.db.add(item)
        self.db.commit()

        rows = _get_upcoming(self.db, limit=5, today=today)
        self.assertEqual(rows[0]["title"], "Assignment XYZ")
        self.assertTrue(rows[0]["overdue"])
        self.assertEqual(rows[0]["days_left"], -2)
        row_titles = [r["title"] for r in rows]
        self.assertNotIn("Vyřešené", row_titles)
        non_overdue = [r for r in rows if not r["overdue"]]
        days = [r["days_left"] for r in non_overdue]
        self.assertEqual(days, sorted(days))
        self.assertEqual(non_overdue[0]["title"], "Zkouška z práva")
        self.assertEqual(non_overdue[0]["days_left"], 3)

    def test_notification_priority_sort(self):
        n1 = _make_notification(
            self.db, "n-info", "info", "school", "Info school", "zprava info",
            read=False, created_at=_now() - timedelta(minutes=10),
        )
        _ = n1
        n2 = _make_notification(
            self.db, "n-important", "important", "finance", "Bilance nízká", "important zpráva",
            read=False, created_at=_now() - timedelta(minutes=1),
            action_url="/finance",
        )
        _ = n2
        n3 = _make_notification(
            self.db, "n-warning", "warning", "work", "Work zaostává", "warning zpráva",
            read=False, created_at=_now() - timedelta(minutes=5),
        )
        _ = n3
        self.db.commit()

        rows = _get_notifications_preview(self.db, limit=3, now=_now())
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["severity"], "important")
        self.assertEqual(rows[1]["severity"], "warning")
        self.assertEqual(rows[2]["severity"], "info")
        self.assertEqual(rows[0]["action_url"], "/finance")

    def test_work_goal_progress_included(self):
        today = _today()
        session_date = today
        s1 = WorkSession(
            date=session_date, hours=42.0, project="Proj",
            description="", hourly_rate=400, sync_to_finance=False,
        )
        self.db.add(s1)

        g = Goal(
            area="work", title="100h měsíčně", status="active", priority="high",
            progress=0, tracking_type="automatic", source="work_month_hours",
            target_value=100, target_date=today + timedelta(days=19),
        )
        self.db.add(g)
        self.db.commit()

        work = _get_work_with_goal(self.db, today=today)
        self.assertEqual(work["this_month_hours"], 42.0)
        self.assertIsNotNone(work["goal"])
        self.assertEqual(work["goal"]["title"], "100h měsíčně")
        self.assertEqual(work["goal"]["target_value"], 100.0)
        self.assertEqual(work["goal"]["current_value"], 42.0)
        self.assertEqual(work["goal"]["progress"], 42)

    def test_finance_goal_progress_included(self):
        today = _today()
        today_created = datetime(2026, 9, 11, 8, 0, 0)
        inc = FinanceTransaction(
            amount=50000, category="plat", description="",
            transaction_type="income", created_at=today_created,
        )
        exp = FinanceTransaction(
            amount=15000, category="nájem", description="",
            transaction_type="expense", created_at=today_created,
        )
        old_inc = FinanceTransaction(
            amount=30000, category="plat", description="",
            transaction_type="income",
            created_at=today_created - timedelta(days=31),
        )
        self.db.add_all([inc, exp, old_inc])
        g = Goal(
            area="finance", title="Bilance 100k", status="active", priority="high",
            progress=0, tracking_type="automatic", source="finance_balance",
            target_value=100000, target_date=today + timedelta(days=120),
        )
        self.db.add(g)
        self.db.commit()

        fin = _get_finance_with_goal(self.db, today=today)
        self.assertEqual(fin["balance"], 65000.0)
        self.assertEqual(fin["this_month_income"], 50000.0)
        self.assertEqual(fin["this_month_expenses"], 15000.0)
        self.assertIsNotNone(fin["goal"])
        self.assertEqual(fin["goal"]["current_value"], 65000.0)
        self.assertEqual(fin["goal"]["target_value"], 100000.0)
        self.assertEqual(fin["goal"]["progress"], 65)

    def test_wot_grind_priority_ordered(self):
        g1 = WotGrind(tank="Tank Low", xp_remaining=1000, priority="low", status="active")
        g2 = WotGrind(tank="Tank High", xp_remaining=50000, priority="high", status="active")
        g3 = WotGrind(tank="Tank Medium", xp_remaining=5000, priority="medium", status="in_progress")
        done = WotGrind(tank="Hotové", xp_remaining=0, priority="high", status="completed")
        self.db.add_all([g1, g2, g3, done])
        self.db.commit()

        wot = _get_wot_quick_status(self.db, limit=2)
        tank_names = [g["tank"] for g in wot["top_grinds"]]
        self.assertEqual(tank_names[:2], ["Tank High", "Tank Medium"])
        self.assertNotIn("Hotové", tank_names)

    def test_mff_quick_status_tracks_t4_and_avg_bc(self):
        c1 = MffCharacter(
            name="Thor", tier="T4", level=80, priority="high", status="built",
            uniform="u", ctp="ctp", artifact="a",
            uru_slots_total=20, uru_slots_filled=20, odin_blessings_count=8,
            iso8_set="iso", team_supports="s1,s2",
        )
        c2 = MffCharacter(
            name="Loki", tier="T3", level=80, priority="medium", status="built",
            uniform="u", ctp="", artifact="",
            uru_slots_total=20, uru_slots_filled=0, odin_blessings_count=0,
            iso8_set="", team_supports="",
        )
        self.db.add_all([c1, c2])
        self.db.commit()

        mff = _get_mff_quick_status(self.db)
        self.assertEqual(mff["tracked_characters"], 2)
        self.assertEqual(mff["t4_count"], 1)
        self.assertEqual(mff["priority_count"], 1)
        self.assertGreater(mff["average_build_completeness"], 0)


if __name__ == "__main__":
    unittest.main()
