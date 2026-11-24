"""MRK-128: WoW sbírky – denní snapshot počtů, vývoj za týden, seznam „chci získat“ s automatickým odškrtnutím.
Bez sítě: falešný transport z test_wow (FakeApi.collections)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

sys.path.insert(0, os.path.dirname(__file__))

import test_wow  # noqa: E402

from models import ActivityLog, DomainEvent  # noqa: E402
from module_contracts import ContextRequest  # noqa: E402
from modules.wow import battlenet, collections, integrations, service  # noqa: E402
from modules.wow.models import WowCollectionSnapshot, WowWish  # noqa: E402

KEY = ("pyrewood-village", "thrallík")


def mounts(*names):
    return {"mounts": [{"mount": {"name": n, "id": i}, "is_useable": True} for i, n in enumerate(names, 1)]}


def pets(*names):
    return {"pets": [{"species": {"name": n, "id": i}, "level": 1, "id": i} for i, n in enumerate(names, 1)]}


def achievements(points, done=(), open_=()):
    items = [{"id": i, "achievement": {"name": n, "id": i}, "completed_timestamp": 1763900000000}
             for i, n in enumerate(done, 1)]
    items += [{"id": 100 + i, "achievement": {"name": n, "id": 100 + i}, "criteria": {"is_completed": False}}
              for i, n in enumerate(open_, 1)]
    return {"total_quantity": len(items), "total_points": points, "achievements": items}


class CollectionsBase(test_wow.WowTestBase):
    def setUp(self):
        super().setUp()
        self._col_patch = patch.object(collections, "utc_now", lambda: self.clock[0])
        self._col_patch.start()
        self.q(lambda db: service.add_character(db, "Thrallík", "Pyrewood Village", 60))
        self.set_api(mounts("Swift Brown Steed", "Black Stallion"), pets("Mechanical Squirrel"),
                     achievements(120, done=("Level 10", "Level 20"), open_=("Level 60",)))

    def tearDown(self):
        self._col_patch.stop()
        super().tearDown()

    def set_api(self, m=None, p=None, a=None):
        for what, value in (("mounts", m), ("pets", p), ("achievements", a)):
            if value is not None:
                self.api.collections[KEY + (what,)] = value

    def sync(self, force=False):
        return self.q(lambda db: collections.sync_collections(db, battlenet.client(), now=self.clock[0], force=force))

    def overview(self):
        return self.q(lambda db: collections.overview(db, self.clock[0]))

    def events(self):
        return self.q(lambda db: [(e.event_type, e.payload) for e in
                                  db.query(DomainEvent).filter_by(event_type=collections.ACQUIRED_EVENT).all()])


class SnapshotTestCase(CollectionsBase):
    def test_counts_from_api_and_audit(self):
        self.assertEqual(self.sync(), "ok")
        last = self.overview()["latest"]
        self.assertEqual({k: last[k] for k in collections.COUNTS},
                         {"mounts": 2, "pets": 1, "achievements": 2, "achievement_points": 120})
        self.assertEqual(last["day"], "2026-11-23")
        acts = self.q(lambda db: db.query(ActivityLog).filter_by(entity_type="wow_collection").count())
        self.assertEqual(acts, 1, "první snapshot je změna – audit ve stejné transakci")

    def test_once_per_six_hours_unless_forced(self):
        self.sync()
        self.set_api(m=mounts("Swift Brown Steed", "Black Stallion", "Raven Lord"))
        self.clock[0] += timedelta(hours=1)
        self.assertEqual(self.sync(), "skipped")
        self.assertEqual(self.overview()["latest"]["mounts"], 2)
        self.assertEqual(self.sync(force=True), "ok")
        self.assertEqual(self.overview()["latest"]["mounts"], 3)
        self.assertEqual(self.q(lambda db: db.query(WowCollectionSnapshot).count()), 1, "jeden řádek na den")

    def test_same_values_write_no_activity(self):
        self.sync()
        self.sync(force=True)
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).filter_by(entity_type="wow_collection").count()), 1)

    def test_week_delta_and_history(self):
        self.sync()
        self.clock[0] += timedelta(days=8)
        self.set_api(m=mounts("Swift Brown Steed", "Black Stallion", "Raven Lord", "Invincible"),
                     a=achievements(150, done=("Level 10", "Level 20", "Level 60")))
        self.sync()
        ov = self.overview()
        self.assertEqual(ov["week"], {"mounts": 2, "pets": 0, "achievements": 1, "achievement_points": 30})
        self.assertEqual([h["day"] for h in ov["history"]], ["2026-11-23", "2026-12-01"])

    def test_single_snapshot_has_no_trend(self):
        self.sync()
        self.assertEqual(self.overview()["week"], {k: None for k in collections.COUNTS})

    def test_failed_endpoint_keeps_last_known_value(self):
        self.sync()
        self.clock[0] += timedelta(days=1)
        self.api.collections[KEY + ("mounts",)] = 429
        self.set_api(p=pets("Mechanical Squirrel", "Lil' K.T."))
        self.assertEqual(self.sync(), "ok")
        last = self.overview()["latest"]
        self.assertEqual((last["mounts"], last["pets"]), (2, 2), "výpadek mountů nechá včerejší číslo")

    def test_everything_down_is_unavailable_and_writes_nothing(self):
        for what in ("mounts", "pets", "achievements"):
            self.api.collections[KEY + (what,)] = 503
        self.assertEqual(self.sync(), "unavailable")
        self.assertIsNone(self.overview()["latest"])

    def test_no_character_and_no_keys(self):
        self.q(lambda db: service.delete_character(db, 1))
        self.assertEqual(self.sync(), "no_character")
        self.assertEqual(self.q(lambda db: collections.sync_collections(db, None)), "not_configured")

    def test_large_achievement_list_is_accepted(self):
        many = achievements(9000, done=[f"Achievement number {i}" for i in range(9000)])
        self.assertGreater(len(json.dumps(many)), battlenet.MAX_BYTES, "větší než limit profilu")
        self.set_api(a=many)
        self.sync()
        self.assertEqual(self.overview()["latest"]["achievements"], 9000)

    def test_goal_sources_read_the_snapshot(self):
        self.sync()
        values = self.q(lambda db: {s: service.goal_value(db, s) for s in collections.GOAL_SOURCES})
        self.assertEqual(values, {"wow_mounts": (2.0, True), "wow_pets": (1.0, True),
                                  "wow_achievement_points": (120.0, True)})

    def test_hourly_step_syncs_collections_after_characters(self):
        self.clock[0] += timedelta(hours=7)
        out = self.q(lambda db: service.sync_due(db, now=self.clock[0]))
        self.assertEqual(out["collections"], "ok")
        self.assertEqual(self.overview()["latest"]["mounts"], 2)


class WishTestCase(CollectionsBase):
    def add(self, kind, name):
        return self.q(lambda db: collections.add_wish(db, kind, name, battlenet.client()))

    def test_wish_ticks_itself_once_when_api_shows_it(self):
        w = self.add("mount", "Invincible")
        self.assertFalse(w["acquired"])
        self.assertFalse(w["already_owned"])
        self.sync()
        self.assertEqual(self.events(), [])
        self.clock[0] += timedelta(days=1)
        self.set_api(m=mounts("Swift Brown Steed", "Black Stallion", "INVINCIBLE"))
        self.sync()
        self.assertEqual(self.events(), [(collections.ACQUIRED_EVENT, {"wish_id": w["id"], "kind": "mount"})])
        self.sync(force=True)
        self.assertEqual(len(self.events()), 1, "odškrtnutí jen jednou")
        wish = self.overview()["wishes"][0]
        self.assertTrue(wish["acquired"])
        acts = self.q(lambda db: db.query(ActivityLog).filter_by(entity_type="wow_wish", action_type="acquired").count())
        self.assertEqual(acts, 1, "událost má projekci v Aktivitě")

    def test_achievement_counts_only_when_completed(self):
        self.add("achievement", "Level 60")
        self.sync()
        self.assertEqual(self.events(), [], "rozpracovaný achievement není získaný")
        self.clock[0] += timedelta(days=1)
        self.set_api(a=achievements(130, done=("Level 10", "Level 20", "Level 60")))
        self.sync()
        self.assertEqual(len(self.events()), 1)

    def test_already_owned_is_ticked_without_mission(self):
        w = self.add("pet", "mechanical  squirrel")
        self.assertTrue(w["already_owned"])
        self.assertTrue(w["acquired"])
        self.sync()
        self.assertEqual(self.events(), [], "nic se nezískalo – žádná událost")

    def test_failed_endpoint_never_ticks(self):
        self.add("mount", "Invincible")
        self.api.collections[KEY + ("mounts",)] = 503
        self.sync()
        self.assertFalse(self.overview()["wishes"][0]["acquired"])

    def test_validation_and_duplicates(self):
        self.add("mount", "Ashes of Al’ar")
        for kind, name, status in (("toy", "Hearthstone", 400), ("mount", "x", 400), ("mount", "ashes of  al'ar", 409)):
            with self.subTest(name=name), self.assertRaises(collections.CollectionError) as err:
                self.add(kind, name)
            self.assertEqual(err.exception.status, status)

    def test_order_open_first(self):
        self.add("mount", "Invincible")
        self.clock[0] += timedelta(minutes=1)
        self.add("pet", "Mechanical Squirrel")  # už vlastněný → získaný
        self.clock[0] += timedelta(minutes=1)
        self.add("achievement", "Level 60")
        self.assertEqual([w["name"] for w in self.overview()["wishes"]], ["Invincible", "Level 60", "Mechanical Squirrel"])

    def test_delete_is_audited(self):
        w = self.add("mount", "Invincible")
        self.q(lambda db: collections.delete_wish(db, w["id"]))
        self.assertEqual(self.q(lambda db: db.query(WowWish).count()), 0)
        self.assertEqual(self.q(lambda db: db.query(ActivityLog).filter_by(entity_type="wow_wish", action_type="delete").count()), 1)
        with self.assertRaises(collections.CollectionError):
            self.q(lambda db: collections.delete_wish(db, w["id"]))


class RaceTestCase(CollectionsBase):
    """Codex review #113: hodinový krok × ruční obnova pro den BEZ snapshotu – oba načtou snap=None, druhý insert
    narazí na unikátní `day`. Souborová SQLite (oddělená spojení), aby se sessions opravdu prokládaly."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.engine.dispose()
        self.engine = create_engine(f"sqlite+pysqlite:///{self._tmp.name}/race.db", poolclass=NullPool)
        from database import Base
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.q(lambda db: service.add_character(db, "Thrallík", "Pyrewood Village", 60))

    def tearDown(self):
        super().tearDown()
        self._tmp.cleanup()

    def test_two_syncs_for_a_new_day_never_crash(self):
        inner_done = []
        real = battlenet.Client.collection

        def interleaved(cli, realm, name, what):
            if what == "mounts" and not inner_done:
                inner_done.append(True)
                # druhá obnova proběhne celá (a commitne) mezi načtením snap=None a insertem první
                self.set_api(m=mounts("Swift Brown Steed", "Black Stallion", "Raven Lord"))
                self.assertEqual(self.sync(force=True), "ok")
                self.set_api(m=mounts("Swift Brown Steed", "Black Stallion", "Raven Lord", "Invincible"))
            return real(cli, realm, name, what)

        with patch.object(battlenet.Client, "collection", interleaved):
            self.assertEqual(self.sync(force=True), "ok", "prohraný insert nesmí shodit obnovu (REST by vrátil 500)")
        rows = self.q(lambda db: [(r.day, r.mounts) for r in db.query(WowCollectionSnapshot).all()])
        self.assertEqual(rows, [(date(2026, 11, 23), 4)], "jeden řádek na den, novější hodnoty z prvního běhu")
        audits = self.q(lambda db: [json.loads(a.delta_json) for a in
                                    db.query(ActivityLog).filter_by(entity_type="wow_collection").order_by(ActivityLog.id)])
        self.assertEqual(len(audits), 2)
        self.assertEqual(audits[1], {"mounts": {"old": 3, "new": 4}}, "audit prohraného běhu = jen jeho změna")


