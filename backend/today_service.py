"""Režim Dnes (Roadmap 4G) – „Co dnes potřebuje moji pozornost?" Deterministicky, bez LLM, jen čtení.

GET /today skládá EXISTUJÍCÍ zdroje (žádná nová business pravidla):
- časová osa: připomínky, zkoušky a úkoly s termínem v pražském dni D (00:00–24:00 Europe/Prague, DST přes time_utils);
- pozornost: po termínu (úkoly, zkoušky, nevyřízené připomínky z dřívějška) + neřešená nepřečtená upozornění
  (stejná sémantika jako karta „Vyžaduje pozornost" na Řídicím centru);
- dnešní plán: akce denního plánovače (planner_service.generate_plan – stejný výpočet jako /planner a /dashboard);
- potom: nejbližší termíny v dalších 7 dnech (max. 3).

Deduplikace podle záznamu (`ref` = „assignment:12"): každý záznam je jen v JEDNÉ sekci s pořadím
časová osa > pozornost > plán > potom. Informace z vyšších sekcí se nezahodí – položka dostane značku
(priorita z plánu, závažnost z upozornění). Každá sekce se počítá zvlášť: chyba jednoho zdroje = `errors[sekce]`,
ostatní sekce se vrátí normálně.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from module_registry import ModuleAccess, current_access
from notifications_service import list_notifications
from planner_service import generate_plan
from statuses import norm
from text_utils import format_date_cz
from time_utils import now_local, utc_now
from today_types import UPCOMING_DAYS, TodayContext, TodayItem

log = logging.getLogger(__name__)

WEEKDAYS_CZ = ("pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle")
MAX_ATTENTION = 8
MAX_UPCOMING = 3
SEVERITY_RANK = {"important": 0, "warning": 1, "info": 2}

SECTION_ERRORS = {
    "timeline": "Dnešní termíny se nepodařilo načíst.",
    "attention": "Položky k vyřízení se nepodařilo načíst.",
    "priorities": "Dnešní plán se nepodařilo sestavit.",
    "upcoming": "Další termíny se nepodařilo načíst.",
}


# MRK-20: TodayItem a kontext jsou v today_types (sdílí je poskytovatelé modulů); _Ctx = starý název.
_Ctx = TodayContext
__all__ = ["TodayItem", "TodayContext", "UPCOMING_DAYS", "build_today", "dedupe", "gate_items", "snooze_options"]


# ---------- zdroje modulů (MRK-20: ModuleIntegrations.today) ----------

class SourceFailed(Exception):
    """Sekce se sestavila jen částečně (selhal zdroj některého modulu); `partial` = to, co se podařilo."""

    def __init__(self, partial):
        super().__init__("source failed")
        self.partial = partial


def _collect(c: TodayContext, access: ModuleAccess, part: str, errors: list[str]) -> list:
    """Spojí část `part` (timeline / overdue / upcoming / closed_refs) od jádra a dostupných modulů v pořadí zdrojů.
    Zdroj, který selže, se vynechá a jeho název přidá do `errors` – ostatní moduly se ukážou dál."""
    out: list = []
    for src in sorted((s for _owner, s in access.contributions("today")), key=lambda s: s.order):
        fn = getattr(src, part)
        if fn is None:
            continue
        try:
            out.extend(fn(c))
        except Exception:  # noqa: BLE001 – jeden modul nesmí shodit sekci
            log.exception("today: source %s.%s failed", src.name, part)
            c.db.rollback()
            errors.append(src.name)
    return out


def _entity_refs(access: ModuleAccess) -> dict:
    return {ref.type: ref for _owner, ref in access.contributions("entity_refs")}


# ---------- akce (Roadmap 4H) ----------

def snooze_options(today: date) -> list[dict]:
    """Pevné volby odložení; „zítra" = další pražský kalendářní den v 08:00 (i těsně po půlnoci)."""
    return [
        {"id": "15m", "label": "+15 min", "minutes": 15},
        {"id": "1h", "label": "+1 h", "minutes": 60},
        {"id": "3h", "label": "+3 h", "minutes": 180},
        {"id": "tomorrow", "label": "Zítra 8:00", "until_local": f"{(today + timedelta(days=1)).isoformat()}T08:00"},
    ]


# ---------- časová osa ----------

def timeline_sort_key(item: TodayItem) -> tuple:
    """Hotové dospod; s časem chronologicky; bez času („Během dne") za nimi; pak název."""
    return (item.status == "done", item.time is None, item.time or "", item.title.lower())


