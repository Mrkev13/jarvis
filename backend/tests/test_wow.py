"""MRK-127: World of Warcraft – postavy ze snapshotu Blizzard API. Bez sítě: falešný transport místo requests."""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta
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
import database  # noqa: E402
import goal_history_service as ghs  # noqa: E402
import main  # noqa: E402
from database import Base  # noqa: E402
from models import ActivityLog, DomainEvent, Goal, GoalProgressHistory  # noqa: E402
from modules.wow import battlenet, integrations, service  # noqa: E402
from modules.wow.models import WowCharacter  # noqa: E402

SECRET = "s3cr3t-client-secret"
NOW = datetime(2026, 11, 23, 12, 0)

PROFILE = {
    "name": "Thrallík", "level": 42, "character_class": {"name": "Shaman"}, "race": {"name": "Orc"},
    "faction": {"type": "HORDE", "name": "Horde"}, "realm": {"name": "Pyrewood Village", "slug": "pyrewood-village"},
    "active_spec": {"name": "Enhancement"}, "equipped_item_level": 51, "last_login_timestamp": 1763900000000,
}
PROFESSIONS_RETAIL = {"primaries": [{"profession": {"name": "Mining"}, "tiers": [
    {"skill_points": 10, "max_skill_points": 100, "tier": {"name": "Old"}},
    {"skill_points": 50, "max_skill_points": 100, "tier": {"name": "Current"}}]}],
    "secondaries": [{"profession": {"name": "Fishing"}, "skill_points": 5, "max_skill_points": 300}]}
PROFESSIONS_CLASSIC = {"primaries": [{"profession": {"name": "Herbalism"}, "skill_points": 150, "max_skill_points": 225}]}


class Resp:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data if data is not None else {}
        self.content = json.dumps(self._data).encode()

    def json(self):
        return self._data


class FakeApi:
    """Blizzard: token + profil + profese. `profiles[(realm, name)]` = data nebo HTTP kód."""

    def __init__(self):
        self.profiles = {("pyrewood-village", "thrallík"): dict(PROFILE)}
        self.professions = {("pyrewood-village", "thrallík"): PROFESSIONS_RETAIL}
        self.media = {}  # MRK-139: character-media (výchozí 404 = bez obrázků)
        self.token_status = 200
        self.namespace = "profile-classic1x-eu"
        self.calls = []

    def __call__(self, method, url, **kw):
        self.calls.append((method, url, kw))
        assert kw.get("allow_redirects") is False and kw.get("timeout"), "bez přesměrování a s timeoutem"
        if url == battlenet.TOKEN_URL:
            if self.token_status != 200:
                return Resp(self.token_status)
            return Resp(200, {"access_token": "tok-123", "expires_in": 86399})
        assert url.startswith("https://eu.api.blizzard.com/profile/wow/character/"), url
        assert kw["params"]["namespace"] == self.namespace
        path = url.split("/profile/wow/character/", 1)[1]
        parts = path.split("/")
        from urllib.parse import unquote
        if self.namespace.startswith("profile-forever-"):  # MRK-130: bez realmu, /character/{jmeno-prijmeni}
            parts = ["forever"] + parts
        key = (parts[0], unquote(parts[1]))
        table = (self.media if len(parts) > 2 and parts[2] == "character-media"
                 else self.professions if len(parts) > 2 else self.profiles)
        value = table.get(key, 404)
        return Resp(value) if isinstance(value, int) else Resp(200, value)


ENV = {"BATTLENET_CLIENT_ID": "client-id", "BATTLENET_CLIENT_SECRET": SECRET, "WOW_REGION": "eu",
       "WOW_NAMESPACE": "profile-classic1x-eu"}


