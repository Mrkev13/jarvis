"""Roadmap 4G: režim Dnes – pražský den, časová osa, pozornost, plán, deduplikace, částečné selhání, auth."""
import os
import sys
import time
import unittest
from datetime import date, datetime
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("GROQ_API_KEY", "x")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import bcrypt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import auth_service  # noqa: E402
import main  # noqa: E402
import planner_service  # noqa: E402
import today_service as ts  # noqa: E402
from database import Base  # noqa: E402
from module_registry import ModuleAccess  # noqa: E402
from models import Assignment, Exam, Notification, Reminder, Subject  # noqa: E402
from time_utils import local_to_utc  # noqa: E402

# So 10. 10. 2026 14:00 Praha (CEST = UTC+2)
NOW = datetime(2026, 10, 10, 12, 0)


def utc(y, mo, d, h, mi=0):
    """Pražský čas → naive UTC."""
    return local_to_utc(datetime(y, mo, d, h, mi))


class TodayBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.db.add(Subject(id=1, name="Fyzika"))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add(self, *rows):
        self.db.add_all(rows)
        self.db.commit()

    def build(self, now=NOW):
        return ts.build_today(self.db, now_utc=now, access=ModuleAccess({"calendar": False}))  # These cases isolate core/School semantics.

    @staticmethod
    def ids(items):
        return [it["id"] for it in items]

    def notification(self, nid, source_type, source_id, severity="important", title="Upozornění", **kw):
        return Notification(id=nid, area=kw.pop("area", "school"), title=title, message=kw.pop("message", "Zpráva"),
                            severity=severity, notification_type="overdue", source_type=source_type, source_id=source_id,
                            dedupe_key=f"n{nid}", created_at=NOW, last_triggered_at=NOW, action_url=kw.pop("action_url", "/school"))


class DateSemanticsTestCase(TodayBase):
    def test_today_tomorrow_yesterday(self):
        self.add(
            Reminder(id=1, title="Fyzio", due_at=utc(2026, 10, 10, 17), status="scheduled"),
            Reminder(id=2, title="Zítra", due_at=utc(2026, 10, 11, 9), status="scheduled"),
            Exam(id=1, title="Test fyzika", subject_id=1, exam_date=date(2026, 10, 10), status="upcoming"),
            Assignment(id=1, title="Sada", subject_id=1, due_date=date(2026, 10, 11), status="todo"),
            Assignment(id=2, title="Stará", subject_id=1, due_date=date(2026, 10, 8), status="todo"),
        )
        out = self.build()
        self.assertEqual(out["date"], "2026-10-10")
        self.assertEqual(out["date_label"], "sobota 10. 10. 2026")
        self.assertEqual(self.ids(out["timeline"]), ["reminder:1", "exam:1"])
        self.assertIn("assignment:2", self.ids(out["attention"]), "včerejší a starší = po termínu")
        self.assertEqual(self.ids(out["upcoming"]), ["reminder:2"], "zítřek je až v Potom")
        self.assertIn("assignment:1", self.ids(out["priorities"]), "zítřejší termín z plánovače zůstává v plánu, ne v Potom")

    def test_midnight_uses_prague_not_utc(self):
        # 22:30 UTC 10. 10. = 00:30 Praha 11. 10. → „dnes" je už 11. 10.
        self.add(
            Reminder(id=1, title="Ranní", due_at=utc(2026, 10, 11, 8), status="scheduled"),
            Reminder(id=2, title="Pozdní včera", due_at=utc(2026, 10, 10, 23, 45), status="done"),
        )
        out = self.build(now=datetime(2026, 10, 10, 22, 30))
        self.assertEqual(out["date"], "2026-10-11")
        self.assertEqual(self.ids(out["timeline"]), ["reminder:1"])
        self.assertEqual(out["now_local"], "00:30")

    def test_dst_end_day_has_25_hours(self):
        # 25. 10. 2026: 03:00 CEST → 02:00 CET. Položka v 23:30 místního času patří do dne, v 00:10 další den ne.
        self.add(
            Reminder(id=1, title="Noc", due_at=utc(2026, 10, 25, 23, 30), status="scheduled"),
            Reminder(id=2, title="Ráno", due_at=utc(2026, 10, 25, 1, 30), status="scheduled"),
            Reminder(id=3, title="Další den", due_at=utc(2026, 10, 26, 0, 10), status="scheduled"),
        )
        out = self.build(now=datetime(2026, 10, 24, 22, 30))  # 00:30 CEST 25. 10.
        self.assertEqual(out["date"], "2026-10-25")
        self.assertEqual([(it["id"], it["time"]) for it in out["timeline"]], [("reminder:2", "01:30"), ("reminder:1", "23:30")])

    def test_sunday_to_monday(self):
        self.add(Exam(id=1, title="Pondělní", subject_id=1, exam_date=date(2026, 10, 12), status="upcoming"))
        sunday = self.build(now=datetime(2026, 10, 11, 20, 0))  # ne 22:00
        self.assertEqual(sunday["date_label"], "neděle 11. 10. 2026")
        self.assertNotIn("exam:1", self.ids(sunday["timeline"]))
        self.assertIn("exam:1", self.ids(sunday["priorities"]) + self.ids(sunday["upcoming"]))
        monday = self.build(now=datetime(2026, 10, 11, 22, 5))  # po 00:05
        self.assertEqual(self.ids(monday["timeline"]), ["exam:1"])


