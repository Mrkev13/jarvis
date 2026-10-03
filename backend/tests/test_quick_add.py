"""Roadmap 4E: Rychlé přidání – deterministický parser, validace, endpointy a bezpečný zápis přes pending akce."""
import os
import sys
import time
import unittest
from datetime import datetime, timedelta
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

import ai  # noqa: E402
import auth_service  # noqa: E402
import main  # noqa: E402
import quick_add_service as qa  # noqa: E402
import reminder_actions  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from models import (  # noqa: E402
    ActivityLog, Assignment, Exam, FinanceTransaction, PendingAction, Reminder, Subject, WorkSession,
)
from time_utils import local_to_utc  # noqa: E402

# So 3. 10. 2026 12:00 v Praze (CEST, UTC+2)
NOW = datetime(2026, 10, 3, 10, 0)
SUBJECTS = [
    {"id": 1, "name": "Právo", "code": "PRA"},
    {"id": 2, "name": "English in IT", "code": "EIT"},
    {"id": 3, "name": "Algoritmizace", "code": "ALG"},
    {"id": 4, "name": "Fyzika", "code": "FYZ1"},
    {"id": 5, "name": "Fyzika II", "code": "FYZ2"},
]


def p(text, now=NOW, subjects=SUBJECTS):
    return qa.parse(text, now_utc=now, subjects=subjects)


def fields_of(errors):
    return {e["field"] for e in errors}


class ReminderParseTestCase(unittest.TestCase):
    def test_tomorrow_with_time(self):
        r = p("zítra fyzio v 17:00")
        self.assertEqual(r["kind"], "reminder")
        self.assertEqual(r["confidence"], "high")
        self.assertEqual(r["fields"], {"title": "Fyzio", "due_local": "2026-10-04T17:00"})
        self.assertTrue(r["ready"])
        self.assertEqual(r["display"]["subtitle"], "zítra v 17:00")
        self.assertEqual(r["display"]["area"], "reminders")

    def test_explicit_keyword_weekday(self):
        r = p("připomeň mi v pátek zavolat mámě")
        self.assertEqual(r["kind"], "reminder")
        self.assertEqual(r["fields"]["title"], "Zavolat mámě")
        self.assertEqual(r["fields"]["due_local"], "2026-10-09T09:00")
        self.assertTrue(any("09:00" in w for w in r["warnings"]), "výchozí čas je vidět")

    def test_relative(self):
        r = p("za 2 hodiny vyndat prádlo")
        self.assertEqual(r["kind"], "reminder")
        self.assertEqual(r["fields"], {"title": "Vyndat prádlo", "due_local": "2026-10-03T14:00"})
        r = p("za 30 minut čaj")
        self.assertEqual(r["fields"]["due_local"], "2026-10-03T12:30")
        r = p("za půl hodiny čaj")
        self.assertEqual(r["fields"]["due_local"], "2026-10-03T12:30")

    def test_time_passed_today_moves_to_tomorrow_with_warning(self):
        r = p("v 8:00 vitamíny")
        self.assertEqual(r["fields"]["due_local"], "2026-10-04T08:00")
        self.assertTrue(any("zítra" in w for w in r["warnings"]))

    def test_next_week_weekday(self):
        # „příští" = den v příštím kalendářním týdnu; ze soboty je to tedy nejbližší pondělí
        self.assertEqual(p("připomeň mi příští pondělí kontrola")["fields"]["due_local"], "2026-10-05T09:00")
        wed = datetime(2026, 10, 7, 10, 0)
        self.assertEqual(p("připomeň mi v pátek kontrola", now=wed)["fields"]["due_local"], "2026-10-09T09:00")
        self.assertEqual(p("připomeň mi příští pátek kontrola", now=wed)["fields"]["due_local"], "2026-10-16T09:00")
        self.assertEqual(p("připomeň mi ve středu kontrola", now=wed)["fields"]["due_local"], "2026-10-07T09:00")

    def test_missing_when_and_what(self):
        r = p("připomeň mi zavolat")
        self.assertIn("due_local", fields_of(r["needs_input"]))
        self.assertFalse(r["ready"])
        self.assertEqual(r["confidence"], "medium")
        r = p("připomeň mi zítra v 10:00")
        self.assertIn("title", fields_of(r["needs_input"]))

    def test_invalid_time(self):
        r = p("zítra v 25:00 schůzka")
        self.assertFalse(r["ready"])

    def test_near_midnight_prague(self):
        # 22:30 UTC = 00:30 v Praze dalšího dne → „zítra" je 5. 10., ne 4. 10.
        late = datetime(2026, 10, 3, 22, 30)
        self.assertEqual(p("zítra fyzio v 17:00", now=late)["fields"]["due_local"], "2026-10-05T17:00")
        self.assertEqual(p("dnes 3 hodiny RaceX", now=late)["fields"]["date"], "2026-10-04")

    def test_dst_end(self):
        # 25. 10. 2026 končí letní čas (03:00 CEST → 02:00 CET). Relativní čas počítá s pražskou zónou.
        before = datetime(2026, 10, 24, 20, 0)  # 22:00 CEST
        r = p("zítra v 10:00 budík", now=before)
        self.assertEqual(r["fields"]["due_local"], "2026-10-25T10:00")
        self.assertEqual(local_to_utc(datetime(2026, 10, 25, 10, 0)), datetime(2026, 10, 25, 9, 0))
        night = datetime(2026, 10, 24, 23, 30)  # 01:30 CEST
        r = p("za 2 hodiny prádlo", now=night)
        self.assertTrue(r["fields"]["due_local"].startswith("2026-10-25T0"))


