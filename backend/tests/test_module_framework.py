"""MRK-20 (Platform 2.0 C): architektonické testy rámce modulů – příspěvky se objevují samy, vypnutý modul
nepřispívá nikam, agregátory nemají modulový kód a nový modul jde přidat bez úpravy agregátorů.

Testovací modul `alpha` (jen v testu, žádná produkční stránka ani tabulka) prochází všemi agregátory:
vyhledávání, Dnes, GET /dashboard, AI kontext, Rychlé přidání a hodinový job. Žádný reálný Groq.
"""
import ast
import inspect
import os
import subprocess
import sys
import unittest
from dataclasses import fields
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("GROQ_API_KEY", "x")
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import auth_service  # noqa: E402
import main  # noqa: E402
import module_registry as mr  # noqa: E402
import quick_add_service as qa  # noqa: E402
import scheduler_service  # noqa: E402
import search_service as ss  # noqa: E402
import today_service as ts  # noqa: E402
from context_service import build_current_context  # noqa: E402
from core_integrations import CORE_INTEGRATIONS  # noqa: E402
from database import Base  # noqa: E402
from models import Assignment, FinanceTransaction, MffCharacter, Subject, WorkSession, WotGrind  # noqa: E402
from module_contracts import (  # noqa: E402
    CONTRIBUTION_CAPABILITY, ContextSection, DashboardSection, EntityRef, ModuleIntegrations, QuickAddKind,
    QuickAddRule, ScheduledStep, SearchSource, TodaySource,
)
from module_registry import ModuleAccess, ModuleDef  # noqa: E402
from today_types import TodayItem  # noqa: E402

KINDS = tuple(f.name for f in fields(ModuleIntegrations) if f.name != "notes")
IMPLEMENTED = [m for m in mr.MODULES if m.implemented]
NOW = datetime(2026, 10, 7, 8, 0)  # 10:00 Praha


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine, autocommit=False, autoflush=False)


# ---------- testovací modul „alpha" – jen manifest + poskytovatelé, žádná změna agregátorů ----------

HOURLY_RUNS: list[str] = []


def _alpha_search(db, q):
    yield "alpha_item", 1, "Alfa záznam lasagne", "Alfa · test", "alfa", "alpha", "/alpha?item=1"


def _alpha_today(c):
    return [TodayItem(id="alpha_item:1", type="alpha_item", title="Alfa dnes", area="alpha", date=c.today.isoformat(),
                      status="open", href="/alpha?item=1")]


def _alpha_upcoming(c):
    return [TodayItem(id="alpha_item:2", type="alpha_item", title="Alfa zítra", area="alpha", status="upcoming",
                      date=c.today.isoformat())]


def _alpha_parse(t, d, now_utc, ctx):
    d.fields = {"title": t.rest()}


ALPHA = ModuleDef(
    "alpha", "Alfa", default_enabled=True, implemented=True, capabilities=mr.ALL_CAPABILITIES,
    entity_types=frozenset({"alpha_item"}), context_areas=frozenset({"alpha"}), api_prefixes=("/alpha",),
    quick_add_kinds=("alpha_meal",),
    integrations=ModuleIntegrations(
        search=(SearchSource("alpha", 55, _alpha_search),),
        today=(TodaySource("alpha", 30, timeline=_alpha_today, upcoming=_alpha_upcoming),),
        entity_refs=(EntityRef("alpha_item", "/alpha?item={id}", planner_actions=("complete",)),),
        dashboard=(DashboardSection("alpha", lambda db, access: {"count": 1}),),
        context=(ContextSection("alpha", ("lasagn", "alfa"), order=45, build=lambda req: ["Alfa: 1 záznam"],
                                covered_tools=("get_alpha",)),),
        # priorita 5 = před připomínkou; slovo „lasagne" jinak nic nezná
        quick_add_rules=(QuickAddRule(5, "alpha_meal", lambda t: "high" if "lasagn" in t.f else None),),
        quick_add_kinds=(QuickAddKind("alpha_meal", _alpha_parse, lambda f, d, today, now, db: ("add_alpha", dict(f)),
                                      lambda f, ctx, today: {"title": f.get("title") or "Alfa", "subtitle": "", "area": "alpha"}),),
        hourly=(ScheduledStep("alpha step", lambda db: HOURLY_RUNS.append("alpha") or "ok"),),
    ),
)
WITH_ALPHA = (*mr.MODULES, ALPHA)


