"""Roadmap 6C: feature flagy modulů – registr, parsování prostředí a brány (search, Dnes, Quick Add, AI, API).

Budoucí moduly (Food, Fitness…) zatím nemají kód, proto brány dokazují testovací moduly (FIXTURES) a vypnutí
existujících modulů přes `ModuleAccess(flags)`. Žádný reálný Groq.
"""
import os
import re
import sys
import unittest
from datetime import date, datetime
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
import main  # noqa: E402
import module_registry as mr  # noqa: E402
import quick_add_service as qa  # noqa: E402
import search_service as ss  # noqa: E402
import tool_router  # noqa: E402
import tools  # noqa: E402
from context_service import build_current_context  # noqa: E402
from database import Base  # noqa: E402
from models import (  # noqa: E402
    Assignment, Exam, FinanceTransaction, Goal, MffCharacter, Subject, WorkSession, WotGrind, WotMilestone, WotReplay,
)
from module_registry import ModuleAccess, ModuleDef  # noqa: E402
from today_service import TodayItem, gate_items  # noqa: E402

ALL = mr.ALL_CAPABILITIES
FIXTURES = (
    ModuleDef("alpha", "Alfa", default_enabled=True, implemented=True, capabilities=ALL,
              entity_types=frozenset({"alpha_item"}), context_areas=frozenset({"alpha"}),
              api_prefixes=("/alpha",), quick_add_kinds=("alpha_meal",)),
    ModuleDef("beta", "Beta", default_enabled=False, implemented=True, capabilities=ALL,
              entity_types=frozenset({"beta_item"}), context_areas=frozenset({"beta"}),
              api_prefixes=("/beta",), quick_add_kinds=("beta_meal",)),
    ModuleDef("gamma", "Gama", default_enabled=False, implemented=False),
)
MODULE_ENV = [m.env_name for m in mr.MODULES]


def _clean_env():
    """Prostředí bez MODULE_* (lokální .env vývojáře nesmí ovlivnit testy)."""
    return {k: v for k, v in os.environ.items() if k not in MODULE_ENV}


class FlagParsingTestCase(unittest.TestCase):
    def test_defaults(self):
        flags = mr.resolve_flags(env={})
        for mid in ("school", "work", "finance", "goals", "wot", "mff", "habits"):
            self.assertIs(flags[mid], True, mid)
        for mid in ("food", "fitness", "projects", "knowledge", "car", "travel", "entertainment"):
            self.assertIs(flags[mid], False, mid)

    def test_explicit_on_off(self):
        for raw, expected in [("1", True), ("true", True), (" ON ", True), ("yes", True),
                              ("0", False), ("false", False), ("Off", False), ("no", False)]:
            with self.subTest(raw=raw):
                self.assertIs(mr.resolve_flags(env={"MODULE_WOT_ENABLED": raw})["wot"], expected)
                self.assertIs(mr.resolve_flags(env={"MODULE_FOOD_ENABLED": raw})["food"], expected)

    def test_invalid_or_blank_value_keeps_safe_default(self):
        # překlep nesmí schovat hotový modul ani zapnout budoucí
        for raw in ("ture", "maybe", "2", "   "):
            with self.subTest(raw=raw):
                flags = mr.resolve_flags(env={"MODULE_SCHOOL_ENABLED": raw, "MODULE_FOOD_ENABLED": raw})
                self.assertIs(flags["school"], True)
                self.assertIs(flags["food"], False)

    def test_reads_process_environment(self):
        with patch.dict(os.environ, {**_clean_env(), "MODULE_MFF_ENABLED": "false"}, clear=True):
            access = mr.current_access()
            self.assertFalse(access.is_available("mff"))
            self.assertTrue(access.is_available("wot"))
        with patch.dict(os.environ, _clean_env(), clear=True):
            self.assertTrue(mr.current_access().is_available("mff"))