class FinanceParseTestCase(unittest.TestCase):
    def test_store_expense(self):
        r = p("Albert 820 Kč")
        self.assertEqual(r["kind"], "finance")
        self.assertEqual(r["confidence"], "high")
        self.assertEqual(r["fields"], {"transaction_type": "expense", "amount": 820.0, "category": "Potraviny",
                                       "description": "Albert"})
        self.assertTrue(any("albert" in w for w in r["warnings"]), "odvozená kategorie je vidět")
        self.assertTrue(r["ready"])

    def test_decimal_comma(self):
        r = p("oběd 189,90 Kč")
        self.assertEqual(r["fields"]["amount"], 189.9)
        self.assertEqual(r["fields"]["category"], "Jídlo")
        self.assertIn("189,90\xa0Kč", r["display"]["subtitle"])

    def test_income(self):
        r = p("příjem Servind 5000 Kč")
        self.assertEqual(r["fields"]["transaction_type"], "income")
        self.assertEqual(r["fields"]["amount"], 5000.0)
        self.assertEqual(r["fields"]["description"], "Servind")
        self.assertTrue(r["display"]["subtitle"].startswith("Příjem"))

    def test_unknown_category_is_explicit(self):
        r = p("dárek 300 Kč")
        self.assertEqual(r["fields"]["category"], "Ostatní")
        self.assertTrue(any("Ostatní" in w for w in r["warnings"]))

    def test_bare_number_asks(self):
        r = p("Albert 820")
        self.assertEqual(r["kind"], "finance")
        self.assertEqual(r["confidence"], "medium")
        self.assertEqual(r["needs_input"][0]["field"], "amount")
        self.assertEqual(r["needs_input"][0]["question"], "Je to 820 Kč?")
        self.assertFalse(r["ready"])

    def test_negative_amount(self):
        r = p("-500 Kč")
        self.assertIn("amount", fields_of(r["errors"]))
        self.assertFalse(r["ready"])

    def test_thousands(self):
        self.assertEqual(p("nájem 12 500 Kč")["fields"]["amount"], 12500.0)
        self.assertEqual(p("nájem 12 500 Kč")["fields"]["category"], "Bydlení")