class WowTestBase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.api = FakeApi()
        self.clock = [NOW]
        battlenet.reset_token_cache()
        self._patches = [
            patch.dict(os.environ, ENV),
            patch.object(battlenet, "client", lambda: battlenet.Client(battlenet.load_config(), self.api)),
            patch.object(service, "utc_now", lambda: self.clock[0]),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        battlenet.reset_token_cache()
        self.engine.dispose()

    def q(self, fn):
        db = self.Session()
        try:
            out = fn(db)
            db.commit()
            return out
        finally:
            db.close()


class NormalizeTestCase(unittest.TestCase):
    def test_name_and_realm(self):
        self.assertEqual(service.normalize_name("  thrallÍK "), ("Thrallík", "thrallík"))
        self.assertEqual(service.realm_slug("Pyrewood Village"), "pyrewood-village")
        self.assertEqual(service.realm_slug("Kel'Thuzad"), "kelthuzad")
        self.assertEqual(service.realm_slug("pyrewood-village"), "pyrewood-village")
        for bad in ("a", "Thrall2", "two words", "x" * 13):
            with self.subTest(bad=bad), self.assertRaises(service.WowError):
                service.normalize_name(bad)
        for bad in ("", "  ", "Ревущий фьорд", "../etc"):
            with self.subTest(bad=bad), self.assertRaises(service.WowError):
                service.realm_slug(bad)
        self.assertEqual(service.normalize_target("60"), 60)
        with self.assertRaises(service.WowError):
            service.realm_slug("Forever")  # Forever nemá realm – chce jméno + příjmení

    def test_forever_name_and_surname(self):
        """MRK-130: „Jméno Příjmení“ / jmeno-prijmeni = WoW Forever bez realmu; jedno slovo = klasický realm."""
        for raw in ("Zareth Malgrave", "  zareth   MALGRAVE ", "zareth-malgrave"):
            with self.subTest(raw=raw):
                self.assertEqual(service.parse_character(raw, ""), ("Zareth Malgrave", "zareth-malgrave", "forever"))
        self.assertEqual(service.parse_character("Zareth Malgrave", "Pyrewood Village")[2], "forever", "realm se ignoruje")
        self.assertEqual(service.parse_character("Thrallík", "Pyrewood Village"),
                         ("Thrallík", "thrallík", "pyrewood-village"))
        for bad in ("Zareth M4lgrave", "Zareth X", "a b c", "Abcdefghijkl Abcdefghijkl", "Zareth"):
            with self.subTest(bad=bad), self.assertRaises(service.WowError):
                service.parse_character(bad, "")
        self.assertEqual(battlenet.Client._char_path("forever", "zareth-malgrave"),
                         "/profile/wow/character/zareth-malgrave")
        self.assertEqual(battlenet.Client._char_path("pyrewood-village", "thrallík"),
                         "/profile/wow/character/pyrewood-village/thrall%C3%ADk")
        self.assertIsNone(service.normalize_target(""))
        with self.assertRaises(service.WowError):
            service.normalize_target(101)

    def test_config_requires_both_keys_and_a_valid_namespace(self):
        with patch.dict(os.environ, {"BATTLENET_CLIENT_ID": "", "BATTLENET_CLIENT_SECRET": ""}):
            self.assertIsNone(battlenet.load_config())
            self.assertEqual(battlenet.config_status(), {"configured": False, "region": None, "namespace": None})
        with patch.dict(os.environ, {**ENV, "WOW_NAMESPACE": "static-eu"}):
            self.assertIsNone(battlenet.load_config(), "jen profile namespace")
        with patch.dict(os.environ, {**ENV, "WOW_NAMESPACE": "profile-classic1x-us"}):
            self.assertIsNone(battlenet.load_config(), "namespace musí patřit k regionu")
        with patch.dict(os.environ, {**ENV, "WOW_NAMESPACE": "profile-forever-eu"}):
            self.assertEqual(battlenet.load_config().namespace, "profile-forever-eu")
        with patch.dict(os.environ, {**ENV, "WOW_NAMESPACE": "profile-forever-us"}):
            self.assertIsNone(battlenet.load_config())
        with patch.dict(os.environ, ENV):
            status = battlenet.config_status()
            self.assertEqual(status, {"configured": True, "region": "eu", "namespace": "profile-classic1x-eu"})
            self.assertNotIn(SECRET, json.dumps(status))


class SyncTestCase(WowTestBase):
    def add(self, name="Thrallík", realm="Pyrewood Village", target=60):
        return self.q(lambda db: service.add_character(db, name, realm, target))

    def test_add_loads_the_snapshot(self):
        out = self.add()
        self.assertEqual(out["result"], "ok")
        c = out["character"]
        self.assertEqual((c["name"], c["level"], c["class_name"], c["race_name"], c["faction"], c["item_level"]),
                         ("Thrallík", 42, "Shaman", "Orc", "Horde", 51))
        self.assertEqual((c["realm_name"], c["levels_to_go"], c["at_target"], c["sync_status"]),
                         ("Pyrewood Village", 18, False, "ok"))
        self.assertEqual(c["professions"], [{"name": "Mining", "skill": 50, "max": 100, "secondary": False},
                                            {"name": "Fishing", "skill": 5, "max": 300, "secondary": True}])
        self.assertEqual(c["last_synced_at"], NOW.isoformat() + "Z")
        token_calls = [c for c in self.api.calls if c[1] == battlenet.TOKEN_URL]
        self.assertEqual(len(token_calls), 1)
        self.assertEqual(token_calls[0][2]["auth"], ("client-id", SECRET))
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).filter_by(area="wow", action_type="create").count()), 1)

    def test_classic_professions_and_missing_item_level(self):
        profile = dict(PROFILE)
        profile.pop("equipped_item_level")
        self.api.profiles[("pyrewood-village", "thrallík")] = profile
        self.api.professions[("pyrewood-village", "thrallík")] = PROFESSIONS_CLASSIC
        c = self.add()["character"]
        self.assertIsNone(c["item_level"])
        self.assertEqual(c["professions"], [{"name": "Herbalism", "skill": 150, "max": 225, "secondary": False}])

    def test_unknown_character_and_duplicates(self):
        out = self.add(name="Nobody")
        self.assertEqual((out["result"], out["character"]["sync_status"]), ("not_found", "not_found"))
        self.assertIn("nenalezena", out["message"])
        self.add()
        with self.assertRaises(service.WowError) as err:
            self.add(name="thrallík", realm="pyrewood village")
        self.assertEqual(err.exception.status, 409)

    def test_api_outage_keeps_the_last_known_state(self):
        self.add()
        self.api.profiles[("pyrewood-village", "thrallík")] = 503
        self.clock[0] = NOW + timedelta(hours=7)
        out = self.q(lambda db: service.sync_one(db, 1))
        self.assertEqual(out["result"], "unavailable")
        c = out["character"]
        self.assertEqual((c["level"], c["sync_status"], c["last_synced_at"]), (42, "error", NOW.isoformat() + "Z"))

    def test_bad_keys_are_reported_without_secrets(self):
        self.api.token_status = 401
        out = self.add()
        self.assertEqual(out["result"], "unauthorized")
        self.assertNotIn(SECRET, json.dumps(out))
        self.assertNotIn("tok-123", json.dumps(out))

    def test_level_up_emits_one_event_and_refreshes_goals(self):
        self.add()
        self.q(lambda db: db.add(Goal(title="Shaman na 60", area="wow", tracking_type="automatic",
                                      source=service.GOAL_MAX_LEVEL, target_value=60, status="active")))
        self.api.profiles[("pyrewood-village", "thrallík")] = {**PROFILE, "level": 45}
        self.clock[0] = NOW + timedelta(hours=7)
        self.assertEqual(self.q(lambda db: service.sync_one(db, 1))["character"]["level"], 45)
        self.q(lambda db: service.sync_one(db, 1))  # stejný level → žádná další událost
        events = self.q(lambda db: [(e.event_type, dict(e.payload)) for e in db.query(DomainEvent).all()])
        self.assertEqual(events, [("wow.character.level_up",
                                   {"character_id": 1, "level": 45, "previous_level": 42, "target_level": 60})])
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).filter_by(action_type="level_up").one().summary),
                         "Thrallík – level 45 (cíl 60)")
        last = self.q(lambda db: [(h.current_value, h.progress) for h in
                                  db.query(GoalProgressHistory).order_by(GoalProgressHistory.id.desc()).limit(1)])
        self.assertEqual(last, [(45.0, 75)])

    def test_concurrent_syncs_emit_one_level_up(self):
        """Codex review #91: hodinový krok a ruční obnova načtou stejný snapshot (42) – level_up jen jednou."""
        self.add()
        self.api.profiles[("pyrewood-village", "thrallík")] = {**PROFILE, "level": 43}
        a, b = self.Session(), self.Session()
        try:
            ca, cb = a.get(WowCharacter, 1), b.get(WowCharacter, 1)
            self.assertEqual((ca.level, cb.level), (42, 42))
            client = battlenet.client()
            self.assertEqual(service.sync_character(a, ca, client), "ok")
            a.commit()
            self.assertEqual(service.sync_character(b, cb, client), "ok")
            b.commit()
        finally:
            a.close()
            b.close()
        events = self.q(lambda db: db.query(DomainEvent).filter_by(event_type="wow.character.level_up").count())
        self.assertEqual(events, 1)
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).filter_by(action_type="level_up").count()), 1)

    def test_losing_sync_does_not_overwrite_the_winner_with_an_older_answer(self):
        """Codex review #91 (2. kolo): A uloží 43, B má starší odpověď 42 – B ji zahodí; další sync 43 nic nezopakuje."""
        self.add()
        a, b = self.Session(), self.Session()
        try:
            ca, cb = a.get(WowCharacter, 1), b.get(WowCharacter, 1)
            self.api.profiles[("pyrewood-village", "thrallík")] = {**PROFILE, "level": 43, "equipped_item_level": 60}
            self.assertEqual(service.sync_character(a, ca, battlenet.client()), "ok")
            a.commit()
            self.api.profiles[("pyrewood-village", "thrallík")] = {**PROFILE, "level": 42}  # starší odpověď pro B
            self.assertEqual(service.sync_character(b, cb, battlenet.client()), "ok")
            b.commit()
        finally:
            a.close()
            b.close()
        state = self.q(lambda db: (lambda c: (c.level, c.item_level))(db.get(WowCharacter, 1)))
        self.assertEqual(state, (43, 60), "vítězný snapshot zůstal")
        self.api.profiles[("pyrewood-village", "thrallík")] = {**PROFILE, "level": 43, "equipped_item_level": 60}
        self.q(lambda db: service.sync_one(db, 1))
        self.assertEqual(self.q(lambda db: db.query(DomainEvent).count()), 1, "žádná druhá událost 42→43")
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).filter_by(action_type="sync").count()), 1,
                         "jen vítězova změna item levelu")

    def test_snapshot_changes_without_level_up_are_audited(self):
        """Codex review #91: item level / profese / pokles levelu = řádek Aktivity s deltou; beze změny nic."""
        self.add()
        self.api.profiles[("pyrewood-village", "thrallík")] = {**PROFILE, "equipped_item_level": 90}
        self.q(lambda db: service.sync_one(db, 1))
        rows = self.q(lambda db: [(a.action_type, a.summary, json.loads(a.delta_json))
                                  for a in db.query(ActivityLog).filter_by(action_type="sync").all()])
        self.assertEqual(rows, [("sync", "WoW Thrallík: údaje z Blizzard API (item level 51 → 90)",
                                 {"item_level": {"old": 51, "new": 90}})])
        self.q(lambda db: service.sync_one(db, 1))  # stejná data
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).filter_by(action_type="sync").count()), 1)
        self.api.profiles[("pyrewood-village", "thrallík")] = {**PROFILE, "level": 40, "equipped_item_level": 90}
        self.q(lambda db: service.sync_one(db, 1))
        last = self.q(lambda db: json.loads(db.query(ActivityLog).filter_by(action_type="sync")
                                            .order_by(ActivityLog.id.desc()).first().delta_json))
        self.assertEqual(last, {"level": {"old": 42, "new": 40}})
        self.assertEqual(self.q(lambda db: db.query(DomainEvent).count()), 0, "pokles levelu není level_up")

    def test_level_up_with_other_changes_logs_both(self):
        self.add()
        self.api.profiles[("pyrewood-village", "thrallík")] = {**PROFILE, "level": 44, "equipped_item_level": 60}
        self.q(lambda db: service.sync_one(db, 1))
        acts = self.q(lambda db: {a.action_type: json.loads(a.delta_json) for a in db.query(ActivityLog)
                                  .filter(ActivityLog.action_type.in_(["sync", "level_up"])).all()})
        self.assertEqual(acts, {"level_up": {"level": {"old": 42, "new": 44}},
                                "sync": {"item_level": {"old": 51, "new": 60}}})

    def test_goal_sources(self):
        self.add()
        self.api.profiles[("pyrewood-village", "garrosh")] = {**PROFILE, "name": "Garrosh", "level": 60}
        self.add(name="Garrosh", target=60)
        self.add(name="Rexxar", target=None)  # nenalezen
        values = self.q(lambda db: {s: ghs.compute_automatic_goal_current_value_with_ok(db, s)
                                    for s in service.GOAL_SOURCES})
        self.assertEqual(values, {service.GOAL_AT_TARGET: (1.0, True), service.GOAL_MAX_LEVEL: (60.0, True)})

    def test_hourly_sync_is_bounded_and_idle_without_keys(self):
        for i, n in enumerate("Aaa Bbb Ccc Ddd Eee Fff Ggg Hhh Iii Jjj Kkk Lll".split()):
            self.api.profiles[("pyrewood-village", n.lower())] = {**PROFILE, "name": n, "level": 10 + i}
            self.add(name=n, target=None)
        self.api.calls.clear()
        self.assertEqual(self.q(integrations.hourly_sync)["synced"], 0, "čerstvé postavy se znovu nenačítají")
        self.clock[0] = NOW + timedelta(hours=7)
        out = self.q(integrations.hourly_sync)
        self.assertEqual(out["synced"], service.SYNC_BATCH)
        self.assertEqual((out["due"], out["remaining"]), (12, 2), "kolik zbylo na další běh")
        with patch.object(battlenet, "client", lambda: None):
            self.assertEqual(self.q(integrations.hourly_sync), {"synced": 0, "skipped": "not_configured"})

    def test_rate_limit_stops_the_batch(self):
        self.add()
        self.add(name="Garrosh", target=None)
        self.api.profiles = {k: 429 for k in [("pyrewood-village", "thrallík"), ("pyrewood-village", "garrosh")]}
        self.clock[0] = NOW + timedelta(hours=7)
        self.assertEqual(self.q(lambda db: service.sync_due(db))["results"], {"rate_limited": 1})

    def test_target_and_delete_write_activity(self):
        self.add()
        self.assertEqual(self.q(lambda db: service.set_target(db, 1, 42))["at_target"], True)
        self.q(lambda db: service.delete_character(db, 1))
        acts = self.q(lambda db: [a.action_type for a in db.query(ActivityLog).filter_by(area="wow").order_by(ActivityLog.id)])
        self.assertEqual(acts, ["create", "update", "delete"])
        self.assertEqual(self.q(lambda db: db.query(WowCharacter).count()), 0)

    def test_search_and_context(self):
        self.add()
        rows = self.q(lambda db: list(integrations.search_characters(db, "thrall")))
        self.assertEqual(rows[0][:3], ("wow_character", 1, "Thrallík"))
        self.assertEqual(rows[0][6], "/wow?wowchar=1")
        self.assertIn("level 42", rows[0][3])
        lines = self.q(lambda db: integrations.context_wow(type("R", (), {"db": db})()))
        self.assertTrue(lines[0].startswith("WoW postavy: Thrallík Shaman lvl 42/60"), lines)


