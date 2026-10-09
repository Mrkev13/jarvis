# Module Framework (Platform 2.0)

Status: **phases A1/A2 (MRK-7, MRK-18) and C (MRK-20) implemented on `main`. The Habits pilot (MRK-21, phase D)
is the acceptance test, recorded in §10.** Phase B (domain events, MRK-19) is separate. This document describes what the code does **today**. The original
proposal (MRK-8 branch, `docs/module-framework.md` there) is kept as history. Where the two differ, this file wins.

Related: [module-feature-flags.md](module-feature-flags.md) (flags, runtime state, per-surface behaviour),
[module-integration-checklist.md](module-integration-checklist.md) (how to fill a `ModuleDef`),
[architecture-principles.md](architecture-principles.md).

## 1. Principles (unchanged)

- **Static and explicit.** One registry file per side (`backend/module_registry.py`, `frontend/lib/modules.ts`).
  Modules are wired by ordinary imports. No entry points, no folder scanning, no runtime plugin loading.
- **Existing modules stay where they are.** Their providers live next to them (`school_integrations.py` …).
  Nothing moved into `modules/` folders.
- **Aggregators own policy, modules own data.** Ranking, caps, dedupe, ordering, token budget, grounding, error
  isolation and gating stay in the aggregators. Providers return data (what to show, Czech titles, refs, hrefs).
  A provider never sorts other modules' items, never applies a global cap, and never writes.
- **Writes stay in module services / WRITE tools** behind the pending-action flow. Quick Add, Today actions and AI
  only *call* them.
- **Feature flags are the gate.** Every contribution is gated by the runtime module state (env > DB > default,
  MRK-18). A disabled module contributes nothing anywhere. Its data is untouched.

## 2. Pieces

| File | Role |
|---|---|
| `backend/module_contracts.py` | Typed contribution dataclasses (`SearchSource`, `TodaySource`, `EntityRef`, `DashboardSection`, `ContextSection`, `QuickAddRule`, `QuickAddKind`, `ScheduledStep`) and `ModuleIntegrations`. Leaf of the import graph. |
| `backend/<module>_integrations.py` | The module's providers: `INTEGRATIONS = ModuleIntegrations(...)`. Code moved unchanged from the aggregators. |
| `backend/core_integrations.py` | Contributions of **core** (reminders, memory, notifications). Always on, not a `ModuleDef`. |
| `backend/module_registry.py` | `ModuleDef(..., integrations=<module>_integrations.INTEGRATIONS)`, `ModuleAccess.contributions(kind)`, `all_contributions(kind)`. |
| `backend/modules/<id>/` | **New modules (MRK-21+)** live in one package: `models.py`, `service.py`, `router.py`, `integrations.py` (`INTEGRATIONS`). Legacy modules keep their root `<id>_integrations.py`. |
| Shared leaf helpers | `today_types.py` (`TodayItem`, `TodayContext`), `context_format.py` (CURRENT STATE line helpers), `quick_add_text.py` (Quick Add text/number/date/time core), `text_utils.fold_text` / `join_parts`. |
| `frontend/lib/modules.ts` | `MODULES` (mirror of the backend registry, parity-tested) and `MODULE_UI` (nav entry, search link params, Ctrl+K group order). |

**Import rule (tested):** provider files and shared leaf helpers never import an aggregator (`search_service`,
`today_service`, `context_service`, `quick_add_service`, `scheduler_service`, `main`, `tool_router`, `ai`,
briefing/weekly snapshots) or `module_registry`. That is what allows the registry to import the providers without
cycles.

## 3. Backend contribution contract

`ModuleDef.integrations: ModuleIntegrations`. Every field is optional. Leave out what does not apply.

