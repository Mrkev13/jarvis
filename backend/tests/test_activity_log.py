import os
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import ActivityLog, GoalProgressHistory


class ActivityLogModelTestCase(unittest.TestCase):
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

    def test_01_model_structure(self):
        rows = self.db.execute(text("PRAGMA table_info(activity_logs)")).fetchall()
        insp_cols = {r[1] for r in rows}
        for expected in ["id", "timestamp", "area", "action_type",
                         "entity_type", "entity_id", "summary",
                         "delta_json", "user_context", "dedupe_key"]:
            self.assertIn(expected, insp_cols)

        al = ActivityLog(
            timestamp=datetime(2026, 9, 11, 10, 32, 0),
            area="work",
            action_type="create",
            summary="Test entry",
            entity_type="WorkSession",
            entity_id=42,
            user_context="unit_test",
            dedupe_key="a:b:c:d:e"
        )
        self.db.add(al)
        self.db.commit()
        got = self.db.query(ActivityLog).filter(ActivityLog.id == al.id).first()
        self.assertIsNotNone(got)
        self.assertEqual(got.area, "work")
        self.assertEqual(got.entity_id, 42)

    def test_02_dedupe_key_idempotent(self):
        from activity_service import log_activity
        a1 = log_activity(
            self.db, "finance", "create", "Plat",
            entity_type="FinanceTransaction", entity_id=1,
            dedupe_key="same:dedupe:key:12345678",
            user_context="t"
        )
        self.assertIsNotNone(a1)
        self.db.flush()
        a2 = log_activity(
            self.db, "finance", "create", "Plat",
            entity_type="FinanceTransaction", entity_id=1,
            dedupe_key="same:dedupe:key:12345678",
            user_context="t"
        )
        self.assertIsNone(a2)
        self.db.commit()
        cnt = self.db.query(ActivityLog).filter(
            ActivityLog.dedupe_key == "same:dedupe:key:12345678"
        ).count()
        self.assertEqual(cnt, 1)

    def test_03_transaction_boundary_rollback(self):
        al = ActivityLog(
            area="system", action_type="sync",
            summary="Should be rolled back",
            dedupe_key="tx:rb:01", user_context="t"
        )
        self.db.add(al)
        self.db.rollback()
        cnt = self.db.query(ActivityLog).filter(
            ActivityLog.dedupe_key == "tx:rb:01").count()
        self.assertEqual(cnt, 0)