class ForeverTestCase(WowTestBase):
    """MRK-130: WoW Forever – namespace profile-forever-eu, postava jméno + příjmení bez realmu."""

    FOREVER = {"name": "Zareth", "surname": "Malgrave", "level": 23, "character_class": {"name": "Warlock"},
               "race": {"name": "Undead"}, "faction": {"name": "Horde"}, "ruleset": {"name": "Normal"},
               "last_login_timestamp": 1763900000000}

    def setUp(self):
        super().setUp()
        p = patch.dict(os.environ, {"WOW_NAMESPACE": "profile-forever-eu"})
        p.start()
        self._patches.append(p)
        self.api.namespace = "profile-forever-eu"
        self.api.profiles = {("forever", "zareth-malgrave"): dict(self.FOREVER)}
        self.api.professions = {("forever", "zareth-malgrave"): PROFESSIONS_CLASSIC}

    def test_add_forever_character(self):
        out = self.q(lambda db: service.add_character(db, "zareth malgrave", "", 60))
        self.assertEqual(out["result"], "ok", out)
        c = out["character"]
        self.assertEqual((c["name"], c["realm_slug"], c["realm_name"], c["level"], c["class_name"], c["levels_to_go"]),
                         ("Zareth Malgrave", "forever", "Forever · Normal", 23, "Warlock", 37))
        self.assertEqual(c["professions"], [{"name": "Herbalism", "skill": 150, "max": 225, "secondary": False}])
        urls = [u for _m, u, _kw in self.api.calls if u != battlenet.TOKEN_URL]
        self.assertEqual(urls, ["https://eu.api.blizzard.com/profile/wow/character/zareth-malgrave",
                                "https://eu.api.blizzard.com/profile/wow/character/zareth-malgrave/professions",
                                "https://eu.api.blizzard.com/profile/wow/character/zareth-malgrave/character-media"])
        with self.assertRaises(service.WowError) as err:
            self.q(lambda db: service.add_character(db, "Zareth-Malgrave", "", None))
        self.assertEqual(err.exception.status, 409)

    def test_ruleset_as_string_and_level_up(self):
        self.api.profiles[("forever", "zareth-malgrave")] = {**self.FOREVER, "ruleset": "PvP"}
        self.q(lambda db: service.add_character(db, "Zareth Malgrave", "", None))
        self.api.profiles[("forever", "zareth-malgrave")] = {**self.FOREVER, "ruleset": "PvP", "level": 24}
        c = self.q(lambda db: service.sync_one(db, 1))["character"]
        self.assertEqual((c["realm_name"], c["level"]), ("Forever · PvP", 24))
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).filter_by(action_type="level_up").one().summary),
                         "Zareth Malgrave – level 24")

    def test_not_found_explains_forever_visibility(self):
        out = self.q(lambda db: service.add_character(db, "Nobody Here", "", None))
        self.assertEqual(out["result"], "not_found")
        self.assertIn("od levelu 10", out["message"])

    def test_check_script_tries_the_forever_namespace(self):
        import io
        from contextlib import redirect_stdout

        sys.path.insert(0, os.path.join(BACKEND_DIR, "scripts"))
        import check_battlenet

        api = self.api

        def transport(method, url, **kw):
            if "/collections/" in url or "/achievements/" in url:
                return Resp(404)
            return api(method, url, **kw)

        out = io.StringIO()
        with patch.object(battlenet.requests, "request", transport), redirect_stdout(out):
            code = check_battlenet.main(["--name", "Zareth Malgrave"])
        text = out.getvalue()
        self.assertEqual(code, 0, text)
        self.assertIn("profile-forever-eu: postava 200 · pole level, character_class, race, last_login_timestamp, "
                      "surname, ruleset · profese 200", text)
        self.assertIn("DOPORUČENÍ: WOW_NAMESPACE=profile-forever-eu", text)
        self.assertNotIn("profile-classic1x-eu", text, "Forever postava nezkouší realmové namespace")
        for secret in (SECRET, "tok-123", "Zareth", "zareth", "Malgrave", "malgrave"):
            self.assertNotIn(secret, text)


