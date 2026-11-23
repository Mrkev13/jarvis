"""Příspěvky WoW (MRK-127) do globálních agregátorů – vyhledávání, Co se změnilo, AI kontext, hodinový krok a REST.

Žádný agregátor o WoW neví: vše jde přes `ModuleDef.integrations` (module_registry.py). Dnes, widget ani Rychlé přidání
zatím nemá smysl (postavy nemají termín ani časté vytváření). Hodinový krok obnoví postavy z Blizzard API nejvýš jednou
za 6 h a nejvýš 10 najednou; bez klíčů nedělá nic.
"""
from __future__ import annotations

from context_format import list_or_none, short
from module_contracts import (
    ChangeSource, activity_changes, event_changes,
    ContextRequest, ContextSection, EntityRef, ModuleIntegrations, ScheduledStep, SearchSource,
)
from modules.wow import service
from modules.wow.router import router
from text_utils import join_parts

ROW_LIMIT = service.MAX_CHARACTERS
EVENTS = ("wow.character.level_up",)

# ---------- vyhledávání ----------


def search_characters(db, q):
    for c in service.all_characters(db)[:ROW_LIMIT]:
        level = f"level {c.level}" if c.level is not None else ""
        target = f"cíl {c.target_level}" if c.target_level else ""
        sub = join_parts("WoW postava", c.class_name or "", level, target, c.realm_name or c.realm_slug)
        extra = join_parts("wow warcraft alt postava", c.race_name or "", c.realm_slug, sep=" ")
        yield "wow_character", c.id, c.name, sub, extra, "wow", f"/wow?wowchar={c.id}"


# ---------- AI kontext (jen čtení snapshotu, žádné API) ----------


def context_wow(req: ContextRequest) -> list[str]:
    chars = service.all_characters(req.db)
    items = []
    for c in chars[:12]:
        lvl = f"lvl {c.level}" if c.level is not None else "lvl ?"
        target = f"/{c.target_level}" if c.target_level else ""
        items.append(short(join_parts(c.name, c.class_name or "", lvl + target, sep=" "), 40))
    return [f"WoW postavy: {list_or_none(items, len(chars))}"]


def character_names(db):
    return [c.name for c in service.all_characters(db)]


def hourly_sync(db):
    return service.sync_due(db)


INTEGRATIONS = ModuleIntegrations(
    changes=(ChangeSource(
        "wow", areas=frozenset({"wow"}),
        from_event=event_changes({"character": "/wow?wowchar={id}"}, {"wow.character.level_up": "WoW: nový level"}),
        from_activity=activity_changes({"wow_character": "/wow?wowchar={id}"}, "/wow"),
    ),),
    search=(SearchSource("wow", 92, search_characters),),
    entity_refs=(EntityRef("wow_character", "/wow?wowchar={id}"),),
    context=(
        ContextSection("wow", ("wow", "warcraft", "altik", "alty", "altu"), order=78, build=context_wow,
                       name_hints=character_names),
    ),
    hourly=(ScheduledStep("wow character sync", hourly_sync),),
    routers=(router,),
)