| Field | Contract | Gated by capability | Aggregator keeps |
|---|---|---|---|
| `search: (SearchSource(name, order, fetch(db, q)),)` | yields `(type, id, title, subtitle, extra, area, href)` | `search` | scoring, sort, `PER_TYPE`, `MAX_RESULTS`, entity-type filter, per-source error isolation |
| `today: (TodaySource(name, order, timeline=, overdue=, upcoming=, closed_refs=),)` | each `fn(TodayContext) -> list[TodayItem]` (closed_refs → `set[str]`) | `today` | dedupe across sections, `MAX_ATTENTION`, `MAX_UPCOMING`, sorting, notifications merge, planner priorities, section errors |
| `entity_refs: (EntityRef(type, href, planner_actions=, notification_source=),)` | how a ref `"<type>:<id>"` opens (`href` with `{id}`), which Today actions a planner row gets, whether notifications with that `source_type` attach to the record | module available | planner + notification logic |
| `dashboard: (DashboardSection(key, build(db, access), empty=None),)` | one key of `GET /dashboard` | `dashboard` | payload shape (every registered key always present, `empty` when off), error isolation |
| `context: (ContextSection(area, keywords, order=, build=, covered_tools=, name_hints=),)` | AI area keywords; CURRENT STATE lines `build(ContextRequest) -> list[str]`; read tools the section covers; record names that mark the area (`name_hints(db)`) | `ai_context` | implied areas ("plán" → school, goals…), order/trim by token budget, memory, error isolation |
| `quick_add_rules: (QuickAddRule(priority, kind, detect(text) -> confidence \| None),)` | one classification rule; lower priority wins, first match | rules are static (see below) | rule ordering, "disabled kind → unknown", confidence policy |
| `quick_add_kinds: (QuickAddKind(kind, parse, to_tool_call, display, context=, output=),)` | parse into a `Draft`; validate → `(WRITE tool, args)`; Czech preview; optional extra data (`context(db)`) and response keys (`output(ctx)`) | `quick_add` | response shape, pending-action prepare/confirm, `QuickAddInvalid` |
| `hourly: (ScheduledStep(name, run(db)),)` | idempotent, bounded step of the hourly job | module available | scheduling, commit/rollback per step, infrastructure steps |
| `routers: (APIRouter,)` (MRK-21) | the module's REST routes under its `api_prefixes` | always mounted; disabled → 404 via `require_module_available` | `main.py` mounts every registered router; app-level auth + module gate apply (tested) |
| `timeline: (TimelineSource,)` (MRK-13) | the module's items of one Prague day as `TimelineItem`s (timed or day-section); optional `free_blocks(req, min_minutes)` | `today` | `timeline_service.get_day_timeline` collects, orders, sections, caps and adds free blocks; the AI context gets it via `ContextRequest.day_timeline` (providers never import the service) |

Static vs gated tables. Classification inputs are built from **all** registered modules (`all_contributions`):
AI area keywords and Quick Add rules. A text that only matches a disabled module therefore becomes "unknown"
instead of being guessed as another kind, and tool routing behaves the same without DB access. Everything that
**produces output** goes through `access.contributions(kind)`, so disabled modules produce nothing.

Example (abridged, real file):

```python
# backend/work_integrations.py
INTEGRATIONS = ModuleIntegrations(
    search=(SearchSource("work", 50, search_work),),
    dashboard=(DashboardSection("work", lambda db, access: get_work_with_goal(db)),),
    context=(ContextSection("work", ("prac", "odprac", "hodin", ...), order=50, build=context_work,
                            covered_tools=("get_work_summary",), name_hints=project_names),),
    quick_add_rules=(QuickAddRule(40, "work", detect_work_keyword), QuickAddRule(50, "work", detect_work_hours)),
    quick_add_kinds=(QuickAddKind("work", parse_work, work_tool_call, work_display),),
)
```

Numeric orders in use (keep gaps for new modules):

| | school | reminders (core) | notifications (core) | goals | work | finance | memory (core) | wot | mff |
|---|---|---|---|---|---|---|---|---|---|
| search source order | 10 | 40 | – | 70 | 50 | 60 | 80 | 90 | 100 |
| Today source order | 20 | 10 | – | – | – | – | – | – | – |
| CURRENT STATE order | 10 | 20 | 30 | 40 | 50 | 60 | – | 70 | (no section) |
| Quick Add rule priority | 20 exam, 30 assignment | 10 keyword, 60 time | – | – | 40 keyword/rate, 50 hours | 70 money/keyword, 80 bare number | – | – | – |

The orders reproduce the old hard-coded sequences exactly. A golden comparison against `main` on the same seeded DB
(search, Today, AI context, 32 Quick Add texts plus `to_tool_call`, `/dashboard`) produced identical output.

## 4. Frontend manifest

`frontend/lib/modules.ts`:
- `MODULES`: id, label, default, implemented, capabilities, entity types, routes, Quick Add kinds. One line per
  module. The backend parity test reads it.