class TimelineTestCase(TodayBase):
    def test_sorting_untimed_done_and_next(self):
        self.add(
            Reminder(id=1, title="Večer", due_at=utc(2026, 10, 10, 19), status="scheduled"),
            Reminder(id=2, title="Ráno hotovo", due_at=utc(2026, 10, 10, 8), status="done"),
            Reminder(id=3, title="Odpoledne", due_at=utc(2026, 10, 10, 16, 15), status="scheduled"),
            Reminder(id=4, title="Zaznělo", due_at=utc(2026, 10, 10, 11), status="fired"),
            Assignment(id=1, title="Esej", subject_id=1, due_date=date(2026, 10, 10), status="todo"),
            Assignment(id=2, title="Hotový úkol", subject_id=1, due_date=date(2026, 10, 10), status="done"),
        )
        out = self.build()
        tl = out["timeline"]
        self.assertEqual(self.ids(tl), ["reminder:4", "reminder:3", "reminder:1", "assignment:1", "reminder:2", "assignment:2"])
        status = {it["id"]: it["status"] for it in tl}
        self.assertEqual(status, {"reminder:4": "due", "reminder:3": "upcoming", "reminder:1": "upcoming",
                                  "assignment:1": "open", "reminder:2": "done", "assignment:2": "done"})
        nxt = out["summary"]["next"]
        self.assertEqual((nxt["id"], nxt["time"], nxt["minutes_until"]), ("reminder:3", "16:15", 135))
        self.assertEqual(out["summary"]["remaining"], 4)
        self.assertEqual(out["summary"]["done"], 2)
        self.assertEqual(tl[0]["href"], "/reminders?reminder=4")
        self.assertEqual(tl[3]["href"], "/school?assignment=1")
        self.assertEqual(tl[3]["subtitle"], "Úkol · termín dnes · Fyzika")

    def test_recurring_fired_today_is_past(self):
        self.add(Reminder(id=1, title="Protažení", due_at=utc(2026, 10, 11, 7), status="scheduled", recurrence="daily",
                          local_time="07:00", last_fired_at=utc(2026, 10, 10, 7)))
        out = self.build()
        self.assertEqual([(it["id"], it["status"], it["time"]) for it in out["timeline"]], [("reminder:1", "past", "07:00")])
        self.assertEqual(out["upcoming"], [], "další výskyt zítra se neopakuje v Potom")

    def test_no_next_after_last_event(self):
        self.add(Reminder(id=1, title="Ráno", due_at=utc(2026, 10, 10, 8), status="done"))
        self.assertIsNone(self.build()["summary"]["next"])


