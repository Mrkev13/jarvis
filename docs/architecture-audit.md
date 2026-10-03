# Architecture audit – after Roadmap 3.0 (v0.8.0)

Baseline: `main` @ `d86c064` (v0.8.0, phases A–G). Audit and fixes on `feat/roadmap3-5-architecture`.
Principles referenced as **P1–P18** ([architecture-principles.md](architecture-principles.md)).

---

## 1. Architecture map

### Backend (FastAPI + SQLAlchemy + Alembic, ~14.6k lines in `backend/*.py`)

```
main.py (2.9k lines, 83 routes, no APIRouter)          ← REST, auth middleware, startup (migrations, recovery, scheduler)
 ├─ auth_service        PIN (bcrypt) + session cookies (hashed tokens)
 ├─ tools.py (1.4k)     legacy read/write functions used by AI tools and some routes
 ├─ read_queries        filtered, capped AI read queries
 ├─ planner_service     deterministic daily/weekly planner (+ planner_guard grounding)
 ├─ notifications_service  deadline / stagnation notifications (upsert by dedupe_key)
 ├─ reminder_service + reminder_actions   reminders (Phase D) and their AI propose/execute
 ├─ mutation_service (1.1k)  AI edit/delete/complete plans, stale checks, undo (Phases B/C)
 ├─ activity_service    audit log (activity_logs)
 ├─ goal_history_service  goal progress, automatic goals, stagnation
 ├─ backup_service      SQLite copy / pg_dump with retention
 ├─ delivery_service + webpush   notification → external delivery queue, Web Push (RFC 8291/8292)
 ├─ briefing_snapshot + briefing_service       Daily Briefing (Phase F)
 └─ weekly_snapshot + weekly_review_service    Weekly Review (Phase G)

AI layer
 ai.py (0.9k)  client + retry (_llm_create_with_retry), chat tool loop (ask_ai), pending-action state machine,
               confirm/execute + audit, conversation summarisation
 context_service (CURRENT STATE prefetch) · history_service (window + summary) · tool_registry / tool_router
 structured_llm (one-shot strict-schema calls for briefing/weekly) · planner_guard (grounding)
 llm_config / llm_budget / llm_usage (limits, token estimates, usage logging)

Cross-cutting (Roadmap 3.5): statuses · env_config · time_utils · text_utils
scheduler_service: APScheduler BackgroundScheduler, single worker; jobs hourly (off by default), reminders+delivery
                   (60 s), daily briefing (300 s), weekly review (900 s); each job isolated
alembic: 13 revisions (0001–0012), additive since 0007
```

### Frontend (Next.js 16 App Router, React 19, Tailwind 4)

- 14 routes, all client components; biggest: `/ai` 2150 lines, `/mff` 1124, `/school` 945, `/goals` 910,
  dashboard 773.
- Data access: `lib/api.ts apiFetch` (credentials, 401 → /login). Every page re-implements the
  load/loading/error pattern (`useCallback` + `queueMicrotask` in `useEffect`).
- Shared components: `Sidebar`, `NotificationsBell`, `ConfirmDialog`, `PlannerCards`, `PushSettings`,
  `DailyBriefingCard`, `WeeklyReviewCard/View`, `motion/*`. Pure helpers with node tests in `lib/*.ts`.
- Motion: `app/motion.css` tokens + `lib/motion.ts`; reduced motion handled centrally for `motion-*` classes.
- Auth: `middleware.ts` → backend `/auth/session/validate` (lenient on backend errors), `lib/publicPaths.ts`.

### Tests

- Backend: 46 unittest files, 495 tests, no pytest/conftest; in-memory SQLite per file; fake clocks via
  `now=` / patched `utc_now`; fake LLMs per file, shared HTTP fake + delivery provider in `tests/fakes.py`;
  PostgreSQL migration test opt-in via `TEST_POSTGRES_URL`.
- Frontend: `node --test` over `lib/*.test.mjs` (native TS stripping), 57 tests. No Playwright suite in repo.

### Operations

- Windows: `run-backend.cmd` (uvicorn `--reload`, 0.0.0.0:8000) and `run-frontend.cmd` (checks
  `NEXT_PUBLIC_API_URL` prefix). Tailscale serve for HTTPS (Web Push on mobile) documented in AGENTS.md §21.
- Startup: Alembic upgrade (`RUN_ALEMBIC_UPGRADE_AT_STARTUP`), pending-action recovery, scheduler start.
- Single backend worker assumed (scheduler, in-process rate limiting).

---

## 2. Findings

