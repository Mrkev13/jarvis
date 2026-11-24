"""Příspěvky WoW (MRK-127) do globálních agregátorů – vyhledávání, Co se změnilo, AI kontext, hodinový krok a REST.

Žádný agregátor o WoW neví: vše jde přes `ModuleDef.integrations` (module_registry.py). MRK-128 přidává sbírky:
karta na Řídicím centru (sekce `wow` v GET /dashboard), seznam přání ve vyhledávání a AI kontextu, událost získání.
Dnes ani Rychlé přidání zatím nemá smysl (postavy nemají termín ani časté vytváření). Hodinový krok obnoví postavy z Blizzard API nejvýš jednou
za 6 h a nejvýš 10 najednou; bez klíčů nedělá nic.
"""
from __future__ import annotations

from context_format import list_or_none, short
from module_contracts import (
    ChangeSource, activity_changes, event_changes,
    ContextRequest, ContextSection, DashboardSection, EntityRef, ModuleIntegrations, ScheduledStep, SearchSource,
)
from modules.wow import collections, service
from modules.wow.router import router
from text_utils import join_parts

ROW_LIMIT = service.MAX_CHARACTERS
EVENTS = ("wow.character.level_up", collections.ACQUIRED_EVENT)

# ---------- vyhledávání ----------


def search_characters(db, q):
    for c in service.all_characters(db)[:ROW_LIMIT]:
        level = f"level {c.level}" if c.level is not None else ""
        target = f"cíl {c.target_level}" if c.target_level else ""
        sub = join_parts("WoW postava", c.class_name or "", level, target, c.realm_name or c.realm_slug)
        extra = join_parts("wow warcraft alt postava", c.race_name or "", c.realm_slug, sep=" ")
        yield "wow_character", c.id, c.name, sub, extra, "wow", f"/wow?wowchar={c.id}"


def search_wishes(db, q):
    """MRK-128: seznam „chci získat“ (mount / mazlíček / achievement)."""
    for w in collections.all_wishes(db):
        state = "získáno" if w.acquired_at else "chci získat"
        sub = join_parts("WoW sbírka", collections.KIND_LABELS.get(w.kind, w.kind), state)
        yield "wow_wish", w.id, w.name, sub, f"wow warcraft sbírka {w.kind}", "wow", f"/wow?wowwish={w.id}"


# ---------- AI kontext (jen čtení snapshotu, žádné API) ----------


def context_wow(req: ContextRequest) -> list[str]:
    chars = service.all_characters(req.db)
    items = []
    for c in chars[:12]:
        lvl = f"lvl {c.level}" if c.level is not None else "lvl ?"
        target = f"/{c.target_level}" if c.target_level else ""
        items.append(short(join_parts(c.name, c.class_name or "", lvl + target, sep=" "), 40))
    lines = [f"WoW postavy: {list_or_none(items, len(chars))}"]
    # MRK-128: sbírka – jen počty z posledního snapshotu a otevřená přání (bez API)
    col = collections.overview(req.db)
    last, week = col["latest"], col["week"]
    if last:
        parts = []
        for key in collections.COUNTS:
            if last[key] is None:
                continue
            d = week[key]
            trend = f" ({'+' if d > 0 else ''}{d} za týden)" if d else ""
            parts.append(f"{collections.COUNT_LABELS[key]} {last[key]}{trend}")
        if parts:
            lines.append("WoW sbírka: " + ", ".join(parts))
    wanted = [short(w["name"], 40) for w in col["wishes"] if not w["acquired"]]
    if wanted:
        lines.append(f"WoW chci získat: {list_or_none(wanted[:10], len(wanted))}")
    return lines


def dashboard_wow(db, access):
    """MRK-128: karta Her na Řídicím centru – postavy + sbírka (jen uložené snapshoty)."""
    col = collections.overview(db)
    return {"summary": service.summary(db), "collection": col["latest"], "week": col["week"],
            "open_wishes": col["open_wishes"]}


def character_names(db):
    return [c.name for c in service.all_characters(db)]


def hourly_sync(db):
    return service.sync_due(db)


INTEGRATIONS = ModuleIntegrations(
    changes=(ChangeSource(
        "wow", areas=frozenset({"wow"}),
        from_event=event_changes({"character": "/wow?wowchar={id}", "wish": "/wow?wowwish={id}"},
                                 {"wow.character.level_up": "WoW: nový level",
                                  collections.ACQUIRED_EVENT: "WoW: získáno do sbírky"}),
        from_activity=activity_changes({"wow_character": "/wow?wowchar={id}", "wow_wish": "/wow?wowwish={id}"},
                                       "/wow"),
    ),),
    search=(SearchSource("wow", 92, search_characters), SearchSource("wow wishes", 93, search_wishes)),
    entity_refs=(EntityRef("wow_character", "/wow?wowchar={id}"), EntityRef("wow_wish", "/wow?wowwish={id}")),
    dashboard=(DashboardSection("wow", dashboard_wow),),
    context=(
        ContextSection("wow", ("wow", "warcraft", "altik", "alty", "altu", "mount", "achievement", "sbirk"), order=78, build=context_wow,
                       name_hints=character_names),
    ),
    hourly=(ScheduledStep("wow character sync", hourly_sync),),
    routers=(router,),
)