class AttentionAndDedupTestCase(TodayBase):
    def test_overdue_and_notifications_dedup(self):
        self.add(
            Assignment(id=1, title="Sada", subject_id=1, due_date=date(2026, 10, 2), status="todo"),
            Exam(id=1, title="Zítřejší test", subject_id=1, exam_date=date(2026, 10, 12), status="upcoming"),
            Reminder(id=1, title="Stará připomínka", due_at=utc(2026, 10, 9, 18), status="fired"),
            self.notification(1, "assignment", 1, "important", "Po termínu: Sada"),
            self.notification(2, "goal", None, "warning", "Cíl spoření stagnuje", area="finance", action_url="/goals"),
            self.notification(3, "exam", 1, "warning", "Zkouška za 2 dny"),
        )
        out = self.build()
        att = out["attention"]
        self.assertEqual(self.ids(att)[0], "assignment:1", "nejzávažnější první")
        self.assertEqual(self.ids(att).count("assignment:1"), 1, "upozornění k úkolu se spojí s položkou")
        self.assertIn("reminder:1", self.ids(att))
        self.assertIn("notification:2", self.ids(att), "upozornění bez záznamu zůstává")
        self.assertIn("exam:1", self.ids(att), "upozornění na blízký termín = pozornost")
        self.assertNotIn("exam:1", self.ids(out["upcoming"]), "jednou, ne i v Potom")
        self.assertEqual(out["summary"]["attention"], len(att))
        self.assertEqual(att[0]["href"], "/school?assignment=1")

    def test_today_item_with_notification_stays_in_timeline_with_severity(self):
        self.add(
            Reminder(id=1, title="Fyzio", due_at=utc(2026, 10, 10, 11), status="fired"),
            self.notification(1, "reminder", 1, "important", "Fyzioterapie", area="reminders", action_url="/reminders"),
        )
        out = self.build()
        self.assertEqual(self.ids(out["timeline"]), ["reminder:1"])
        self.assertEqual(out["timeline"][0]["severity"], "important")
        self.assertEqual(out["attention"], [], "neopakuje se v Pozornosti")

    def test_planner_items_deduplicated_with_badge(self):
        self.add(
            Assignment(id=1, title="Sada", subject_id=1, due_date=date(2026, 10, 2), status="todo"),
            Exam(id=1, title="test", subject_id=1, exam_date=date(2026, 10, 10), status="upcoming"),
            Exam(id=2, title="Fyzika", subject_id=1, exam_date=date(2026, 10, 13), status="upcoming"),
        )
        out = self.build()
        everywhere = self.ids(out["timeline"]) + self.ids(out["attention"]) + self.ids(out["priorities"]) + self.ids(out["upcoming"])
        self.assertEqual(len(everywhere), len(set(everywhere)), f"žádný záznam dvakrát: {everywhere}")
        by_id = {it["id"]: it for it in out["timeline"] + out["attention"]}
        self.assertIsNotNone(by_id["assignment:1"]["priority"], "priorita z plánu jako značka")
        self.assertIsNotNone(by_id["exam:1"]["priority"])
        self.assertIn("exam:2", self.ids(out["priorities"]), "plán: termín za 3 dny zůstává v plánu (je nejvýš)")
        self.assertEqual(out["priorities"][0]["href"], "/school?exam=2")

    def test_dedupe_rules_unit(self):
        T = ts.TodayItem
        tl = [T(id="exam:1", type="exam", title="A")]
        att = [T(id="exam:1", type="exam", title="A"), T(id="assignment:2", type="assignment", title="B")]
        pr = [T(id="assignment:2", type="planner", title="B", priority=1), T(id="goal:3", type="planner", title="C", priority=2)]
        up = [T(id="goal:3", type="exam", title="C"), T(id="exam:4", type="exam", title="D")]
        out = ts.dedupe(tl, att, pr, up, {"exam:1": "warning"})
        self.assertEqual([[it.id for it in out[k]] for k in ("timeline", "attention", "priorities", "upcoming")],
                         [["exam:1"], ["assignment:2"], ["goal:3"], ["exam:4"]])
        self.assertEqual(out["attention"][0].priority, 1)
        self.assertEqual(out["timeline"][0].severity, "warning")

    def test_notification_for_finished_record_is_dropped(self):
        self.add(
            Assignment(id=1, title="Sada", subject_id=1, due_date=date(2026, 10, 2), status="done"),
            Reminder(id=1, title="Lístky", due_at=utc(2026, 10, 9, 9), status="done"),
            self.notification(1, "assignment", 1, "important", "Po termínu: Sada"),
            self.notification(2, "reminder", 1, "warning", "Lístky", area="reminders"),
        )
        self.assertEqual(self.build()["attention"], [], "upozornění k vyřízenému záznamu se nezobrazí")

    def test_no_attention(self):
        out = self.build()
        self.assertEqual(out["attention"], [])
        self.assertEqual(out["summary"]["attention"], 0)