def build_timeline(c: TodayContext, access: ModuleAccess) -> list[TodayItem]:
    errors: list[str] = []
    items = _collect(c, access, "timeline", errors)
    if errors:
        raise SourceFailed(sorted(items, key=timeline_sort_key))
    return sorted(items, key=timeline_sort_key)


# ---------- pozornost ----------

def _notification_ref(n: dict, refs: dict) -> str | None:
    """Upozornění k záznamu (source_type typu, který modul hlásí jako `notification_source`) → ref záznamu."""
    st, sid = n.get("source_type"), n.get("source_id")
    ref = refs.get(st)
    return f"{st}:{sid}" if ref is not None and ref.notification_source and sid is not None else None


def _safe_href(url) -> str | None:
    return url if isinstance(url, str) and url.startswith("/") and not url.startswith("//") else None


def build_attention(c: TodayContext, access: ModuleAccess) -> tuple[list[TodayItem], dict[str, str]]:
    """(položky, závažnost podle ref z upozornění) – upozornění k záznamu se spojí s jeho položkou."""
    errors: list[str] = []
    items = {it.id: it for it in _collect(c, access, "overdue", errors)}
    severity_by_ref: dict[str, str] = {}
    # Ref záznamů, které už nic nepotřebují (hotové úkoly, uzavřené zkoušky, neaktivní připomínky).
    closed = set(_collect(c, access, "closed_refs", errors))
    refs = _entity_refs(access)
    for n in list_notifications(c.db, unread_only=True, include_resolved=False, now=c.now_utc):
        sev = norm(n.get("severity")) or "info"
        ref = _notification_ref(n, refs)
        if ref in closed:
            # Roadmap 4H: záznam je už vyřízený (např. právě dokončený z Dnes) – upozornění by do dalšího běhu
            # generate_notifications jen strašilo. Stejné pravidlo jako _resolve_if_no_longer_relevant, jen čtením.
            continue
        if ref:
            prev = severity_by_ref.get(ref)
            if prev is None or SEVERITY_RANK.get(sev, 3) < SEVERITY_RANK.get(prev, 3):
                severity_by_ref[ref] = sev
            if ref in items:
                continue
        key = ref or f"notification:{n['id']}"
        if key in items:
            continue
        items[key] = TodayItem(
            id=key, type="notification", title=n.get("title") or "", subtitle=n.get("message") or "",
            area=n.get("area"), status="open", severity=sev, href=_safe_href(n.get("action_url")), source_id=n.get("id"),
        )
    for ref, sev in severity_by_ref.items():
        if ref in items and SEVERITY_RANK.get(sev, 3) < SEVERITY_RANK.get(items[ref].severity or "", 3):
            items[ref].severity = sev
    ordered = sorted(items.values(), key=lambda it: (SEVERITY_RANK.get(it.severity or "", 3), it.date or "9999", it.title.lower()))
    if errors:
        raise SourceFailed((ordered, severity_by_ref))
    return ordered, severity_by_ref


# ---------- plán, potom ----------

def build_priorities(c: TodayContext, access: ModuleAccess) -> list[TodayItem]:
    plan = generate_plan(c.db, mode="daily", today=c.today)
    refs = _entity_refs(access)
    items = []
    for a in plan.get("actions") or []:
        ref = a.get("ref")
        kind, _, rid = (ref or "").partition(":")
        entity = refs.get(kind) if ref else None
        items.append(TodayItem(
            id=ref or f"planner:{a.get('priority')}", type="planner", title=a.get("title") or "",
            subtitle=a.get("reason") or "", area=a.get("area"), status="open", priority=int(a.get("priority") or 0) or None,
            href=entity.href.format(id=rid) if entity else "/planner", source_id=int(ref.split(":")[1]) if ref else None,
            actions=list(entity.planner_actions) if entity else [],
        ))
    return items


def build_upcoming(c: TodayContext, access: ModuleAccess) -> list[TodayItem]:
    errors: list[str] = []
    items = sorted(_collect(c, access, "upcoming", errors), key=lambda it: (it.date or "", it.time or "99:99", it.title.lower()))
    if errors:
        raise SourceFailed(items)
    return items


# ---------- skladba ----------