class WorkParseTestCase(unittest.TestCase):
    def test_hours_with_keyword(self):
        r = p("2 h práce Servind")
        self.assertEqual(r["kind"], "work")
        self.assertEqual(r["confidence"], "high")
        self.assertEqual(r["fields"]["hours"], 2.0)
        self.assertEqual(r["fields"]["project"], "Servind")
        self.assertEqual(r["fields"]["hourly_rate"], 0)
        self.assertEqual(r["fields"]["date"], "2026-10-03")
        self.assertTrue(any("sazby" in w for w in r["warnings"]), "sazba se nevymýšlí")

    def test_rate_and_earnings(self):
        r = p("6,5 h Workshop za 375 Kč/h")
        self.assertEqual(r["fields"]["hours"], 6.5)
        self.assertEqual(r["fields"]["hourly_rate"], 375.0)
        self.assertEqual(r["fields"]["project"], "Workshop")
        self.assertIn("2\xa0437,50\xa0Kč", r["display"]["subtitle"])
        self.assertTrue(r["ready"])

    def test_today_hours_word(self):
        r = p("dnes 3 hodiny RaceX")
        self.assertEqual(r["kind"], "work")
        self.assertEqual(r["fields"]["hours"], 3.0)
        self.assertEqual(r["fields"]["project"], "RaceX")

    def test_ambiguous_without_keyword(self):
        r = p("2 h Servind")
        self.assertEqual(r["kind"], "work")
        self.assertEqual(r["confidence"], "medium")
        self.assertTrue(any("zkontroluj" in w for w in r["warnings"]))

    def test_too_many_hours(self):
        r = p("40 h práce")
        self.assertIn("hours", fields_of(r["errors"]))
        self.assertFalse(r["ready"])

    def test_money_without_rate_is_not_rate(self):
        r = p("3 h práce Servind 900 Kč")
        self.assertEqual(r["fields"]["hourly_rate"], 0)
        self.assertTrue(any("/h" in w for w in r["warnings"]))


class SchoolParseTestCase(unittest.TestCase):
    def test_exam_with_declined_subject(self):
        r = p("test z práva 18. 10.")
        self.assertEqual(r["kind"], "exam")
        self.assertEqual(r["fields"]["subject_id"], 1)
        self.assertEqual(r["fields"]["exam_date"], "2026-10-18")
        self.assertEqual(r["fields"]["exam_type"], "test")
        self.assertEqual(r["fields"]["title"], "Test z práva")
        self.assertIn("Právo", r["display"]["subtitle"])
        self.assertTrue(r["ready"])
        self.assertEqual(len(r["subjects"]), len(SUBJECTS))

    def test_exam_multiword_subject(self):
        r = p("zkouška English in IT 5. 11.")
        self.assertEqual(r["fields"]["subject_id"], 2)
        self.assertEqual(r["fields"]["exam_date"], "2026-11-05")
        self.assertEqual(r["fields"]["exam_type"], "exam")

    def test_assignment_until_friday(self):
        r = p("úkol algoritmizace do pátku")
        self.assertEqual(r["kind"], "assignment")
        self.assertEqual(r["fields"]["subject_id"], 3)
        self.assertEqual(r["fields"]["due_date"], "2026-10-09")
        self.assertEqual(r["fields"]["priority"], "medium")

    def test_exam_without_date_asks(self):
        r = p("test z práva")
        self.assertEqual([n["question"] for n in r["needs_input"]], ["Kdy je termín?"])
        self.assertFalse(r["ready"])

    def test_no_or_multiple_subjects_never_guess(self):
        r = p("zkouška z chemie 20. 10.")
        self.assertIsNone(r["fields"]["subject_id"])
        self.assertIn("subject_id", fields_of(r["needs_input"]))
        r = p("test fyz 20. 10.")  # kód FYZ odpovídá Fyzika i Fyzika II? ne – kódy jsou FYZ1/FYZ2
        self.assertIsNone(r["fields"]["subject_id"])
        r = p("test fyzik 20. 10.", subjects=[{"id": 4, "name": "Fyzika"}, {"id": 6, "name": "Fyzika pro informatiky"}])
        self.assertIsNone(r["fields"]["subject_id"])
        self.assertTrue(any("více" in w for w in r["warnings"]))

    def test_exact_name_with_longer_sibling_is_flagged(self):
        r = p("test fyzika 20. 10.")  # existuje i Fyzika II → vybráno, ale viditelně
        self.assertEqual(r["fields"]["subject_id"], 4)
        self.assertTrue(any("Fyzika II" in w for w in r["warnings"]))

    def test_code_and_priority(self):
        r = p("důležitý úkol FYZ2 15. 10.")
        self.assertEqual(r["fields"]["subject_id"], 5)
        self.assertEqual(r["fields"]["priority"], "high")

    def test_past_date_rolls_to_next_year(self):
        self.assertEqual(p("test z práva 1. 9.")["fields"]["exam_date"], "2027-09-01")

    def test_impossible_date(self):
        r = p("test z práva 31. 2.")
        self.assertIn("date", fields_of(r["errors"]))
        self.assertFalse(r["ready"])


