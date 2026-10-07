# Module Framework, Feature Flags & Domain Events (Platform 2.0)

Status: **proposal** – to be split into Linear issues. Principles: [architecture-principles.md](architecture-principles.md)
(P1–P18). Today's per-module checklist: [module-integration-checklist.md](module-integration-checklist.md).

Roadmap context:
`current bugs → production readiness → **Platform 2.0 (this doc)** → Habits pilot → Global Visual Refresh → Calendar
→ Fitness → Food → Life Admin → Intelligence → Voice → Smart Home / Mirror`

---

## 1. Why now (and why this does not break KISS/YAGNI)

The checklist deliberately said *"a checklist, not a framework"*, *"no runtime plugin registry"* and *"no event
bus"*. That was right at 5 modules. The rule of three (P2) is now met many times over:

- **School alone is wired by hand into 32 files**: 18 in the backend (`models`, `main`, `tools`, `tool_registry`,
  `read_queries`, `context_service`, `search_service`, `today_service`, `quick_add_service`, `briefing_snapshot`,
  `weekly_snapshot`, `weekly_review_service`, `planner_service`, `notifications_service`, `goal_history_service`,
  `mutation_service`, `ai`, `text_utils`) and 14 in the frontend (`navigation`, `areas`, `search`, `quickAdd`,
  `today`, `dashboardLayout`, `labels`, `activity`, `aiActions`, `widgets`, `QuickAddDialog`,
  `SearchHighlighter`, …).
- The roadmap has ~10 more modules (Habits, Calendar, Fitness, Food, Life Admin, Projects, Knowledge Base, Travel…).
  At ~30 touch points each, that is ~300 hand-made edits, and each one is a place to forget something.
- Feature flags ("hide Food from nav, Search, Today, Dashboard and AI") are impossible to implement reliably while
  every aggregation point has its own hard-coded list of modules.
- Jarvis companion, Desktop Jarvis (MRK-17), Smart Mirror, Voice and Home Assistant all need *the same* live
  stream of "something happened". Building it once is cheaper than five ad-hoc channels.

What stays the same (non-negotiable):

- **Static and explicit.** Modules are registered by a plain import in one registry file. No entry points, no
  directory scanning, no runtime plugin loading, no DI container.
- **Deterministic before AI (P7) and safe writes (P9)** are unchanged; the framework only decides *where* a
  module plugs in, not *how* writes are confirmed.
- **The aggregators keep their rules.** Search still ranks, Today still dedupes and caps, the tool router still
  routes. They just iterate over registered providers instead of hard-coded blocks.

---

## 2. Concepts

| Concept | One sentence |
|---|---|
| **Module** | A bounded life area (school, finance, habits…) with its own models, service, router and integrations. |
| **ModuleSpec** (backend manifest) | A frozen dataclass that declares the module's identity, flag and the providers it contributes. |
| **Module manifest** (frontend) | The TS counterpart: nav entry, icon, area style, widgets, Quick Add field defs, search params, labels. |
| **Provider** | A small pure-ish function the aggregator calls: `search_source`, `today_source`, `briefing_source`… |
| **Feature flag** | `enabled` state of a module, resolved once per request; disabled modules contribute nothing anywhere. |
| **Domain event** | An immutable fact (`school.assignment.completed`) written in the same transaction as the change. |
| **Event consumer** | Something that reacts to events: activity log, history, notifications, SSE stream, Jarvis, later HA. |

---

## 3. Backend

### 3.1 Layout for new modules

```
backend/
  module_registry.py          # the ONLY list of modules (explicit imports, fixed order)
  module_spec.py              # ModuleSpec + provider type definitions
  events.py                   # DomainEvent, emit(), consumer registry
  modules/
    habits/
      __init__.py             # MODULE = ModuleSpec(...)
      models.py               # SQLAlchemy models (imported by alembic/env.py via the registry)
      service.py              # create/update/delete/query – the only write path (REST + AI + Quick Add)
      router.py               # APIRouter, mounted under /habits
      integrations.py         # search/today/briefing/weekly/context providers, quick-add kind, tools
      events.py               # event type constants + payload builders
  tests/modules/habits/...
```

Existing modules (school, finance, work, wot, mff, goals, reminders, memory) **are not moved up front**. They get a
thin `ModuleSpec` in phase A (identity + flag only) and are migrated provider by provider when touched (P16).

