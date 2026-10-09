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
    # MRK-13: denní osa dodaná agregátorem (poskytovatel nesmí importovat timeline_service ani registr);
    # volá se líně, jen když se sekce opravdu staví. None = osa není k dispozici.
    day_timeline: Callable[[], dict] | None = None


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


# ---------- „Co se změnilo" (change_feed, MRK-28) ----------

@dataclass(frozen=True)
class ChangeItem:
    """Jedna změna v přehledu „Co se změnilo" – stabilní tvar odpovědi GET /changes (docs/what-changed.md).
    `id` = „event:<id>" / „activity:<id>", `module_id` None = jádro, `source` = „event" | „activity"."""
    id: str
    occurred_at: str
    module_id: str | None
    entity_type: str | None
    entity_id: str | None
    kind: str
    title: str
    summary: str
    href: str | None
    source: str


@dataclass(frozen=True)
class ChangeDraft:
    """Co modul řekne o jedné změně; id, vlastníka, čas a zdroj doplní change_feed."""
    kind: str
    title: str
    entity_type: str | None = None
    entity_id: str | None = None
    summary: str = ""
    href: str | None = None


@dataclass(frozen=True)
class ChangeSource:
    """Změny modulu pro „Co se změnilo". Doménové události modulu (vlastník = `module_id` události) mapuje
    `from_event(event, title)`, kde `title` je shrnutí jeho projekce do Aktivity (payload události jména nenese);
    záznamy Aktivity oblastí `areas` (legacy toky bez události) mapuje `from_activity(row)`. None = položku
    nezobrazit. Řazení, dedupe, šum, filtry a limity drží change_feed."""
    name: str
    areas: frozenset[str] = frozenset()
    from_event: Callable[[Any, str | None], ChangeDraft | None] | None = None
    from_activity: Callable[[Any], ChangeDraft | None] | None = None


# Akce Aktivity → druh změny (stabilní slovník pro frontend); neznámá akce projde beze změny.
ACTIVITY_KINDS = {"create": "created", "update": "updated", "delete": "deleted", "complete": "completed",
                  "archive": "archived", "restore": "restored", "check": "updated", "snooze": "snoozed",
                  "cancel": "cancelled"}


def entity_slug(entity_type: str | None) -> str | None:
    """„WotGrind" → „wot_grind", „habit_entry" zůstane – Aktivita historicky míchá oba zápisy."""
    if not entity_type:
        return None
    out = []
    for i, ch in enumerate(entity_type):
        if ch.isupper() and i and entity_type[i - 1] != "_":
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def activity_changes(hrefs: dict[str, str], default_href: str | None = None) -> Callable[[Any], ChangeDraft | None]:
    """Běžné mapování řádku Aktivity: druh z akce, titulek = shrnutí, odkaz podle typu záznamu (`{id}` v šabloně).
    Smazaný záznam už otevřít nejde → bez odkazu."""
    def build(row) -> ChangeDraft | None:
        slug = entity_slug(row.entity_type)
        kind = ACTIVITY_KINDS.get(row.action_type, row.action_type)
        template = hrefs.get(slug or "", default_href)
        href = None
        if kind != "deleted" and template:
            href = template.format(id=row.entity_id) if "{id}" in template and row.entity_id is not None else (
                template.split("?")[0] if "{id}" in template else template)
        return ChangeDraft(kind=kind, title=row.summary, entity_type=slug,
                           entity_id=None if row.entity_id is None else str(row.entity_id), href=href)
    return build


def event_changes(hrefs: dict[str, str], fallback_titles: dict[str, str]) -> Callable[[Any, str | None], ChangeDraft | None]:
    """Běžné mapování doménové události `<modul>.<agregát>.<akce>`: druh = akce, odkaz podle agregátu."""
    def build(event, title: str | None) -> ChangeDraft | None:
        kind = event.type.rsplit(".", 1)[-1]
        template = hrefs.get(event.aggregate_type)
        href = None
        if template:
            href = template.format(id=event.aggregate_id) if "{id}" in template and event.aggregate_id else template
        return ChangeDraft(kind=kind, title=title or fallback_titles.get(event.type, event.type),
                           entity_type=event.aggregate_type, entity_id=event.aggregate_id, href=href)
    return build


# ---------- denní časová osa (timeline_service, MRK-13) ----------

@dataclass(frozen=True)
class TimelineItem:
    """Jedna položka denní osy – prezentační tvar (žádné ORM objekty). Odvozené, nikdy se neukládá.
    `starts_at` None nebo `all_day` = denní sekce (termín, celodenní); jinak časová položka (`ends_at` None = okamžik).
    `busy` = zdroj skutečně obsazuje čas (volné bloky dnes počítá jen Kalendář – docs/calendar.md)."""
    id: str
    kind: str                      # calendar_event | reminder | exam | assignment …
    title: str
    date: str                      # pražské datum dne osy (ISO)
    status: str                    # upcoming | now | past | due | done | open
    module_id: str | None = None   # None = jádro (doplní timeline_service podle vlastníka příspěvku)
    subtitle: str = ""
    starts_at: Any = None          # aware UTC datetime nebo None
    ends_at: Any = None
    all_day: bool = False
    href: str | None = None
    busy: bool = False


@dataclass
class TimelineRequest:
    db: Any
    day: date
    start: Any      # aware UTC začátek pražského dne
    end: Any        # aware UTC konec (23/24/25 h)
    now: Any        # aware UTC
    cache: dict[str, Any] = field(default_factory=dict)  # sdílená data v rámci jednoho požadavku


@dataclass(frozen=True)
class TimelineSource:
    """Položky modulu pro denní osu. `build(req)` → TimelineItem; `free_blocks(req, min_minutes)` → volitelně
    odvozené volné bloky (dnes jen Kalendář). Řazení, sekce, limity a vkládání volna drží timeline_service."""
    name: str
    order: int
    build: Callable[[TimelineRequest], list[TimelineItem]]
    free_blocks: Callable[[TimelineRequest, int], Any] | None = None


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
    changes: tuple[ChangeSource, ...] = ()
    timeline: tuple[TimelineSource, ...] = ()
    # REST modulu (fastapi.APIRouter). main.py připojí routery VŠECH modulů; vypnutý modul hlídá
    # main.require_module_available (404 podle `api_prefixes`) a auth platí stejně jako pro ostatní cesty.
    routers: tuple[Any, ...] = ()
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
    "changes": None,
    "timeline": "today",
    "routers": None,
}