class UnknownAndLimitsTestCase(unittest.TestCase):
    def test_nonsense(self):
        r = p("asdf qwer")
        self.assertEqual(r["kind"], "unknown")
        self.assertFalse(r["ready"])

    def test_empty(self):
        self.assertEqual(p("")["kind"], "empty")
        self.assertEqual(p("  ")["kind"], "empty")

    def test_long_text_is_clipped(self):
        r = p("oběd 100 Kč " + "x" * 2000)
        self.assertLessEqual(len(r["fields"].get("description", "")), qa.MAX_TEXT)

    def test_no_confidence_scores(self):
        for text in ("Albert 820 Kč", "Albert 820", "2 h Servind", "asdf"):
            self.assertIn(p(text)["confidence"], ("high", "medium", "low"))

    def test_performance(self):
        texts = ["zítra fyzio v 17:00", "Albert 820 Kč", "6,5 h Workshop za 375 Kč/h", "test z práva 18. 10.",
                 "úkol algoritmizace do pátku", "asdf qwer", "x" * 300]
        start = time.perf_counter()
        for _ in range(20):
            for t in texts:
                p(t)
        per_call_ms = (time.perf_counter() - start) * 1000 / (20 * len(texts))
        self.assertLess(per_call_ms, 50)


class ToolCallValidationTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(Subject(id=1, name="Právo"))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def call(self, kind, fields):
        return qa.to_tool_call(self.db, kind, fields, now_utc=NOW)

    def invalid(self, kind, fields):
        with self.assertRaises(qa.QuickAddInvalid) as ctx:
            self.call(kind, fields)
        return fields_of(ctx.exception.errors)

    def test_finance(self):
        tool, args = self.call("finance", {"amount": "189,90", "transaction_type": "expense", "category": "Jídlo",
                                           "description": "oběd"})
        self.assertEqual(tool, "add_finance_transaction")
        self.assertEqual(args["amount"], 189.9)
        self.assertIn("amount", self.invalid("finance", {"amount": -5, "transaction_type": "expense"}))
        self.assertIn("amount", self.invalid("finance", {"amount": "abc", "transaction_type": "expense"}))
        self.assertIn("amount", self.invalid("finance", {"amount": None, "transaction_type": "expense"}))
        self.assertIn("amount", self.invalid("finance", {"amount": 1e12, "transaction_type": "expense"}))
        self.assertIn("transaction_type", self.invalid("finance", {"amount": 5, "transaction_type": "gift"}))

    def test_work(self):
        tool, args = self.call("work", {"date": "2026-10-03", "hours": 6.5, "project": "Workshop", "hourly_rate": 375})
        self.assertEqual(tool, "add_work_session")
        self.assertEqual(args, {"date_value": "2026-10-03", "hours": 6.5, "project": "Workshop", "hourly_rate": 375.0,
                                "description": "", "sync_to_finance": True})
        self.assertIn("hours", self.invalid("work", {"date": "2026-10-03", "hours": 40}))
        self.assertIn("hours", self.invalid("work", {"date": "2026-10-03", "hours": 0}))
        self.assertIn("hourly_rate", self.invalid("work", {"date": "2026-10-03", "hours": 2, "hourly_rate": -1}))
        self.assertIn("date", self.invalid("work", {"date": "2026-02-31", "hours": 2}))
        self.assertIn("date", self.invalid("work", {"date": "2030-01-01", "hours": 2}))

    def test_reminder(self):
        tool, args = self.call("reminder", {"title": "Fyzio", "due_local": "2026-10-04T17:00"})
        self.assertEqual((tool, args), ("add_reminder", {"title": "Fyzio", "due_local": "2026-10-04T17:00"}))
        self.assertIn("due_local", self.invalid("reminder", {"title": "x", "due_local": "2026-10-03T11:00"}))
        self.assertIn("due_local", self.invalid("reminder", {"title": "x", "due_local": "2028-01-01T10:00"}))
        self.assertIn("due_local", self.invalid("reminder", {"title": "x", "due_local": "zítra"}))
        self.assertIn("title", self.invalid("reminder", {"title": " ", "due_local": "2026-10-04T17:00"}))

    def test_school(self):
        tool, args = self.call("exam", {"title": "Test z práva", "subject_id": 1, "exam_date": "2026-10-18",
                                        "exam_type": "test"})
        self.assertEqual(tool, "add_school_exam")
        self.assertEqual(args["subject_id"], 1)
        tool, args = self.call("assignment", {"title": "Esej", "subject_id": "1", "due_date": "2026-10-09",
                                              "priority": "evil"})
        self.assertEqual(tool, "add_school_assignment")
        self.assertEqual(args["priority"], "medium")
        self.assertIn("subject_id", self.invalid("exam", {"title": "x", "subject_id": 99, "exam_date": "2026-10-18"}))
        self.assertIn("subject_id", self.invalid("exam", {"title": "x", "subject_id": None, "exam_date": "2026-10-18"}))
        self.assertIn("exam_date", self.invalid("exam", {"title": "x", "subject_id": 1, "exam_date": "2026-02-31"}))
        self.assertIn("due_date", self.invalid("assignment", {"title": "x", "subject_id": 1, "due_date": ""}))

    def test_unsupported_kind(self):
        self.assertIn("kind", self.invalid("goal", {"title": "x"}))
        self.assertIn("kind", self.invalid("unknown", {}))