class RegistryTestCase(unittest.TestCase):
    def test_ids_and_ownership_are_unique(self):
        ids = [m.id for m in mr.MODULES]
        self.assertEqual(len(ids), len(set(ids)))
        for attr in ("entity_types", "context_areas", "quick_add_kinds"):
            owned = [x for m in mr.MODULES for x in getattr(m, attr)]
            self.assertEqual(len(owned), len(set(owned)), attr)
        for m in mr.MODULES:
            self.assertLessEqual(m.capabilities, ALL, m.id)
            self.assertRegex(m.id, r"^[a-z][a-z_]*$")

    def test_existing_modules_unchanged_by_default(self):
        access = ModuleAccess(mr.resolve_flags(env={}))
        for mid in ("school", "work", "finance", "goals", "wot", "mff"):
            self.assertTrue(access.is_available(mid), mid)
            for cap in ("nav", "search", "dashboard", "ai_context"):
                self.assertTrue(access.allows(mid, cap), (mid, cap))
        for kind in qa.KINDS:
            self.assertTrue(access.allows_quick_add_kind(kind), kind)

    def test_planned_modules_stay_unavailable_even_when_flag_is_on(self):
        on = {m.env_name: "true" for m in mr.MODULES}
        access = ModuleAccess(mr.resolve_flags(env=on))
        for mid in ("food", "fitness", "projects", "knowledge", "car", "travel", "entertainment"):
            self.assertFalse(access.is_available(mid), mid)
            self.assertFalse(any(access.allows(mid, c) for c in mr.CAPABILITIES), mid)

    def test_fixture_capabilities(self):
        access = ModuleAccess({"alpha": True, "beta": False, "gamma": True}, FIXTURES)
        self.assertTrue(access.is_available("alpha"))
        self.assertFalse(access.is_available("beta"))
        self.assertFalse(access.is_available("gamma"), "flag bez implementace nic neodkryje")
        for cap in mr.CAPABILITIES:
            self.assertTrue(access.allows("alpha", cap))
            self.assertFalse(access.allows("beta", cap))
        self.assertFalse(access.allows("unknown", "nav"))
        with self.assertRaises(ValueError):
            access.allows("alpha", "teleport")
        # zapnutí přes flag funguje stejně jako výchozí stav
        self.assertTrue(ModuleAccess({"beta": True}, FIXTURES).allows("beta", "today"))

    def test_capability_not_declared_is_denied(self):
        access = ModuleAccess(mr.resolve_flags(env={}))
        self.assertFalse(access.allows("wot", "quick_add"))
        self.assertFalse(access.allows("goals", "quick_add"))

    def test_refs_paths_and_core(self):
        access = ModuleAccess({"alpha": True, "beta": False}, FIXTURES)
        self.assertTrue(access.allows_ref("alpha_item:1", "today"))
        self.assertFalse(access.allows_ref("beta_item:1", "today"))
        self.assertTrue(access.allows_ref("planner:2", "today"), "neznámý typ = jádro")
        self.assertTrue(access.allows_ref(None, "today"))
        self.assertFalse(access.allows_path("/beta"))
        self.assertFalse(access.allows_path("/beta/items/3"))
        self.assertTrue(access.allows_path("/betamax"), "jen celý segment")
        self.assertTrue(access.allows_path("/alpha/items"))
        self.assertTrue(access.allows_path("/reminders"))

    def test_goal_and_goals_paths(self):
        access = ModuleAccess({"goals": False})
        for path in ("/goal", "/goal/3", "/goals/list", "/goals/summary"):
            self.assertFalse(access.allows_path(path), path)
        self.assertTrue(access.allows_path("/reminders"))

    def test_public_config_has_only_safe_values(self):
        with patch.dict(os.environ, {**_clean_env(), "MODULE_WOT_ENABLED": "false"}, clear=True):
            config = mr.current_access().public_config()
        self.assertEqual([c["id"] for c in config], [m.id for m in mr.MODULES])
        for entry in config:
            # A2: + enabled/source/locked/implemented/default_enabled/depends_on – stále žádné hodnoty prostředí
            self.assertEqual(set(entry), {"id", "label", "available", "capabilities", "enabled", "source", "locked",
                                          "implemented", "default_enabled", "depends_on"})
            for key in ("available", "enabled", "locked", "implemented", "default_enabled"):
                self.assertIsInstance(entry[key], bool)
            self.assertIn(entry["source"], {"env", "db", "default"})
            self.assertNotIn("false", str(entry["label"]).lower())
        wot = next(c for c in config if c["id"] == "wot")
        self.assertEqual((wot["available"], wot["capabilities"]), (False, []))
        self.assertEqual((wot["enabled"], wot["source"], wot["locked"]), (False, "env", True))