- `MODULE_UI[id]`: `nav { href, label, keywords, order }`, `searchParams` (record params of the module's hrefs),
  `searchGroupOrder`. Added in MRK-21, all pure data:
  - `area` (badge colour classes)
  - `typeLabels` (Today row type)
  - `todayActions` (entity type → action → `{button, ariaLabel, success, path, body}`). The Today page runs these
    through one generic path in `useTodayActions`.
  - `widgets` (widget defs; `WIDGETS = CORE_WIDGETS + MODULE_WIDGETS`). The React components go in
    `frontend/modules/registry.tsx` under the same id.
- New modules keep their manifest in `frontend/modules/<id>/manifest.ts` and their page and components in the same
  folder. `app/<route>/page.tsx` is a one-line wrapper.

Derived from the manifest (core entries stay local):
- `NAV_PAGES` (`lib/navigation.ts`): core pages before and after, module pages sorted by `nav.order`. Used by the
  sidebar, mobile menu and Ctrl+K pages.
- `SEARCH_TARGET_PARAMS`, `GROUP_ORDER` (`lib/search.ts`).
- Quick Add `KIND_AREAS` / `KIND_HREFS` (`lib/quickAdd.ts`): area = owning module, page = its nav href.

Runtime flags come from `GET /modules` (MRK-18). `ModuleAccess` filters all of the above.

## 5. What stays global (by design)

- Core contributions: reminders, memory, notifications (`core_integrations.py`); core pages (Řídicí centrum, Dnes,
  Týdenní přehled, Plánovač, Aktivita, Paměť, AI, Nastavení).
- Aggregator policy (§3 last column). The cross-area **implied rules** in `context_service.classify_areas` ("plán",
  "přehled", work → finance + goals) are global policy that names areas, not module data.
- Infrastructure jobs: notifications generation, backups, monitoring, reminder delivery, Daily Briefing / Weekly
  Review jobs (`scheduler_service`).
- Auth, the module REST gate (`require_module_available`), `GET /modules`.

## 6. Migrated integrations (MRK-20)

| Surface | Before (central file, modules referenced) | After |
|---|---|---|
| Search | `search_service._candidates()`: school, reminders, work, finance, goals, memory, wot (grind + replay), mff | `ModuleIntegrations.search` per module + core |
| Today | `today_service`: `_school_items_today`, `_reminder_items_today`, `_overdue_items`, `_closed_refs`, `build_upcoming`, `_ref_href`, `_notification_ref`, planner `complete` for assignments | `ModuleIntegrations.today` + `entity_refs` |
| `GET /dashboard` | `main.py`: `_top_active_goals`, `_get_work_with_goal`, `_get_finance_with_goal`, `_get_upcoming`, `_get_wot_quick_status`, `_get_mff_quick_status` + `shows("<id>")` per key | `ModuleIntegrations.dashboard` (old `main._get_*` names kept as aliases) |
| AI context | `context_service`: `_AREA_WORDS`, `_school/_work/_finance/_goal/_wot/_reminder/_notification_lines`, `_AREA_SECTIONS_ORDER`, `_COVERED_TOOLS`, project/tank name queries | `ModuleIntegrations.context` (+ core) |
| Quick Add | `quick_add_service`: `KINDS`, `classify()` if-chain, parse/display/`to_tool_call` branches, keyword regexes, category rules | `quick_add_rules` + `quick_add_kinds`; shared core in `quick_add_text.py` |
| Scheduler | `scheduler_service._run_hourly_job` calls the goal snapshot directly | goals `ScheduledStep`; failures isolated per step |
| Frontend nav / search | `NAV_PAGES` module entries, `SEARCH_TARGET_PARAMS`, `GROUP_ORDER`, `KIND_AREAS`, `KIND_HREFS` | derived from `MODULES` + `MODULE_UI` |

Gating that MRK-7 had added by hand in these places (`shows("wot")`, `allows_context_area`, the Quick Add
check, Today `gate_items`) is now implied by `contributions()`. The entity-type and ref checks remain as a second
line of defence.

## 7. Remaining legacy / manual integration points (later cleanup)

| Place | Modules referenced | Why still manual | Suggested next step |
|---|---|---|---|
| `backend/main.py` REST routes of **legacy** modules | school, work, finance, goals, wot, mff | Router split (MRK-20 step 7) is a large move with no behaviour change. **New modules already use `ModuleIntegrations.routers`** (MRK-21). | move each legacy module's routes into `routers` (start with WoT) |
| `tool_registry.py`, `tools.py`, `read_queries.py` | all | AI tool specs/executors; already **gated** through `ToolSpec.areas` → `context_areas` (`tool_router._ordered`) | `ModuleIntegrations.tools` once tool specs move per module |
| `briefing_snapshot.py`, `weekly_snapshot.py` (+ `_strip_refs` lists in `briefing_service` / `weekly_review_service`) | school, reminders, goals, finance, work | One monolithic snapshot with cross-module caps, grounding and forecasts. No clean, low-risk provider contract yet. **Not gated by module state** (pre-existing, same as on `main` before MRK-20). | `briefing_sources` / `weekly_sources` with refs; gate by `today` / new `briefing` capability |
| `planner_service.py`, `notifications_service.py` | school, goals, work, finance | Deterministic candidate rules per type, used by planner, Today, dashboard and notifications | `planner_sources`, `notification_types` |
| `POST /today/actions/prepare` + reminder/assignment branches in `useTodayActions` | school, reminders | Legacy pending-action flows. **New modules declare `MODULE_UI.todayActions`** and call their own endpoint (MRK-21). | migrate when those flows are touched |
| `mutation_service` EntityDefs | school, finance, work, goals, wot, mff | AI modify/undo definitions | contribute EntityDefs per module |
| `ai.py` system prompt | names modules | static prompt text | generate the module list from available modules |
| Frontend `lib/areas.ts` (`AREA_STYLES`) | all + memory labels | area colours/labels also label memories and goals. **New modules: `MODULE_UI.area` + module label fallback** (MRK-21). | tone tokens (Visual Refresh) |
| Frontend `CORE_WIDGETS` + `components/dashboard/widgets.tsx` | goals, school, work, finance, wot, mff | Legacy widgets with persisted ids. **New modules use `MODULE_UI.widgets` + `modules/registry.tsx`** (MRK-21). | move legacy widgets when touched |
| Frontend `quickAdd.ts` `QuickAddKind` union, `KIND_LABELS`, `FIELD_DEFS`, examples | kinds | typed form definitions | `MODULE_UI.quickAdd` |
| Frontend `today.ts`, `labels.ts`, `activity.ts`, `aiActions.ts` | various | display labels | per-module label maps |
| `models.py` + Alembic | all | one declarative Base, one migration chain | keep (models may move next to modules later) |

## 8. Adding a module – files touched (as proven by Habits, MRK-21)

**Module-local, new files:**
- `backend/modules/<id>/` with `models.py`, `service.py`, `router.py` and `integrations.py`
- `frontend/modules/<id>/` with `manifest.ts`, `lib.ts` + `lib.test.mjs`, the page and the widget components
- `frontend/app/<route>/page.tsx` (one-line wrapper)
- `backend/tests/test_<id>.py`

**Registry / shared, edited (one line or one entry each):**

| File | Change | Needed when |
|---|---|---|
| `backend/module_registry.py` | full `ModuleDef(..., integrations=<id>_integrations.INTEGRATIONS)` + one import | always |
| `frontend/lib/modules.ts` | the `MODULES` line + `MODULE_UI.<id>` (imported from the manifest) | always |
| `backend/models.py` | one import line + `MODULE_MODELS` (registers tables for Alembic, `create_all`, drift test) | when it stores data |
| `backend/alembic/versions/…` + `test_alembic_migration.py` table set | additive migration and its round-trip case | when it stores data |
| `frontend/modules/registry.tsx` | one entry per widget component | only with a dashboard widget |
| `backend/tool_registry.py` (+ `tools.py`/`read_queries.py`) | AI tools | only with AI tools |
| `frontend/lib/quickAdd.ts` | kind union, label, `FIELD_DEFS`, example | only with Quick Add (still central, see §7) |

**No edits needed** (verified by Habits):
- **Aggregators:** `search_service`, `today_service`, `context_service`, `quick_add_service`, `scheduler_service`,
  `main.py` (routes and `dashboard_get`).
- **Frontend shared lists:** `lib/navigation.ts`, `lib/search.ts`, `lib/today.ts`, `hooks/useTodayActions.ts`,
  `app/today/page.tsx`, `lib/dashboardLayout.ts`, `app/page.tsx`, `lib/areas.ts`.

One snapshot test lists the visible navigation on purpose (`lib/moduleFramework.test.mjs`) and is updated when
navigation changes.

## 9. Tests that keep it honest

- `backend/tests/test_module_framework.py`:
  - contributions are discovered from `ModuleDef`; no duplicate sources, keys, areas, kinds or priorities
  - manifest and providers agree
  - a disabled module contributes nothing; core is always present
  - search sources only return the module's own entity types
  - aggregators contain no module models or ids (AST check)
  - provider files are import leaves; every aggregator imports first without a cycle
  - the fake `alpha` module works end to end (search, Today, `/dashboard`, AI context, Quick Add "zítra k obědu lasagne", hourly job), and so does its disabled variant
  - failing providers are isolated
  - global ranking, caps and rule order hold
- `backend/tests/test_module_registry.py`: flags, gates, the FE/BE registry parity.
- `frontend/lib/moduleFramework.test.mjs`:
  - `MODULE_UI` consistency
  - derived registries equal the previous lists
  - search params match the backend hrefs
  - a new module appears in navigation from its manifest alone

## 10. Acceptance test: Habits pilot (MRK-21)

Habits ([habits.md](habits.md)) uses search, Today with row actions, a dashboard section and widget, AI context,
REST and the runtime flag. Quick Add is left out: its frontend form definitions are still central.

**Framework gaps found and fixed generically (one-time, not per module):**
1. No router slot → `ModuleIntegrations.routers`, mounted by `main.py` from the registry.
2. Today row actions hard-coded per type → `MODULE_UI.todayActions` and one generic path in `lib/today.ts`,
   `useTodayActions` and the Today page.
3. Dashboard widgets and components central → `MODULE_UI.widgets` + `modules/registry.tsx`, and
   `WIDGETS = CORE_WIDGETS + MODULE_WIDGETS`. Module widgets that are hidden by default keep the 4B.1 layout.
4. Area and type labels central → `MODULE_UI.area` / `typeLabels`, with a fallback in `areaMeta` / `TYPE_LABELS`.
5. Tooling only covered root files → `npm test` and CI pyflakes include `modules/**`. The architecture tests cover
   module packages, including models and import isolation.

**Central files touched by the Habits PR outside the module folders:**
- **Required for every future module:** `module_registry.py`, `lib/modules.ts`.
- **Required when the module stores data:** `models.py` (one line) and the migration with its table-set pin.
- **Required when the module has a widget:** `frontend/modules/registry.tsx`.
- **One-time framework fixes** (not needed again): `main.py`, `module_contracts.py`, `lib/today.ts`,
  `hooks/useTodayActions.ts`, `app/today/page.tsx`, `lib/dashboardLayout.ts`, `app/page.tsx`, `lib/areas.ts`,
  `package.json`, `.github/workflows/ci.yml`, `backend/modules/__init__.py`.
- **Test pins updated once:** the habits entry moved from planned to implemented (`test_module_registry`,
  `modules.test`), the dashboard default-layout tests separate core from module widgets, and the navigation counts
  now derive from `NAV_PAGES`.

**Verdict:** accepted. No aggregator has Habits-specific code (AST purity test). Search, Today, dashboard, AI context
and REST picked Habits up from its `ModuleDef`; disabling it in Settings removes it everywhere, and re-enabling
restores its data.


## 11. Guardrails: explicitly out of scope

Carried over from the original MRK-8 design (PR #2), the only decisions not covered elsewhere:

- No runtime plugin loading, third-party modules or marketplace (§1).
- No generic CRUD or admin generator: each module still writes its own service and UI.
- Single user: no multi-user permissions or roles. "Permissions" means what a module allows non-UI actors to do:
  AI tools are READ or WRITE (WRITE always goes through pending actions), and Today offers only declared actions.
- No external message broker (Redis, MQTT) for the app's own events. The transactional outbox and SSE
  ([domain-events.md](domain-events.md)) are the bus. MQTT arrives with Home Assistant as a *consumer* of domain
  events.
- Home Assistant (future): a module may declare allowlisted device actions only, and irreversible ones (locks,
  valves) are always confirm-only. Jarvis never talks to devices directly: `Jarvis → validated action → HA`.
- No rewriting existing modules just to match the package layout. Legacy modules move when they are touched.
