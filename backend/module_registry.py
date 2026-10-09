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

MRK-18 A2 – runtime nastavení. Zapnutí modulu se určuje JEDINÝM resolverem (`resolve_states`):

    1. prostředí  MODULE_<ID>_ENABLED s platnou hodnotou  → vynuceno (locked, Nastavení ho nezmění)
    2. databáze   řádek v `module_settings`               → volba z Nastavení
    3. manifest   `ModuleDef.default_enabled`

Chybějící/prázdná proměnná = žádné vynucení. Nesmyslná hodnota („ture") = také žádné vynucení (A1 politika:
překlep nesmí potichu schovat modul) – jen varování v logu, platí DB/manifest. `implemented=False` vždy vyhrává.
Frontend stav čte za běhu z GET /modules (žádné build-time flagy).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

import finance_integrations
import goals_integrations
import mff_integrations
import school_integrations
import work_integrations
import wot_integrations
from modules.habits import integrations as habits_integrations
from modules.calendar import integrations as calendar_integrations
from modules.fitness import integrations as fitness_integrations
from core_integrations import CORE_INTEGRATIONS
from env_config import parse_flag
from module_contracts import CONTRIBUTION_CAPABILITY, NO_INTEGRATIONS, ModuleIntegrations

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
    # Moduly, bez kterých tento nedává smysl (zatím žádné; GET /modules je jen hlásí).
    depends_on: tuple[str, ...] = ()
    # MRK-20: co modul dodává globálním agregátorům (search, Dnes, dashboard, AI kontext, Rychlé přidání,
    # hodinový job) – `module_contracts.ModuleIntegrations` z `<modul>_integrations.py`. Agregátory se ptají
    # přes `ModuleAccess.contributions(...)`, takže vypnutý modul nepřispívá nikam a nový modul nevyžaduje
    # úpravu agregátorů.
    integrations: ModuleIntegrations = NO_INTEGRATIONS
    # MRK-19: doménové události modulu `<modul>.<agregát>.<akce>`; nedeklarovaný typ `append_domain_event` odmítne.
    event_types: frozenset[str] = frozenset()

    @property
    def env_name(self) -> str:
        return f"MODULE_{self.id.upper()}_ENABLED"


def _planned(module_id: str, label: str) -> ModuleDef:
    """Budoucí modul: zatím bez kódu i schopností, výchozí vypnutý."""
    return ModuleDef(module_id, label, default_enabled=False, implemented=False)


MODULES: tuple[ModuleDef, ...] = (
    ModuleDef("school", "Škola", default_enabled=True, implemented=True, capabilities=ALL_CAPABILITIES,
              entity_types=frozenset({"subject", "assignment", "exam", "study_material", "study_course"}),
              context_areas=frozenset({"school", "school_materials"}),
              api_prefixes=("/school",), quick_add_kinds=("exam", "assignment"),
              integrations=school_integrations.INTEGRATIONS,
              event_types=frozenset({"school.assignment.completed", "school.assignment.reopened",
                                     "school.exam.closed", "school.exam.reopened",
                                     "school.material.created", "school.material.updated",
                                     "school.material.source_missing", "school.material.restored"})),
    ModuleDef("work", "Práce", default_enabled=True, implemented=True, capabilities=ALL_CAPABILITIES,
              entity_types=frozenset({"work_session"}), context_areas=frozenset({"work"}),
              api_prefixes=("/work",), quick_add_kinds=("work",), integrations=work_integrations.INTEGRATIONS),
    ModuleDef("finance", "Finance", default_enabled=True, implemented=True, capabilities=ALL_CAPABILITIES,
              entity_types=frozenset({"transaction"}), context_areas=frozenset({"finance"}),
              api_prefixes=("/finance",), quick_add_kinds=("finance",), integrations=finance_integrations.INTEGRATIONS),
    ModuleDef("goals", "Cíle", default_enabled=True, implemented=True,
              capabilities=ALL_CAPABILITIES - {"quick_add"},
              entity_types=frozenset({"goal"}), context_areas=frozenset({"goals"}),
              api_prefixes=("/goals", "/goal"), integrations=goals_integrations.INTEGRATIONS),
    ModuleDef("wot", "World of Tanks", default_enabled=True, implemented=True,
              capabilities=ALL_CAPABILITIES - {"quick_add", "today"},
              # wot_replay = Replay Library (Game Enrichment C) ve vyhledávání; /wot pokrývá i /wot/replays,
              # /wot/milestones a /wot/screenshots (milníky ani splnění se nevyhledávají – nemají vlastní typ výsledku).
              entity_types=frozenset({"wot_grind", "wot_resource", "wot_replay"}), context_areas=frozenset({"wot"}),
              api_prefixes=("/wot",), integrations=wot_integrations.INTEGRATIONS),
    ModuleDef("mff", "Marvel Future Fight", default_enabled=True, implemented=True,
              capabilities=ALL_CAPABILITIES - {"quick_add", "today"},
              entity_types=frozenset({"mff_character"}), context_areas=frozenset({"mff"}),
              api_prefixes=("/mff",), integrations=mff_integrations.INTEGRATIONS),
    _planned("food", "Jídlo"),
    ModuleDef("fitness", "Fitness", default_enabled=True, implemented=True,
              capabilities=frozenset({"nav", "search", "today", "ai_context"}),
              entity_types=frozenset({"fitness_exercise", "fitness_workout", "fitness_rehab_exercise", "fitness_rehab_session"}),
              context_areas=frozenset({"fitness"}), api_prefixes=("/fitness",),
              integrations=fitness_integrations.INTEGRATIONS, event_types=frozenset(fitness_integrations.EVENTS)),
    # MRK-21: první modul postavený celý v balíčku modules/habits/ (pilot rámce, docs/habits.md).
    ModuleDef("habits", "Návyky", default_enabled=True, implemented=True,
              capabilities=frozenset({"nav", "search", "today", "dashboard", "ai_context"}),
              entity_types=frozenset({"habit"}), context_areas=frozenset({"habits"}), api_prefixes=("/habits",),
              integrations=habits_integrations.INTEGRATIONS,
              event_types=frozenset({"habits.entry.done", "habits.entry.skipped"})),
    ModuleDef("calendar", "Kalendář", default_enabled=True, implemented=True,
              capabilities=frozenset({"nav", "search", "today", "ai_context"}),
              entity_types=frozenset({"calendar_event"}), context_areas=frozenset({"calendar"}), api_prefixes=("/calendar",),
              integrations=calendar_integrations.INTEGRATIONS,
              event_types=frozenset({"calendar.event.created", "calendar.event.updated", "calendar.event.cancelled",
                                     "calendar.event.source_missing", "calendar.event.restored"})),
    _planned("projects", "Projekty"),
    _planned("knowledge", "Znalosti"),
    _planned("car", "Auto"),
    _planned("travel", "Cestování"),
    _planned("entertainment", "Zábava"),
)