class TodayGateTestCase(unittest.TestCase):
    def test_disabled_module_items_are_dropped(self):
        items = [
            TodayItem(id="alpha_item:1", type="alpha_item", title="A"),
            TodayItem(id="beta_item:1", type="beta_item", title="B"),
            TodayItem(id="planner:1", type="planner", title="Plán"),
            TodayItem(id="notification:9", type="notification", title="Upozornění"),
        ]
        kept = gate_items(items, ModuleAccess({"alpha": True, "beta": False}, FIXTURES))
        self.assertEqual([it.id for it in kept], ["alpha_item:1", "planner:1", "notification:9"])

    def test_school_off_removes_school_refs(self):
        items = [TodayItem(id="exam:1", type="exam", title="Test"), TodayItem(id="reminder:1", type="reminder", title="R")]
        self.assertEqual([it.id for it in gate_items(items, ModuleAccess({"school": False}))], ["reminder:1"])


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine, autocommit=False, autoflush=False)


class SearchGateTestCase(unittest.TestCase):
    def setUp(self):
        self.engine, Session = _session()
        self.db = Session()
        fyz = Subject(name="Fyzika", active=True)
        self.db.add(fyz)
        self.db.flush()
        self.db.add_all([
            Assignment(title="Fyzikální protokol", subject_id=fyz.id, due_date=date(2026, 10, 16)),
            WotGrind(tank="Fyzik tank", xp_remaining=100),
            FinanceTransaction(amount=10, category="other", description="Fyzikální tabulky", transaction_type="expense",
                               created_at=datetime(2026, 10, 2, 10)),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_disabled_module_records_are_filtered_ranking_kept(self):
        everything = ss.search(self.db, "fyzik", access=ModuleAccess({}))["results"]
        self.assertEqual({r["type"] for r in everything}, {"subject", "assignment", "wot_grind", "transaction"})
        filtered = ss.search(self.db, "fyzik", access=ModuleAccess({"school": False, "wot": False}))["results"]
        self.assertEqual([r["type"] for r in filtered], ["transaction"])
        # relativní pořadí zbylých výsledků se nemění
        self.assertEqual([r["id"] for r in filtered], [r["id"] for r in everything if r["type"] == "transaction"])


class QuickAddGateTestCase(unittest.TestCase):
    NOW = datetime(2026, 10, 1, 8, 0)

    def test_disabled_module_is_not_parsed_into_a_record(self):
        on = qa.parse("zaplatil jsem 250 kč za oběd", now_utc=self.NOW, subjects=[], access=ModuleAccess({}))
        self.assertEqual(on["kind"], "finance")
        off = qa.parse("zaplatil jsem 250 kč za oběd", now_utc=self.NOW, subjects=[], access=ModuleAccess({"finance": False}))
        self.assertEqual((off["kind"], off["ready"], off["fields"]), ("unknown", False, {}))

    def test_core_kind_is_unaffected(self):
        off = ModuleAccess({m.id: False for m in mr.MODULES})
        self.assertEqual(qa.parse("připomeň mi zítra v 9 zavolat mámě", now_utc=self.NOW, subjects=[], access=off)["kind"], "reminder")

    def test_prepare_refuses_disabled_kind_even_if_client_sends_it(self):
        with self.assertRaises(qa.QuickAddInvalid) as ctx:
            qa.to_tool_call(None, "work", {"hours": 2, "date": "2026-10-01"}, now_utc=self.NOW, access=ModuleAccess({"work": False}))
        self.assertEqual(ctx.exception.errors[0]["field"], "kind")

    def test_future_module_kind_gate(self):
        # Food zatím nemá parser; brána ale existuje: druh fixture modulu je povolen jen zapnutému modulu
        self.assertTrue(ModuleAccess({"alpha": True}, FIXTURES).allows_quick_add_kind("alpha_meal"))
        self.assertFalse(ModuleAccess({"beta": False}, FIXTURES).allows_quick_add_kind("beta_meal"))


class AiContextGateTestCase(unittest.TestCase):
    NOW = datetime(2026, 10, 1, 8, 0)

    def setUp(self):
        self.engine, Session = _session()
        self.db = Session()
        self.db.add_all([
            WorkSession(date=date(2026, 10, 1), hours=4, project="Servind", hourly_rate=300, sync_to_finance=False),
            FinanceTransaction(amount=9000, category="salary", description="výplata", transaction_type="income",
                               created_at=datetime(2026, 9, 30, 10)),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_disabled_module_contributes_no_section(self):
        q = "jak jsem na tom s penězi a prací"
        on = build_current_context(self.db, q, now_utc=self.NOW, access=ModuleAccess({}))
        self.assertIn("finance", on.sections)
        off = build_current_context(self.db, q, now_utc=self.NOW, access=ModuleAccess({"finance": False}))
        self.assertNotIn("finance", off.sections)
        self.assertIn("work", off.sections)

    def test_canonical_answer(self):
        access = ModuleAccess({"wot": False})
        self.assertFalse(access.allows("wot", "ai_context"))
        self.assertTrue(access.allows("mff", "ai_context"))
        self.assertTrue(access.allows_context_area("notifications"), "jádro")
        self.assertFalse(ModuleAccess({"alpha": True}, FIXTURES).allows("gamma", "ai_context"))

    def test_tools_of_disabled_module_are_not_offered(self):
        with patch.dict(os.environ, {**_clean_env(), "MODULE_WOT_ENABLED": "false"}, clear=True):
            names = tool_router.all_tools_route().names
        self.assertFalse(any(n in names for n in ("get_wot_resources", "get_wot_grinds", "update_wot_resource", "upsert_wot_grind")))
        self.assertIn("get_mff_summary", names)
        self.assertIn("modify_records", names, "víceoblastní tool zůstává")
        with patch.dict(os.environ, _clean_env(), clear=True):
            self.assertIn("get_wot_grinds", tool_router.all_tools_route().names)


class ApiGateTestCase(unittest.TestCase):
    PIN = "4821"

    def setUp(self):
        self.engine, Session = _session()
        self._orig = (auth_service.SessionLocal, main.SessionLocal, tools.SessionLocal, auth_service.AUTH_PIN_HASH,
                      auth_service._failed_attempts)
        auth_service.SessionLocal = main.SessionLocal = tools.SessionLocal = Session
        auth_service._failed_attempts = {}
        auth_service.AUTH_PIN_HASH = ""
        db = Session()
        db.add_all([MffCharacter(name="Luna Snow", tier="T4"), Goal(area="finance", title="Rezerva", progress=10)])
        db.commit()
        db.close()
        self.client = TestClient(main.app)
        self._env = patch.dict(os.environ, _clean_env(), clear=True)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        (auth_service.SessionLocal, main.SessionLocal, tools.SessionLocal, auth_service.AUTH_PIN_HASH,
         auth_service._failed_attempts) = self._orig
        self.engine.dispose()

    def test_disabled_module_routes_return_clean_404(self):
        self.assertEqual(self.client.get("/mff/characters").status_code, 200)
        os.environ["MODULE_MFF_ENABLED"] = "false"
        r = self.client.get("/mff/characters")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["detail"]["module"], "mff")
        self.assertEqual(self.client.post("/mff/character", json={"name": "X"}).status_code, 404)
        self.assertEqual(self.client.get("/wot/grinds").status_code, 200)
        self.assertEqual(self.client.get("/reminders").status_code, 200, "jádro beze změny")

    def test_flags_never_bypass_auth(self):
        auth_service.AUTH_PIN_HASH = bcrypt.hashpw(self.PIN.encode(), bcrypt.gensalt(rounds=4)).decode()
        os.environ["MODULE_MFF_ENABLED"] = "false"
        # vypnutý i zapnutý modul: bez session vždy 401 (auth běží před bránou modulu)
        self.assertEqual(self.client.get("/mff/characters").status_code, 401)
        self.assertEqual(self.client.get("/wot/grinds").status_code, 401)
        self.assertEqual(self.client.get("/modules").status_code, 401)
        self.assertEqual(self.client.post("/auth/login", json={"pin": self.PIN}).status_code, 200)
        self.assertEqual(self.client.get("/mff/characters").status_code, 404)
        self.assertEqual(self.client.get("/wot/grinds").status_code, 200)

    def test_modules_endpoint(self):
        os.environ["MODULE_WOT_ENABLED"] = "off"
        os.environ["MODULE_FOOD_ENABLED"] = "on"
        body = self.client.get("/modules").json()["modules"]
        by_id = {m["id"]: m for m in body}
        self.assertFalse(by_id["wot"]["available"])
        self.assertFalse(by_id["food"]["available"], "neimplementovaný modul")
        self.assertTrue(by_id["school"]["available"])
        self.assertNotIn("off", str(body))

    def test_dashboard_skips_disabled_sections(self):
        with patch.object(main, "generate_plan", return_value={"actions": [
            {"title": "Úkol", "ref": "assignment:1"}, {"title": "Cíl", "ref": "goal:1"}], "summary": ""}):
            on = self.client.get("/dashboard").json()
            self.assertIsNotNone(on["mff"])
            self.assertEqual(on["goals"]["count"], 1)
            os.environ.update({"MODULE_MFF_ENABLED": "false", "MODULE_GOALS_ENABLED": "false"})
            off = self.client.get("/dashboard").json()
        self.assertIsNone(off["mff"])
        self.assertIsNone(off["goals"])
        self.assertIsNotNone(off["wot"])
        self.assertEqual([a["ref"] for a in off["today"]["actions"]], ["assignment:1"])

    def test_today_action_for_disabled_module_is_refused(self):
        os.environ["MODULE_SCHOOL_ENABLED"] = "false"
        r = self.client.post("/today/actions/prepare", json={"action": "complete", "ref": "assignment:1"})
        self.assertEqual(r.status_code, 404)


class FrontendParityTestCase(unittest.TestCase):
    """Frontend má zrcadlový registr (lib/modules.ts) – id, výchozí stav, implementace a vlastnictví se shodují."""

    TS = Path(BACKEND_DIR).parent / "frontend" / "lib" / "modules.ts"

    @staticmethod
    def _list(text: str) -> set[str]:
        return set(re.findall(r'"([a-z_]+)"', text))

    def test_registries_match(self):
        if not self.TS.exists():
            self.skipTest("frontend není k dispozici")
        src = self.TS.read_text(encoding="utf-8")
        fe = {}
        for line in src.splitlines():
            m = re.match(r'\s*\{ id: "(\w+)"', line)
            if m:
                get = lambda key: re.search(rf"{key}: \[([^\]]*)\]", line).group(1)  # noqa: E731
                fe[m.group(1)] = {
                    "default": "defaultEnabled: true" in line,
                    "implemented": "implemented: true" in line,
                    "capabilities": self._list(get("capabilities")),
                    "entity_types": self._list(get("entityTypes")),
                    "quick_add_kinds": self._list(get("quickAddKinds")),
                }
            m = re.match(r'\s*planned\("(\w+)"', line)
            if m:
                fe[m.group(1)] = {"default": False, "implemented": False, "capabilities": set(), "entity_types": set(),
                                  "quick_add_kinds": set()}
        be = {m.id: {"default": m.default_enabled, "implemented": m.implemented, "capabilities": set(m.capabilities),
                     "entity_types": set(m.entity_types), "quick_add_kinds": set(m.quick_add_kinds)} for m in mr.MODULES}
        self.assertEqual(list(fe), list(be))
        self.assertEqual(fe, be)

    def test_frontend_routes_are_backend_api_prefixes(self):
        """MRK-7: stránka modulu (frontend routes) má stejný prefix i na backendu – brána stránky i API sedí."""
        if not self.TS.exists():
            self.skipTest("frontend není k dispozici")
        src = self.TS.read_text(encoding="utf-8")
        for line in src.splitlines():
            m = re.match(r'\s*\{ id: "(\w+)"', line)
            if m:
                routes = set(re.findall(r'"(/[a-z/]+)"', re.search(r"routes: \[([^\]]*)\]", line).group(1)))
                self.assertTrue(routes <= set(mr.ModuleAccess({}).get(m.group(1)).api_prefixes), m.group(1))



class MainEraGateTestCase(unittest.TestCase):
    """MRK-7: přírůstky mainu od původní větve flagů – Replay Library, milníky WoT, splnění ve Škole, AI zápisy."""

    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

    def setUp(self):
        self.engine, self.Session = _session()
        self._orig = (auth_service.SessionLocal, main.SessionLocal, tools.SessionLocal, auth_service.AUTH_PIN_HASH,
                      auth_service._failed_attempts)
        auth_service.SessionLocal = main.SessionLocal = tools.SessionLocal = self.Session
        auth_service._failed_attempts = {}
        auth_service.AUTH_PIN_HASH = ""
        db = self.Session()
        subj = Subject(name="Fyzika", active=True)
        db.add(subj)
        db.flush()
        now = datetime(2026, 10, 7, 12)
        db.add_all([
            WotGrind(tank="Kranvagn", xp_remaining=52000, status="active", priority="high"),
            WotMilestone(tank="Progetto 65", milestone_type="mastery", mastery="ace", favorite=False, created_at=now, updated_at=now),
            WotReplay(original_filename="progetto.wotreplay", stored_filename="0" * 32 + ".wotreplay", file_size=10, sha256="a" * 64,
                      uploaded_at=now, created_at=now, updated_at=now, tank_name="Progetto 65", map_name="Útesy", tags=["carry"],
                      favorite=False, parser_status="parsed"),
            Assignment(title="Protokol", subject_id=subj.id, status="todo"),
            Exam(title="Zápočet", subject_id=subj.id, status="upcoming"),
        ])
        db.commit()
        db.close()
        self.client = TestClient(main.app)
        self._env = patch.dict(os.environ, _clean_env(), clear=True)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        (auth_service.SessionLocal, main.SessionLocal, tools.SessionLocal, auth_service.AUTH_PIN_HASH,
         auth_service._failed_attempts) = self._orig
        self.engine.dispose()

    def counts(self):
        db = self.Session()
        try:
            return tuple(db.query(m).count() for m in (WotGrind, WotMilestone, WotReplay))
        finally:
            db.close()

    def test_wot_off_gates_replays_milestones_and_search_without_touching_data(self):
        self.assertEqual(self.client.get("/wot/replays").status_code, 200)
        self.assertEqual(self.client.get("/wot/milestones").status_code, 200)
        db = self.Session()
        try:
            on = {r["type"] for r in ss.search(db, "progetto")["results"]}
        finally:
            db.close()
        self.assertEqual(on, {"wot_replay"})
        before = self.counts()

        os.environ["MODULE_WOT_ENABLED"] = "false"
        for method, url in (("get", "/wot/replays"), ("get", "/wot/replays/1"), ("get", "/wot/replays/1/file"),
                            ("post", "/wot/replays?filename=x.wotreplay"), ("patch", "/wot/replays/1"),
                            ("delete", "/wot/replays/1"), ("get", "/wot/milestones"), ("delete", "/wot/milestones/1"),
                            ("post", "/wot/milestones/1/screenshots"), ("get", "/wot/screenshots/1/file"),
                            ("get", "/wot/grinds/completed"), ("post", "/wot/grind/1/complete")):
            kwargs = {"json": {}} if method == "patch" else {"content": self.PNG} if method == "post" else {}
            r = getattr(self.client, method)(url, **kwargs)
            self.assertEqual((r.status_code, r.json()["detail"]["module"]), (404, "wot"), url)
        db = self.Session()
        try:
            self.assertEqual(ss.search(db, "progetto")["results"], [], "replaye zmizí z vyhledávání")
            self.assertEqual(ss.search(db, "kranvagn")["results"], [])
        finally:
            db.close()
        self.assertIsNone(self.client.get("/dashboard").json()["wot"])
        self.assertEqual(self.counts(), before, "data WoT zůstávají beze změny")

        os.environ["MODULE_WOT_ENABLED"] = "true"
        self.assertEqual(len(self.client.get("/wot/replays").json()["items"]), 1, "po zapnutí vše zpět")
        self.assertEqual(len(self.client.get("/wot/milestones").json()), 1)
        self.assertIsNotNone(self.client.get("/dashboard").json()["wot"])

    def test_school_completion_endpoints_follow_the_school_flag(self):
        os.environ["MODULE_SCHOOL_ENABLED"] = "false"
        for url in ("/school/assignment/1/complete", "/school/assignment/1/reopen", "/school/exam/1/close", "/school/exam/1/reopen"):
            self.assertEqual(self.client.post(url, json={}).status_code, 404, url)
        os.environ["MODULE_SCHOOL_ENABLED"] = "true"
        self.assertEqual(self.client.post("/school/assignment/1/complete").status_code, 200)

    def test_ai_mutations_of_disabled_module_are_refused(self):
        import mutation_service as ms

        os.environ["MODULE_WOT_ENABLED"] = "false"
        db = self.Session()
        try:
            with self.assertRaises(ms.MutationRefused) as ctx:
                ms.resolve_mutation(db, "wot_grind", "update", {"id": 1}, {"priority": "low"})
            self.assertEqual(ctx.exception.code, "module_unavailable")
            ms.resolve_mutation(db, "school_assignment", "complete", {"id": 1})  # jiný modul beze změny
            os.environ["MODULE_WOT_ENABLED"] = "true"
            plan = ms.resolve_mutation(db, "wot_grind", "update", {"id": 1}, {"priority": "low"})
            os.environ["MODULE_WOT_ENABLED"] = "false"  # vypnuto mezi návrhem a potvrzením → nic se nezmění
            with patch.object(ms, "SessionLocal", self.Session), self.assertRaises(ms.StaleTarget):
                ms.apply_mutation_plan(plan)
        finally:
            db.close()
        db = self.Session()
        try:
            self.assertEqual(db.get(WotGrind, 1).priority, "high")
        finally:
            db.close()

    def test_quick_add_time_parsing_is_core(self):
        """MRK-11: schůzka s časem je připomínka (jádro) – funguje i se všemi moduly vypnutými."""
        off = ModuleAccess({m.id: False for m in mr.MODULES})
        r = qa.parse("21.10.2026 fyzio od 14 hodin", now_utc=datetime(2026, 10, 3, 10), subjects=[], access=off)
        self.assertEqual((r["kind"], r["fields"]["due_local"], r["ready"]), ("reminder", "2026-10-21T14:00", True))


if __name__ == "__main__":
    unittest.main()