class ClaimTestCase(CollectionsBase):
    def test_conflict_rolls_back_only_the_savepoint(self):
        """Konflikt na `day` vrátí jen savepoint – dřívější zápisy vnější transakce (postavy v sync_due) zůstanou."""
        self.sync()

        def go(db):
            collections.add_wish(db, "pet", "Lil' K.T.")  # neuložený zápis vnější transakce
            snap, created = collections._claim_today(db, date(2026, 11, 23), self.clock[0], {k: None for k in collections.COUNTS})
            return created, snap.mounts

        self.assertEqual(self.q(go), (False, 2), "vrátí vítězný řádek")
        self.assertEqual(self.q(lambda db: db.query(WowWish).count()), 1, "vnější zápis přežil")


class IntegrationTestCase(CollectionsBase):
    def test_search_context_dashboard_and_changes(self):
        self.q(lambda db: collections.add_wish(db, "mount", "Invincible"))
        self.sync()
        self.clock[0] += timedelta(days=8)
        self.set_api(m=mounts("Swift Brown Steed", "Black Stallion", "Invincible"))
        self.sync()
        hits = self.q(lambda db: list(integrations.search_wishes(db, "inv")))
        self.assertEqual(hits[0][0], "wow_wish")
        self.assertEqual(hits[0][-1], "/wow?wowwish=1")
        lines = self.q(lambda db: integrations.context_wow(ContextRequest(db=db, today=date(2026, 12, 1),
                                                                          local_now=self.clock[0])))
        self.assertIn("WoW sbírka: mounti 3 (+1 za týden)", lines[1])
        dash = self.q(lambda db: integrations.dashboard_wow(db, None))
        self.assertEqual((dash["collection"]["mounts"], dash["week"]["mounts"], dash["open_wishes"]), (3, 1, 0))
        source = integrations.INTEGRATIONS.changes[0]
        row = self.q(lambda db: db.query(DomainEvent.event_type, DomainEvent.aggregate_type, DomainEvent.aggregate_id)
                     .filter_by(event_type=collections.ACQUIRED_EVENT).one())

        class E:  # tvar, který dostane ChangeSource.from_event
            type, aggregate_type, aggregate_id = row
        self.assertEqual(source.from_event(E, None).href, "/wow?wowwish=1")