### 3.2 ModuleSpec

```python
@dataclass(frozen=True)
class ModuleSpec:
    id: str                         # stable snake_case, == activity area, == frontend manifest id; never renamed
    label: str                      # Czech, e.g. "Návyky"
    core: bool = False              # core modules cannot be disabled (ai, reminders, system)
    default_enabled: bool = True    # used when no override exists (see §5)
    depends_on: tuple[str, ...] = ()  # hard deps: cannot enable without them (e.g. food → calendar, if ever needed)

    router: APIRouter | None = None
    models: tuple[type, ...] = ()   # for alembic/env.py and contract tests

    # integration providers – every one optional; omit what does not make sense (as with the checklist)
    search_sources: tuple[SearchSource, ...] = ()
    today_sources: tuple[TodaySource, ...] = ()
    briefing_sources: tuple[BriefingSource, ...] = ()
    weekly_sources: tuple[WeeklySource, ...] = ()
    planner_sources: tuple[PlannerSource, ...] = ()
    dashboard_summary: DashboardSummary | None = None   # contributes a key to GET /dashboard
    quick_add: tuple[QuickAddKind, ...] = ()
    tools: tuple[ToolSpec, ...] = ()                     # existing ToolSpec, areas=(id,)
    context: ContextProvider | None = None               # area keywords + CURRENT STATE section
    today_actions: tuple[TodayAction, ...] = ()
    notification_types: tuple[str, ...] = ()             # deliverable types this module may emit
    event_types: tuple[EventType, ...] = ()              # see §4; documented, version-tagged
    scheduler_jobs: tuple[JobSpec, ...] = ()             # isolated, idempotent, bounded (P10, P11, P13)
```

Provider signatures are the existing per-aggregator shapes, lifted out of the aggregators unchanged, e.g.:

```python
SearchSource = Callable[[Session, str], Iterable[SearchCandidate]]      # today's _candidates() tuple, named
TodaySource  = Callable[[TodayCtx], TodayContribution]                  # timeline / attention / upcoming items
BriefingSource = Callable[[Session, date], list[BriefingItem]]          # deterministic, capped, with refs
```

### 3.3 Registry

```python
# module_registry.py
from modules.habits import MODULE as HABITS
from legacy_modules import SCHOOL, FINANCE, WORK, WOT, MFF, GOALS, REMINDERS, MEMORY

MODULES: tuple[ModuleSpec, ...] = (SCHOOL, REMINDERS, GOALS, WORK, FINANCE, HABITS, WOT, MFF, MEMORY)

def enabled_modules(db) -> tuple[ModuleSpec, ...]: ...   # resolves flags (§5), cached per request
def module(id: str) -> ModuleSpec: ...
```

Order in `MODULES` is the default order for sections everywhere (CURRENT STATE, briefing, search groups). It replaces
`_AREA_SECTIONS_ORDER`, `GROUP_ORDER` and similar local lists.

### 3.4 How each aggregator changes

| Aggregator | Today | After |
|---|---|---|
| `search_service._candidates` | one hard-coded loop per entity | `for m in enabled: for src in m.search_sources: yield from src(db, q)` |
| `today_service` | `_school_items_today`, `_reminder_items_today`… | iterate `today_sources`; dedupe/caps stay in `today_service` |
| `briefing_snapshot` / `weekly_snapshot` | per-module blocks | iterate `briefing_sources` / `weekly_sources`; caps + grounding unchanged |
| `quick_add_service.classify` | fixed `KINDS` + keyword regexes | kinds contributed by modules, **explicit numeric priority** (still deterministic) |
| `context_service` / `tool_router` | `_AREA_WORDS`, `_AREA_SUMMARY_TOOLS` | from `m.context` and `m.tools`; only enabled modules |
| `main.py` dashboard | ~360 lines of aggregation | `{m.id: m.dashboard_summary(db) for m in enabled if m.dashboard_summary}` |
| `notifications_service` / `delivery_service` | per-type code | `notification_types` declare ownership; delivery rules unchanged |
| `scheduler_service` | 4 hand-registered jobs | core jobs stay; module jobs registered from `scheduler_jobs` of enabled modules |

Rules that keep this honest:

- Aggregators **own policy** (ranking, caps, dedupe, ordering, grounding). Providers **own data** (what to show,
  Czech titles, refs, hrefs). A provider never caps globally or reorders other modules.
