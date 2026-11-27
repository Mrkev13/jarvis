"""MRK-106: tabulka M-ek z Wargaming API – klient (falešný transport, nikdy síť), výchozí stav bez milníků, nové M =
milník „čeká na replay“ + událost, souběh, párování replaye, AI dotaz, REST, bezpečnost (application_id nikde)."""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("GROQ_API_KEY", "x")
TESTS_DIR = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(TESTS_DIR, ".."))
for p in (BACKEND_DIR, TESTS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import database  # noqa: E402
import goal_history_service as ghs  # noqa: E402
import replay_fixtures as fx  # noqa: E402
import wot_integrations  # noqa: E402
import wot_mastery_service as svc  # noqa: E402
import wot_replay_service as wrs  # noqa: E402
import wot_wargaming as wg  # noqa: E402
from models import ActivityLog, DomainEvent, WotMilestone, WotVehicleMastery  # noqa: E402
from test_wot_milestones import WotBase  # noqa: E402

APP_ID = "0123456789abcdef0123456789abcdef"
ACCOUNT = 500123
ENV = {"WG_APPLICATION_ID": APP_ID, "WG_REGION": "eu", "WOT_NICKNAME": "tester_1"}
NOW = datetime(2026, 9, 14, 20, 0)
VEHICLES = {
    1: {"tank_id": 1, "name": "Progetto M35 mod. 46", "short_name": "Progetto 46", "tag": "It13_Progetto_M35_mod_46",
        "tier": 8, "nation": "italy", "type": "mediumTank"},
    2: {"tank_id": 2, "name": "Object 279 (e)", "short_name": "Obj. 279 (e)", "tag": "R157_Object_279R", "tier": 10,
        "nation": "ussr", "type": "heavyTank"},
    3: {"tank_id": 3, "name": "IS-3", "short_name": "IS-3", "tag": "R41_IS-3", "tier": 8, "nation": "ussr",
        "type": "heavyTank"},
}


class Resp:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data
        self.content = json.dumps(data).encode()

    def json(self):
        return self._data


class FakeWg:
    def __init__(self):
        self.marks = {1: 3, 2: 4, 3: 0}
        self.battles = {1: 120, 2: 300, 3: 15}
        self.error = None
        self.private = False
        self.calls = []

    def __call__(self, method, url, **kw):
        self.calls.append((url, kw))
        assert kw.get("allow_redirects") is False and kw.get("timeout"), "bez přesměrování, s timeoutem"
        assert url.startswith("https://api.worldoftanks.eu/wot/"), url
        assert kw["params"]["application_id"] == APP_ID
        if self.error:
            return Resp(200, {"status": "error", "error": {"code": 407, "message": self.error}})
        method_path = url.split("/wot/", 1)[1].rstrip("/")
        if method_path == "account/list":
            assert kw["params"]["type"] == "exact"
            return Resp(200, {"status": "ok", "data": [{"account_id": ACCOUNT, "nickname": "Tester_1"}]})
        if method_path == "tanks/stats":
            rows = None if self.private else [
                {"tank_id": t, "mark_of_mastery": m, "all": {"battles": self.battles[t]}} for t, m in self.marks.items()]
            return Resp(200, {"status": "ok", "data": {str(ACCOUNT): rows}})
        if method_path == "encyclopedia/vehicles":
            ids = [int(x) for x in kw["params"]["tank_id"].split(",")]
            return Resp(200, {"status": "ok", "data": {str(i): VEHICLES.get(i) for i in ids}})
        raise AssertionError(method_path)


class MasteryBase(WotBase):
    def setUp(self):
        super().setUp()
        self.api = FakeWg()
        self.clock = [NOW]
        self._mp = [
            patch.dict(os.environ, ENV),
            patch.object(wg, "client", lambda: wg.Client(wg.load_config(), self.api)),
            patch.object(svc, "utc_now", lambda: self.clock[0]),
            patch.object(database, "SessionLocal", self.Session),
        ]
        for p in self._mp:
            p.start()

    def tearDown(self):
        for p in self._mp:
            p.stop()
        super().tearDown()

    def sync(self, force=True):
        def go(db):
            out = svc.sync(db, wg.client(), now=self.clock[0], force=force)
            db.commit()
            return out
        return self.q(go)

    def aces_events(self):
        return self.q(lambda db: db.query(DomainEvent).filter_by(event_type=svc.ACE_EVENT).count())


class ClientTestCase(MasteryBase):
    def test_config_needs_all_three_values(self):
        self.assertIsNotNone(wg.load_config())
        for key, bad in (("WG_APPLICATION_ID", "not-hex!"), ("WOT_NICKNAME", "a b"), ("WG_REGION", "mars")):
            with self.subTest(key=key), patch.dict(os.environ, {key: bad}):
                self.assertIsNone(wg.load_config())
        self.assertEqual(wg.config_status(), {"configured": True, "region": "eu"})

    def test_api_errors_are_codes_only(self):
        for message, code in (("INVALID_APPLICATION_ID", "unauthorized"), ("REQUEST_LIMIT_EXCEEDED", "rate_limited"),
                              ("SOMETHING_NEW", "invalid_response")):
            with self.subTest(message=message):
                self.api.error = message
                self.assertEqual(self.sync()["result"], code)
        self.api.error = None
        self.api.private = True
        self.assertEqual(self.sync()["result"], "private")
        self.assertEqual(self.q(lambda db: db.query(WotVehicleMastery).count()), 0)

    def test_no_keys_does_nothing(self):
        self.assertEqual(self.q(lambda db: svc.sync(db, None)), {"result": "not_configured"})


class SyncTestCase(MasteryBase):
    def test_first_sync_is_baseline_without_milestones(self):
        out = self.sync()
        self.assertEqual((out["result"], out["tanks"], out["new_aces"], out["baseline"]), ("ok", 3, 0, True))
        rows = self.q(lambda db: {r.tank_id: (r.name, r.tier, r.mark_of_mastery, r.tag) for r in db.query(WotVehicleMastery)})
        self.assertEqual(rows[2], ("Object 279 (e)", 10, 4, "R157_Object_279R"))
        self.assertEqual(self.q(lambda db: db.query(WotMilestone).count()), 0, "stará M nemají datum – nic se nezakládá")
        self.assertEqual(self.aces_events(), 0)

    def test_new_ace_creates_pending_milestone_event_and_counts_for_goal(self):
        self.sync()
        self.clock[0] += timedelta(hours=7)
        self.api.marks[1] = 4
        out = self.sync(force=False)
        self.assertEqual(out["new_aces"], 1)
        m = self.q(lambda db: db.query(WotMilestone).one())
        self.assertEqual((m.tank, m.mastery, m.source, m.notes), ("Progetto M35 mod. 46", "ace", "api", svc.PENDING_NOTE))
        self.assertEqual(self.aces_events(), 1)
        ov = self.q(svc.overview)
        progetto = next(t for t in ov["tanks"] if t["tank_id"] == 1)
        self.assertEqual((progetto["mark_label"], progetto["pending_replay"], progetto["ace_count"]), ("M", True, 1))
        self.assertEqual(ov["summary"]["pending_replays"], 1)
        value = self.q(lambda db: ghs.compute_automatic_goal_current_value_with_ok(db, ghs.WOT_ACE_MASTERY_SOURCE))
        self.assertEqual(value, (1.0, True), "cíl „M-ka celkem“ ho započítá")
        self.sync()
        self.assertEqual(self.aces_events(), 1, "další sync nové M nezopakuje")

    def test_new_tank_played_straight_to_ace(self):
        self.sync()
        self.api.marks[4] = 4
        self.api.battles[4] = 1
        VEHICLES[4] = {"tank_id": 4, "name": "T-34", "short_name": "T-34", "tag": "R04_T-34", "tier": 5, "nation": "ussr",
                       "type": "mediumTank"}
        try:
            self.assertEqual(self.sync()["new_aces"], 1)
        finally:
            del VEHICLES[4]

    def test_hourly_throttle(self):
        """MRK-146: hodinový krok načte odznaky každou hodinu; do 50 min od posledního načtení se nevolá."""
        self.sync()
        self.clock[0] += timedelta(minutes=30)
        self.assertEqual(self.sync(force=False), {"result": "skipped"})
        self.clock[0] += timedelta(minutes=30)
        self.assertEqual(self.sync(force=False)["result"], "ok")

    def test_hourly_step_uses_the_integration(self):
        out = self.q(lambda db: wot_integrations.hourly_mastery(db))
        self.assertEqual(out["result"], "ok")

    def test_concurrent_transition_records_one_milestone(self):
        self.sync()
        self.api.marks[1] = 4
        # druhý běh přepne odznak dřív (commitne), první pak podmíněný update prohraje
        db1 = self.Session()
        try:
            list(db1.query(WotVehicleMastery).all())  # načtený stav 3
            self.sync()
            out = svc.sync(db1, wg.client(), now=self.clock[0], force=True)
            db1.commit()
        finally:
            db1.close()
        self.assertEqual(out["new_aces"], 0)
        self.assertEqual(self.q(lambda db: db.query(WotMilestone).count()), 1)

    def test_activity_only_when_something_changed(self):
        self.sync()
        self.sync()
        rows = self.q(lambda db: db.query(ActivityLog).filter_by(entity_type="wot_vehicle_mastery").count())
        self.assertEqual(rows, 1)


class PairingTestCase(MasteryBase):
    def pending_progetto(self, detected=NOW):
        self.sync()
        self.clock[0] = detected
        self.api.marks[1] = 4
        self.sync()

    def upload(self, data=fx.PROGETTO):
        def go(db):
            r = wrs.upload_replay(db, data, "x.wotreplay", tank_name="Progetto M35 mod. 46")
            db.commit()
            return r.id, r.linked_milestone_id
        return self.q(go)

    def test_replay_fills_pending_milestone_by_tag(self):
        self.pending_progetto()
        rid, linked = self.upload()
        m = self.q(lambda db: db.query(WotMilestone).one())
        self.assertEqual(linked, m.id)
        self.assertEqual((m.map_name, m.damage, m.kills, m.played_on.isoformat(), m.notes),
                         ("Útesy", 5205, 5, "2026-09-14", None))
        self.assertFalse(self.q(lambda db: svc.overview(db)["summary"]["pending_replays"]))

    def test_later_battle_is_a_repeated_ace_not_paired(self):
        self.pending_progetto(detected=NOW - timedelta(days=5))
        _, linked = self.upload()
        self.assertIsNone(linked)

    def test_create_milestone_from_replay_reuses_pending(self):
        self.sync()
        rid, _ = self.upload()  # nahráno PŘED detekcí – zatím nic k párování
        self.api.marks[1] = 4
        self.sync()
        def go(db):
            r, m = wrs.create_milestone_from_replay(db, rid)
            db.commit()
            return m.id
        mid = self.q(go)
        self.assertEqual(self.q(lambda db: db.query(WotMilestone).count()), 1, "žádná duplicita")
        self.assertEqual(self.q(lambda db: db.get(WotMilestone, mid).damage), 5205)


class ReplayFirstTestCase(MasteryBase):
    """Codex review #116: pořadí replay → „Vytvořit Mko z replaye“ → teprve pak API detekce (6h interval)."""

    upload = PairingTestCase.upload

    def test_api_detection_reuses_the_ace_already_recorded_from_a_replay(self):
        self.clock[0] = NOW - timedelta(hours=7)
        self.sync()                       # výchozí stav: Progetto má I (3)
        self.clock[0] = NOW
        rid, _ = self.upload()            # bitva 2026-09-14 18:15 UTC, M
        def make(db):
            r, m = wrs.create_milestone_from_replay(db, rid)
            db.commit()
            return m.id
        mid = self.q(make)
        self.clock[0] = NOW + timedelta(hours=1)
        self.api.marks[1] = 4
        out = self.sync()
        self.assertEqual(out["new_aces"], 1)
        self.assertEqual(self.q(lambda db: db.query(WotMilestone).count()), 1, "žádný druhý milník za stejnou bitvu")
        row = self.q(lambda db: db.query(WotVehicleMastery).filter_by(tank_id=1).one())
        self.assertEqual(row.ace_milestone_id, mid, "API řádek se připojí k existujícímu M")
        self.assertEqual(self.aces_events(), 0, "nic nového se nezískalo – M už je zapsané")
        ov = self.q(svc.overview)
        self.assertEqual(ov["summary"]["pending_replays"], 0)
        self.assertEqual(self.q(lambda db: ghs.compute_automatic_goal_current_value_with_ok(db, ghs.WOT_ACE_MASTERY_SOURCE)),
                         (1.0, True), "cíl M-ka celkem jen jednou")

    def test_older_manual_ace_does_not_swallow_a_new_one(self):
        # ruční M z doby PŘED minulou synchronizací (kdy API ještě M nehlásilo) není tahle bitva
        self.clock[0] = NOW - timedelta(days=3)
        self.sync()
        def old(db):
            import wot_service
            wot_service.create_milestone(db, {"tank": "Progetto M35 mod. 46", "mastery": "ace", "played_on": "2026-09-10"})
            db.commit()
        self.q(old)
        self.clock[0] = NOW
        self.sync()                       # mezitím další sync (odznak beze změny)
        self.clock[0] = NOW + timedelta(hours=7)
        self.api.marks[1] = 4
        self.sync()
        self.assertEqual(self.q(lambda db: db.query(WotMilestone).count()), 2)
        self.assertEqual(self.aces_events(), 1)


class QueryAndApiTestCase(MasteryBase):
    def test_ai_query_is_computed(self):
        self.sync()
        out = self.q(lambda db: svc.query(db, tier=8, mastery="without_ace"))
        self.assertEqual([i["name"] for i in out["items"]], ["Progetto M35 mod. 46", "IS-3"])
        self.assertEqual(out["matching"], 2)
        ussr = self.q(lambda db: svc.query(db, nation="SSSR"))
        self.assertEqual({i["name"] for i in ussr["items"]}, {"Object 279 (e)", "IS-3"})
        lines = self.q(lambda db: wot_integrations.context_mastery(type("R", (), {"db": db})()))
        self.assertIn("3 tanků, M 1, I 1", lines[0])

    def test_rest_and_no_secrets(self):
        self.login()
        r = self.client.post("/wot/mastery/refresh")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["result"], "ok")
        body = self.client.get("/wot/mastery").text
        self.assertIn("Object 279 (e)", body)
        for secret in (APP_ID, str(ACCOUNT), "tester_1", "Tester_1"):
            self.assertNotIn(secret, body)
        acts = self.q(lambda db: " ".join(f"{a.summary} {a.delta_json}" for a in db.query(ActivityLog)))
        self.assertNotIn(APP_ID, acts)


if __name__ == "__main__":
    unittest.main()
