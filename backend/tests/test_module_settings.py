"""MRK-18 A2: runtime nastavení modulů – precedence prostředí > databáze > manifest, PUT /modules/{id},
zámek při vynucení prostředím (409) a nedotčená data modulu. Žádný reálný Groq ani síť."""
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
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
import tool_router  # noqa: E402
import tools  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, ModuleSetting, WotGrind, WotMilestone  # noqa: E402

MODULE_ENV = [m.env_name for m in mr.MODULES]
WOT = next(m for m in mr.MODULES if m.id == "wot")


def _clean_env():
    return {k: v for k, v in os.environ.items() if k not in MODULE_ENV}


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


class PrecedenceTestCase(unittest.TestCase):
    """Čistý resolver: env > DB > manifest (env/overrides předané přímo, bez DB)."""

    def state(self, env=None, overrides=None, module="wot"):
        return mr.resolve_states(env=env or {}, overrides=overrides or {})[module]

    def test_default_when_nothing_set(self):
        st = self.state()
        self.assertEqual((st.enabled, st.source, st.locked), (True, "default", False))
        self.assertEqual(self.state(module="food").enabled, False)

    def test_db_override_without_env(self):
        st = self.state(overrides={"wot": False})
        self.assertEqual((st.enabled, st.source, st.locked), (False, "db", False))

    def test_env_true_beats_db_false(self):
        st = self.state(env={"MODULE_WOT_ENABLED": "true"}, overrides={"wot": False})
        self.assertEqual((st.enabled, st.source, st.locked), (True, "env", True))

    def test_env_false_beats_db_true(self):
        st = self.state(env={"MODULE_WOT_ENABLED": "0"}, overrides={"wot": True})
        self.assertEqual((st.enabled, st.source, st.locked), (False, "env", True))

    def test_missing_or_blank_env_lets_db_decide(self):
        for env in ({}, {"MODULE_WOT_ENABLED": ""}, {"MODULE_WOT_ENABLED": "   "}):
            with self.subTest(env=env):
                st = self.state(env=env, overrides={"wot": False})
                self.assertEqual((st.enabled, st.source), (False, "db"))

    def test_malformed_env_is_not_an_override(self):
        # A1 politika: překlep nesmí potichu schovat ani vynutit modul → ignorovat, varovat, platí DB/manifest.
        with self.assertLogs("module_registry", level="WARNING"):
            mr._warned.discard("MODULE_WOT_ENABLED")
            st = self.state(env={"MODULE_WOT_ENABLED": "ture"}, overrides={"wot": False})
        self.assertEqual((st.enabled, st.source, st.locked), (False, "db", False))
        st = self.state(env={"MODULE_WOT_ENABLED": "maybe"})
        self.assertEqual((st.enabled, st.source), (True, "default"))

    def test_unimplemented_module_stays_unavailable_even_when_forced(self):
        access = mr.ModuleAccess(states=mr.resolve_states(env={"MODULE_FOOD_ENABLED": "on"}, overrides={}))
        self.assertTrue(access.state("food").enabled)
        self.assertFalse(access.is_available("food"))


class DbOverridesTestCase(unittest.TestCase):
    def setUp(self):
        self.engine, self.Session = _session()
        self._patch = patch.object(mr, "SessionLocal", self.Session)
        self._patch.start()
        mr.invalidate_cache()

    def tearDown(self):
        self._patch.stop()
        mr.invalidate_cache()
        self.engine.dispose()

    def rows(self):
        with self.Session() as db:
            return {r.module_id: r.enabled for r in db.query(ModuleSetting).all()}

    def save(self, module_id, enabled):
        with self.Session() as db:
            mr.save_override(db, module_id, enabled)
            db.commit()
        mr.invalidate_cache()

    def test_only_non_default_values_are_stored(self):
        self.save("wot", False)
        self.assertEqual(self.rows(), {"wot": False})
        self.save("wot", True)  # = manifest → řádek pryč (žádná duplikace výchozího stavu)
        self.assertEqual(self.rows(), {})
        self.save("food", True)
        self.save("food", None)  # None = zpět na výchozí
        self.assertEqual(self.rows(), {})
        with self.assertRaises(KeyError), self.Session() as db:
            mr.save_override(db, "nope", True)

    def test_resolver_reads_db_through_cache(self):
        self.save("wot", False)
        with patch.dict(os.environ, _clean_env(), clear=True):
            self.assertFalse(mr.current_access().is_available("wot"))
            # přímý zápis do DB bez invalidace: cache drží poslední známý stav až do TTL
            with self.Session() as db:
                db.query(ModuleSetting).delete()
                db.commit()
            self.assertFalse(mr.current_access().is_available("wot"))
            with patch.object(mr, "_clock", lambda: 10**9):
                self.assertTrue(mr.current_access().is_available("wot"), "po TTL se znovu načte")

    def test_db_failure_falls_back_without_raising(self):
        self.save("mff", False)
        with patch.dict(os.environ, _clean_env(), clear=True):
            self.assertFalse(mr.current_access().is_available("mff"))
            mr.invalidate_cache()
            broken = patch.object(mr, "_load_from_db", side_effect=RuntimeError("db down"))
            with broken:
                # bez cache → manifest; gating nikdy nespadne
                self.assertTrue(mr.current_access().is_available("mff"))
        # chybějící tabulka (DB před migrací) = žádné overridy
        engine = create_engine("sqlite://", poolclass=StaticPool)
        with patch.object(mr, "SessionLocal", sessionmaker(bind=engine)), patch.dict(os.environ, _clean_env(), clear=True):
            mr.invalidate_cache()
            self.assertTrue(mr.current_access().is_available("mff"))
        engine.dispose()


