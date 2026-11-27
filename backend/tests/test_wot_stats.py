"""MRK-153: statistiky WoT po bitvách ze snímků Wargaming API – ukládání jen při změně, rozdíly za období
(výchozí stav, nový tank, víc bitev mezi synchronizacemi), bitvy po dnech, hodnocení a zdroje v čase, REST. Bez sítě."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import wot_stats_service as svc
from database import Base
from models import WotAccountSnapshot, WotTankSnapshot, WotVehicleMastery

# Praha CET (UTC+1): 27. 11. 2026 12:00 UTC = 13:00 místního času
NOW = datetime(2026, 11, 27, 12, 0)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([WotVehicleMastery(tank_id=1, name="Progetto M35 mod. 46", short_name="Progetto 46", tier=8,
                                       mark_of_mastery=3, updated_at=NOW),
                     WotVehicleMastery(tank_id=2, name="Object 279 (e)", short_name="Obj. 279 (e)", tier=10,
                                       mark_of_mastery=4, updated_at=NOW)])
    session.commit()
    yield session
    session.close()
    engine.dispose()


def tank(tid, battles, wins, damage, frags=0, xp=0, survived=0):
    return {"tank_id": tid, "battles": battles, "wins": wins, "damage": damage, "frags": frags, "xp": xp,
            "survived": survived}


def at(db, when, *rows):
    n = svc.record_tanks(db, list(rows), when)
    db.commit()
    return n


def test_only_changes_are_stored(db):
    assert at(db, NOW - timedelta(days=3), tank(1, 100, 55, 300000), tank(2, 50, 30, 200000)) == 2
    assert at(db, NOW - timedelta(days=2), tank(1, 100, 55, 300000), tank(2, 50, 30, 200000)) == 0, "beze změny"
    assert at(db, NOW - timedelta(days=1), tank(1, 103, 57, 309000), tank(2, 50, 30, 200000)) == 1
    assert db.query(WotTankSnapshot).count() == 3


def test_today_counts_battles_since_local_midnight(db):
    at(db, NOW - timedelta(days=3), tank(1, 100, 55, 300000, 120, 90000, 40), tank(2, 50, 30, 200000))
    at(db, NOW - timedelta(hours=14), tank(1, 102, 56, 306000, 122, 92000, 41))   # včera 23:00 Praha
    at(db, NOW - timedelta(hours=2), tank(1, 105, 58, 315000, 125, 95000, 43))     # dnes: +3 bitvy, 2 výhry
    s = svc.stats(db, "today", NOW)
    assert s["summary"]["battles"] == 3 and s["summary"]["wins"] == 2
    assert s["summary"]["win_rate"] == 66.7 and s["summary"]["avg_damage"] == 3000.0 and s["summary"]["avg_frags"] == 1.0
    assert [t["name"] for t in s["tanks"]] == ["Progetto 46"]
    assert s["best_tank"]["tank_id"] == 1 and s["daily"] == [] and s["partial"] is False


def test_baseline_sync_is_not_counted_and_new_tank_starts_from_zero(db):
    at(db, NOW - timedelta(hours=3), tank(1, 100, 55, 300000))       # výchozí stav (první synchronizace) dnes
    at(db, NOW - timedelta(hours=1), tank(1, 101, 56, 303000), tank(9, 2, 1, 4000))  # nový tank přibyl
    s = svc.stats(db, "today", NOW)
    assert s["summary"]["battles"] == 3, "1 bitva Progetta + 2 na novém tanku, nic z výchozího stavu"
    assert {t["tank_id"]: t["battles"] for t in s["tanks"]} == {9: 2, 1: 1}
    assert s["tanks"][0]["name"] == "Tank 9", "tank mimo tabulku M-ek má záložní název"
    # Hub začal ukládat až dnes dopoledne → i „dnes“ je neúplné (bitvy od půlnoci do prvního snímku neznáme)
    assert s["partial"] is True and s["data_since"] == "2026-11-27T09:00:00Z"
    assert svc.stats(db, "week", NOW)["partial"] is True


def test_week_daily_breakdown_and_all_time(db):
    at(db, NOW - timedelta(days=10), tank(1, 100, 50, 300000), tank(2, 40, 20, 160000))
    at(db, NOW - timedelta(days=5), tank(1, 104, 53, 312000))
    at(db, NOW - timedelta(days=1), tank(2, 46, 24, 190000))
    at(db, NOW - timedelta(hours=1), tank(1, 106, 54, 318000))
    s = svc.stats(db, "week", NOW)
    assert s["summary"]["battles"] == 4 + 6 + 2
    daily = {d["date"]: d["battles"] for d in s["daily"]}
    assert len(s["daily"]) == 7 and daily["2026-11-22"] == 4 and daily["2026-11-26"] == 6 and daily["2026-11-27"] == 2
    assert sum(daily.values()) == s["summary"]["battles"]
    everything = svc.stats(db, "all", NOW)
    assert everything["summary"]["battles"] == 106 + 46 and everything["from"] is None and everything["daily"] == []
    assert svc.stats(db, "nesmysl", NOW)["period"] == "week"


def test_rating_and_resources_series_only_on_change(db):
    assert svc.record_rating(db, 5100, 900, NOW - timedelta(days=10))
    assert not svc.record_rating(db, 5100, 900, NOW - timedelta(days=9)), "beze změny nic"
    assert svc.record_rating(db, 5150, 910, NOW - timedelta(days=2))
    assert svc.record_rating(db, 5180, 915, NOW - timedelta(hours=1))
    assert not svc.record_rating(db, None, None, NOW)
    assert svc.record_resources(db, {"credits": 1_000_000, "gold": 500, "free_xp": 10, "bonds": 5}, NOW - timedelta(days=3))
    assert not svc.record_resources(db, {"credits": 1_000_000, "gold": 500, "free_xp": 10, "bonds": 5}, NOW - timedelta(days=2))
    assert svc.record_resources(db, {"credits": 1_200_000, "gold": 500, "free_xp": 10, "bonds": 5}, NOW - timedelta(hours=2))
    db.commit()
    assert db.query(WotAccountSnapshot).count() == 5
    s = svc.stats(db, "week", NOW)
    assert [p["value"] for p in s["rating"]] == [5100, 5150, 5180], "kotva = poslední hodnota před začátkem týdne"
    assert s["rating_now"] == 5180 and s["rating_change"] == 80
    assert [p["value"] for p in s["resources"]["credits"]] == [1_000_000, 1_200_000]
    assert svc.stats(db, "all", NOW)["rating"][0]["value"] == 5100


def test_ai_context_lines(db):
    at(db, NOW - timedelta(days=3), tank(1, 100, 55, 300000))
    at(db, NOW - timedelta(hours=1), tank(1, 102, 57, 306000))
    lines = svc.context_lines(db, NOW)
    assert lines[0] == "WoT dnes: 2 bitev, výhry 100.0 %, průměrný damage 3000"
    assert lines[1].startswith("WoT týden: 2 bitev")


def test_mastery_sync_records_tanks_and_rating(db):
    import wot_mastery_service
    import wot_wargaming as wg

    class Resp:
        status_code = 200

        def __init__(self, data):
            self._d = data
            self.content = b"{}"

        def json(self):
            return self._d

    def transport(method, url, **kw):
        path = url.split("/wot/", 1)[1].rstrip("/")
        if path == "account/list":
            return Resp({"status": "ok", "data": [{"account_id": 7, "nickname": "tester_1"}]})
        if path == "tanks/stats":
            assert "all.damage_dealt" in kw["params"]["fields"]
            return Resp({"status": "ok", "data": {"7": [{"tank_id": 1, "mark_of_mastery": 3, "all": {
                "battles": 120, "wins": 66, "damage_dealt": 360000, "frags": 140, "xp": 100000, "survived_battles": 50}}]}})
        if path == "encyclopedia/vehicles":
            return Resp({"status": "ok", "data": {}})
        if path == "account/info":
            assert kw["params"]["fields"] == "global_rating,statistics.all.battles"
            return Resp({"status": "ok", "data": {"7": {"global_rating": 5321, "statistics": {"all": {"battles": 1200}}}}})
        raise AssertionError(path)

    cfg = wg.Config("0123456789abcdef0123456789abcdef", "eu", "tester_1")
    with patch.object(wot_mastery_service, "log_activity"):
        out = wot_mastery_service.sync(db, wg.Client(cfg, transport), now=NOW, force=True)
    db.commit()
    assert out["result"] == "ok"
    snap = db.query(WotTankSnapshot).one()
    assert (snap.battles, snap.wins, snap.damage, snap.frags, snap.xp, snap.survived) == (120, 66, 360000, 140, 100000, 50)
    rating = db.query(WotAccountSnapshot).filter_by(kind="rating").one()
    assert (rating.global_rating, rating.battles) == (5321, 1200)