class MediaTestCase(WowTestBase):
    """MRK-139: hrdinské karty – avatar a celý render z character-media, jen oficiální hosty Blizzardu."""

    MEDIA = {"assets": [
        {"key": "avatar", "value": "https://render.worldofwarcraft.com/eu/character/pyrewood-village/1/2-avatar.jpg"},
        {"key": "inset", "value": "https://render.worldofwarcraft.com/eu/character/pyrewood-village/1/2-inset.jpg"},
        {"key": "main-raw", "value": "https://render.worldofwarcraft.com/eu/character/pyrewood-village/1/2-main-raw.png"},
    ]}

    def add(self):
        return self.q(lambda db: service.add_character(db, "Thrallík", "Pyrewood Village", 60))

    def test_media_urls_are_stored(self):
        self.api.media[("pyrewood-village", "thrallík")] = self.MEDIA
        c = self.add()["character"]
        self.assertEqual(c["avatar_url"], self.MEDIA["assets"][0]["value"])
        self.assertEqual(c["render_url"], self.MEDIA["assets"][2]["value"], "main-raw má přednost (průhledné pozadí)")
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).filter_by(action_type="sync").count()), 0,
                         "obrázky nejsou změna snapshotu pro Aktivitu")

    def test_missing_media_keeps_the_sync_and_old_urls(self):
        self.api.media[("pyrewood-village", "thrallík")] = self.MEDIA
        self.add()
        self.api.media[("pyrewood-village", "thrallík")] = 503
        out = self.q(lambda db: service.sync_one(db, 1))
        self.assertEqual(out["result"], "ok", "výpadek obrázků nesmí shodit synchronizaci")
        self.assertTrue(out["character"]["render_url"].endswith("main-raw.png"), "zůstanou poslední známé")

    def test_only_official_render_hosts(self):
        bad = {"assets": [
            {"key": "avatar", "value": "http://render.worldofwarcraft.com/eu/a.jpg"},
            {"key": "main-raw", "value": "https://evil.example.com/x.png"},
            {"key": "main", "value": "https://render.worldofwarcraft.com.evil.io/x.jpg"},
            {"key": "inset", "value": "https://render.worldofwarcraft.com/eu/x.jpg?track=1"},
        ]}
        self.assertEqual(service.parse_media(bad), (None, None))
        self.assertEqual(service.parse_media(None), (None, None))
        self.assertEqual(service.parse_media({"assets": [{"key": "main", "value": "https://render-eu.worldofwarcraft.com/a/b-main.jpg"}]}),
                         (None, "https://render-eu.worldofwarcraft.com/a/b-main.jpg"))


