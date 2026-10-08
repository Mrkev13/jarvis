"""„Co se změnilo" (MRK-28) – deterministický přehled změn za období, bez LLM.

Zdroje (docs/what-changed.md):
- doménové události (MRK-19) – preferované; titulek pro člověka = shrnutí jejich projekce do Aktivity
  (`dedupe_key = "event:<id>"`), payload události jména nenese,
- Aktivita – záložní zdroj pro toky bez událostí a pro události, které už smazala retence.
Řádek Aktivity, který je projekcí načtené události, se spotřebuje (žádná duplicita).

Mapování patří modulům (`ModuleIntegrations.changes`, module_contracts.ChangeSource); tady je jen politika:
sběr, dedupe, šum (stejný jako ranní přehled – briefing_snapshot.meaningful_activity), vypnuté moduly, filtry,
řazení a limity. Vypnutý modul nepřispívá a jeho záznamy se nezobrazí.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

import domain_events as de
from briefing_snapshot import _NOISE_ACTIONS, _NOISE_AREAS, meaningful_activity
from models import ActivityLog, DomainEvent
from module_contracts import ChangeItem

log = logging.getLogger(__name__)

SINCE_DEFAULT = timedelta(days=7)
SINCE_MAX = timedelta(days=90)
LIMIT_DEFAULT = 50
LIMIT_MAX = 200
SCAN_MAX = 2000  # nejvýš tolik událostí a řádků Aktivity na dotaz (dlouhá nepřítomnost → `truncated`)
CORE = "core"  # klíč filtru pro změny jádra (připomínky, paměť)
CORE_LABEL = "Obecné"
NOISE_EVENT_PREFIXES = ("system.",)
_PROJECTION_KEY = re.compile(r"^event:(\d+)$")
_MODULE_TOKEN = re.compile(r"^[a-z][a-z0-9_]{0,49}$")


class ChangeFeedError(ValueError):
    """Neplatný vstup GET /changes (→ 422)."""


def parse_since(raw: str | None, now: datetime) -> datetime:
    """ISO čas (s časovou zónou nebo UTC) → aware UTC. Výchozí 7 dní, starší než 90 dní se zarovná na 90."""
    if raw is None or raw.strip() == "":
        return now - SINCE_DEFAULT
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ChangeFeedError("Parametr since musí být čas ve formátu ISO 8601.") from exc
    if dt > now:
        raise ChangeFeedError("Parametr since nesmí být v budoucnosti.")
    return max(dt, now - SINCE_MAX)


def parse_modules(raw: str | None) -> frozenset[str] | None:
    if raw is None or raw.strip() == "":
        return None
    tokens = {t.strip() for t in raw.split(",") if t.strip()}
    if not tokens or any(not _MODULE_TOKEN.match(t) for t in tokens):
        raise ChangeFeedError("Parametr module je seznam id modulů oddělených čárkou.")
    return frozenset(tokens)


def clamp_limit(limit: int | None) -> int:
    return max(1, min(int(LIMIT_DEFAULT if limit is None else limit), LIMIT_MAX))


def _safe(fn, *args):
    """Chyba jednoho mapování nesmí shodit celý přehled; loguje se jen typ (bez obsahu záznamu)."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001
        log.warning("change feed: provider failed (%s)", type(exc).__name__)
        return None


def _item(draft, *, item_id: str, occurred: datetime, owner: str | None, source: str) -> tuple[datetime, ChangeItem]:
    return occurred, ChangeItem(id=item_id, occurred_at=de.iso(occurred), module_id=owner, entity_type=draft.entity_type,
                      entity_id=draft.entity_id, kind=draft.kind, title=draft.title, summary=draft.summary,
                      href=draft.href, source=source)