class ModuleSettingsApiTestCase(unittest.TestCase):
    def setUp(self):
        self.engine, self.Session = _session()
        self._orig = (auth_service.SessionLocal, main.SessionLocal, tools.SessionLocal, auth_service.AUTH_PIN_HASH)
        auth_service.SessionLocal = main.SessionLocal = tools.SessionLocal = self.Session
        auth_service.AUTH_PIN_HASH = ""
        self._patches = [patch.object(mr, "SessionLocal", self.Session), patch.dict(os.environ, _clean_env(), clear=True)]
        for p in self._patches:
            p.start()
        mr.invalidate_cache()
        with self.Session() as db:
            db.add(WotGrind(tank="Progetto M40 mod. 65", xp_remaining=1000, status="active"))
            db.add(WotMilestone(tank="Progetto M40 mod. 65", mastery="ace"))
            db.commit()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        mr.invalidate_cache()
        (auth_service.SessionLocal, main.SessionLocal, tools.SessionLocal, auth_service.AUTH_PIN_HASH) = self._orig
        self.engine.dispose()

    def module(self, module_id):
        return next(m for m in self.client.get("/modules").json()["modules"] if m["id"] == module_id)

    def test_get_modules_metadata(self):
        wot = self.module("wot")
        self.assertEqual({k: wot[k] for k in ("enabled", "available", "source", "locked", "implemented", "default_enabled", "depends_on")},
                         {"enabled": True, "available": True, "source": "default", "locked": False, "implemented": True,
                          "default_enabled": True, "depends_on": []})
        food = self.module("food")
        self.assertEqual((food["available"], food["implemented"]), (False, False))

    def test_disable_and_reenable_at_runtime_keeps_data(self):
        r = self.client.put("/modules/wot", json={"enabled": False})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["enabled"], r.json()["source"], r.json()["available"]), (False, "db", False))
        self.assertEqual(self.client.get("/wot/grinds").status_code, 404, "bez restartu")
        self.assertNotIn("get_wot_grinds", tool_router.all_tools_route().names, "AI tooly modulu zmizí")
        with self.Session() as db:
            self.assertEqual((db.query(WotGrind).count(), db.query(WotMilestone).count()), (1, 1), "data zůstávají")
            logs = db.query(ActivityLog).filter_by(area="system").all()
            self.assertEqual([(a.action_type, a.entity_type) for a in logs], [("module.disabled", "Module")])
        r = self.client.put("/modules/wot", json={"enabled": True})
        self.assertEqual((r.status_code, r.json()["source"], r.json()["available"]), (200, "default", True))
        self.assertEqual(self.client.get("/wot/grinds").status_code, 200)
        self.assertEqual(len(self.client.get("/wot/grinds").json()), 1)
        with self.Session() as db:
            self.assertEqual(db.query(ModuleSetting).count(), 0, "výchozí stav se do DB neukládá")

    def test_env_forced_module_is_locked_and_put_returns_409(self):
        with self.Session() as db:
            mr.save_override(db, "wot", True)  # nic (výchozí), pak DB vypnuto…
            mr.save_override(db, "wot", False)
            db.commit()
        mr.invalidate_cache()
        os.environ["MODULE_WOT_ENABLED"] = "true"  # …ale prostředí vynutí zapnuto
        wot = self.module("wot")
        self.assertEqual((wot["enabled"], wot["source"], wot["locked"]), (True, "env", True))
        r = self.client.put("/modules/wot", json={"enabled": False})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"]["module"], "wot")
        with self.Session() as db:
            self.assertEqual({s.module_id: s.enabled for s in db.query(ModuleSetting)}, {"wot": False}, "409 nic nezapsal")
            self.assertEqual(db.query(ActivityLog).filter_by(area="system").count(), 0)
        os.environ["MODULE_WOT_ENABLED"] = "nonsense"  # neplatná hodnota = žádné vynucení → platí DB
        self.assertEqual((self.module("wot")["source"], self.module("wot")["enabled"]), ("db", False))

    def test_unknown_or_unimplemented_module(self):
        self.assertEqual(self.client.put("/modules/nope", json={"enabled": True}).status_code, 404)
        self.assertEqual(self.client.put("/modules/food", json={"enabled": True}).status_code, 422)
        self.assertEqual(self.client.put("/modules/wot", json={"enabled": "yes please"}).status_code, 422)
        self.assertEqual(self.client.put("/modules/wot", json={}).status_code, 422)

    def test_every_toggle_is_audited(self):
        for enabled in (False, True, False, True):
            self.assertEqual(self.client.put("/modules/wot", json={"enabled": enabled}).status_code, 200)
        self.client.put("/modules/wot", json={"enabled": True})  # beze změny → žádný záznam
        with self.Session() as db:
            actions = [a.action_type for a in db.query(ActivityLog).filter_by(area="system").order_by(ActivityLog.id)]
        self.assertEqual(actions, ["module.disabled", "module.enabled", "module.disabled", "module.enabled"])

    def test_reset_to_default_with_null(self):
        self.client.put("/modules/mff", json={"enabled": False})
        r = self.client.put("/modules/mff", json={"enabled": None})
        self.assertEqual((r.status_code, r.json()["source"], r.json()["enabled"]), (200, "default", True))


if __name__ == "__main__":
    unittest.main()