class CheckScriptTestCase(WowTestBase):
    def test_prints_only_states_and_recommends_the_namespace(self):
        import io
        from contextlib import redirect_stdout

        sys.path.insert(0, os.path.join(BACKEND_DIR, "scripts"))
        import check_battlenet

        api = self.api

        def transport(method, url, **kw):
            if url != battlenet.TOKEN_URL and kw["params"]["namespace"] != "profile-classic1x-eu":
                return Resp(404)  # jiné verze hry postavu neznají
            if "/collections/" in url or "/achievements/" in url:
                return Resp(404)
            return api(method, url, **kw)

        out = io.StringIO()
        with patch.object(battlenet.requests, "request", transport), redirect_stdout(out):
            code = check_battlenet.main(["--realm", "Pyrewood Village", "--name", "Thrallík"])
        text = out.getvalue()
        self.assertEqual(code, 0, text)
        self.assertIn("TOKEN: ok", text)
        self.assertIn("profile-eu: postava 404", text)
        self.assertIn("profile-classic1x-eu: postava 200 · pole level, character_class, race, equipped_item_level", text)
        self.assertIn("profese 200 · mounty 404", text)
        self.assertIn("DOPORUČENÍ: WOW_NAMESPACE=profile-classic1x-eu", text)
        for secret in (SECRET, "tok-123", "Thrallík", "thrallík", "Pyrewood", "pyrewood"):
            self.assertNotIn(secret, text)