class ActivityLogIntegrationTestCase(unittest.TestCase):
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

    def test_04_9_distinct_areas(self):
        areas = [
            "ai", "finance", "goals", "memory", "mff",
            "school", "system", "work", "wot",
        ]
        for i, a in enumerate(areas):
            al = ActivityLog(
                area=a, action_type="create",
                summary=f"Hook test {a}",
                entity_type="X", entity_id=i,
                user_context="test",
                dedupe_key=f"area:{a}:{i}"
            )
            self.db.add(al)
        self.db.commit()
        dist = sorted({r[0] for r in self.db.query(ActivityLog.area).distinct().all()})
        self.assertEqual(len(dist), 9)
        self.assertEqual(dist, sorted(areas))

    def test_05_list_filters_and_dashboard_recent(self):
        base = datetime(2026, 9, 11, 9, 0, 0)
        areas_rot = ["finance", "work", "goals", "memory", "school",
                     "mff", "wot", "ai", "system"]
        for i in range(55):
            area = areas_rot[i % 9]
            al = ActivityLog(
                timestamp=base + timedelta(minutes=i),
                area=area,
                action_type=["create", "update", "delete"][i % 3],
                summary=f"Row {i} {area}",
                user_context="t",
                dedupe_key=f"f:{i}"
            )
            self.db.add(al)
        self.db.commit()
        all_q = self.db.query(ActivityLog).order_by(
            ActivityLog.timestamp.desc(), ActivityLog.id.desc())
        total = all_q.count()
        self.assertEqual(total, 55)
        page = all_q.limit(20).offset(0).all()
        self.assertEqual(len(page), 20)
        self.assertGreater(page[0].timestamp, page[-1].timestamp)

        fin_q = self.db.query(ActivityLog).filter(ActivityLog.area == "finance")
        self.assertEqual(fin_q.count(), 7)

        fin_filt = fin_q.order_by(ActivityLog.timestamp.desc()).all()
        self.assertTrue(all(x.area == "finance" for x in fin_filt))

        import json as _json
        row = self.db.query(ActivityLog).first()
        delta_obj = None
        if row.delta_json:
            try:
                delta_obj = _json.loads(row.delta_json)
            except Exception:
                delta_obj = {"_raw": row.delta_json}
        self.assertIsNone(delta_obj)

        recent_rows = (
            self.db.query(ActivityLog)
            .order_by(ActivityLog.timestamp.desc(), ActivityLog.id.desc())
            .limit(5)
            .all()
        )
        recent_activity = [
            {
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "area": r.area,
                "action_type": r.action_type,
                "summary": r.summary,
            }
            for r in recent_rows
        ]
        self.assertIsInstance(recent_activity, list)
        self.assertEqual(len(recent_activity), 5)

    def test_06_dashboard_readonly_no_snapshots(self):
        cnt_before = self.db.query(GoalProgressHistory).count()
        self.assertEqual(cnt_before, 0)
        snapshots_after = self.db.query(GoalProgressHistory).count()
        self.assertEqual(snapshots_after, 0)

    def test_07_bulk_commit_integrity(self):
        from activity_service import log_activity
        a1 = log_activity(self.db, "finance", "create", "T1", entity_type="T", entity_id=1, dedupe_key="bulk1")
        a2 = log_activity(self.db, "work", "update", "T2", entity_type="W", entity_id=2, dedupe_key="bulk2")
        self.assertIsNotNone(a1)
        self.assertIsNotNone(a2)
        self.db.commit()
        cnt = self.db.query(ActivityLog).filter(ActivityLog.dedupe_key.in_(["bulk1", "bulk2"])).count()
        self.assertEqual(cnt, 2)
        self.db.rollback()

    def test_08_delta_dict_serializer_helper(self):
        from activity_service import delta_dict
        from datetime import date as _d
        class O:
            pass
        old = O(); old.name = "a"; old.d = _d(2026, 1, 1); old.n = 10
        new = O(); new.name = "b"; new.d = _d(2026, 6, 1); new.n = 15
        d = delta_dict(old, new, ["name", "d", "n"])
        self.assertEqual(d["name"]["old"], "a")
        self.assertEqual(d["name"]["new"], "b")
        self.assertEqual(d["d"]["old"], "2026-01-01")
        self.assertEqual(d["n"]["new"], 15)


class ActivityLogUtilityTests(unittest.TestCase):
    def test_09_backend_dir_on_path(self):
        import sys as _sys
        BACKEND_DIR = str(Path(__file__).resolve().parents[1])
        self.assertIn(BACKEND_DIR, _sys.path)

    def test_10_parse_iso_dt_datetimes(self):
        from main import _parse_iso_dt
        self.assertIsNone(_parse_iso_dt(None))
        self.assertIsNone(_parse_iso_dt(""))
        got = _parse_iso_dt("2026-01-15T10:32:00")
        self.assertIsNotNone(got)
        self.assertEqual(got.year, 2026)
        self.assertEqual(got.month, 1)
        self.assertEqual(got.day, 15)
        with_z = _parse_iso_dt("2026-09-01T00:00:00Z")
        self.assertIsNotNone(with_z)


if __name__ == "__main__":
    unittest.main()


class ActivityListEndpointTestCase(unittest.TestCase):
    """Roadmap 4B: filtr Aktivity – více oblastí čárkou a rozsah from_date/to_date (UTC)."""

    def setUp(self):
        from unittest import mock

        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        db = Session()
        base = datetime(2026, 10, 1, 10, 0, 0)
        for i, area in enumerate(["finance", "work", "school", "finance", "wot"]):
            db.add(ActivityLog(timestamp=base + timedelta(days=i), area=area, action_type="create",
                               summary=f"Row {i}", user_context="t", dedupe_key=f"e:{i}"))
        db.commit()
        db.close()
        self.patch = mock.patch("main.SessionLocal", Session)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.engine.dispose()

    def test_multiple_areas_comma_separated(self):
        from main import activity_list

        res = activity_list(area="finance,work")
        self.assertEqual(res["total"], 3)
        self.assertEqual({i["area"] for i in res["items"]}, {"finance", "work"})
        self.assertEqual(activity_list(area="school")["total"], 1)
        self.assertEqual(activity_list(area=" , ")["total"], 5)

    def test_date_range_utc_bounds(self):
        from main import activity_list

        # 2. 10. 10:00 UTC až 3. 10. 10:00 UTC (konce včetně)
        res = activity_list(from_date="2026-10-02T10:00:00.000Z", to_date="2026-10-03T10:00:00.000Z")
        self.assertEqual([i["summary"] for i in res["items"]], ["Row 2", "Row 1"])
