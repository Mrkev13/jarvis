"""MRK-12: historical records are ID-based; grind slots remain unique by tank.

Uses real Pydantic requests and endpoint handlers without HTTP/auth transport.
All writes use a fresh in-memory DB and temporary media; no LLM calls.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("GROQ_API_KEY", "unused-test-key")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from database import Base
import main
import media_storage
import wot_replay_service as replays
import replay_fixtures as fixtures
from models import WotGrind, WotMilestone, WotReplay


class DuplicateWotRecordsTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.media = tempfile.TemporaryDirectory(prefix="mrk12-media-")
        self.enterContext(patch.object(main, "SessionLocal", self.Session))
        self.enterContext(patch.object(media_storage, "MEDIA_DIR", self.media.name))
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.media.cleanup)
        # Fail immediately if any code unexpectedly tries an external request.
        self.enterContext(patch("socket.socket.connect", side_effect=AssertionError("Network forbidden in MRK-12 tests")))

    def create(self, **fields):
        return main.wot_milestone_create(main.WotMilestoneRequest(
            tank="Progetto 65", played_on="2026-09-14", **fields))

    def test_two_identical_ace_records_have_distinct_ids_and_independent_crud(self):
        first = self.create(mastery="ace", damage=5205, notes="First battle")
        second = self.create(mastery="ace", damage=5205, notes="First battle")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(main.wot_milestones()), 2)
        main.wot_milestone_update(first["id"], main.WotMilestoneRequest(damage=6000, notes="Edited"))
        rows = {m["id"]: m for m in main.wot_milestones()}
        self.assertEqual((rows[first["id"]]["damage"], rows[first["id"]]["notes"]), (6000, "Edited"))
        self.assertEqual(rows[second["id"]], second)
        main.wot_milestone_delete(first["id"])
        self.assertEqual(main.wot_milestones(), [second])

    def test_memorable_battles_without_mastery_can_repeat(self):
        first = self.create(notes="Memorable battle", favorite=True)
        second = self.create(notes="Another memorable battle", favorite=True)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual([m["mastery"] for m in main.wot_milestones()], [None, None])

    def test_same_tank_replays_create_separate_ace_milestones_and_keep_links(self):
        ids = []
        for damage in (5205, 6000):
            with self.Session() as db:
                data = fixtures.build(fixtures.header(), fixtures.results(damage=damage))
                replay = replays.upload_replay(db, data, "battle.wotreplay", tank_name="Progetto 65")
                db.commit()
                replay, milestone = replays.create_milestone_from_replay(db, replay.id)
                db.commit()
                ids.append((replay.id, milestone.id))
        (r1, m1), (r2, m2) = ids
        self.assertNotEqual(m1, m2)
        rows = {m["id"]: m for m in main.wot_milestones()}
        self.assertEqual((rows[m1]["replay_ids"], rows[m2]["replay_ids"]), ([r1], [r2]))
        self.assertEqual((rows[m1]["mastery"], rows[m2]["mastery"]), ("ace", "ace"))
        main.wot_milestone_update(m1, main.WotMilestoneRequest(notes="Edited only first"))
        with self.Session() as db:
            self.assertIsNone(db.get(WotMilestone, m2).notes)
            filtered = replays.list_replays(db, tank="Progetto 65", mastery="ace")
            self.assertEqual({r["id"] for r in filtered["items"]}, {r1, r2})
        main.wot_milestone_delete(m1)
        with self.Session() as db:
            self.assertIsNone(db.get(WotReplay, r1).linked_milestone_id)
            self.assertEqual(db.get(WotReplay, r2).linked_milestone_id, m2)
            self.assertEqual(db.query(WotReplay).count(), 2)
        self.assertEqual(main.wot_milestones()[0]["replay_ids"], [r2])
        self.assertEqual(len(list((Path(self.media.name) / "wot-replays").iterdir())), 2)

    def test_grind_upsert_keeps_one_slot_and_repeated_completion_history(self):
        def upsert(xp):
            main.add_wot_grind(main.WotGrindRequest(tank="Progetto 65", xp_remaining=xp))
        upsert(100000)
        with self.Session() as db:
            gid = db.query(WotGrind).one().id
        upsert(50000)
        with self.Session() as db:
            grind = db.query(WotGrind).one()
            self.assertEqual((grind.id, grind.xp_remaining, grind.xp_start), (gid, 50000, 100000))
            db.add(WotGrind(tank="Progetto 65", xp_remaining=1, status="active"))
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
        main.wot_grind_complete(gid)
        upsert(30000)
        main.wot_grind_complete(gid)
        history = main.wot_grinds_completed()
        self.assertEqual(len(history), 2)
        self.assertNotEqual(history[0]["completion_id"], history[1]["completion_id"])
        self.assertEqual({h["tank"] for h in history}, {"Progetto 65"})


if __name__ == "__main__":
    unittest.main()