- Providers are read-only. The only write path is the module's `service.py`, which REST, AI tools, Quick Add and
  Today actions all call (closes audit L7 for new modules).
- A failing provider is isolated: the aggregator logs the category and continues without that module (P10).

### 3.5 `GET /modules`

```json
[{ "id": "habits", "label": "Návyky", "enabled": true, "core": false, "depends_on": [] }, ...]
```

Single source of truth for the frontend's flag state. `PUT /modules/{id}` toggles a non-core module (§5).

---

## 4. Domain events

### 4.1 Model

```python
@dataclass(frozen=True)
class DomainEvent:
    type: str            # "<module>.<entity>.<verb>", e.g. "school.assignment.completed", "reminder.due"
    module: str          # == ModuleSpec.id
    ref: str | None      # "<entity_type>:<id>" – the same ref Today/planner/notifications already use
    payload: dict        # small, display-ready (title, due date…), JSON; never secrets or raw private blobs
    source: str          # user_context: "manual" | "ai_confirm" | "quick_add" | "today" | "scheduler" | "system"
    dedupe_key: str | None = None   # required for time-derived events (see 4.2)
    version: int = 1
```

Naming: past tense for facts (`created`, `updated`, `completed`, `reopened`, `deleted`), plain noun for time
events (`due`, `upcoming`, `overdue`, `streak_broken`). The type list lives in the module's `events.py` and is
declared in `ModuleSpec.event_types`; an undeclared type fails in tests, not in production.

### 4.2 Two kinds of events

1. **Fact events** come from a write. `service.py` calls `events.emit(db, event)` **before** `db.commit()`.
2. **Time events** (`school.exam.upcoming`, `reminder.due`) come from scheduler jobs. They need a `dedupe_key`
   (`"school.exam.upcoming:exam:12:2026-10-20"`) so that running a job twice emits once (P11).

### 4.3 Transactional outbox + consumers

```
service.py ── db.add(change) ── events.emit(db, e) ── db.commit()
                                   │
                                   ├─ in-transaction consumers (synchronous, same session, may fail the write)
                                   │     • activity log  (event → ActivityLog row via module's summary builder)
                                   │     • history tables (goal progress, grind completion, year-in-review facts)
                                   │     • INSERT domain_events (the outbox)
                                   │
                                   └─ after-commit consumers (never fail the write; own session; P10)
                                         • notifications (create once by dedupe key – fixes audit L5)
                                         • SSE broadcaster → Jarvis companion, Desktop Jarvis, Mirror
                                         • later: Home Assistant bridge, voice feedback
```

- **Activity Log becomes a consumer**, not the bus. Atomicity (FR-AL-1) is preserved because it still runs inside
  the write transaction. The activity row keeps its current shape; the module supplies `summary` and `delta`.
- `domain_events` table (Alembic, additive): `id` (monotonic PK), `occurred_at` (naive UTC), `type`, `module`, `ref`,
  `payload_json`, `source`, `dedupe_key` (UNIQUE, nullable), `version`.
- Retention: **keep them** (single user, tiny volume). They are the raw material for *What changed?*,
  retrospectives and Year in Review. Revisit only if the table exceeds ~1M rows.
- Existing `log_activity` call sites keep working. They are migrated to `emit` when their module is touched; no
  big-bang rewrite.

### 4.4 Live stream: `GET /events/stream` (SSE)

- Server-Sent Events over the existing session cookie auth. One-way is enough: clients act through normal REST.
- Each SSE message `id:` = `domain_events.id`. On reconnect the browser sends `Last-Event-ID`, the server replays
  the missed rows from the outbox (bounded, e.g. max 200 / 24 h), then streams live. No lost events across
  restarts, no extra broker.
- Filters: `?modules=school,reminders&types=*.completed`. Disabled modules are never streamed.
- Single Uvicorn worker (already required by APScheduler) means an in-process broadcaster is enough. Moving to
  several workers or a separate miniPC service later means swapping the broadcaster for Postgres `LISTEN/NOTIFY`,
  with the outbox and the contract unchanged.
- Device clients (Desktop Jarvis, Mirror) later get **scoped read-only tokens** for this endpoint instead of the
  PIN session. Out of scope for Platform 2.0, but the endpoint is designed so that a token can be added without
  changing the event format.

