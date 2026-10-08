"""Smlouvy příspěvků modulů (MRK-20, Platform 2.0 C) – co modul dává globálním agregátorům.

Malé typované dataclassy a obyčejné funkce, žádná abstraktní základní třída, žádné objevování za běhu.
Modul vyplní `ModuleIntegrations` ve vlastním souboru vedle svého kódu (`school_integrations.py`…) a
`module_registry.ModuleDef.integrations` ho na něj napojí obyčejným importem.

Rozdělení odpovědnosti (docs/module-framework.md):
- modul dodává DATA (co ukázat, české titulky, ref, href),
- agregátor drží POLITIKU (řazení, limity, dedupe, pořadí sekcí, rozpočet tokenů, izolace chyb, gating flagy).
Provider nikdy neřadí cizí moduly, neořezává globálně a nic nezapisuje.

Tento soubor nesmí importovat nic z aplikace (je listem grafu importů) – jinak by vznikly cykly mezi registrem
a agregátory, které registr používají.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Iterable

# ---------- vyhledávání (search_service) ----------

# (typ, id, titulek, podtitulek, extra slova, oblast, href) – stejný tvar jako dřív `_candidates()`.
SearchCandidate = tuple[str, int, str, str, str, str, str]


@dataclass(frozen=True)
class SearchSource:
    """Záznamy jednoho typu (nebo pár souvisejících typů) pro globální vyhledávání.

    `fetch(db, query)` vrací kandidáty; skóre, řazení, limit na typ a celkový limit dělá search_service.
    `order` = stabilní pořadí zdrojů (shoda skóre a titulku → pořadí kandidátů), nic víc.
    """
    name: str
    order: int
    fetch: Callable[[Any, str], Iterable[SearchCandidate]]


# ---------- režim Dnes (today_service) ----------

TodayFn = Callable[[Any], list]  # (today_service.TodayContext) -> list[TodayItem]


@dataclass(frozen=True)
class TodaySource:
    """Položky modulu pro Dnes. Každá část je volitelná; dedupe, řazení sekcí a limity dělá today_service.

    - timeline: záznamy v pražském dni D
    - overdue: po termínu / nevyřízené (sekce Pozornost; upozornění přidá today_service)
    - upcoming: příštích 7 dní
    - closed_refs: ref záznamů, které už nic nepotřebují (upozornění k nim se v Dnes nezobrazí)
    """
    name: str
    order: int
    timeline: TodayFn | None = None
    overdue: TodayFn | None = None
    upcoming: TodayFn | None = None
    closed_refs: Callable[[Any], set[str]] | None = None


@dataclass(frozen=True)
class EntityRef:
    """Jak otevřít záznam z refu „<typ>:<id>" (plánovač v Dnes, upozornění) a co s ním jde udělat z Dnes."""
    type: str
    href: str                                  # šablona s {id}, např. "/school?assignment={id}"
    planner_actions: tuple[str, ...] = ()      # akce řádku plánu v Dnes (Roadmap 4H), např. ("complete",)
    notification_source: bool = False          # upozornění s `source_type` tohoto typu se spojí se záznamem


# ---------- GET /dashboard (main.dashboard_get) ----------


@dataclass(frozen=True)
class DashboardSection:
    """Klíč payloadu GET /dashboard. `build(db, access)`; nedostupný modul = `empty` (tvar odpovědi stálý)."""
    key: str
    build: Callable[[Any, Any], Any]
    empty: Any = None


# ---------- AI kontext (context_service) ----------


@dataclass(frozen=True)
class ContextRequest:
    db: Any
    today: date
    local_now: datetime


@dataclass(frozen=True)
class ContextSection:
    """Oblast AI kontextu modulu: klíčová slova (routing + výběr sekcí), sekce CURRENT STATE a pokryté tooly.

    `order` = pořadí sekce v CURRENT STATE (None = oblast bez sekce, jen routing toolů – např. MFF).
    `name_hints(db)` = názvy záznamů, jejichž zmínka označí oblast (projekty práce, tanky).
    Implikovaná pravidla („plán" → škola, cíle…) a rozpočet tokenů zůstávají v context_service.
    """
    area: str
    keywords: tuple[str, ...]
    order: int | None = None
    build: Callable[[ContextRequest], list[str]] | None = None
    covered_tools: tuple[str, ...] = ()
    name_hints: Callable[[Any], Iterable[str]] | None = None


# ---------- Rychlé přidání (quick_add_service) ----------


@dataclass(frozen=True)
class QuickAddRule:
    """Jedno pravidlo klasifikace: `detect(text) -> jistota | None`. Pravidla se zkoušejí podle `priority`
    (nižší dřív, první shoda vyhrává) – deterministicky, stejně jako dřívější řetězec if v `classify()`."""
    priority: int
    kind: str
    detect: Callable[[Any], str | None]


@dataclass(frozen=True)
class QuickAddKind:
    """Druh Rychlého přidání: rozbor textu, ověření polí → (WRITE tool, argumenty) a český náhled.

    - parse(text, draft, now_utc, ctx): vyplní draft.fields / needs_input / warnings (ctx = předměty apod.)
    - to_tool_call(fields, draft, today, db) -> (tool, args); chyby přes draft.error()
    - display(fields, ctx, today) -> {title, subtitle, area}
    - context(db) -> dict: data navíc pro rozbor (např. předměty školy), načtou se jen pro rozpoznaný druh
    - output(ctx) -> dict: klíče navíc v odpovědi náhledu (např. „subjects" pro výběr předmětu)
    Zápis jde vždy přes existující WRITE tool a pending akci (quick_add_service), nikdy přímo.
    """
    kind: str
    parse: Callable[..., None]
    to_tool_call: Callable[..., tuple[str, dict]]
    display: Callable[..., dict]
    context: Callable[[Any], dict] | None = None
    output: Callable[[dict], dict] | None = None


# ---------- scheduler (scheduler_service) ----------


@dataclass(frozen=True)
class ScheduledStep:
    """Krok hodinového jobu, který patří modulu (idempotentní, omezený). `run(db)` vrací krátký výsledek do logu.
    Infrastrukturní kroky (notifikace, zálohy, monitoring) zůstávají globální ve scheduler_service."""
    name: str
    run: Callable[[Any], Any]


# ---------- souhrn příspěvků modulu ----------


@dataclass(frozen=True)
class ModuleIntegrations:
    search: tuple[SearchSource, ...] = ()
    today: tuple[TodaySource, ...] = ()
    entity_refs: tuple[EntityRef, ...] = ()
    dashboard: tuple[DashboardSection, ...] = ()
    context: tuple[ContextSection, ...] = ()
    quick_add_rules: tuple[QuickAddRule, ...] = ()
    quick_add_kinds: tuple[QuickAddKind, ...] = ()
    hourly: tuple[ScheduledStep, ...] = ()
    notes: dict[str, str] = field(default_factory=dict)  # volitelný popis pro docs/testy, nic nespouští


NO_INTEGRATIONS = ModuleIntegrations()

# Schopnost (module_registry.CAPABILITIES), která příspěvek gatuje. Hodinový krok patří ke kterékoli dostupnosti
# modulu (None = stačí, že je modul dostupný).
CONTRIBUTION_CAPABILITY: dict[str, str | None] = {
    "search": "search",
    "today": "today",
    "entity_refs": None,
    "dashboard": "dashboard",
    "context": "ai_context",
    "quick_add_rules": "quick_add",
    "quick_add_kinds": "quick_add",
    "hourly": None,
}