def dedupe(timeline: list[TodayItem], attention: list[TodayItem], priorities: list[TodayItem],
           upcoming: list[TodayItem], severity_by_ref: dict[str, str] | None = None) -> dict[str, list[TodayItem]]:
    """Každý záznam v jedné sekci: časová osa > pozornost > plán > potom. Značky se přenesou na ponechanou položku."""
    severity_by_ref = severity_by_ref or {}
    shown: dict[str, TodayItem] = {}
    out: dict[str, list[TodayItem]] = {}
    for name, items in (("timeline", timeline), ("attention", attention), ("priorities", priorities), ("upcoming", upcoming)):
        kept = []
        for it in items:
            if it.id in shown:
                keeper = shown[it.id]
                if it.priority and not keeper.priority:
                    keeper.priority = it.priority
                continue
            if name == "timeline" and it.id in severity_by_ref and it.status != "done":
                it.severity = severity_by_ref[it.id]
            shown[it.id] = it
            kept.append(it)
        out[name] = kept
    out["upcoming"] = out["upcoming"][:MAX_UPCOMING]
    out["attention"] = out["attention"][:MAX_ATTENTION]
    return out


def next_item(timeline: list[TodayItem], now_local_naive: datetime) -> tuple[TodayItem | None, int | None]:
    """Nejbližší položka s časem, která ještě nenastala (minuty od teď), jinak (None, None)."""
    hhmm = f"{now_local_naive:%H:%M}"
    for it in timeline:
        if it.time and it.status == "upcoming" and it.time > hhmm:
            h, m = map(int, it.time.split(":"))
            at = now_local_naive.replace(hour=h, minute=m, second=0, microsecond=0)
            return it, max(0, int((at - now_local_naive).total_seconds() // 60))
    return None, None


def date_label(d: date) -> str:
    return f"{WEEKDAYS_CZ[d.weekday()]} {format_date_cz(d)}"


def gate_items(items: list[TodayItem], access: ModuleAccess) -> list[TodayItem]:
    """Roadmap 6C: položky modulu, který nesmí do Dnes, se vynechají (podle refu „<typ>:<id>")."""
    return [it for it in items if access.allows_ref(it.id, "today")]


def build_today(db: Session, now_utc: datetime | None = None, *, access: ModuleAccess | None = None) -> dict:
    now_utc = now_utc or utc_now()
    local_now = now_local(now_utc)
    c = TodayContext(db=db, now_utc=now_utc, today=local_now.date(), now_local_naive=local_now.replace(tzinfo=None))
    access = access or current_access()
    errors: dict[str, str] = {}

    def section(name, fn, default):
        try:
            return fn()
        except SourceFailed as partial:
            # MRK-20: selhal jen některý modul – sekce ukáže zbytek a hlášku chyby
            errors[name] = SECTION_ERRORS[name]
            return partial.partial
        except Exception:  # noqa: BLE001 – jeden zdroj nesmí shodit celou stránku
            log.exception("today: section %s failed", name)
            db.rollback()
            errors[name] = SECTION_ERRORS[name]
            return default

    timeline = section("timeline", lambda: build_timeline(c, access), [])
    attention, severity_by_ref = section("attention", lambda: build_attention(c, access), ([], {}))
    priorities = section("priorities", lambda: build_priorities(c, access), [])
    upcoming = section("upcoming", lambda: build_upcoming(c, access), [])
    timeline, attention, priorities, upcoming = (gate_items(s, access) for s in (timeline, attention, priorities, upcoming))
    sections = dedupe(timeline, attention, priorities, upcoming, severity_by_ref)

    nxt, minutes = next_item(sections["timeline"], c.now_local_naive)
    remaining = sum(1 for it in sections["timeline"] if it.status in ("upcoming", "due", "open"))
    return {
        "date": c.today.isoformat(),
        "date_label": date_label(c.today),
        "now_local": f"{c.now_local_naive:%H:%M}",
        "summary": {
            "remaining": remaining,
            "done": sum(1 for it in sections["timeline"] if it.status in ("done", "past")),
            "attention": len(sections["attention"]),
            "next": {**nxt.as_dict(), "minutes_until": minutes} if nxt else None,
        },
        "timeline": [it.as_dict() for it in sections["timeline"]],
        "attention": [it.as_dict() for it in sections["attention"]],
        "priorities": [it.as_dict() for it in sections["priorities"]],
        "upcoming": [it.as_dict() for it in sections["upcoming"]],
        "snooze_options": snooze_options(c.today),
        "errors": errors,
    }