class ApiTestCase(WowTestBase):
    def setUp(self):
        super().setUp()
        self._api_patches = [
            patch.object(main, "SessionLocal", self.Session),
            patch.object(database, "SessionLocal", self.Session),
            patch.object(auth_service, "SessionLocal", self.Session),
            patch.object(auth_service, "_failed_attempts", {}),
            patch.object(auth_service, "AUTH_PIN_HASH", bcrypt.hashpw(b"4821", bcrypt.gensalt(rounds=4)).decode()),
        ]
        for p in self._api_patches:
            p.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self._api_patches:
            p.stop()
        super().tearDown()

    def test_requires_session(self):
        self.assertEqual(self.client.get("/wow").status_code, 401)

    def test_rest_round_trip(self):
        self.assertEqual(self.client.post("/auth/login", json={"pin": "4821"}).status_code, 200)
        overview = self.client.get("/wow").json()
        self.assertEqual(overview["config"]["configured"], True)
        self.assertEqual(overview["characters"], [])
        r = self.client.post("/wow/characters", json={"name": "Thrallík", "realm": "Pyrewood Village", "target_level": 60})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["result"], "ok")
        self.assertEqual(self.client.post("/wow/characters", json={"name": "x", "realm": "y"}).status_code, 400)
        self.assertEqual(self.client.patch("/wow/characters/1", json={"target_level": 40}).json()["at_target"], True)
        self.assertEqual(self.client.post("/wow/characters/1/refresh").json()["result"], "ok")
        self.assertEqual(self.client.post("/wow/refresh").json()["synced"], 1)
        self.assertEqual(self.client.get("/wow").json()["summary"],
                         {"characters": 1, "max_level": 42, "with_target": 1, "at_target": 1})
        self.assertEqual(self.client.delete("/wow/characters/1").json(), {"ok": True})
        self.assertEqual(self.client.delete("/wow/characters/1").status_code, 404)
        self.assertNotIn(SECRET, self.client.get("/wow").text)


if __name__ == "__main__":
    unittest.main()