def _access(**flags):
    return ModuleAccess({"alpha": True, **flags}, WITH_ALPHA)


class RegistryContractTestCase(unittest.TestCase):
    """Statický registr: příspěvky se najdou samy z ModuleDef, bez duplicit a v souladu s manifestem."""

    def test_implemented_modules_bring_integrations_planned_do_not(self):
        for m in mr.MODULES:
            has_any = any(getattr(m.integrations, k) for k in KINDS)
            self.assertEqual(has_any, m.implemented, m.id)

    def test_every_contribution_kind_is_gated_by_a_known_capability(self):
        self.assertEqual(set(CONTRIBUTION_CAPABILITY), set(KINDS))
        for cap in CONTRIBUTION_CAPABILITY.values():
            self.assertTrue(cap is None or cap in mr.ALL_CAPABILITIES, cap)

    def test_no_duplicates(self):
        def names(kind, attr):
            return [getattr(item, attr) for _o, item in mr.all_contributions(kind)]

        for kind, attr in [("search", "name"), ("today", "name"), ("entity_refs", "type"), ("dashboard", "key"),
                           ("context", "area"), ("quick_add_kinds", "kind"), ("quick_add_rules", "priority"),
                           ("hourly", "name")]:
            values = names(kind, attr)
            self.assertEqual(len(values), len(set(values)), f"{kind}.{attr}: {values}")
        self.assertEqual(len({s.order for _o, s in mr.all_contributions("search")}), len(names("search", "name")))

    def test_manifest_matches_contributions(self):
        for m in IMPLEMENTED:
            i = m.integrations
            self.assertEqual(set(m.quick_add_kinds), {k.kind for k in i.quick_add_kinds}, m.id)
            self.assertEqual({r.kind for r in i.quick_add_rules}, set(m.quick_add_kinds), m.id)
            self.assertLessEqual({c.area for c in i.context}, set(m.context_areas), m.id)
            self.assertLessEqual({r.type for r in i.entity_refs}, set(m.entity_types), m.id)
            if i.search:
                self.assertIn("search", m.capabilities, m.id)
            if i.today:
                self.assertIn("today", m.capabilities, m.id)
            if i.dashboard:
                self.assertIn("dashboard", m.capabilities, m.id)

    def test_core_is_always_present(self):
        off = ModuleAccess({m.id: False for m in mr.MODULES})
        for kind in KINDS:
            owners = {o for o, _ in off.contributions(kind)}
            self.assertLessEqual(owners, {None}, kind)
            self.assertEqual(len(off.contributions(kind)), len(getattr(CORE_INTEGRATIONS, kind)), kind)

    def test_disabled_module_contributes_nothing(self):
        for m in IMPLEMENTED:
            off = ModuleAccess({m.id: False})
            for kind in KINDS:
                self.assertNotIn(m.id, {o for o, _ in off.contributions(kind)}, (m.id, kind))
            on = ModuleAccess({})
            self.assertTrue(any(o == m.id for k in KINDS for o, _ in on.contributions(k)), m.id)

    def test_capability_level_gating(self):
        # WoT nemá „today" → žádný příspěvek do Dnes, i když je modul zapnutý
        access = ModuleAccess({})
        self.assertFalse(access.contributes("wot", "today"))
        self.assertTrue(access.contributes("wot", "search"))
        self.assertTrue(access.contributes("goals", "hourly"), "hodinový krok patří k dostupnosti modulu")

    def test_search_sources_only_return_owned_types(self):
        engine, Session = _session()
        db = Session()
        s = Subject(name="Fyzika")
        db.add(s)
        db.flush()
        db.add_all([Assignment(title="Úkol", subject_id=s.id), WorkSession(date=date(2026, 10, 1), hours=1),
                    FinanceTransaction(amount=1, category="other", transaction_type="expense"), WotGrind(tank="IS-7", xp_remaining=1),
                    MffCharacter(name="Luna Snow", tier="T4")])
        db.commit()
        try:
            for m in IMPLEMENTED:
                for src in m.integrations.search:
                    for typ, *_rest in src.fetch(db, "x"):
                        self.assertIn(typ, m.entity_types, (m.id, src.name))
        finally:
            db.close()
            engine.dispose()