SOURCE_ENV = "env"
SOURCE_DB = "db"
SOURCE_DEFAULT = "default"

_warned: set[str] = set()


@dataclass(frozen=True)
class ModuleState:
    """Rozhodnutý stav jednoho modulu: hodnota flagu a odkud pochází (env vynucuje = locked)."""
    enabled: bool
    source: str

    @property
    def locked(self) -> bool:
        return self.source == SOURCE_ENV


def env_override(module: ModuleDef, env: Mapping[str, str | None]) -> bool | None:
    """Vynucení z prostředí: True/False jen pro přítomnou PLATNOU hodnotu; jinak None (nevynuceno)."""
    raw = env.get(module.env_name)
    if raw is None or not str(raw).strip():
        return None
    value, valid = parse_flag(raw, module.default_enabled)
    if not valid:
        if module.env_name not in _warned:
            _warned.add(module.env_name)
            log.warning("module flags: %s has an invalid value – ignored (no override)", module.env_name)
        return None
    return value


def resolve_states(modules: Iterable[ModuleDef] = MODULES, env: Mapping[str, str | None] | None = None,
                   overrides: Mapping[str, bool] | None = None) -> dict[str, ModuleState]:
    """Kanonický resolver A2: prostředí > databáze > manifest. `env`/`overrides` = testy; jinak proces a DB."""
    env = os.environ if env is None else env
    overrides = db_overrides() if overrides is None else overrides
    out: dict[str, ModuleState] = {}
    for m in modules:
        forced = env_override(m, env)
        if forced is not None:
            out[m.id] = ModuleState(forced, SOURCE_ENV)
        elif m.id in overrides:
            out[m.id] = ModuleState(bool(overrides[m.id]), SOURCE_DB)
        else:
            out[m.id] = ModuleState(m.default_enabled, SOURCE_DEFAULT)
    return out


def resolve_flags(modules: Iterable[ModuleDef] = MODULES, env: Mapping[str, str] | None = None,
                  overrides: Mapping[str, bool] | None = None) -> dict[str, bool]:
    """Hodnoty flagů (bez ohledu na `implemented`) – zkratka nad `resolve_states`."""
    return {mid: st.enabled for mid, st in resolve_states(modules, env, overrides).items()}


# ---------- uložené volby (module_settings) ----------
# Jeden proces (uvicorn --workers 1) → stačí cache v paměti: zápis přes `save_override` ji hned obnoví,
# TTL jen pojistka pro ruční zásah do DB. Chyba DB (chybějící tabulka před migrací, výpadek) = poslední známý
# stav, jinak žádné overridy → manifest/env, nikdy výjimka v gatingu požadavku.
DB_CACHE_TTL_SECONDS = 30.0

try:
    from database import SessionLocal  # noqa: E402  (testy patchují module_registry.SessionLocal)
except Exception:  # pragma: no cover - import bez DB_URL
    SessionLocal = None  # type: ignore[assignment]

_cache_lock = threading.Lock()
_cache: tuple[float, dict[str, bool]] | None = None
_clock: Callable[[], float] = time.monotonic


