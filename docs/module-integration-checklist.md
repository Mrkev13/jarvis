# Module integration checklist (Life Modules, Roadmap 5+)

A checklist, **not a framework**. A new module is "well integrated" when it ticks the boxes that make sense for
it; skip what does not apply and say why in the PR. Principles: [architecture-principles.md](architecture-principles.md).

## 1. Data and domain
- [ ] Model(s) in `backend/models.py` with an **additive** Alembic migration (upgrade/downgrade/re-upgrade test;
      PostgreSQL check for non-trivial changes).
- [ ] Timestamps stored as naive UTC (`utc_now()`); user dates via `today_local()` / `time_utils`.
- [ ] Status values added to `statuses.py` if other modules (planner, briefing, AI) need to interpret them.
- [ ] A focused domain service module (`<module>_service.py`): create/update/delete + queries; REST handlers and
      AI tools both call it (no duplicated write logic in `main.py` and `tools.py`).
- [ ] Every write calls `log_activity` (area = module name, meaningful summary, delta for edits).

## 2. REST API
- [ ] Routes in a dedicated `APIRouter` module (do not grow `main.py`); session auth applies automatically.
- [ ] Stable, documented response shapes; times for display returned as Prague-local or with clear UTC marking.
- [ ] Validation errors as 4xx with Czech `detail`.

## 3. Frontend
- [ ] Route under `frontend/app/<module>/`, using Roadmap 4 primitives (PageHeader, Card, states, badges).
- [ ] Loading, error and empty states; mobile layout; reduced motion; Czech copy.
- [ ] Pure helpers in `lib/<module>.ts` with `node --test` coverage.
- [ ] Sidebar entry only when the module is usable (no placeholder pages).

## 4. AI integration (only where useful)
- [ ] Read access: a capped query in `read_queries.py` + `ToolSpec` in `tool_registry.py` with correct `areas`;
      area keywords in `context_service` if CURRENT STATE should include it.
- [ ] Writes: resolver (preview) + executor through the pending-action flow; stale checks; undo if feasible
      (`mutation_service` EntityDef where it fits). Never a direct AI write.
- [ ] Tool routing tests (`test_tool_router.py`) and token budget check (`test_llm_budget.py`).

## 5. Briefing, review and notifications (only where relevant)
- [ ] Daily Briefing: deterministic items with refs in `briefing_snapshot` (today/overdue/soon), respecting caps.
- [ ] Weekly Review: deterministic metrics/items in `weekly_snapshot` (with previous-week comparison and a
      noise-free activity summary); forecasts only from deterministic candidates.
- [ ] Notifications via a dedupe key; external delivery only by adding the type to `deliverable_types` with an
      env toggle.
- [ ] Planner: deterministic candidates only if the module has deadlines/priorities.

## 6. Search integration (Roadmap 4D – Global Search / Ctrl+K)
- [ ] Records: add a source to `_candidates()` in `backend/search_service.py` yielding
      `(type, id, title, subtitle, extra, area, href)` – title = what the user names the record, subtitle = Czech
      context (kind · date · status, no raw enums/ISO dates), extra = other searchable words, bounded query
      (`ROW_LIMIT`), only records the module page actually shows (e.g. active ones).
- [ ] `href` = module page + record param (`/<module>?<param>=<id>`); add the param to
      `SEARCH_TARGET_PARAMS` (`frontend/lib/search.ts`) and `data-search-target="<param>-<id>"` (or
      `EntityRow searchTarget`) on the row so the result opens focused and highlighted.
- [ ] New area: label in `lib/areas.ts` (group heading) and position in `GROUP_ORDER`.
- [ ] Page: entry in `lib/navigation.ts` (Czech label + keywords) – sidebar and Ctrl+K share it.
- [ ] Tests: a representative hit in `backend/tests/test_search.py`; never index secrets, tokens, raw payloads or
      internal ids; a ui-check query for the module (mock `search.json` regenerated from the real service).
- [ ] Search only navigates – creating data belongs to Quick Add (§7).

## 7. Quick Add integration (Roadmap 4E – Smart Quick Add)
Only when the module has a record people create often from one sentence; otherwise skip.
- [ ] A WRITE tool for creating the record already exists (`tools.py`, `tool_registry.py`) and writes its Activity
      entry with the passed `user_context` – Quick Add never gets its own mutation code.
- [ ] Parser (`backend/quick_add_service.py`): an explicit keyword set for the kind, its place in the fixed
      `classify()` priority, a `_parse_<kind>()` that fills fields, asks via `need()` for anything missing and never
      invents values (categories only from explicit rules, shown as a warning); Prague dates via `time_utils`.
- [ ] Validation in `to_tool_call()` (ranges, dates, foreign keys must exist) – the frontend is never trusted.
- [ ] `_display()` Czech title/subtitle (no raw enums/ISO dates); area for the badge.
- [ ] Frontend: `QuickAddKind`, `FIELD_DEFS`, `KIND_AREAS`, `KIND_HREFS` and one example in `lib/quickAdd.ts`.
- [ ] Tests: parser matrix incl. ambiguous and invalid input in `backend/tests/test_quick_add.py`, prepare → confirm
      end to end (source `quick_add`, no AI approve log), `lib/quickAdd.test.mjs`; mock fixture regenerated from the
      real parser and a ui-check case.
- [ ] No undo promise for creates; no LLM call for unknown text.

## 8. Dashboard widget integration (Roadmap 4F – Command Center)
Only when the module has a compact, glanceable summary; otherwise skip.
- [ ] Data: extend `GET /dashboard` (one shared request) with a small summary, or – for a widget with its own
      lifecycle – a separate endpoint fetched by the page only while the widget is visible (like
      `/briefing/today`). Widgets never fetch on their own.