class AggregatorPurityTestCase(unittest.TestCase):
    """Agregátory migrovaných ploch nesmí obsahovat modulový kód (modely ani id modulů)."""

    MODULE_MODELS = ("Assignment", "Exam", "Subject", "WorkSession", "FinanceTransaction", "Goal", "WotGrind",
                     "WotResource", "WotReplay", "MffCharacter")
    MODULE_IDS = tuple(m.id for m in mr.MODULES)

    def _assert_pure(self, name, source, *, allow_ids=()):
        tree = ast.parse(source)
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        imported = {a.name.split(".")[-1] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        self.assertFalse((used | imported) & set(self.MODULE_MODELS), f"{name} odkazuje na model modulu")
        strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        leaked = (strings & set(self.MODULE_IDS)) - set(allow_ids)
        self.assertFalse(leaked, f"{name} obsahuje id modulu: {leaked}")

    def _file(self, name):
        return (Path(BACKEND_DIR) / name).read_text(encoding="utf-8")

    def test_search_today_quick_add_scheduler_are_module_free(self):
        for name in ("search_service.py", "today_service.py", "quick_add_service.py", "scheduler_service.py"):
            self._assert_pure(name, self._file(name))

    def test_dashboard_endpoint_is_module_free(self):
        self._assert_pure("main.dashboard_get", inspect.getsource(main.dashboard_get))

    def test_context_service_keeps_only_global_policy(self):
        # Globální implikovaná pravidla („plán" → škola, cíle…) odkazují na oblasti jménem – to je politika, ne data.
        self._assert_pure("context_service.py", self._file("context_service.py"),
                          allow_ids=("school", "goals", "work", "finance", "wot", "mff"))
        import context_service as cs
        for helper in ("_school_lines", "_work_lines", "_finance_lines", "_goal_lines", "_wot_lines", "_reminder_lines"):
            self.assertFalse(hasattr(cs, helper), helper)

    def test_provider_files_are_import_leaves(self):
        """Poskytovatelé neimportují agregátory ani registr (jinak cyklus a skrytá závislost na pořadí importů)."""
        forbidden = {"main", "module_registry", "search_service", "today_service", "context_service",
                     "quick_add_service", "scheduler_service", "tool_router", "ai", "briefing_snapshot", "weekly_snapshot"}
        files = [*Path(BACKEND_DIR).glob("*_integrations.py"), *(Path(BACKEND_DIR) / f for f in (
            "module_contracts.py", "quick_add_text.py", "context_format.py", "today_types.py"))]
        self.assertGreaterEqual(len(files), 11)
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            mods |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            self.assertFalse(mods & forbidden, f"{path.name}: {mods & forbidden}")

    def test_every_aggregator_imports_first_without_cycles(self):
        env = {**os.environ, "DATABASE_URL": "sqlite+pysqlite:///:memory:", "GROQ_API_KEY": "x"}
        for mod in ("module_registry", "search_service", "today_service", "context_service", "quick_add_service",
                    "scheduler_service", "reminder_service", "tool_router", "school_integrations", "main"):
            r = subprocess.run([sys.executable, "-c", f"import {mod}"], cwd=BACKEND_DIR, env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{mod}: {r.stderr[-600:]}")


class FakeModuleEndToEndTestCase(unittest.TestCase):
    """Nový modul = manifest + poskytovatelé. Agregátory ho najdou bez jediné úpravy; vypnutý zmizí všude."""

    def setUp(self):
        self.engine, self.Session = _session()
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_search(self):
        on = ss.search(self.db, "lasagne", access=_access())["results"]
        self.assertEqual([(r["type"], r["href"]) for r in on], [("alpha_item", "/alpha?item=1")])
        self.assertEqual(ss.search(self.db, "lasagne", access=_access(alpha=False))["results"], [])

    def test_search_failing_source_is_isolated(self):
        broken = ModuleDef("beta", "Beta", True, True, capabilities=frozenset({"search"}),
                           entity_types=frozenset({"beta_item"}),
                           integrations=ModuleIntegrations(search=(SearchSource("beta", 1, lambda db, q: 1 / 0),)))
        access = ModuleAccess({"alpha": True, "beta": True}, (*WITH_ALPHA, broken))
        with self.assertLogs("search_service", level="ERROR"):
            out = ss.search(self.db, "lasagne", access=access)
        self.assertEqual([r["type"] for r in out["results"]], ["alpha_item"])

    def test_today(self):
        with patch.object(ts, "generate_plan", return_value={"actions": [{"title": "Alfa plán", "ref": "alpha_item:7", "priority": 1}]}):
            on = ts.build_today(self.db, now_utc=NOW, access=_access())
            off = ts.build_today(self.db, now_utc=NOW, access=_access(alpha=False))
        self.assertEqual([it["id"] for it in on["timeline"]], ["alpha_item:1"])
        self.assertEqual([it["id"] for it in on["upcoming"]], ["alpha_item:2"])
        plan = on["priorities"][0]
        self.assertEqual((plan["href"], plan["actions"]), ("/alpha?item=7", ["complete"]), "odkaz a akce z EntityRef")
        self.assertEqual(on["errors"], {})
        self.assertEqual(off["timeline"] + off["upcoming"] + off["priorities"], [])

    def test_today_failing_source_keeps_other_modules(self):
        def boom(c):
            raise RuntimeError("boom")
        broken = ModuleDef("beta", "Beta", True, True, capabilities=frozenset({"today"}),
                           integrations=ModuleIntegrations(today=(TodaySource("beta", 1, timeline=boom),)))
        access = ModuleAccess({"alpha": True, "beta": True}, (*WITH_ALPHA, broken))
        with patch.object(ts, "generate_plan", return_value={"actions": []}):
            out = ts.build_today(self.db, now_utc=NOW, access=access)
        self.assertEqual([it["id"] for it in out["timeline"]], ["alpha_item:1"])
        self.assertEqual(out["errors"], {"timeline": ts.SECTION_ERRORS["timeline"]})

    def test_ai_context(self):
        on = build_current_context(self.db, "kolik mám lasagní", now_utc=NOW, access=_access())
        self.assertIn("alpha", on.sections)
        self.assertIn("Alfa: 1 záznam", on.text)
        self.assertIn("get_alpha", on.covered_tools)
        off = build_current_context(self.db, "kolik mám lasagní", now_utc=NOW, access=_access(alpha=False))
        self.assertNotIn("alpha", off.sections)
        self.assertNotIn("Alfa", off.text)

    def test_quick_add(self):
        on = qa.parse("zítra k obědu lasagne", now_utc=NOW, access=_access())
        self.assertEqual((on["kind"], on["display"]["area"]), ("alpha_meal", "alpha"))
        self.assertEqual(qa.to_tool_call(self.db, "alpha_meal", {"title": "Lasagne"}, now_utc=NOW, access=_access()),
                         ("add_alpha", {"title": "Lasagne"}))
        off = qa.parse("zítra k obědu lasagne", now_utc=NOW, access=_access(alpha=False))
        self.assertEqual((off["kind"], off["fields"], off["ready"]), ("unknown", {}, False),
                         "vypnutý modul nevytvoří skrytá data a nehádá jiný druh")
        with self.assertRaises(qa.QuickAddInvalid):
            qa.to_tool_call(self.db, "alpha_meal", {"title": "x"}, now_utc=NOW, access=_access(alpha=False))

    def test_dashboard_and_scheduler(self):
        orig = (auth_service.SessionLocal, main.SessionLocal, auth_service.AUTH_PIN_HASH)
        auth_service.SessionLocal = main.SessionLocal = self.Session
        auth_service.AUTH_PIN_HASH = ""
        try:
            with patch.object(main, "current_access", return_value=_access()), \
                    patch.object(main, "generate_plan", return_value={"actions": [], "summary": ""}):
                on = TestClient(main.app).get("/dashboard").json()
            with patch.object(main, "current_access", return_value=_access(alpha=False)), \
                    patch.object(main, "generate_plan", return_value={"actions": [], "summary": ""}):
                off = TestClient(main.app).get("/dashboard").json()
        finally:
            auth_service.SessionLocal, main.SessionLocal, auth_service.AUTH_PIN_HASH = orig
        self.assertEqual(on["alpha"], {"count": 1})
        self.assertIn("alpha", off)
        self.assertIsNone(off["alpha"], "klíč zůstává, hodnota prázdná")
        for key in ("goals", "work", "finance", "upcoming", "wot", "mff"):
            self.assertIn(key, on)

        HOURLY_RUNS.clear()
        with patch.object(scheduler_service, "SessionLocal", self.Session), \
                patch.object(scheduler_service, "current_access", return_value=_access()), \
                patch.object(scheduler_service, "create_all_overdue_and_upcoming_notifications", return_value=0):
            scheduler_service._run_hourly_job()
        self.assertEqual(HOURLY_RUNS, ["alpha"])
        HOURLY_RUNS.clear()
        with patch.object(scheduler_service, "SessionLocal", self.Session), \
                patch.object(scheduler_service, "current_access", return_value=_access(alpha=False)), \
                patch.object(scheduler_service, "create_all_overdue_and_upcoming_notifications", return_value=0):
            scheduler_service._run_hourly_job()
        self.assertEqual(HOURLY_RUNS, [], "vypnutý modul nespouští své kroky (data zůstávají)")


class GlobalPolicyRegressionTestCase(unittest.TestCase):
    """Globální politika zůstala v agregátorech: pořadí, limity a gating platí pro příspěvky všech modulů."""

    def test_search_ranking_and_per_type_cap(self):
        many = ModuleDef("gamma", "Gama", True, True, capabilities=frozenset({"search"}), entity_types=frozenset({"g"}),
                         integrations=ModuleIntegrations(search=(SearchSource("gamma", 1, lambda db, q: (
                             ("g", i, f"Fyzika {i}", "", "", "gamma", f"/g?i={i}") for i in range(20))),)))
        engine, Session = _session()
        db = Session()
        try:
            out = ss.search(db, "fyzika", access=ModuleAccess({"gamma": True}, (*mr.MODULES, many)))
        finally:
            db.close()
            engine.dispose()
        self.assertEqual(len(out["results"]), ss.PER_TYPE)
        self.assertEqual(out["total"], 20)
        scores = [r["score"] for r in out["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_quick_add_rule_order_is_the_old_fixed_priority(self):
        order = [(r.priority, r.kind) for r in qa._RULES]
        self.assertEqual(order, [(10, "reminder"), (20, "exam"), (30, "assignment"), (40, "work"), (50, "work"),
                                 (60, "reminder"), (70, "finance"), (80, "finance")])

    def test_today_section_cap_still_global(self):
        def many(c):
            return [TodayItem(id=f"alpha_item:{i}", type="alpha_item", title=f"A{i}", status="upcoming",
                              date=c.today.isoformat()) for i in range(10)]
        mod = ModuleDef("alpha", "Alfa", True, True, capabilities=frozenset({"today"}), entity_types=frozenset({"alpha_item"}),
                        integrations=ModuleIntegrations(today=(TodaySource("alpha", 1, upcoming=many),)))
        engine, Session = _session()
        db = Session()
        try:
            with patch.object(ts, "generate_plan", return_value={"actions": []}):
                out = ts.build_today(db, now_utc=NOW, access=ModuleAccess({"alpha": True}, (*mr.MODULES, mod)))
        finally:
            db.close()
            engine.dispose()
        self.assertEqual(len(out["upcoming"]), ts.MAX_UPCOMING)


if __name__ == "__main__":
    unittest.main()