class EmptyAndPartialTestCase(TodayBase):
    def test_completely_empty_day(self):
        out = self.build()
        self.assertEqual((out["timeline"], out["attention"], out["priorities"], out["upcoming"]), ([], [], [], []))
        self.assertEqual(out["summary"], {"remaining": 0, "done": 0, "attention": 0, "next": None})
        self.assertEqual(out["errors"], {})

    def test_only_future_item(self):
        self.add(Reminder(id=1, title="Lístky", due_at=utc(2026, 10, 14, 10), status="scheduled"))
        out = self.build()
        self.assertEqual(out["timeline"], [])
        self.assertEqual(self.ids(out["upcoming"]), ["reminder:1"])
        self.assertEqual(out["upcoming"][0]["date"], "2026-10-14")

    def test_one_source_error_keeps_other_sections(self):
        self.add(Reminder(id=1, title="Fyzio", due_at=utc(2026, 10, 10, 17), status="scheduled"),
                 Assignment(id=1, title="Sada", subject_id=1, due_date=date(2026, 10, 2), status="todo"))
        with patch.object(ts, "generate_plan", side_effect=RuntimeError("boom")):
            out = self.build()
        self.assertEqual(out["errors"], {"priorities": ts.SECTION_ERRORS["priorities"]})
        self.assertEqual(self.ids(out["timeline"]), ["reminder:1"])
        self.assertEqual(self.ids(out["attention"]), ["assignment:1"])
        with patch.object(ts, "list_notifications", side_effect=RuntimeError("boom")):
            out = self.build()
        self.assertEqual(list(out["errors"]), ["attention"])
        self.assertEqual(self.ids(out["timeline"]), ["reminder:1"])

    def test_upcoming_is_bounded(self):
        self.add(*[Exam(id=i, title=f"T{i}", subject_id=1, exam_date=date(2026, 10, 11 + i % 5), status="upcoming") for i in range(1, 8)],
                 Exam(id=50, title="Daleko", subject_id=1, exam_date=date(2026, 10, 30), status="upcoming"))
        with patch.object(ts, "generate_plan", return_value={"actions": []}):
            out = self.build()
        self.assertEqual(len(out["upcoming"]), ts.MAX_UPCOMING)
        self.assertNotIn("exam:50", self.ids(out["upcoming"]))
        self.assertEqual([it["date"] for it in out["upcoming"]], sorted(it["date"] for it in out["upcoming"]))

    def test_fast(self):
        self.add(*[Reminder(id=i, title=f"R{i}", due_at=utc(2026, 10, 10, 8 + i % 12), status="scheduled") for i in range(1, 60)])
        start = time.perf_counter()
        self.build()
        self.assertLess(time.perf_counter() - start, 1.0)


class PlannerRefTestCase(unittest.TestCase):
    def test_action_ref(self):
        self.assertEqual(planner_service.action_ref("assignment:overdue:12"), "assignment:12")
        self.assertEqual(planner_service.action_ref("exam:deadline:3:4"), "exam:4")
        self.assertEqual(planner_service.action_ref("goal:stagnation:7"), "goal:7")
        self.assertEqual(planner_service.action_ref("work:behind:9"), "goal:9")
        self.assertIsNone(planner_service.action_ref("weird"))
        self.assertIsNone(planner_service.action_ref(None))


class TodayApiTestCase(unittest.TestCase):
    PIN = "4821"

    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine)
        self._patches = [
            patch.object(auth_service, "SessionLocal", Session),
            patch.object(main, "SessionLocal", Session),
            patch.object(auth_service, "_failed_attempts", {}),
            patch.object(auth_service, "AUTH_PIN_HASH", bcrypt.hashpw(self.PIN.encode(), bcrypt.gensalt(rounds=4)).decode()),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()

    def test_requires_session_and_returns_shape(self):
        self.assertEqual(self.client.get("/today").status_code, 401)
        self.assertEqual(self.client.post("/auth/login", json={"pin": self.PIN}).status_code, 200)
        r = self.client.get("/today")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()), {"date", "date_label", "now_local", "summary", "timeline", "attention", "priorities", "upcoming", "snooze_options", "errors"})


if __name__ == "__main__":
    unittest.main()