- [ ] Component in `components/dashboard/widgets.tsx` taking `WidgetProps`; keeps its own Loading/Error/Empty
      states; must render well at every allowed size (mobile is always one column).
- [ ] Registry: add the id to `WIDGET_IDS` and an entry to `WIDGETS` – stable semantic snake_case id (persisted
      forever, never renamed or reused), `defaultOrder` between existing ones, `defaultSize`, `allowedSizes`,
      `defaultVisible`, `usesDashboardData`; add it to `WIDGET_COMPONENTS`.
- [ ] Existing users get the new widget automatically after its default predecessor (`normalizeLayout`); check the
      default desktop packing still balances (`packDesktop` test).
- [ ] Tests: registry uniqueness test still passes, default order assertion updated, a ui-check screenshot.
- [ ] No runtime plugin loading; no pixel positions.

## 9. Today Mode integration (Roadmap 4G – Dnes)
Only for records that are dated or need action today; otherwise skip.
- [ ] Source mapping in `backend/today_service.py`: an explicit function that returns `TodayItem`s – into the
      timeline (dated today, `local_day_bounds_utc`), attention (overdue / needs action) or upcoming (next 7 days).
      Reuse the module's own status rules (`statuses.py`), never new ones; no runtime plugin registry.
- [ ] Stable `id` = ref `"<type>:<id>"` (the same ref the planner and notifications use) so deduplication works;
      `href` = the module deep link (`/<module>?<param>=<id>`, see Search integration).
- [ ] Czech subtitle (kind · subject · date, no raw enums/ISO), `time` only when the record really has one.
- [ ] Tests in `backend/tests/test_today.py`: today vs. tomorrow vs. overdue, midnight/DST if timed, dedup with
      planner/notifications; regenerate `frontend/scripts/fixtures/today*.json` from the real service.
- [ ] Keep it bounded – Today shows what matters today, not the module's list.

## 10. Today actions integration (Roadmap 4H – Act from Today)
Only for a low-risk action the module already supports cleanly; never new domain behaviour for Today's sake.
- [ ] The action already exists as a safe path: a module endpoint with validation/stale checks and Activity
      logging that accepts `user_context`, or a `modify_records` action (pending → confirm, snapshot, undo).
- [ ] Expose it declaratively: add the action id to `TodayItem.actions` in `backend/today_service.py` only for
      states where it is valid (e.g. active, not recurring); no URLs or commands in the payload.
- [ ] Wire it: a module endpoint gets `?source=today` (only that value maps to `user_context="today"`), or
      `POST /today/actions/prepare` gets one more explicit `(action, ref)` mapping to an existing tool.
- [ ] Frontend: one branch in `useTodayActions.run` + labels in `lib/today.ts` (`actionLabel`, `successMessage`);
      controls named with the record title; at most one primary action per row.
- [ ] Stale/failed cases return 400/404/409 (stale → refresh) vs. other errors (retry); undo only if the backend
      supports it; finished records must leave the active sections (and their notifications).
- [ ] Tests: `backend/tests/test_today_actions.py` (success, stale, duplicate, source, auth) and a ui-check case
      with a `today-after-*.json` fixture generated by the real service.

## 11. Game visual asset integration (Game Enrichment A)
Only for game modules whose entities are recognised by a picture.
- [ ] Matching from official data, not a hand-kept list: WoT tanks resolve at runtime from the Tankopedia manifest
      (`resolveTank`); small fixed sets (MFF characters, currencies) get a registry entry in `frontend/lib/gameAssets.ts`
      (stable snake_case slug). Aliases only for spellings no tier resolves; unknown/ambiguous names fall back.
- [ ] Source: an official API/CDN or explicit official URL in `scripts/game-assets.sources.json`; never generated
      lookalikes, never committed files (gitignored cache, attribution in the manifest).
- [ ] UI: `GameImage` with a size token, next to the text (never instead of it); decorative only when the label is visible.
- [ ] Tests: resolution/alias cases in `lib/gameAssets.test.mjs` against `scripts/fixtures/game-assets-manifest.json`;
      ui-check with the stub manifest (image, not in manifest, failing load) and a 390 px check.

## 12. User uploads and milestones (Game Enrichment B)
Only when a module truly needs user files (e.g. WoT milestone screenshots, `docs/wot-milestones.md`).
- [ ] Store through `backend/media_storage.py` (own purpose folder under `MEDIA_DIR`): type from file signature,
      size limit from env, server-generated names, serve only by DB id; never `public/`, never committed.
- [ ] Metadata row per file (original name only as display text); deleting the parent deletes rows **and** files
      after the commit. Document that `MEDIA_DIR` is outside the DB backup.
- [ ] Completion-like events: explicit user action + confirm, a history table that survives deletes, an activity
      row with `delta.event` and a dedupe key – no event bus.
- [ ] Tests: valid types, invalid type, oversize, traversal/unsafe name, delete cleanup; ui-check with a stateful mock
      and neutral stub images (no game art), reduced-motion path and 390 px.

## 13. Operations and quality
- [ ] Config via `env_config` (documented in `.env.template` and AGENTS.md); feature toggle only if needed.
- [ ] Scheduler work (if any) as an isolated, idempotent, bounded job.
- [ ] Logs without secrets or private content.
- [ ] Tests: domain behaviour, boundaries (DST, empty data, caps), failure handling; fake clocks/LLMs only.
- [ ] AGENTS.md section for the module.
