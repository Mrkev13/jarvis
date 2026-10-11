# Calendar usability: Today and week view

This read-only follow-up uses existing Calendar occurrence and Free Blocks services.
There is no migration, new endpoint, persistence or Fitness change.

## Today

The Calendar Today provider computes one shared Free Blocks result for the remainder
of the current Prague day and tomorrow. It uses the existing 07:00–22:00 waking
window and a 30-minute minimum. An ongoing gap is clipped to now; ended gaps are
excluded. The first qualifying gap today appears in Today, or tomorrow in Upcoming.
It is an open derived suggestion, not a scheduled appointment and not `next_item`.
If the result is capped/incomplete, a warning replaces the suggestion.

Only active Calendar occurrences block time. All-day items do not block the waking
window, matching the existing Free Blocks default. School, Reminders and Habits do
not invent busy time. Disabling Calendar removes its contribution.

## Week

`/calendar` includes seven Monday-first Europe/Prague local dates with previous,
current and next week navigation. Each week uses two bounded existing requests:

- `/calendar/occurrences?start=YYYY-MM-DD&end=YYYY-MM-DD` (exclusive end, seven days)
- `/calendar/free-blocks?start=YYYY-MM-DD&end=YYYY-MM-DD&min_minutes=30`

The occurrence endpoint now adds a conservative `truncated` boolean when its cap is
reached. The UI marks incomplete results, including free-time summaries, as uncertain.
There is no query per event or day. Existing services handle recurrence overrides,
DST, cancellation and source absence. All-day end dates remain exclusive; overlapping
occurrences remain separate. Sync refreshes both week resources.

School day-items remain in the existing **Můj den** section. Its providers currently
have a one-day contract; extending that contract for batched weekly School items is
a separate follow-up. No synthetic times are assigned to deadlines.

## Verification

Backend regressions cover clipping, tomorrow fallback, no qualifying gap, incomplete
results, the 25-hour DST day, recurrence overrides, cancelled/source-missing exclusion,
module gating and read-only behavior. Older core/School Today and fake-module tests
explicitly disable Calendar so their exact-output assertions remain isolated.

Frontend tests cover local week arithmetic, bounded range paths, grouping, all-day
formatting and loading/error/empty/incomplete states. Browser verification uses only
synthetic intercepted API responses:

```bash
cd frontend
npm run build
npm run start -- --hostname 127.0.0.1 --port 3034
# In another terminal, with Playwright installed:
node scripts/calendar-week-check.mjs
```

Optional `PLAYWRIGHT_MODULE`, `PLAYWRIGHT_CHROMIUM`, `UI_BASE_URL` select local tools.
Screenshots go to ignored `frontend/scripts/.ui-check/`. No real feed or Groq is used.
Real Windows/Moodle data acceptance remains local. No editor, planner, scheduler sync,
AI tools or Search expansion is included.

Cloud verification: 131 focused backend tests; full backend 1009 passed, 8 skipped,
412 subtests; frontend 360 passed; pyflakes/typecheck/build passed. Lint has only
three existing unused-variable warnings in Calendar `lib.ts`. Synthetic browser
checks passed at 1366 and 390 pixels: navigation, timed/all-day rendering, empty and
error states, sync refresh, no overflow or JavaScript errors.

[Synthetic desktop screenshot](assets/calendar-usability/desktop.png) ·
[Synthetic mobile screenshot](assets/calendar-usability/mobile.png)

Issue draft title: **Calendar usability: next free block in Today and read-only week
view**. Linear is unavailable in this cloud session; create the focused issue and
attach the PR/handoff when access returns.
