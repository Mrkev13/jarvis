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
- [ ] Search only navigates – creating/changing data from the palette belongs to Quick Add.

## 7. Future surfaces (design for, do not build early)
- [ ] Quick Add: a minimal create payload the service accepts.
- [ ] Dashboard widget: a compact summary endpoint or reuse of existing queries.
- [ ] Today Mode: what "today" means for the module (Prague date semantics).

## 8. Operations and quality
- [ ] Config via `env_config` (documented in `.env.template` and AGENTS.md); feature toggle only if needed.
- [ ] Scheduler work (if any) as an isolated, idempotent, bounded job.
- [ ] Logs without secrets or private content.
- [ ] Tests: domain behaviour, boundaries (DST, empty data, caps), failure handling; fake clocks/LLMs only.
- [ ] AGENTS.md section for the module.
