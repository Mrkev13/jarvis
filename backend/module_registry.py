"""Moduly a jejich feature flagy (Roadmap 6C) – jediné místo, které říká „smí modul X dělat Y?".

Není to experimentovací platforma: žádná procenta, kohorty ani vzdálená konfigurace. Jen deterministické
zapnutí/vypnutí modulu přes prostředí aplikace:

    MODULE_<ID>_ENABLED=true|false     (1/true/yes/on, 0/false/no/off; prázdné nebo nesmysl = výchozí)

Modul je DOSTUPNÝ, když je `implemented` a jeho flag je zapnutý. Neimplementovaný modul (Food, Fitness…)
zůstane nedostupný i s flagem `true` – samotný flag nikdy neodkryje nehotovou stránku.

Schopnosti (`capabilities`) říkají, kam modul přispívá; schopnost platí jen pro dostupný modul:
- nav        – položka v navigaci (frontend; tady jen pro úplnost /modules)
- search     – záznamy v globálním vyhledávání (`entity_types` = `SearchResult.type`)
- quick_add  – druhy Rychlého přidání (`quick_add_kinds`)
- today      – položky Dnes (ref `"<entity_type>:<id>"`)
- dashboard  – sekce GET /dashboard a widgety
- ai_context – CURRENT STATE sekce (`context_areas`) a AI tooly těch oblastí

Co do žádného modulu nepatří (připomínky, paměť, plánovač, notifikace…), je jádro a je vždy dostupné.
Flagy řídí dostupnost, NE oprávnění: auth (`main.require_auth`) běží vždy dřív a zapnutý modul nic nepovoluje.

Frontend má zrcadlový registr `frontend/lib/modules.ts` (parita hlídaná testem `test_module_registry.py`).
Budoucí uživatelské preference: `ModuleAccess(flags)` dostane flagy už zúžené o volbu uživatele
(uživatel smí modul jen vypnout, nikdy zapnout to, co aplikace vypnula) – viz docs/module-feature-flags.md.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Mapping

from env_config import env_flag, parse_flag

log = logging.getLogger(__name__)

CAPABILITIES = ("nav", "search", "quick_add", "today", "dashboard", "ai_context")
ALL_CAPABILITIES = frozenset(CAPABILITIES)


@dataclass(frozen=True)
class ModuleDef:
    id: str
    label: str
    default_enabled: bool
    implemented: bool
    capabilities: frozenset[str] = frozenset()
    # Typy záznamů modulu = prefix refu „<typ>:<id>" (vyhledávání, Dnes, plánovač, notifikace).
    entity_types: frozenset[str] = frozenset()
    # Oblasti CURRENT STATE / AI toolů (context_service.AREA_*), ne štítky záznamů (Memory.area „fitness" apod.).
    context_areas: frozenset[str] = frozenset()
    # REST cesty modulu (přesná shoda nebo vše pod „<prefix>/").
    api_prefixes: tuple[str, ...] = ()
    quick_add_kinds: tuple[str, ...] = ()

    @property
    def env_name(self) -> str:
        return f"MODULE_{self.id.upper()}_ENABLED"


def _planned(module_id: str, label: str) -> ModuleDef:
    """Budoucí modul: zatím bez kódu i schopností, výchozí vypnutý."""
    return ModuleDef(module_id, label, default_enabled=False, implemented=False)


MODULES: tuple[ModuleDef, ...] = (
    ModuleDef("school", "Škola", default_enabled=True, implemented=True, capabilities=ALL_CAPABILITIES,
              entity_types=frozenset({"subject", "assignment", "exam"}), context_areas=frozenset({"school"}),
              api_prefixes=("/school",), quick_add_kinds=("exam", "assignment")),
    ModuleDef("work", "Práce", default_enabled=True, implemented=True, capabilities=ALL_CAPABILITIES,
              entity_types=frozenset({"work_session"}), context_areas=frozenset({"work"}),
              api_prefixes=("/work",), quick_add_kinds=("work",)),
    ModuleDef("finance", "Finance", default_enabled=True, implemented=True, capabilities=ALL_CAPABILITIES,
              entity_types=frozenset({"transaction"}), context_areas=frozenset({"finance"}),
              api_prefixes=("/finance",), quick_add_kinds=("finance",)),
    ModuleDef("goals", "Cíle", default_enabled=True, implemented=True,
              capabilities=ALL_CAPABILITIES - {"quick_add"},
              entity_types=frozenset({"goal"}), context_areas=frozenset({"goals"}),
              api_prefixes=("/goals", "/goal")),
    ModuleDef("wot", "World of Tanks", default_enabled=True, implemented=True,
              capabilities=ALL_CAPABILITIES - {"quick_add", "today"},
              entity_types=frozenset({"wot_grind", "wot_resource"}), context_areas=frozenset({"wot"}),
              api_prefixes=("/wot",)),
    ModuleDef("mff", "Marvel Future Fight", default_enabled=True, implemented=True,
              capabilities=ALL_CAPABILITIES - {"quick_add", "today"},
              entity_types=frozenset({"mff_character"}), context_areas=frozenset({"mff"}),
              api_prefixes=("/mff",)),
    _planned("food", "Jídlo"),
    _planned("fitness", "Fitness"),
    _planned("habits", "Návyky"),
    _planned("projects", "Projekty"),
    _planned("knowledge", "Znalosti"),
    _planned("car", "Auto"),
    _planned("travel", "Cestování"),
    _planned("entertainment", "Zábava"),
)

_warned: set[str] = set()


def resolve_flags(modules: Iterable[ModuleDef] = MODULES, env: Mapping[str, str] | None = None) -> dict[str, bool]:
    """Hodnoty flagů (bez ohledu na `implemented`). `env` = testy; jinak prostředí procesu (env_config)."""
    out: dict[str, bool] = {}
    for m in modules:
        value, valid = env_flag(m.env_name, m.default_enabled) if env is None else parse_flag(env.get(m.env_name), m.default_enabled)
        if not valid and m.env_name not in _warned:
            _warned.add(m.env_name)
            log.warning("module flags: %s has an invalid value – using default %s", m.env_name, m.default_enabled)
        out[m.id] = value
    return out


class ModuleAccess:
    """Odpovědi „je modul dostupný / smí přispět do X" pro jednu sadu flagů (čisté, bez I/O)."""

    def __init__(self, flags: Mapping[str, bool] | None = None, modules: Iterable[ModuleDef] = MODULES):
        self.modules = tuple(modules)
        self._by_id = {m.id: m for m in self.modules}
        self.flags = dict(flags) if flags is not None else resolve_flags(self.modules)
        self._by_entity = {t: m for m in self.modules for t in m.entity_types}
        self._by_context_area = {a: m for m in self.modules for a in m.context_areas}
        self._by_kind = {k: m for m in self.modules for k in m.quick_add_kinds}

    def get(self, module_id: str) -> ModuleDef | None:
        return self._by_id.get(module_id)

    def is_available(self, module_id: str) -> bool:
        m = self._by_id.get(module_id)
        return bool(m and m.implemented and self.flags.get(m.id, m.default_enabled))

    def allows(self, module_id: str, capability: str) -> bool:
        """Kanonická odpověď: smí modul `module_id` přispívat do `capability`? Neznámý modul = ne."""
        if capability not in ALL_CAPABILITIES:
            raise ValueError(f"unknown capability: {capability}")
        m = self._by_id.get(module_id)
        return bool(m and capability in m.capabilities and self.is_available(m.id))

    def _allows_owner(self, owner: ModuleDef | None, capability: str) -> bool:
        # Co nepatří žádnému modulu, je jádro → vždy povoleno.
        return owner is None or self.allows(owner.id, capability)

    def allows_entity(self, entity_type: str | None, capability: str) -> bool:
        return self._allows_owner(self._by_entity.get(entity_type or ""), capability)

    def allows_ref(self, ref: str | None, capability: str) -> bool:
        """Ref „exam:12" / „goal:3"; ref bez známého typu (planner:1, notification:5) = jádro."""
        return self.allows_entity((ref or "").partition(":")[0], capability)

    def allows_context_area(self, area: str | None, capability: str = "ai_context") -> bool:
        return self._allows_owner(self._by_context_area.get(area or ""), capability)

    def allows_quick_add_kind(self, kind: str | None) -> bool:
        return self._allows_owner(self._by_kind.get(kind or ""), "quick_add")

    def module_for_path(self, path: str) -> ModuleDef | None:
        for m in self.modules:
            if any(path == p or path.startswith(p + "/") for p in m.api_prefixes):
                return m
        return None

    def allows_path(self, path: str) -> bool:
        m = self.module_for_path(path)
        return m is None or self.is_available(m.id)

    def public_config(self) -> list[dict]:
        """Bezpečný výpis pro klienta – jen id, název a booleovské hodnoty (žádné env hodnoty ani tajemství)."""
        return [
            {
                "id": m.id,
                "label": m.label,
                "available": self.is_available(m.id),
                "capabilities": [c for c in CAPABILITIES if self.allows(m.id, c)],
            }
            for m in self.modules
        ]


def current_access() -> ModuleAccess:
    """Flagy z aktuálního prostředí (čte se při každém volání – levné a testovatelné přes patch.dict)."""
    return ModuleAccess()