def invalidate_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None


def _load_from_db() -> dict[str, bool]:
    from models import ModuleSetting
    db = SessionLocal()
    try:
        known = {m.id for m in MODULES}
        return {row.module_id: bool(row.enabled) for row in db.query(ModuleSetting).all() if row.module_id in known}
    finally:
        db.close()


def db_overrides() -> dict[str, bool]:
    global _cache
    with _cache_lock:
        if _cache is not None and _clock() - _cache[0] < DB_CACHE_TTL_SECONDS:
            return dict(_cache[1])
        previous = _cache
    try:
        loaded = _load_from_db()
    except Exception as exc:  # noqa: BLE001 - gating nesmí spadnout kvůli nastavení
        if "module_settings_db" not in _warned:
            _warned.add("module_settings_db")
            log.warning("module settings: DB overrides unavailable (%s) – using env/manifest", type(exc).__name__)
        return dict(previous[1]) if previous else {}
    with _cache_lock:
        _cache = (_clock(), loaded)
    return dict(loaded)


def save_override(db, module_id: str, enabled: bool | None) -> None:
    """Uloží volbu z Nastavení (jen tabulka module_settings, data modulu se nemění). `None` nebo hodnota
    shodná s manifestem = žádný řádek (výchozí stav se do DB neduplikuje). Commit dělá volající."""
    from models import ModuleSetting
    module = next((m for m in MODULES if m.id == module_id), None)
    if module is None:
        raise KeyError(module_id)
    row = db.get(ModuleSetting, module_id)
    if enabled is None or enabled == module.default_enabled:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(ModuleSetting(module_id=module_id, enabled=enabled))
    else:
        row.enabled = enabled


class ModuleAccess:
    """Odpovědi „je modul dostupný / smí přispět do X" pro jednu sadu flagů (čisté, bez I/O)."""

    def __init__(self, flags: Mapping[str, bool] | None = None, modules: Iterable[ModuleDef] = MODULES,
                 states: Mapping[str, ModuleState] | None = None):
        self.modules = tuple(modules)
        self._by_id = {m.id: m for m in self.modules}
        if states is None:
            states = ({mid: ModuleState(bool(v), SOURCE_DEFAULT) for mid, v in flags.items()} if flags is not None
                      else resolve_states(self.modules))
        self.states = dict(states)
        self.flags = {mid: st.enabled for mid, st in self.states.items()}
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

    def contributes(self, module_id: str, kind: str) -> bool:
        """Smí modul přispět příspěvkem druhu `kind` (`module_contracts.CONTRIBUTION_CAPABILITY`)?"""
        capability = CONTRIBUTION_CAPABILITY[kind]
        return self.allows(module_id, capability) if capability else self.is_available(module_id)

    def contributions(self, kind: str) -> list[tuple[str | None, object]]:
        """MRK-20: příspěvky druhu `kind` od jádra (vlastník None, vždy) a od modulů, které smí přispět.
        Pořadí: jádro, pak moduly v pořadí registru; agregátor si řadí sám (pořadí zdrojů, sekcí…)."""
        out: list[tuple[str | None, object]] = [(None, item) for item in getattr(CORE_INTEGRATIONS, kind)]
        for m in self.modules:
            if self.contributes(m.id, kind):
                out.extend((m.id, item) for item in getattr(m.integrations, kind))
        return out

    def state(self, module_id: str) -> ModuleState:
        m = self._by_id[module_id]
        return self.states.get(module_id) or ModuleState(m.default_enabled, SOURCE_DEFAULT)

    def public_config(self) -> list[dict]:
        """Bezpečný výpis pro klienta – id, název, booleovské hodnoty a zdroj (žádné env hodnoty ani tajemství)."""
        out = []
        for m in self.modules:
            st = self.state(m.id)
            out.append({
                "id": m.id,
                "label": m.label,
                "available": self.is_available(m.id),
                "enabled": st.enabled,
                "source": st.source,
                "locked": st.locked,
                "implemented": m.implemented,
                "default_enabled": m.default_enabled,
                "depends_on": list(m.depends_on),
                "capabilities": [c for c in CAPABILITIES if self.allows(m.id, c)],
            })
        return out


def all_contributions(kind: str, modules: Iterable[ModuleDef] = MODULES) -> list[tuple[str | None, object]]:
    """Všechny registrované příspěvky bez ohledu na stav modulů – pro statické tabulky (klíčová slova routingu,
    pravidla klasifikace Rychlého přidání, klíče payloadu GET /dashboard). Gating dělá vždy `contributions`."""
    out: list[tuple[str | None, object]] = [(None, item) for item in getattr(CORE_INTEGRATIONS, kind)]
    for m in modules:
        out.extend((m.id, item) for item in getattr(m.integrations, kind))
    return out


def current_access() -> ModuleAccess:
    """Stav z prostředí (čte se při každém volání) + uložených voleb (cache v paměti) – viz `resolve_states`."""
    return ModuleAccess()