| # | Finding | Classification | Risk | Action |
|---|---|---|---|---|
| F1 | Status lists duplicated in 8 modules; automatic goals missed `"finished"` | **FIX NOW** ✅ | low | `statuses.py`, regression test |
| F2 | Env booleans parsed 3 ways; scheduler vs services disagreed on `"on"` | **FIX NOW** ✅ | low | `env_config.py`, test |
| F3 | `date.today()` (server tz) in dashboard, planner, notifications, goals, work summary | **FIX NOW** ✅ | low | `today_local()` |
| F4 | AI read tools returned naive UTC timestamps (follow-up #2) | **FIX NOW** ✅ | low | Prague ISO with offset, test |
| F5 | Backup: absolute SQLite path broken on Linux (`lstrip("/")`) | **FIX NOW** ✅ | low | `make_url().database` |
| F6 | Pending confirm claim only flushed, not committed, before execution | **FIX NOW** ✅ | low | commit claim, test |
| F7 | Audit `entity_id = hash(action_id)` changes every process start | **FIX NOW** ✅ | low | use PendingAction id |
| F8 | LLM error classification by Czech message text (3 places) | **FIX NOW** ✅ | low | `LLMRateLimitError` |
| F9 | Private cross-module imports; 4× clip, 6× weekday tuples | **FIX NOW** ✅ | low | `text_utils`, `strict_text_problems`, `schedule_label` |
| F10 | Briefing JSON parser duplicated `parse_json_object`; leftover aliases | **FIX NOW** ✅ | low | reuse shared parser |
| F11 | Dead helpers + unused imports | **DELETE** ✅ | low | removed (list below) |
| F12 | Test modules import fakes from other test modules | **FIX NOW** ✅ | low | `tests/fakes.py` |
| F13 | Light OS theme turns the dark app white (unlayered `body {}`) | **FIX NOW** ✅ | low | `@layer base` |
| R1 | No shared data-fetching hook; no abort/debounce; loading starts `false`; 3 pages without loading state | ROADMAP 4 | med | `useApiResource` + states |
| R2 | Server error text extracted ad hoc (`readError` + 5 inline copies) | ROADMAP 4 | low | `lib/api` helper |
| R3 | UI primitives copied (card class ×60, page header ×13, badges ×4 palettes, `formatNumber` ×5 …) | ROADMAP 4 | med | design-system primitives |
| R4 | `ConfirmDialog`: no busy state (double submit), no `role="dialog"`/focus trap | ROADMAP 4 | low | rebuild as primitive |
| R5 | Shell: two `NotificationsBell` instances poll twice; login renders inside app shell; 2× `<h1>` | ROADMAP 4 | low | `AppShell` |
| R6 | Language mix (EN/CZ) in titles, labels, badges | ROADMAP 4 | low | copy pass |
| R7 | `/activity` light-theme cards; WoT "coming soon" placeholders | ROADMAP 4 | low | restyle / hide |
| R8 | `animate-pulse/bounce` ignore reduced motion; `animate-in` classes from missing plugin | ROADMAP 4 | low | motion-safe variants |
| R9 | `/ai` page 2150 lines (formatters, markdown, local `WeeklyPlanCard` name clash) | ROADMAP 4 | med | split components |
| R10 | `middleware.ts` deprecated in Next 16 (`proxy.ts`); `API_URL` defined 3× | ROADMAP 4 | low | rename + one constant |
| L1 | `main.py` 2.9k lines, 83 routes, domain logic in handlers (`/chat`, `/work/session`, dashboard) | LATER | med | APIRouter per module when touched |
| L2 | `ai.py` mixes client/retry, chat loop, pending state machine (raises `HTTPException`), audit | LATER | med | `llm_client.py` + `pending_actions.py` |
| L3 | Background jobs import the whole chat stack (`structured_llm` → `ai`) | LATER | low | solved by L2 |
| L4 | Briefing/weekly near-duplicate claim/generate/notify/run_scheduled | LATER | med | extract at third instance |
| L5 | 4 notification creation sites without a shared create-once helper | LATER | low | helper with next new type |
| L6 | Push delivery runs inside the reminders job; 12 h max age for all types | LATER | low | documented; own job if needed |
| L7 | `tools.py` write functions duplicate REST handlers (finance, work, goals…) | LATER | med | domain service per module (Roadmap 5) |
| L8 | In-memory DB setup copied in 33 test files | LATER | low | helper for new tests, migrate when touched |
| L9 | `datetime.utcnow()` (deprecated in 3.12) ~30 uses | LATER | low | mechanical swap to `utc_now()` |
| L10 | Unused endpoints `GET /ai/confirm/{id}`, `POST /ai/execute` | LATER (delete) | low | remove after confirming no external client |
| L11 | `classify_areas` matches "test" as school (follow-up #1) | LATER | low | heuristic tuning + test |
| L12 | `DATABASE_URL` default differs (database.py none vs backup/alembic sqlite) | LATER | low | one default in env_config |
| D1 | Single `ZoneInfo` in `time_utils`, tool registry/router, mutation plan/stale/undo design, delivery layering, structured_llm core | LEAVE | – | coherent, well tested |
| D2 | Scheduler boilerplate (4 small jobs) | LEAVE | – | no job framework (YAGNI) |
| D3 | Separate daily vs weekly snapshot modules; different grounding strictness | LEAVE | – | intentional |
| D4 | No repository layer / DI container | LEAVE | – | not needed at this size |

### FIX NOW details

- **F1 statuses** – `briefing_snapshot`, `context_service`, `weekly_snapshot`, `goal_history_service`,
  `planner_service`, `notifications_service`, `main` (dashboard) and `reminder_service` each carried their own
  lists. `goal_history_service` lacked `"finished"` and compared untrimmed values, so the automatic goals
  *school_completed_assignments / school_open_assignments* disagreed with every other view (P6). Fixed in
  `statuses.py`; `read_queries` re-exports for existing imports. Test: `tests/test_statuses.py`.
- **F2 env** – `DAILY_BRIEFING_ENABLED=on` (or with spaces) made the scheduler skip the job while
  `/briefing/today` said `enabled: true` (P6, P10). All parsing via `env_config`; unused
  `briefing_push_enabled` / `review_push_enabled` removed. Test: `tests/test_env_config.py`.
- **F3/F4 time** – implicit server timezone (P12). Test: `tests/test_read_queries.py` (CET/CEST).
- **F5 backup** – POSIX absolute SQLite URLs (`sqlite:////…`) became relative; `test_backup` failed on Linux.
- **F6 pending** – the executor ran in its own session while the claim was uncommitted; a crash between the
  executor commit and finalize left the action `pending` (confirmable again) and startup recovery never saw
  `executing` (P9, P11). Test: `tests/test_pending_claim.py` (file DB, separate sessions).
- **F7 audit ids** – `hash()` of a string is randomised per process (P14).
- **F8 errors** – `/chat` returned 429 only if the message contained "Rate limit"/"překročen" (P6).
- **F9/F10** – P4 (public interfaces), P3.
- **F12** – `tests/fakes.py`: `FakeGroq`, `completion`, `groq_error`, `FakeProvider`.
- **F13** – unlayered CSS beats Tailwind 4 layers; verified with Chromium in light and dark scheme.

### Deleted (F11)

`auth_service._bcrypt_hash_pin`, `database.get_db`, `notifications_service.ALLOWED_SEVERITIES`,
`planner_guard.PLANNER_AREAS`, `reminder_service.today_bounds_local`, `tools.get_automatic_goal_current_value`,
`tools.create_weekly_plan` (never registered as a tool), `ai` re-export of `tool_registry._tool`,
`briefing_service._classify_call_error/_usage_from`, unused imports (pyflakes now clean),
`frontend/public/{file,globe,next,vercel,window}.svg`. Each had zero references in code, tests and docs.

### Do NOT refactor (now)

- `mutation_service` – large but cohesive (plan → snapshot → stale check → apply → undo); covered by ~80 tests.
- `tool_registry` / `tool_router` – the A5 single source of truth works; keep adding tools there.
- `time_utils`, `structured_llm`, `delivery_service` / `webpush` layering.
- Daily vs weekly snapshot separation and their different grounding strictness.
- Scheduler job functions – four small isolated jobs; a framework would add more code than it removes.

---

## 3. Status of specific audit areas

- **Statuses:** canonical (F1). Remaining literal lists are *choice enums* in tool schemas / mutation field
  definitions (what the AI may set) — intentionally explicit.
- **Time:** one `ZoneInfo`; no manual offsets; server-local dates removed (F3). `datetime.utcnow()` remains as
  naive-UTC storage helper usage (L9).
- **AI layer:** one retry loop (`_llm_create_with_retry`), one structured-call path; classification by type (F8);
  remaining coupling is L2/L3.
- **Schedulers:** isolated jobs, flags consistent (F2), catch-up after restart for briefing/weekly; single worker
  assumption documented.
- **Notifications/delivery:** generic queue (`deliverable_types`); creation helper missing (L5).
- **Pending/undo:** design coherent; claim commit fixed (F6); state-machine ownership split across ai/main/
  mutation_service (L2).
- **Frontend API access / components:** see R1–R10 and [roadmap4-ui-foundation.md](roadmap4-ui-foundation.md).
- **Config:** all variables documented in `.env.template` / AGENTS.md (AUTH_SESSION_TTL_HOURS,
  AUTH_COOKIE_NAME, WEEKLY_REVIEW_ENABLED added).
- **Tests:** cross-test imports removed (F12); DB setup duplication is L8.
