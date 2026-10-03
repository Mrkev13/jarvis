# Standa Hub – Architecture & Product Principles

Permanent rules for every future roadmap (Roadmap 3.5 onward). They describe how this codebase already works
at its best; when code disagrees with them, the code is the debt. Concrete examples point at real modules.

Audit and current debt: [`architecture-audit.md`](architecture-audit.md) · open items:
[`follow-ups.md`](follow-ups.md) · new modules: [`module-integration-checklist.md`](module-integration-checklist.md) ·
frontend direction: [`roadmap4-ui-foundation.md`](roadmap4-ui-foundation.md).

---

## Canonical modules (single sources of truth)

Use these; never re-declare their content locally.

| Concept | Module |
|---|---|
| Record statuses (assignment done, exam open/passed, goal inactive, reminder active, MFF built) + `norm()` | `backend/statuses.py` |
| Environment variables (bool/int/str parsing, `.env` loading) | `backend/env_config.py` (`llm_config.py` for AI limits) |
| Europe/Prague time, day/week/month bounds, naive-UTC storage | `backend/time_utils.py` |
| User-visible text helpers (`clip`, Czech weekday names) | `backend/text_utils.py` |
| AI tools: schema, function, areas, resolver | `backend/tool_registry.py` (routing: `tool_router.py`) |
| One-shot structured LLM calls (strict schema, error categories, usage) | `backend/structured_llm.py` |
| Grounding checks (numbers, dates, names) | `backend/planner_guard.py` |
| Audit trail | `backend/activity_service.log_activity` |
| Notification → external delivery | `backend/delivery_service.py` (`deliverable_types`) |
| Frontend API access | `frontend/lib/api.ts` (`apiFetch`) |
| Motion tokens and reduced motion | `frontend/app/motion.css` + `frontend/lib/motion.ts` |

---

## 1. KISS
Prefer the simplest design that solves today's problem. A function beats a class, a module beats a framework,
an `if` beats a strategy registry. *Example:* four scheduler jobs are four small functions, not a job framework.

## 2. YAGNI
Do not build extension points for hypothetical modules. Add the second abstraction layer only when a second real
user exists; extract a generic helper at the **third** real copy (rule of three). *Example:* Daily Briefing and
Weekly Review share `structured_llm`, but their state machines stay separate until a third scheduled AI artifact
appears.

## 3. DRY – carefully
Remove duplication of *knowledge* (status lists, timezone math, env parsing, error categories). Do not merge
unrelated concepts that merely look alike (e.g. the daily and weekly snapshots have different granularity and
stay separate modules).

## 4. SOLID (pragmatic)
- **Single responsibility:** a module has one reason to change. Snapshot = deterministic data; service = state
  machine + persistence; route = HTTP.
- **Clear interfaces:** modules import each other's *public* names. No `from x import _private` across modules
  (tests may reach into internals). Two older exceptions still exist — see audit L13.
- **Dependency direction:** `routes (main.py) → services → domain helpers (statuses, time_utils, text_utils)
  → models`. Domain/service code must not raise `HTTPException`; leaf modules import nothing app-specific.

## 5. Separation of concerns
Keep separate: persistence (models, Alembic) · domain logic (services) · deterministic computation (snapshots,
read_queries, planner) · AI orchestration (ai.py, structured_llm) · scheduling (scheduler_service) · delivery
(delivery_service, webpush) · REST (main.py) · UI (frontend). A scheduler job calls a service function; it does
not contain business logic.

## 6. Single source of truth
One canonical definition per shared concept (table above). New status values, env variables, tool definitions
or area names are added in their canonical module first.

## 7. Deterministic before AI
If something can be queried, calculated, validated or classified safely without an LLM, do that first and give
the model only the result. *Examples:* briefing/weekly snapshots, precomputed weekly metrics and forecast
confidence, tool routing, quiet-day / quiet-week shortcuts that skip the LLM entirely.

## 8. AI is not the database
State lives in the database and is owned by domain services. The LLM reads deterministic context and proposes;
it never becomes the source of truth. AI output that is stored (briefings, reviews) is grounded against the
snapshot and labelled as generated.

## 9. Safe writes by default
Every AI write goes through: resolver preview → explicit user confirmation → stale-target check → atomic
execution → audit (`activity_logs`) → undo where supported. The confirm claim is committed before execution.
No tool may write without a pending action.

## 10. Graceful degradation
Failure of Groq, Web Push, Daily Briefing, Weekly Review or any scheduler job must not break unrelated features.
Each job is isolated (own try/except, own session); AI features show a deterministic fallback when the model is
unavailable; errors are categorised, not swallowed silently.

## 11. Idempotence
Schedulers, reminders, notifications, deliveries, briefings, reviews and retries must be safe to run twice:
unique keys (`dedupe_key`, `briefing_date`, `week_start`), conditional-UPDATE claims, "exists → skip" checks.

## 12. Explicit time semantics
Database timestamps are **naive UTC** (`time_utils.utc_now()`); user-facing schedules and "today" use
**Europe/Prague** (`today_local()`, `local_day_bounds_utc()`, …). Never call `date.today()` / `datetime.now()`
without a timezone. Times shown to users or to the AI are converted with `to_local()` and carry an offset.

## 13. Bounded work
Every automated process has limits: list caps, token budgets (`llm_budget`, snapshot caps), output ceilings,
retry counts, backoff, stale-claim timeouts. Daily provider limits never cause busy loops.

## 14. Observability without secrets
Log ids, states, timings, counts and error *categories*. Never log secrets, private keys, raw push
subscriptions/endpoints, PIN hashes, or full prompts/snapshots. LLM usage is logged as numbers only.

## 15. Additive migrations
Schema changes go through Alembic, preferably additive (new tables/columns). Destructive changes need an
explicit justification, a data plan and an upgrade/downgrade test (SQLite + PostgreSQL where it matters).

## 16. Small bounded modules
Avoid god services and god components. New code goes into a focused module; when touching an oversized file
(`main.py`, `ai.py`, `frontend/app/ai/page.tsx`), move the touched part out rather than growing it.

## 17. Stable public interfaces
The frontend depends on REST response shapes, never on backend internals (internal refs, table layout).
Changing a response shape is a deliberate, versioned change; removing an endpoint requires checking all clients.

## 18. Tests around behaviour
Test domain behaviour, boundaries (DST, week/year edges), failure handling and regressions — not implementation
trivia. Use fake clocks (`now=` parameters or patched `utc_now`) and fake providers (`tests/fakes.py`);
**never** call a real LLM in tests. Every bug fix comes with a regression test that fails without the fix.

---

## Product principles (short)

- **Truthful over impressive:** AI text must be supported by data; forecasts are labelled as estimates.
- **Czech UI, Prague time.** One language per screen (Roadmap 4 finishes the cleanup).
- **Quiet when nothing matters:** no fake urgency; empty states say so briefly.
- **Hide unfinished features** rather than showing placeholder panels.
