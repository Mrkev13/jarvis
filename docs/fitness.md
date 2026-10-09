# Fitness & Rehab (MRK-33)

Fitness is a runtime module (`fitness`, enabled by default). It records completed manual workouts and rehab practice. Rehab entries and pain ratings are self-reported tracking, not diagnosis or medical guidance.

## Definitions and durable history

`fitness_exercises` and `fitness_rehab_exercises` define names, type and optional descriptive metadata. Archive/restore changes their availability for new entries. Existing history stays readable. There is no hard-delete API; reference foreign keys use `RESTRICT`. Renaming a definition leaves recorded name/type snapshots unchanged, and changing the type of a used definition is rejected.

`fitness_workouts` contains performed date, optional title, notes, duration and source (`manual`). Ordered `fitness_workout_sets` store measurements, RIR, completion and notes. `fitness_rehab_sessions` contains performed date and notes; ordered `fitness_rehab_entries` store measurements, set count and optional pain-before/after ratings. Both preserve definition name/type snapshots.

Sessions use `performed_on` (a Prague calendar date), not an invented start time. Future dates are rejected. Creation/update timestamps follow the repository's naive-UTC DB convention and are returned as UTC ISO timestamps. Sessions do not occupy Calendar/free-block time or contribute to the unified day timeline.

## Transactional entry and corrections

Authenticated `POST /fitness/workouts` accepts one session and 1–200 sets; `POST /fitness/rehab/sessions` accepts one session and 1–200 entries. Referenced definitions must exist and be active. Ordering is explicit and unique within a session. Definitions are fetched together, with stable-order row locks on PostgreSQL. All rows, one domain event and its Activity projection commit together, or all roll back.

Session `PATCH` endpoints accept metadata only (performed date/title/notes/duration where supported). Previous and new values remain in durable Activity deltas; identical edits are quiet. Sets/entries cannot be replaced or deleted in this foundation. A future measurement-correction workflow must preserve the original facts and attribution rather than overwrite them silently.

Definitions have list/create/PATCH endpoints at `/fitness/exercises` and `/fitness/rehab/exercises`. `active: false` archives; `active: true` restores. Workouts and rehab sessions have list/create/detail/PATCH endpoints. List queries return the latest 50 sessions and eager-load children; definition lists are bounded to 500.

## Measurement types

| Type | Required | Optional |
|---|---|---|
| `strength` | integer reps ≥ 0 | weight in kg ≥ 0, RIR 0–10 |
| `bodyweight` | integer reps ≥ 0 | RIR 0–10 |
| `duration` | integer seconds > 0 | — |
| `distance` | metres > 0 | integer seconds > 0 |

Incompatible fields are rejected. Values must be finite. Upper bounds: reps 10,000, kg 10,000, seconds 604,800, metres 10,000,000. RIR is workout-only. Rehab set count is 1–100; optional pain ratings are 0–10 and convey no medical interpretation. Notes are bounded; payloads reject unknown fields.

## Progress and framework contributions

`GET /fitness/progress` returns current Prague-week workout/rehab counts and the five latest sessions of each kind. This is frequency, not adherence to an unimplemented plan. `GET /fitness/exercises/{id}/progress` returns recent completed measurements, the last performed date, and session IDs. It reads at most 200 recent sets and returns at most 20 session IDs; it does not compute strength scores or predicted PRs.

The module manifest supplies Search (definition names/workout titles), Today (completed-today facts with no schedule time), bounded AI context, routes, and What Changed. Change rows come from domain events only, avoiding duplicate Activity rows. Transport payloads contain IDs, dates, counts and active state, never notes, pain ratings or instructions. Business records and Activity remain durable after event retention. Disabling Fitness hides routes/providers without deleting records. There are no Fitness AI actions or LLM calls.

`/fitness` provides workouts, exercises and rehab tabs, transactional multi-row forms, archive/restore, dated history/detail and simple progress. Stable query links select an exercise, workout, rehab exercise or rehab session. Advanced editors, charts, plans, coaching, wearables, nutrition and medical decisions are out of scope.

## Migration and verification

`0021_fitness` follows `0020_calendar_source_presence`, adding six tables with numeric/order constraints, restrictive references and date/reference indexes. Downgrade removes these tables: back up first; it is not a history-preserving production rollback.

Focused checks: `python -m pytest backend/tests/test_fitness.py --disable-socket --allow-unix-socket -q`; frontend Fitness tests run with `npm test`. Full CI commands are in [the README](../README.md). Verify migration upgrade → downgrade -1 → upgrade and schema parity on a disposable PostgreSQL database, never the real user DB.

Next steps: an audited correction workflow, pagination/full history browsing, optional real scheduled start/end integration, and richer deterministic progress once actual usage shows a need.

## Synthetic UI verification

After production build/start (`npm run start -- --hostname 127.0.0.1 --port 3033`), run `node scripts/fitness-check.mjs` from `frontend/`. Supply `PLAYWRIGHT_MODULE` and `PLAYWRIGHT_CHROMIUM` if Playwright/Chromium are installed outside the project. The browser intercepts backend requests and uses synthetic data; no real backend, LLM or user database is needed. It verifies type-dependent inputs, a two-set ordered payload, rehab history and horizontal overflow at desktop/mobile widths.

[Desktop screenshot](images/fitness/desktop.png) · [Mobile screenshot](images/fitness/mobile.png)

MRK-33 cloud verification: backend 1000 passed / 8 skipped / 412 subtests, focused Fitness 26 passed; frontend 363 passed, typecheck/build/pyflakes passed. Lint has three existing Calendar warnings. SQLite and disposable PostgreSQL upgrade/downgrade/upgrade and schema parity passed; PostgreSQL batch rollback, snapshots/archive and restrictive FK behavior passed. Independent review found no blockers. No real Windows/mobile device or user DB acceptance was performed. Groq requests: 0.