class QuickAddApiTestCase(unittest.TestCase):
    PIN = "4821"

    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        db = self.Session()
        db.add(Subject(id=1, name="Právo"))
        db.commit()
        db.close()
        self._patches = [
            patch.object(auth_service, "SessionLocal", self.Session),
            patch.object(main, "SessionLocal", self.Session),
            patch.object(ai, "SessionLocal", self.Session),
            patch.object(tools, "SessionLocal", self.Session),
            patch.object(reminder_actions, "SessionLocal", self.Session),
            patch.object(auth_service, "_failed_attempts", {}),
            patch.object(auth_service, "AUTH_PIN_HASH",
                         bcrypt.hashpw(self.PIN.encode(), bcrypt.gensalt(rounds=4)).decode("utf-8")),
            patch.object(ai, "_llm_create_with_retry", side_effect=AssertionError("Rychlé přidání nesmí volat LLM")),
        ]
        for pt in self._patches:
            pt.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        for pt in self._patches:
            pt.stop()
        self.engine.dispose()

    def login(self):
        self.assertEqual(self.client.post("/auth/login", json={"pin": self.PIN}).status_code, 200)

    def count(self, model):
        db = self.Session()
        try:
            return db.query(model).count()
        finally:
            db.close()

    def prepare_and_confirm(self, kind, fields):
        r = self.client.post("/quick-add/prepare", json={"kind": kind, "fields": fields})
        self.assertEqual(r.status_code, 200, r.text)
        pending = r.json()["pending_action"]
        self.assertEqual(pending["arguments"].get("_source"), "quick_add")
        r = self.client.post("/actions/confirm", json={"action_id": pending["id"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get("ok"), r.text)
        return pending, r.json()

    def test_requires_session(self):
        self.assertEqual(self.client.post("/quick-add/parse", json={"text": "Albert 820 Kč"}).status_code, 401)
        r = self.client.post("/quick-add/prepare", json={"kind": "finance",
                                                         "fields": {"amount": 820, "transaction_type": "expense"}})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.count(PendingAction), 0)
        self.assertEqual(self.count(FinanceTransaction), 0)

    def test_parse_is_read_only_and_uses_subjects(self):
        self.login()
        r = self.client.post("/quick-add/parse", json={"text": "test z práva 18. 10."})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["kind"], "exam")
        self.assertEqual(body["fields"]["subject_id"], 1)
        self.assertEqual(body["subjects"], [{"id": 1, "name": "Právo"}])
        self.assertEqual(self.count(PendingAction), 0)
        self.assertEqual(self.count(Exam), 0)
        self.assertEqual(self.count(ActivityLog), 0)

    def test_prepare_does_not_write_until_confirmed(self):
        self.login()
        r = self.client.post("/quick-add/prepare", json={"kind": "finance", "fields": {
            "amount": 820, "transaction_type": "expense", "category": "Potraviny", "description": "Albert"}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.count(PendingAction), 1)
        self.assertEqual(self.count(FinanceTransaction), 0)
        self.assertEqual(self.client.post(f"/ai/reject/{r.json()['pending_action']['id']}").status_code, 200)
        self.assertEqual(self.count(FinanceTransaction), 0)

    def test_prepare_rejects_invalid(self):
        self.login()
        r = self.client.post("/quick-add/prepare", json={"kind": "work", "fields": {"date": "2026-10-03", "hours": 40}})
        self.assertEqual(r.status_code, 422)
        self.assertIn("hours", {e["field"] for e in r.json()["detail"]["errors"]})
        r = self.client.post("/quick-add/prepare", json={"kind": "exam", "fields": {
            "title": "x", "subject_id": 77, "exam_date": "2026-10-18"}})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.count(PendingAction), 0)

    def test_finance_end_to_end_source_label(self):
        self.login()
        self.prepare_and_confirm("finance", {"amount": "189,90", "transaction_type": "expense", "category": "Jídlo",
                                             "description": "oběd"})
        db = self.Session()
        try:
            tx = db.query(FinanceTransaction).one()
            self.assertEqual((tx.amount, tx.category, tx.description), (189.9, "Jídlo", "oběd"))
            logs = db.query(ActivityLog).all()
            self.assertEqual([(lg.area, lg.user_context) for lg in logs], [("finance", "quick_add")])
            self.assertFalse(any(lg.area == "ai" for lg in logs), "Rychlé přidání není akce AI")
            self.assertEqual(db.query(PendingAction).one().status, "executed")
        finally:
            db.close()

    def test_work_end_to_end_syncs_finance(self):
        self.login()
        self.prepare_and_confirm("work", {"date": "2026-10-03", "hours": 6.5, "project": "Workshop",
                                          "hourly_rate": 375, "sync_to_finance": True})
        db = self.Session()
        try:
            ws = db.query(WorkSession).one()
            self.assertEqual((ws.hours, ws.project), (6.5, "Workshop"))
            self.assertEqual(db.query(FinanceTransaction).one().amount, 2437.5)
        finally:
            db.close()

    def test_reminder_end_to_end(self):
        self.login()
        due = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT10:00")
        pending, _ = self.prepare_and_confirm("reminder", {"title": "Fyzio", "due_local": due})
        self.assertIn("preview", pending, "resolver připomínky vrací ověřený náhled")
        db = self.Session()
        try:
            self.assertEqual(db.query(Reminder).one().title, "Fyzio")
            self.assertEqual([lg.user_context for lg in db.query(ActivityLog).all()], ["quick_add"])
        finally:
            db.close()

    def test_school_end_to_end_and_no_undo(self):
        self.login()
        _, result = self.prepare_and_confirm("exam", {"title": "Test z práva", "subject_id": 1,
                                                      "exam_date": "2026-10-18", "exam_type": "test"})
        self.assertNotIn("undo_available", result["result"], "vytvoření nemá undo")
        self.prepare_and_confirm("assignment", {"title": "Esej", "subject_id": 1, "due_date": "2026-10-09"})
        db = self.Session()
        try:
            self.assertEqual(db.query(Exam).one().exam_type, "test")
            self.assertEqual(db.query(Assignment).one().title, "Esej")
            summaries = [lg.summary for lg in db.query(ActivityLog).order_by(ActivityLog.id).all()]
            self.assertIn("18. 10. 2026", summaries[0], "datum česky, ne ISO")
        finally:
            db.close()

    def test_double_confirm_is_rejected(self):
        self.login()
        pending, _ = self.prepare_and_confirm("finance", {"amount": 50, "transaction_type": "expense"})
        r = self.client.post("/actions/confirm", json={"action_id": pending["id"]})
        self.assertEqual(r.json()["error"], "action_already_processed")
        self.assertEqual(self.count(FinanceTransaction), 1)


if __name__ == "__main__":
    unittest.main()