class CollectionsApiTestCase(test_wow.ApiTestCase):
    def test_rest(self):
        self.assertEqual(self.client.post("/auth/login", json={"pin": "4821"}).status_code, 200)
        with patch.object(collections, "utc_now", lambda: self.clock[0]):
            self.client.post("/wow/characters", json={"name": "Thrallík", "realm": "Pyrewood Village"})
            self.api.collections[KEY + ("mounts",)] = mounts("Black Stallion")
            r = self.client.post("/wow/collections/refresh")
            self.assertEqual(r.json()["result"], "ok", r.text)
            self.assertEqual(r.json()["collections"]["latest"]["mounts"], 1)
            r = self.client.post("/wow/wishes", json={"kind": "mount", "name": "Black Stallion"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertTrue(r.json()["already_owned"])
            self.assertEqual(self.client.post("/wow/wishes", json={"kind": "toy", "name": "Xy"}).status_code, 400)
            self.assertEqual(self.client.post("/wow/wishes", json={"kind": "mount", "name": "black stallion"}).status_code, 409)
            self.assertEqual(len(self.client.get("/wow").json()["collections"]["wishes"]), 1)
            self.assertEqual(self.client.delete("/wow/wishes/1").json(), {"ok": True})
            self.assertEqual(self.client.delete("/wow/wishes/1").status_code, 404)


if __name__ == "__main__":
    unittest.main()