def collect(db: Session, access, *, since: datetime) -> tuple[list[ChangeItem], bool]:
    """Všechny změny od `since` (bez filtru modulu a limitu) – nejnovější první; druhá hodnota = ořezáno."""
    sources = access.contributions("changes")
    event_sources = {owner: s for owner, s in sources if owner is not None and s.from_event}
    area_sources = {area: (owner, s) for owner, s in sources if s.from_activity for area in s.areas}

    events = (db.query(DomainEvent).filter(DomainEvent.occurred_at >= since)
              .order_by(DomainEvent.id.desc()).limit(SCAN_MAX).all())
    since_naive = since.astimezone(timezone.utc).replace(tzinfo=None)  # Aktivita ukládá naivní UTC
    # provozní šum se vyřadí už v SQL, aby nespotřeboval limit skenu (zbytek politiky níže)
    rows = (db.query(ActivityLog)
            .filter(ActivityLog.timestamp >= since_naive, ActivityLog.area.notin_(_NOISE_AREAS),
                    ActivityLog.action_type.notin_(_NOISE_ACTIONS))
            .order_by(ActivityLog.timestamp.desc(), ActivityLog.id.desc()).limit(SCAN_MAX).all())
    truncated = len(events) >= SCAN_MAX or len(rows) >= SCAN_MAX

    # Šum a „vytvořeno i smazáno v okně" platí pro VŠECHNY řádky – i pro projekce událostí (jinak by se
    # splnění smazaného úkolu ukázalo, dokud událost nesmaže retence).
    kept_ids = {r.id for r in meaningful_activity(rows)}
    # Projekci spotřebuje jen událost, kterou umí zobrazit vlastník (zdroj s from_event); jinak zůstane
    # řádek Aktivity jako záloha (vypnutý modul / system.* ho pak vyřadí stejně jako jeho Aktivitu).
    shown_events = {e.id: e for e in events
                    if not e.event_type.startswith(NOISE_EVENT_PREFIXES) and e.module_id in event_sources}
    projections: dict[int, ActivityLog] = {}
    legacy: list[ActivityLog] = []
    for row in rows:
        m = _PROJECTION_KEY.match(row.dedupe_key or "")
        if m and int(m.group(1)) in shown_events:
            projections[int(m.group(1))] = row  # spotřebováno událostí
        elif row.id in kept_ids:
            legacy.append(row)

    items: list[tuple[datetime, ChangeItem]] = []
    for row in shown_events.values():
        projection = projections.get(row.id)
        if projection is not None and projection.id not in kept_ids:
            continue  # projekce je šum / patří k záznamu vytvořenému i smazanému v okně
        draft = _safe(event_sources[row.module_id].from_event, de.snapshot(row),
                      projection.summary if projection is not None else None)
        if draft:
            items.append(_item(draft, item_id=f"event:{row.id}", occurred=de.as_utc(row.occurred_at),
                               owner=row.module_id, source="event"))
    for row in legacy:
        owner_source = area_sources.get(row.area)
        if owner_source is None:
            continue
        owner, source = owner_source
        draft = _safe(source.from_activity, row)
        if draft:
            items.append(_item(draft, item_id=f"activity:{row.id}", occurred=de.as_utc(row.timestamp),
                               owner=owner, source="activity"))
    items.sort(key=lambda x: (x[0], x[1].id), reverse=True)  # podle času, ne podle ISO textu
    return [item for _at, item in items], truncated


def filters_for(items: list[ChangeItem], access) -> list[dict]:
    """Filtry odvozené z obsahu: jen moduly, které v období něco mají (pořadí registru, jádro první)."""
    counts: dict[str, int] = {}
    for i in items:
        key = i.module_id or CORE
        counts[key] = counts.get(key, 0) + 1
    out = [{"id": CORE, "label": CORE_LABEL, "count": counts[CORE]}] if CORE in counts else []
    out += [{"id": m.id, "label": m.label, "count": counts[m.id]} for m in access.modules if m.id in counts]
    return out


def build(db: Session, access, *, since: datetime, modules: frozenset[str] | None, limit: int) -> dict:
    items, truncated = collect(db, access, since=since)
    filters = filters_for(items, access)
    if modules is not None:
        items = [i for i in items if (i.module_id or CORE) in modules]
    return {
        "since": de.iso(since),
        "items": [asdict(i) for i in items[:limit]],
        "total": len(items),
        "truncated": truncated or len(items) > limit,
        "filters": filters,
    }
