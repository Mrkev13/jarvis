# Návyky / Habits (MRK-21, Platform 2.0 D pilot)

Habits is a deliberately small module. Its job is to prove that a genuinely new module can be added through
module-local code and the registries alone ([module-framework.md](module-framework.md) §10). It is not a
habit-tracking product: no streaks, achievements, analytics, reminders, recurrence engine or AI coaching.

## Files

| Side | Files |
|---|---|
| Backend | `backend/modules/habits/` – `models.py`, `service.py` (only write path), `router.py` (`/habits/*`), `integrations.py` (contributions) |
| Migration | `backend/alembic/versions/0017_habits.py` (new tables only) |
| Frontend | `frontend/modules/habits/` – `manifest.ts` (pure data), `lib.ts` + `lib.test.mjs`, `HabitsPage.tsx`, `HabitsTodayWidget.tsx`, `browser-check.mjs` |
| Route wrapper | `frontend/app/habits/page.tsx` (App Router needs the physical folder) |
| Tests | `backend/tests/test_habits.py`, migration case in `test_alembic_migration.py` |

## Model

- `Habit`: `name`, `kind` (`check` | `count` | `duration`), optional `target_value` and `unit` (e.g. 2 l, 20 min),
  `active`, `created_at`, `archived_at`. Every habit is **daily**: there is no weekday schedule and no recurrence
  engine.
- `HabitEntry`: `habit_id`, `date` (Prague calendar day), `state`, optional `value` (count), `duration_minutes`
  (duration), `note`, `created_at`, `updated_at`. **Unique `(habit_id, date)`.**

## State semantics

| State | Source | Meaning |
|---|---|---|
| `done` | stored entry | completed that day (with optional value or minutes) |
| `skipped` | stored entry | deliberately skipped. Not counted as a failure in the 7-day summary. |
| `missed` | **inferred** on read | a past day (from the habit's creation day up to yesterday) with no entry |
| `open` | inferred | today, no entry yet |

How "missed" works:
- No scheduler job writes it. `service.day_state()` computes it deterministically on every read, so there is
  nothing to back-fill and no dedupe key to manage.
- The DB check constraint still allows `missed`, for a later import or an explicit write. The API only accepts
  `done` and `skipped`.

## History guarantees (tested)

- **Archiving never deletes entries.** It sets `active = false` and `archived_at`. Restoring brings the full history
  back.
- **No cascade deletes.** The FK is `ON DELETE RESTRICT` and the ORM relationship uses `passive_deletes="all"`.
  Deleting a habit that has entries fails, on PostgreSQL as well.
- **Changing a day's state updates only that day's row.** Every change is written to Activity with a delta of the
  old and new state, value, minutes and note. A completed day is therefore never overwritten without a trace.
  Writing the same state again logs nothing.
- **Disabling the module (Settings) deletes nothing.** Navigation, routes, the API (404) and every contribution
  disappear; re-enabling brings everything back.

## Integration surfaces (all through `ModuleDef.integrations`, no aggregator edits)

| Surface | Contribution |
|---|---|
| REST | `routers=(router,)` – `GET /habits`, `POST /habits`, `POST /habits/{id}/archive`, `POST /habits/{id}/restore`, `POST /habits/{id}/entries` (`?source=today` → Activity context `today`) |
| Search | `SearchSource("habits", 75)` – habits by name, `/habits?habit=<id>` |
| Today | `TodaySource("habits", 30, timeline=…)`: today's active habits. Open habits get `complete` / `skip`; done or skipped ones are shown with their state. Ordering and dedupe stay global. |
| Today actions (frontend) | `MODULE_UI.habits.todayActions` – "Splněno" / "Přeskočit" POST to the module endpoint through the generic path in `useTodayActions` |
| Dashboard | `DashboardSection("habits")` (today done/skipped/total, last 7 days done/expected) + widget `habits_today`, **hidden by default** so the existing dashboard layout does not change; the user adds it under "Upravit dashboard" |
| AI context | `ContextSection("habits", order=75)`: "Návyky dnes: …; posledních 7 dní splněno x/y". Keywords are návyk, habit, rutin and rehab, and active habit names also mark the area. No AI tools. |
| Feature flag | normal module (`MODULE_HABITS_ENABLED`, Settings toggle), default enabled |

Not included in the pilot:
- **Quick Add.** The backend contract supports it, but the frontend Quick Add form definitions (`QuickAddKind`
  union, `FIELD_DEFS`) are still central. Adding "splněno rehab" would mean central frontend edits and new grammar,
  so it is skipped. Next step: move the form definitions into the module manifest.
- **Domain events.** MRK-19 is not on `main`. When it lands, `service.set_entry` / `set_active` are the places to
  emit `habits.habit.checked` / `habits.habit.skipped` / `habits.habit.archived` (missed stays inferred, or becomes a
  time event if a consumer needs it).

## Known limitations

- Daily habits only. Weekday schedules can be added later in `service.day_state`.
- The page edits only today. Past days are visible in the 7-day strip; the API accepts a past `date`, but the UI
  does not expose it.
- Archived habits cannot be checked (409) until they are restored.
