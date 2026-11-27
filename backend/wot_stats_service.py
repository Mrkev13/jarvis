"""MRK-153: statistiky WoT po bitvách – bez replaye, z hodinové synchronizace s Wargaming API.

Ukládání (jen při změně, ať tabulky nebobtnají):
- `record_tanks`: kumulativní součty tanku z `tanks/stats` (bitvy, výhry, damage, frag, XP, přežití) – volá je
  synchronizace M-ek (`wot_mastery_service.sync`), která `tanks/stats` stejně stahuje;
- `record_rating`: osobní hodnocení Wargamingu (`account/info.global_rating`, veřejné);
- `record_resources`: kredity / zlato / Free XP / bondy z propojeného účtu (`wot_account_service.sync`).

Výpočet (`stats`): odehrané bitvy za období = rozdíl kumulativních součtů na konci a na začátku období, po tancích.
Stav tanku v čase t = poslední snímek ≤ t. Tank bez snímku před začátkem: když ho zachytila už úplně první
synchronizace (výchozí stav), je jeho první snímek základ (nic z dřívějška se nepřipisuje); tank, který přibyl
později, začíná od nuly. „Celkově“ (`all`) = poslední snímky všech tanků = celkové statistiky účtu.
Vše deterministicky tady; AI dostane jen výsledek (`context_lines`).
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import WotAccountSnapshot, WotTankSnapshot, WotVehicleMastery
from time_utils import APP_TZ, today_local, utc_now

PERIODS = {"today": 1, "3d": 3, "week": 7, "month": 30, "half": 182, "all": None}
PERIOD_LABELS = {"today": "Dnes", "3d": "3 dny", "week": "Týden", "month": "Měsíc", "half": "Půl roku", "all": "Celkově"}
FIELDS = ("battles", "wins", "damage", "frags", "xp", "survived")
RESOURCE_KEYS = ("credits", "gold", "free_xp", "bonds")
BEST_MIN_BATTLES = 3


# ---------- ukládání ----------


def record_tanks(db: Session, rows: list[dict], now: datetime | None = None) -> int:
    """Uloží snímek tanků, kterým se změnil počet bitev (nebo jsou nové). → počet nových řádků. Nic necommituje."""
    now = now or utc_now()
    latest = dict(db.query(WotTankSnapshot.tank_id, func.max(WotTankSnapshot.battles))
                  .group_by(WotTankSnapshot.tank_id).all())  # bitvy jen rostou → max = poslední stav
    added = 0
    for r in rows:
        battles = r.get("battles")
        if not isinstance(r.get("tank_id"), int) or battles is None or latest.get(r["tank_id"]) == battles:
            continue
        db.add(WotTankSnapshot(tank_id=r["tank_id"], taken_at=now, battles=battles, wins=r.get("wins"),
                               damage=r.get("damage"), frags=r.get("frags"), xp=r.get("xp"), survived=r.get("survived")))
        added += 1
    db.flush()
    return added


def _last(db: Session, kind: str) -> WotAccountSnapshot | None:
    return (db.query(WotAccountSnapshot).filter(WotAccountSnapshot.kind == kind)
            .order_by(WotAccountSnapshot.taken_at.desc(), WotAccountSnapshot.id.desc()).first())


def record_rating(db: Session, rating: int | None, battles: int | None, now: datetime | None = None) -> bool:
    if rating is None:
        return False
    last = _last(db, "rating")
    if last is not None and (last.global_rating, last.battles) == (rating, battles):
        return False
    db.add(WotAccountSnapshot(kind="rating", taken_at=now or utc_now(), global_rating=rating, battles=battles))
    db.flush()
    return True


def record_resources(db: Session, values: dict, now: datetime | None = None) -> bool:
    vals = {k: values.get(k) for k in RESOURCE_KEYS}
    if all(v is None for v in vals.values()):
        return False
    last = _last(db, "resources")
    if last is not None and all(getattr(last, k) == v for k, v in vals.items()):
        return False
    db.add(WotAccountSnapshot(kind="resources", taken_at=now or utc_now(), **vals))
    db.flush()
    return True


# ---------- výpočet ----------


@dataclass
class _Tank:
    times: list[datetime]
    rows: list[tuple]          # (battles, wins, damage, frags, xp, survived) – None → 0
    baseline_first: bool       # zachycen už výchozí synchronizací → první snímek je základ

    def at(self, t: datetime) -> tuple:
        i = bisect.bisect_right(self.times, t)
        if i:
            return self.rows[i - 1]
        return self.rows[0] if self.baseline_first else (0,) * len(FIELDS)


def _load(db: Session) -> tuple[dict[int, _Tank], datetime | None]:
    snaps = (db.query(WotTankSnapshot).order_by(WotTankSnapshot.tank_id, WotTankSnapshot.taken_at,
                                                 WotTankSnapshot.id).all())
    first_sync = min((s.taken_at for s in snaps), default=None)
    tanks: dict[int, _Tank] = {}
    for s in snaps:
        t = tanks.get(s.tank_id)
        if t is None:
            t = tanks[s.tank_id] = _Tank([], [], s.taken_at == first_sync)
        t.times.append(s.taken_at)
        t.rows.append(tuple(getattr(s, f) or 0 for f in FIELDS))
    return tanks, first_sync


def _diff(a: tuple, b: tuple) -> tuple:
    return tuple(max(0, x - y) for x, y in zip(a, b))


def _summary(t: tuple) -> dict:
    battles, wins, damage, frags, xp, survived = t
    per = (lambda v: round(v / battles, 1)) if battles else (lambda v: None)
    return {"battles": battles, "wins": wins, "win_rate": round(100 * wins / battles, 1) if battles else None,
            "avg_damage": per(damage), "avg_frags": per(frags), "avg_xp": per(xp),
            "survival": round(100 * survived / battles, 1) if battles else None}


def _local_midnight_utc(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=APP_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _series(db: Session, kind: str, keys: tuple[str, ...], since: datetime | None) -> dict[str, list[dict]]:
    q = db.query(WotAccountSnapshot).filter(WotAccountSnapshot.kind == kind)
    rows = q.order_by(WotAccountSnapshot.taken_at, WotAccountSnapshot.id).all()
    if since is not None:
        before = [r for r in rows if r.taken_at < since]
        rows = ([before[-1]] if before else []) + [r for r in rows if r.taken_at >= since]  # kotva na začátku období
    return {k: [{"at": _iso(max(r.taken_at, since) if since else r.taken_at), "value": getattr(r, k)}
                for r in rows if getattr(r, k) is not None] for k in keys}


def stats(db: Session, period: str = "week", now: datetime | None = None) -> dict:
    """GET /wot/stats?period=… → souhrn, tanky, bitvy po dnech, hodnocení a zdroje v čase."""
    if period not in PERIODS:
        period = "week"
    now = now or utc_now()
    today = today_local(now)
    tanks, first_sync = _load(db)
    names = {m.tank_id: m for m in db.query(WotVehicleMastery).all()}
    days = PERIODS[period]
    since = None if days is None else _local_midnight_utc(today - timedelta(days=days - 1))

    per_tank = []
    total = (0,) * len(FIELDS)
    for tid, t in tanks.items():
        end = t.at(now)
        d = end if since is None else _diff(end, t.at(since))
        if d[0] <= 0:
            continue
        total = tuple(a + b for a, b in zip(total, d))
        meta = names.get(tid)
        per_tank.append({"tank_id": tid, "name": (meta.short_name or meta.name) if meta else f"Tank {tid}",
                         "tier": meta.tier if meta else None, "tag": meta.tag if meta else None, **_summary(d)})
    per_tank.sort(key=lambda x: (-x["battles"], x["name"]))
    eligible = [x for x in per_tank if x["battles"] >= BEST_MIN_BATTLES] or per_tank
    best = max(eligible, key=lambda x: (x["avg_damage"] or 0, x["battles"]), default=None)

    daily = []
    if since is not None and days > 1:
        for i in range(days):
            day = today - timedelta(days=days - 1 - i)
            lo, hi = _local_midnight_utc(day), min(now, _local_midnight_utc(day + timedelta(days=1)))
            dt = (0,) * len(FIELDS)
            for t in tanks.values():
                dt = tuple(a + b for a, b in zip(dt, _diff(t.at(hi), t.at(lo))))
            daily.append({"date": day.isoformat(), **_summary(dt)})

    rating = _series(db, "rating", ("global_rating",), since)["global_rating"]
    return {
        "period": period, "label": PERIOD_LABELS[period], "periods": [{"key": k, "label": v} for k, v in PERIOD_LABELS.items()],
        "from": _iso(since) if since else None, "to": _iso(now),
        # odkdy Hub statistiky ukládá – starší část období je prázdná a UI to přizná
        "data_since": _iso(first_sync) if first_sync else None,
        "partial": bool(since and first_sync and first_sync > since),
        "summary": _summary(total), "best_tank": best, "tanks": per_tank[:50], "daily": daily,
        "rating": rating, "rating_now": rating[-1]["value"] if rating else None,
        "rating_change": (rating[-1]["value"] - rating[0]["value"]) if len(rating) > 1 else None,
        "resources": _series(db, "resources", RESOURCE_KEYS, since),
    }


def context_lines(db: Session, now: datetime | None = None) -> list[str]:
    """Pro AI kontext WoT jen spočítaný výsledek (dnes a týden)."""
    out = []
    for period in ("today", "week"):
        s = stats(db, period, now)["summary"]
        if s["battles"]:
            out.append(f"WoT {PERIOD_LABELS[period].lower()}: {s['battles']} bitev, výhry {s['win_rate']} %, "
                       f"průměrný damage {s['avg_damage']:.0f}")
    return out
