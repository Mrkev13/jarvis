import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import (
    Goal,
    MffCharacter,
    MFF_ROLE_OPTIONS,
    compute_mff_build_completeness,
    parse_legacy_uru_state,
    legacy_role_string_to_list,
)
from goal_history_service import (
    compute_automatic_goal_current_value,
    compute_goal_progress_and_value,
)
import tools


class MffHelpersTestCase(unittest.TestCase):
    def test_build_completeness_100_percent_all_components(self):
        bc = compute_mff_build_completeness(
            tier="T4",
            level=80,
            uniform="Carnage",
            ctp="Rage",
            artifact="The Book of Vishanti",
            uru_slots_total=20,
            uru_slots_filled=20,
            iso8_set="Attack",
            team_supports="White Fox + Shuri",
        )
        self.assertEqual(bc, 100)

    def test_build_completeness_88_percent_missing_one(self):
        bc = compute_mff_build_completeness(
            tier="T4",
            level=80,
            uniform="Carnage",
            ctp="",
            artifact="The Book of Vishanti",
            uru_slots_total=20,
            uru_slots_filled=20,
            iso8_set="Attack",
            team_supports="White Fox + Shuri",
        )
        self.assertEqual(bc, 88)

    def test_build_completeness_drop_missing_ctp_artifact_unfilled_uru(self):
        bc_full = compute_mff_build_completeness(
            tier="T4",
            level=80,
            uniform="Carnage",
            ctp="Rage",
            artifact="Book",
            uru_slots_total=20,
            uru_slots_filled=20,
            iso8_set="Attack",
            team_supports="WF",
        )
        self.assertEqual(bc_full, 100)

        bc_no_ctp = compute_mff_build_completeness(
            tier="T4", level=80, uniform="Carnage",
            ctp="", artifact="Book",
            uru_slots_total=20, uru_slots_filled=20,
            iso8_set="Attack", team_supports="WF",
        )
        self.assertEqual(bc_no_ctp, 88)

        bc_no_artifact = compute_mff_build_completeness(
            tier="T4", level=80, uniform="Carnage",
            ctp="Rage", artifact="",
            uru_slots_total=20, uru_slots_filled=20,
            iso8_set="Attack", team_supports="WF",
        )
        self.assertEqual(bc_no_artifact, 88)

        bc_unfilled_uru = compute_mff_build_completeness(
            tier="T4", level=80, uniform="Carnage",
            ctp="Rage", artifact="Book",
            uru_slots_total=20, uru_slots_filled=10,
            iso8_set="Attack", team_supports="WF",
        )
        self.assertEqual(bc_unfilled_uru, 88)

        bc_nothing = compute_mff_build_completeness(
            tier="T1", level=1, uniform="",
            ctp="", artifact="",
            uru_slots_total=0, uru_slots_filled=0,
            iso8_set="", team_supports="",
        )
        self.assertEqual(bc_nothing, 0)

    def test_parse_legacy_uru_state(self):
        self.assertEqual(parse_legacy_uru_state("20/20"), (20, 20, 0))
        self.assertEqual(parse_legacy_uru_state("20/20 · 6 OB"), (20, 20, 6))
        self.assertEqual(parse_legacy_uru_state("15/20, 3 OB"), (20, 15, 3))
        self.assertEqual(parse_legacy_uru_state(""), (20, 0, 0))
        self.assertEqual(parse_legacy_uru_state("0/20"), (20, 0, 0))
        self.assertEqual(parse_legacy_uru_state("10 OB"), (20, 0, 10))

    def test_legacy_role_string_to_list(self):
        self.assertEqual(
            sorted(legacy_role_string_to_list("ABX · ABL · GBR")),
            sorted(["ABX", "ABL", "GBR"]),
        )
        self.assertEqual(
            sorted(legacy_role_string_to_list("ABX, ABL|World Boss")),
            sorted(["ABX", "ABL", "World Boss"]),
        )
        self.assertEqual(legacy_role_string_to_list(""), [])
        self.assertEqual(
            sorted(legacy_role_string_to_list('["PvP", "Dispatch"]')),
            sorted(["PvP", "Dispatch"]),
        )


class MffSummaryAndCountsTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _insert(self, **kwargs):
        c = MffCharacter(**kwargs)
        self.db.add(c)
        self.db.flush()
        return c

    def test_t4_built_t4_high_priority_built_counts(self):
        self._insert(
            name="Luna Snow",
            tier="T4", level=80, uniform="K-Pop Star",
            ctp="Rage", artifact="Book of Vishanti",
            uru_slots_total=20, uru_slots_filled=20, odin_blessings_count=6,
            iso8_set="Attack", team_supports="White Fox + Shuri",
            priority="high", status="built",
            roles=["ABX", "ABL", "GBR"],
            build_completeness=100,
        )
        self._insert(
            name="Thor",
            tier="T4", level=80, uniform="Herald of Galactus",
            ctp="Rage", artifact="",
            uru_slots_total=20, uru_slots_filled=20, odin_blessings_count=4,
            iso8_set="Attack", team_supports="Odin",
            priority="medium", status="building",
            roles=["World Boss"],
            build_completeness=88,
        )
        self._insert(
            name="Iron Man",
            tier="T4", level=80, uniform="Endgame",
            ctp="Rage", artifact="Book",
            uru_slots_total=20, uru_slots_filled=20, odin_blessings_count=6,
            iso8_set="Attack", team_supports="War Machine",
            priority="high", status="built",
            roles=["ABX", "PvP"],
            build_completeness=100,
        )
        self._insert(
            name="Captain America",
            tier="T3", level=75, uniform="Endgame",
            ctp="", artifact="",
            uru_slots_total=20, uru_slots_filled=10,
            iso8_set="", team_supports="",
            priority="low", status="planned",
            roles=["Dispatch"],
            build_completeness=25,
        )
        self.db.commit()

        chars = self.db.query(MffCharacter).all()

        t4_count = sum(1 for c in chars if (c.tier or "").strip().lower().replace(" ", "") == "t4")
        self.assertEqual(t4_count, 3)

        built_t4_count = sum(
            1 for c in chars
            if (c.tier or "").strip().lower().replace(" ", "") == "t4"
            and int(getattr(c, "build_completeness", 0) or 0) >= 100
        )
        self.assertEqual(built_t4_count, 2)

        high_priority_built_count = sum(
            1 for c in chars
            if (c.priority or "").strip().lower() == "high"
            and int(getattr(c, "build_completeness", 0) or 0) >= 100
        )
        self.assertEqual(high_priority_built_count, 2)


class MffFilteringTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = Session()
        chars = [
            MffCharacter(
                name="Luna", tier="T4", level=80,
                ctp="R", artifact="B", uniform="U", iso8_set="A",
                team_supports="WF", uru_slots_total=20, uru_slots_filled=20,
                priority="high", status="built",
                roles=["ABX", "ABL", "GBR"], build_completeness=100,
            ),
            MffCharacter(
                name="Thor", tier="T4", level=80,
                ctp="R", artifact="", uniform="U", iso8_set="A",
                team_supports="O", uru_slots_total=20, uru_slots_filled=20,
                priority="medium", status="building",
                roles=["World Boss"], build_completeness=88,
            ),
            MffCharacter(
                name="Cap", tier="T3", level=70,
                ctp="", artifact="", uniform="", iso8_set="",
                team_supports="", uru_slots_total=20, uru_slots_filled=5,
                priority="low", status="planned",
                roles=["Dispatch", "Other"], build_completeness=25,
            ),
        ]
        for c in chars:
            self.db.add(c)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_filter_by_roles_and_criteria(self):
        chars = self.db.query(MffCharacter).all()

        def has_all_roles(c, required):
            r = getattr(c, "roles", None) or []
            if isinstance(r, str):
                r = legacy_role_string_to_list(r)
            return all(req in r for req in required)

        abl_chars = [c.name for c in chars if has_all_roles(c, ["ABL"])]
        self.assertIn("Luna", abl_chars)
        self.assertEqual(len(abl_chars), 1)

        wb_chars = [c.name for c in chars if has_all_roles(c, ["World Boss"])]
        self.assertEqual(wb_chars, ["Thor"])

        dispatch_chars = [c.name for c in chars if has_all_roles(c, ["Dispatch"])]
        self.assertEqual(dispatch_chars, ["Cap"])

        t4_chars = [c.name for c in chars if (c.tier or "").lower().replace(" ", "") == "t4"]
        self.assertEqual(sorted(t4_chars), sorted(["Luna", "Thor"]))

        high_prio = [c.name for c in chars if (c.priority or "").lower() == "high"]
        self.assertEqual(high_prio, ["Luna"])

        bc_ge_80 = [c.name for c in chars if int(c.build_completeness or 0) >= 80]
        self.assertEqual(sorted(bc_ge_80), sorted(["Luna", "Thor"]))

        bc_lt_50 = [c.name for c in chars if int(c.build_completeness or 0) < 50]
        self.assertEqual(bc_lt_50, ["Cap"])


class MffGoalProgressTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = Session()

        for i in range(7):
            self.db.add(MffCharacter(
                name=f"T4Char{i}", tier="T4", level=80,
                uniform="U", ctp="R", artifact="B", iso8_set="A",
                team_supports="T", uru_slots_total=20, uru_slots_filled=20 if i < 4 else 10,
                priority="high" if i < 2 else "medium",
                status="built" if i < 4 else "building",
                roles=["ABX"],
                build_completeness=100 if i < 4 else 88,
            ))
        for i in range(5):
            self.db.add(MffCharacter(
                name=f"T3Char{i}", tier="T3", level=70,
                priority="low", status="planned",
                build_completeness=38,
            ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_mff_t4_count_goal_progress(self):
        goal = Goal(
            area="MFF", title="10 T4",
            tracking_type="automatic", source="mff_t4_count",
            target_value=10.0, status="active",
        )
        self.db.add(goal)
        self.db.commit()

        current = compute_automatic_goal_current_value(self.db, "mff_t4_count")
        self.assertEqual(current, 7.0)

        progress, value = compute_goal_progress_and_value(self.db, goal)
        self.assertEqual(value, 7.0)
        self.assertEqual(progress, 70)

    def test_mff_built_t4_count_goal_progress(self):
        goal = Goal(
            area="MFF", title="10 fully built T4",
            tracking_type="automatic", source="mff_built_t4_count",
            target_value=10.0, status="active",
        )
        self.db.add(goal)
        self.db.commit()

        current = compute_automatic_goal_current_value(self.db, "mff_built_t4_count")
        self.assertEqual(current, 4.0)

        progress, value = compute_goal_progress_and_value(self.db, goal)
        self.assertEqual(value, 4.0)
        self.assertEqual(progress, 40)

    def test_mff_high_priority_built_count_goal_progress(self):
        goal = Goal(
            area="MFF", title="5 high priority fully built",
            tracking_type="automatic", source="mff_high_priority_built_count",
            target_value=5.0, status="active",
        )
        self.db.add(goal)
        self.db.commit()

        current = compute_automatic_goal_current_value(self.db, "mff_high_priority_built_count")
        self.assertEqual(current, 2.0)

        progress, value = compute_goal_progress_and_value(self.db, goal)
        self.assertEqual(value, 2.0)
        self.assertEqual(progress, 40)


class MffUpsertIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.old_sl = getattr(tools, "SessionLocal", None)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        tools.SessionLocal = Session

    def tearDown(self):
        if self.old_sl is not None:
            tools.SessionLocal = self.old_sl
        self.engine.dispose()

    def test_upsert_creates_full_build_100_bc(self):
        result = tools.upsert_mff_character(
            name="Test Full",
            tier="T4", level=80,
            uniform="Royal", ctp="Rage", artifact="Cloak",
            iso8_set="Attack", team_supports="Shuri",
            uru_slots_total=20, uru_slots_filled=20, odin_blessings_count=6,
            priority="high", status="built",
            roles=["ABX", "GBR"],
        )
        self.assertEqual(result["build_completeness"], 100)
        self.assertEqual(sorted(result["roles"]), sorted(["ABX", "GBR"]))
        self.assertEqual(result["uru_slots_total"], 20)
        self.assertEqual(result["uru_slots_filled"], 20)
        self.assertEqual(result["odin_blessings_count"], 6)

    def test_upsert_invalid_uru_validated(self):
        result = tools.upsert_mff_character(
            name="Clamp Test",
            tier="T3", level=70,
            uru_slots_total=20, uru_slots_filled=999,
        )
        self.assertLessEqual(result["uru_slots_filled"], result["uru_slots_total"])
        self.assertEqual(result["level"], 70)

    def test_upsert_level_clamped(self):
        result = tools.upsert_mff_character(
            name="Level Test", tier="T2", level=0,
        )
        self.assertGreaterEqual(result["level"], 1)

    def test_upsert_legacy_uru_state_parsed(self):
        result = tools.upsert_mff_character(
            name="Legacy Uru", tier="T3", level=70,
            uru_state="18/20 · 4 OB",
        )
        self.assertEqual(result["uru_slots_total"], 20)
        self.assertEqual(result["uru_slots_filled"], 18)
        self.assertEqual(result["odin_blessings_count"], 4)

    def test_summary_metrics_match_fixture(self):
        fixtures = [
            dict(name="SM0", tier="T4", level=80, uniform="U", ctp="R",
                 artifact="B", iso8_set="A", team_supports="T",
                 uru_slots_total=20, uru_slots_filled=20, odin_blessings_count=6,
                 priority="high", status="built", roles=["ABX"]),
            dict(name="SM1", tier="T4", level=80, uniform="U", ctp="R",
                 artifact="B", iso8_set="A", team_supports="T",
                 uru_slots_total=20, uru_slots_filled=20, odin_blessings_count=6,
                 priority="high", status="built", roles=["ABX"]),
            dict(name="SM2", tier="T4", level=80, uniform="U", ctp="R",
                 artifact="", iso8_set="A", team_supports="T",
                 uru_slots_total=20, uru_slots_filled=20, odin_blessings_count=3,
                 priority="medium", status="building", roles=["ABX"]),
            dict(name="SM3", tier="T4", level=80, uniform="U", ctp="R",
                 artifact="", iso8_set="A", team_supports="T",
                 uru_slots_total=20, uru_slots_filled=10, odin_blessings_count=0,
                 priority="medium", status="building", roles=["ABX"]),
            dict(name="SM4", tier="T4", level=79, uniform="", ctp="",
                 artifact="", iso8_set="", team_supports="T",
                 uru_slots_total=20, uru_slots_filled=0, odin_blessings_count=0,
                 priority="low", status="planned", roles=["ABX"]),
            dict(name="SM5", tier="T3", level=75, uniform="U", ctp="",
                 artifact="", iso8_set="A", team_supports="T",
                 uru_slots_total=20, uru_slots_filled=0, odin_blessings_count=0,
                 priority="medium", status="building", roles=["ABX"]),
            dict(name="SM6", tier="T3", level=70, uniform="", ctp="",
                 artifact="", iso8_set="", team_supports="",
                 uru_slots_total=20, uru_slots_filled=0, odin_blessings_count=0,
                 priority="low", status="planned", roles=["ABX"]),
        ]
        for f in fixtures:
            tools.upsert_mff_character(**f)
        s = tools.get_mff_summary()
        self.assertEqual(s["tracked_characters"], 7)
        self.assertEqual(s["t4_count"], 5)
        self.assertEqual(s["t3_count"], 2)
        self.assertEqual(s["priority_count"], 2)
        self.assertGreaterEqual(s["built_count"], 2)
        self.assertEqual(s["fully_built_t4_count"], 2)
        avg = s["average_build_completeness"]
        self.assertGreaterEqual(avg, 0)
        self.assertLessEqual(avg, 100)


if __name__ == "__main__":
    unittest.main()
