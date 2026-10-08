"""MRK-28: „Co se změnilo" – kontrakt ChangeItem, události před Aktivitou (bez duplicit), záloha po retenci,
šum, vypnuté moduly, odvozené filtry, since/limit/module a endpoint. SQLite v paměti, žádná síť ani LLM."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
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
import change_feed as cf  # noqa: E402
import domain_events as de  # noqa: E402
import main  # noqa: E402
import module_registry as mr  # noqa: E402
import school_service  # noqa: E402
import tools  # noqa: E402
from activity_service import log_activity  # noqa: E402
from database import Base  # noqa: E402
from models import Assignment, DomainEvent, Exam, Subject  # noqa: E402
from module_contracts import ChangeSource, ModuleIntegrations  # noqa: E402
from modules.habits import service as habits  # noqa: E402

MODULE_ENV = [m.env_name for m in mr.MODULES]
CONTRACT_KEYS = {"id", "occurred_at", "module_id", "entity_type", "entity_id", "kind", "title", "summary", "href",
                 "source"}


def _clean_env():
    return {k: v for k, v in os.environ.items() if k not in MODULE_ENV}


class _FeedCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self._patches = [patch.object(mr, "SessionLocal", self.Session), patch.dict(os.environ, _clean_env(), clear=True)]
        for p in self._patches:
            p.start()
        mr.invalidate_cache()
        with self.Session() as db:
            db.add(Subject(id=1, name="Matematika"))
            db.add(Assignment(id=1, subject_id=1, title="Sada 3", status="todo"))
            db.add(Exam(id=1, subject_id=1, title="Písemka", status="upcoming"))
            db.commit()
        self.now = de.now_utc()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        mr.invalidate_cache()
        self.engine.dispose()

    def feed(self, *, days=7, modules=None, limit=50):
        with self.Session() as db:
            return cf.build(db, mr.current_access(), since=self.now - timedelta(days=days), modules=modules, limit=limit)

    def disable(self, module_id):
        os.environ[f"MODULE_{module_id.upper()}_ENABLED"] = "false"
        mr.invalidate_cache()

    def activity(self, area, action, summary, *, entity_type=None, entity_id=None, ago=timedelta(minutes=5),
                 user_context="manual"):
        with self.Session() as db:
            row = log_activity(db, area, action, summary, entity_type=entity_type, entity_id=entity_id,
                               user_context=user_context)
            row.timestamp = (self.now - ago).replace(tzinfo=None)
            db.commit()
            return row.id


class ContractAndDedupeTestCase(_FeedCase):
    def test_event_is_preferred_and_its_activity_projection_is_not_duplicated(self):
        with self.Session() as db:
            school_service.complete_assignment(db, 1)
            db.commit()
        out = self.feed()
        self.assertEqual(len(out["items"]), 1, "událost + projekce = jedna změna")
        item = out["items"][0]
        self.assertEqual(set(item), CONTRACT_KEYS)
        self.assertEqual(item["source"], "event")
        self.assertTrue(item["id"].startswith("event:"))
        self.assertEqual((item["module_id"], item["entity_type"], item["entity_id"], item["kind"]),
                         ("school", "assignment", "1", "completed"))
        self.assertEqual(item["title"], "Úkol splněn: Sada 3", "titulek z projekce (payload jména nenese)")
        self.assertEqual(item["href"], "/school?assignment=1")
        self.assertTrue(item["occurred_at"].endswith("Z"))

    def test_after_retention_the_activity_row_is_the_fallback(self):
        with self.Session() as db:
            school_service.complete_assignment(db, 1)
            db.commit()
            db.query(DomainEvent).delete()
            db.commit()
        (item,) = self.feed()["items"]
        self.assertEqual((item["source"], item["kind"], item["title"]), ("activity", "completed", "Úkol splněn: Sada 3"))
        self.assertEqual(item["href"], "/school?assignment=1")

    def test_legacy_flows_come_from_activity_with_module_owned_links(self):
        self.activity("finance", "create", "Výdaj 120 Kč", entity_type="FinanceTransaction", entity_id=7)
        self.activity("work", "delete", "Směna smazána", entity_type="WorkSession", entity_id=3, ago=timedelta(minutes=6))
        self.activity("reminders", "create", "Připomínka: zubař", entity_type="Reminder", entity_id=2,
                      ago=timedelta(minutes=7))
        items = self.feed()["items"]
        self.assertEqual([(i["module_id"], i["kind"], i["href"]) for i in items], [
            ("finance", "created", "/finance?transaction=7"),
            ("work", "deleted", None),  # smazaný záznam už otevřít nejde
            (None, "created", "/reminders?reminder=2"),
        ])
        self.assertTrue(all(i["source"] == "activity" for i in items))

    def test_habit_events_and_edits(self):
        with self.Session() as db:
            hid = habits.create_habit(db, "Voda").id
            db.commit()
        with self.Session() as db:
            habits.set_entry(db, hid, "done")
            db.commit()
        items = self.feed()["items"]
        kinds = [(i["source"], i["kind"], i["href"]) for i in items]
        self.assertIn(("event", "done", "/habits"), kinds)
        self.assertIn(("activity", "created", f"/habits?habit={hid}"), kinds)
        self.assertEqual(len(items), 2, "zápis dne = jedna změna (událost), vytvoření návyku = jedna")


class PolicyTestCase(_FeedCase):
    def test_noise_is_filtered_like_the_briefing(self):
        with self.Session() as db:
            de.append_domain_event(db, event_type="system.module.disabled", aggregate_type="module", aggregate_id="mff",
                                   activity=de.ActivityProjection("system", "module.disabled", "Modul MFF vypnut",
                                                                  entity_type="Module"))
            db.commit()
        self.activity("ai", "approve", "Schváleno: create_reminder")
        self.activity("goals", "snapshot", "Snapshot cíle", entity_type="Goal", entity_id=1)
        self.activity("finance", "create", "[test] výdaj", entity_type="FinanceTransaction", entity_id=9)
        self.activity("finance", "create", "Výdaj z testu", entity_type="FinanceTransaction", entity_id=10,
                      user_context="unit_test")
        self.activity("work", "create", "Směna", entity_type="WorkSession", entity_id=4, ago=timedelta(minutes=9))
        self.activity("work", "delete", "Směna smazána", entity_type="WorkSession", entity_id=4)
        self.assertEqual(self.feed()["items"], [], "provoz, test a vytvořeno+smazáno v okně = žádná změna")

    def test_disabled_module_contributes_nothing(self):
        with self.Session() as db:
            school_service.complete_assignment(db, 1)
            db.commit()
        self.activity("school", "create", "Nový úkol", entity_type="Assignment", entity_id=1)
        self.activity("wot", "create", "Grind T-34", entity_type="WotGrind", entity_id=1)
        self.disable("school")
        out = self.feed()
        self.assertEqual([i["module_id"] for i in out["items"]], ["wot"])
        self.assertEqual([f["id"] for f in out["filters"]], ["wot"])

    def test_filters_are_derived_and_module_filter_limit_and_truncation_apply(self):
        for n in range(3):
            self.activity("finance", "create", f"Výdaj {n}", entity_type="FinanceTransaction", entity_id=n + 1,
                          ago=timedelta(minutes=10 + n))
        self.activity("reminders", "complete", "Splněno: pošta", entity_type="Reminder", entity_id=5)
        out = self.feed()
        self.assertEqual(out["filters"], [{"id": "core", "label": "Obecné", "count": 1},
                                          {"id": "finance", "label": "Finance", "count": 3}])
        only = self.feed(modules=frozenset({"finance"}), limit=2)
        self.assertEqual([i["title"] for i in only["items"]], ["Výdaj 0", "Výdaj 1"], "nejnovější první")
        self.assertEqual((only["total"], only["truncated"]), (3, True))
        self.assertEqual(only["filters"], out["filters"], "filtry nezávisí na zvoleném filtru")
        self.assertEqual([i["module_id"] for i in self.feed(modules=frozenset({"core"}))["items"]], [None])

    def test_since_window(self):
        self.activity("finance", "create", "Starý výdaj", entity_type="FinanceTransaction", entity_id=1,
                      ago=timedelta(days=3))
        self.assertEqual(self.feed(days=1)["items"], [])
        self.assertEqual(len(self.feed(days=7)["items"]), 1)

    def test_failing_provider_is_isolated(self):
        self.activity("finance", "create", "Výdaj", entity_type="FinanceTransaction", entity_id=1)
        self.activity("work", "create", "Směna", entity_type="WorkSession", entity_id=1)
        broken = ChangeSource("work", areas=frozenset({"work"}), from_activity=lambda row: 1 / 0)
        work = next(m for m in mr.MODULES if m.id == "work")
        patched = tuple(m if m.id != "work" else
                        type(m)(**{**m.__dict__, "integrations": ModuleIntegrations(changes=(broken,))})
                        for m in mr.MODULES)
        with patch.object(mr, "MODULES", patched), self.assertLogs("change_feed", "WARNING") as logs, \
                self.Session() as db:
            access = mr.ModuleAccess(None, patched)
            items, _ = cf.collect(db, access, since=self.now - timedelta(days=1))
        self.assertEqual([i.module_id for i in items], ["finance"])
        self.assertIn("ZeroDivisionError", "\n".join(logs.output))
        self.assertTrue(work.integrations.changes, "registr zůstal beze změny")


class ParsingTestCase(unittest.TestCase):
    NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)

    def test_since(self):
        self.assertEqual(cf.parse_since(None, self.NOW), self.NOW - timedelta(days=7))
        self.assertEqual(cf.parse_since("2026-10-08T10:00:00Z", self.NOW), datetime(2026, 10, 8, 10, tzinfo=timezone.utc))
        self.assertEqual(cf.parse_since("2026-10-08T12:00:00+02:00", self.NOW), datetime(2026, 10, 8, 10, tzinfo=timezone.utc))
        self.assertEqual(cf.parse_since("2020-01-01T00:00:00Z", self.NOW), self.NOW - timedelta(days=90), "nejvýš 90 dní")
        for bad in ("včera", "2026-13-01", "2026-10-09T00:00:00Z"):
            with self.subTest(bad=bad), self.assertRaises(cf.ChangeFeedError):
                cf.parse_since(bad, self.NOW)

    def test_modules_and_limit(self):
        self.assertIsNone(cf.parse_modules(None))
        self.assertEqual(cf.parse_modules("school, core"), frozenset({"school", "core"}))
        for bad in ("School", "a;b", ","):
            with self.subTest(bad=bad), self.assertRaises(cf.ChangeFeedError):
                cf.parse_modules(bad)
        self.assertEqual([cf.clamp_limit(v) for v in (None, 0, 5, 500)], [50, 50, 5, 200])

    def test_central_service_has_no_per_module_branches(self):
        src = open(os.path.join(BACKEND_DIR, "change_feed.py"), encoding="utf-8").read()
        for m in mr.MODULES:
            self.assertNotIn(f'"{m.id}"', src, f"change_feed nesmí znát modul {m.id}")


class EndpointTestCase(_FeedCase):
    PIN = "4821"

    def setUp(self):
        super().setUp()
        self._orig = (auth_service.SessionLocal, main.SessionLocal, tools.SessionLocal, auth_service.AUTH_PIN_HASH,
                      auth_service._failed_attempts)
        auth_service.SessionLocal = main.SessionLocal = tools.SessionLocal = self.Session
        auth_service._failed_attempts = {}
        auth_service.AUTH_PIN_HASH = bcrypt.hashpw(self.PIN.encode(), bcrypt.gensalt(rounds=4)).decode()
        self.client = TestClient(main.app)

    def tearDown(self):
        (auth_service.SessionLocal, main.SessionLocal, tools.SessionLocal, auth_service.AUTH_PIN_HASH,
         auth_service._failed_attempts) = self._orig
        super().tearDown()

    def test_requires_auth(self):
        self.assertEqual(self.client.get("/changes").status_code, 401)

    def test_authenticated_feed_without_llm(self):
        self.assertEqual(self.client.post("/auth/login", json={"pin": self.PIN}).status_code, 200)
        self.client.put("/modules/mff", json={"enabled": False})  # system.* = šum
        with self.Session() as db:
            school_service.complete_assignment(db, 1)
            db.commit()

        class NoLlm:
            def __getattr__(self, name):
                raise AssertionError("GET /changes nesmí volat LLM (Groq)")
        with patch.object(ai, "client", NoLlm()):
            res = self.client.get("/changes", params={"limit": 10})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(set(body), {"since", "items", "total", "truncated", "filters"})
        self.assertEqual([(i["module_id"], i["kind"]) for i in body["items"]], [("school", "completed")])
        self.assertEqual(self.client.get("/changes", params={"since": "zítra"}).status_code, 422)
        self.assertEqual(self.client.get("/changes", params={"module": "a;b"}).status_code, 422)
        self.assertEqual(self.client.get("/changes", params={"module": "school"}).json()["total"], 1)
        self.assertEqual(self.client.get("/changes", params={"limit": "x"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