### 4.5 What Jarvis does with it

`frontend/lib/jarvisSignals.ts` stays the in-page store (MRK-16 is finished as is). A small `useDomainEvents()`
hook subscribes to SSE and maps events to signals, e.g. `*.completed → pulse success`, `reminder.due → mood warning`.
The mapping is a table in one file, which Desktop Jarvis (MRK-17) reuses.

---

## 5. Feature flags

### 5.1 Semantics

A module is **enabled** or **disabled**. Disabled means *invisible and inert, never data loss*:

| Surface | Disabled behaviour |
|---|---|
| Navigation / Ctrl+K pages | hidden |
| Module page `/habits` | shows a "Modul je vypnutý" state with a link to settings (no 404 – bookmarks stay friendly) |
| REST `/habits/*` | `404` with Czech `detail` (router not mounted for requests while disabled – checked by a dependency) |
| Search, Today, Dashboard, Briefing, Weekly, Planner | providers not called |
| Quick Add | kind not offered; text that only matches it → "unknown" (no fallback guessing) |
| AI | no tools, no CURRENT STATE section, area keywords ignored |
| Scheduler jobs, notifications | not run / not created; pending deliveries of that type are skipped |
| Events / SSE | not emitted (no writes happen anyway) and not streamed |
| Activity log & history | **still readable**; area label still resolves from the registry |
| Data | untouched; re-enabling restores everything |

`core` modules (`ai`, `reminders`, `system`) cannot be disabled. Enabling a module whose `depends_on` is disabled
is refused with a clear message.

### 5.2 Storage and resolution

1. `module_settings` table (`module_id` PK, `enabled`, `updated_at`), toggled from a Settings page via
   `PUT /modules/{id}` and logged as `system.module.enabled/disabled`.
2. If there is no row: env override `MODULE_<ID>_ENABLED` via `env_config.env_bool` (useful for dev and cloud
   sessions), else `ModuleSpec.default_enabled`.
3. Resolved once per request (`enabled_modules(db)`) and once per scheduler job run – never mid-request.

No percentage rollouts, no per-user targeting, no remote config: single user (P1).

---

## 6. Frontend

Next.js App Router needs physical route folders, so pages are not generated. Each module has:

```
frontend/modules/habits/
  manifest.ts        # nav, icon, area style, widgets, quick-add fields, search params, today action labels
  HabitsPage.tsx     # the page; app/habits/page.tsx is a 3-line wrapper with <ModuleGate id="habits">
  lib.ts + lib.test.mjs
frontend/lib/modules.ts   # explicit import list, mirrors backend MODULES order
```

```ts
export const habitsModule: ModuleManifest = {
  id: "habits",
  nav: { href: "/habits", label: "Návyky", keywords: ["návyk", "rutina", "streak", "pitný režim"] },
  icon: HabitsIcon,                       // line/duotone icon from the Visual Refresh set – no emoji
  area: { tone: "teal", label: "Návyky" },// token name, not raw Tailwind classes (Visual Refresh owns the palette)
  widgets: [{ id: "habits_today", title: "Návyky dnes", defaultOrder: 75, defaultSize: "small",
              allowedSizes: ["small", "medium"], usesDashboardData: true, component: HabitsTodayWidget }],
  quickAdd: [{ kind: "habit_log", label: "Záznam návyku", fields: [...], example: "vypil jsem 2 l vody" }],
  searchTargetParams: ["habit"],
  todayActionLabels: { habit_check: "Splněno" },
};
```

- `NAV_PAGES`, `AREA_STYLES`, `WIDGETS`, `FIELD_DEFS`/`KIND_*`, `SEARCH_TARGET_PARAMS` become **derived** from
  `lib/modules.ts` plus the remaining non-module entries (Dashboard, Today, Planner, Activity…).
- Flag state comes from `GET /modules` (one fetch in `AppShell`, cached), so hiding happens in one place.
- New widget ids are prefixed with the module id (`habits_today`). Existing ids stay as they are (they are persisted).
- This is where the **Global Visual Refresh** plugs in: icon, area tone, card/badge/status primitives are
  referenced by token from manifests. Refreshing the primitives restyles every module at once.

### Contract test (backend ↔ frontend)

A fixture `frontend/scripts/fixtures/modules.json` is generated from the real backend registry (same pattern as
the existing search/today fixtures). `lib/modules.test.mjs` asserts the same ids in the same order, a manifest for
every non-headless module, area tone and icon present, quick-add kinds matching the backend's, and widget ids
unique and prefixed.

---

## 7. Permissions (single-user scope)

"Permissions" here means *capabilities a module grants to non-UI actors*, declared in the spec:

- **AI:** which tools are READ vs WRITE (existing `ToolSpec.kind`); WRITE always goes through pending actions.
- **Today actions:** only the actions listed in `today_actions`, only for valid states.
- **Event stream clients:** which modules/types a device token may read (future, see §4.4).
- **Home Assistant (future):** a module may declare *allowlisted device actions*; irreversible ones (locks,
  valves) are always confirm-only. Jarvis never talks to devices directly: `Jarvis → validated action → HA`.

---

## 8. Rollout plan

Each phase is shippable on its own and keeps all existing tests green.

**Phase A – registry + flags without refactoring (small, immediate value)**
- `module_spec.py`, `module_registry.py`, thin `ModuleSpec` for the existing modules (id, label, core, default).
- `module_settings` migration, `GET/PUT /modules`, Settings toggle UI, `ModuleGate`.
- Enforce flags at the *existing* aggregation points by filtering on `area` (search results, Today items, dashboard
  keys, tool router areas, context areas, quick-add kinds, nav). Everything is already tagged with an area, so
  this works before any provider extraction.
- Tests: disabling `wot` removes it from nav, search, Today, dashboard, AI tools and context; data still there;
  re-enable restores it.

**Phase B – domain events + SSE**
- `events.py`, `domain_events` outbox migration, in-transaction activity consumer, after-commit dispatcher,
  `GET /events/stream` with `Last-Event-ID` replay.
- Convert **one** existing flow end to end as proof: assignment complete/reopen (also closes MRK-14's event side)
  and `reminder.due`.
- Jarvis companion subscribes via `useDomainEvents()`.

**Phase C – provider extraction**
- Search first (smallest, best tested), then Today, Quick Add, context/tools, briefing/weekly, dashboard.
- Per aggregator: move existing blocks into the owning module's `integrations.py` unchanged, switch the
  aggregator to iterate, and regenerate fixtures. No behaviour changes in the same PR.

**Phase D – Habits pilot (acceptance test of the framework)**
- Built entirely in `backend/modules/habits/`, `frontend/modules/habits/`, one Alembic revision and one
  `app/habits/page.tsx` wrapper.
- **Acceptance criterion:** outside those folders, the PR touches only the two registry files (+ migration,
  + generated fixture). If Habits needs edits in `search_service`, `today_service`, `context_service`, `main.py` …,
  the framework is not done: fix the framework, not Habits.
- Habits exercises every surface: Today (today's habits), Quick Add (`vypil jsem 2 l vody`), events
  (`habits.habit.checked`, `habits.streak.broken` as a time event), dashboard widget, AI read tool, flag.

**Afterwards**
- Update `module-integration-checklist.md` into a "how to fill a ModuleSpec" guide.
- Migrate legacy modules opportunistically when they are touched (School during MRK-14 follow-ups, WoT during
  MRK-12…). No dedicated big-bang migration.
- Calendar is the first large consumer. Its `Event` entity and a Quick Add kind with a higher priority than
  `work` for "od 14" / "ve 14:00" are the proper fix behind MRK-11.

---

## 9. Explicitly out of scope

- Runtime plugin loading, third-party modules, a marketplace.
- Generic CRUD / admin generator: each module still writes its own service and UI.
- Multi-user permissions or roles.
- External message broker (Redis, MQTT) for the app's own events. MQTT arrives with Home Assistant as a
  *consumer* of domain events, not as the bus.
- Rewriting existing modules just to match the new layout.

---

## 10. Open decisions

1. **Flag storage:** DB + Settings UI with an env override (proposed), or env only?
2. **Core set:** `ai`, `reminders`, `system`. Should `goals` also be core, given that automatic goals read other
   modules?
3. **Event retention:** keep forever (proposed) vs. a time window plus aggregates for Year in Review.
4. **Folder move:** keep legacy modules where they are and wrap them (proposed), or move them into `modules/` when
   they are first migrated?
5. **Habits scope for the pilot:** which 3–5 habits are real enough to use daily (rehab, water, skincare, reading,
   morning/evening routine)?
