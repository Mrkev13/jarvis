# Calendar foundation — MRK-30 / MRK-31

Both issues share this branch: MRK-30 owns the durable Event/source model and
framework/page contributions; MRK-31 owns ICS decoding, source synchronization
and idempotent upserts. No Calendar tools, planner, event editor, month grid or
scheduled feed fetch is installed. Baseline: main `a75b0ea`; migration
`0019_calendar` follows `0018_domain_events` with one linear head.

## Storage and identity

`calendar_sources` holds kind (`ics`), display name, enabled flag, source timezone
and an optional unique allowlisted configuration alias (`moodle`). It never stores
a URL, token, passphrase or arbitrary environment variable. Sources are created
when sync is requested, not seeded on startup. Existing implemented modules
(including Habits) default on, so Calendar also defaults on; no source means no
network activity. Runtime flag: `MODULE_CALENDAR_ENABLED` (env > DB > default).

`calendar_events` stores a unique `(source_id, external_uid, recurrence_id)`;
empty recurrence ID identifies the master. Different sources may share UIDs.
Fields: title, optional description/location, starts/ends, all-day dates/timezone,
active/cancelled status, recurrence metadata, source revision/time, import/create/
update timestamps and cancellation timestamp. Source type comes from the source.
Foreign keys restrict source deletion; there is no hard-delete endpoint.

Timed values are aware UTC, PostgreSQL `timestamptz`; the SQLite adapter restores
UTC timezone information on read and rejects naive writes. All-day records also
retain `starts_on` and **exclusive** `ends_on` dates. Missing all-day end defaults
to the next day. Source timezone is Europe/Prague by default, so a day around DST
can last 23 or 25 hours without shifting its date. Floating times use source
zone; unknown TZIDs and nonexistent DST times are rejected. Ambiguous autumn
wall times follow the timezone/library first-occurrence convention. UTC and
TZID-aware events are normalized to UTC while retaining the zone label.

## Import semantics

`modules.calendar.service.import_ics(db, source, bytes)` owns no commit. The
caller commits Event, domain-event and Activity projection together, or rolls
back all of them. PostgreSQL locks the source for the transaction; event queries
refresh cached ORM rows before revision comparison. Concurrent first Moodle sync
uses conflict-safe source insertion. SQLite is suitable for tests/development;
simultaneous writers may receive locking/constraint errors (it has no row locks).

`icalendar==6.3.2` decodes VEVENT, UID, date/datetime, text escapes, timezone and
recurrence properties. Feed limit: 2 MiB / 2,000 events. A malformed component
increments errors without changing that identity; an unreadable whole calendar
returns an error and changes no events. Database/internal failures abort the
transaction rather than silently produce partial committed writes.

Each identity uses highest SEQUENCE then LAST-MODIFIED (fallback DTSTAMP).
Exact duplicates collapse. Conflicting equal revisions are skipped with an
error; explicit older source revisions cannot roll back newer content. Missing
revision fields preserve existing watermarks and allow unversioned feeds to
update. Their freshness cannot be proven; the latest supplied snapshot wins.

Meaningful changes create/update the same ID. Identical imports make no writes,
activity or events. A newer revision watermark with identical business content
may be stored to reject later stale feeds, but emits no change or updated-at
noise. Return counts: `created`, `updated`, `unchanged`, `cancelled`, `errors`.
No URL, UID, content excerpt or raw error is included in those stats.

Cancellation preserves the record, original schedule and the first timestamp of
that cancellation episode. An identity-only CANCELLED message can cancel an
existing record; without a known schedule, an unknown cancelled identity is
counted as an error. A cancellation without SUMMARY keeps the known title. A
later active update can reactivate the identity; prior cancellation remains in
Activity/domain history. Activity deltas retain previous title/location/schedule/
status facts. Descriptions are business content, not put into domain payloads or
change-feed summaries; no separate full event version table is introduced.

## Source presence: cancelled vs. disappeared (MRK-40)

Two different facts, both kept as history:

- **Cancelled** – the source says `STATUS:CANCELLED` (`status = 'cancelled'`).
- **Source-missing** – the identity is absent from a later *complete* snapshot of
  its source (`source_missing_at` set, migration `0020_calendar_source_presence`).
  Status is unchanged; nothing is deleted.

After each import, a complete snapshot reconciles presence in the same transaction
(under the PostgreSQL source row lock): present identities of that source absent
from it become source-missing (`calendar.event.source_missing` + one Activity row).
When the identity reappears, the **same row** is restored
(`calendar.event.restored`; content changes in the same import ride on that one
fact). Repeating a snapshot emits nothing.

A snapshot is complete only when the whole calendar parses, it contains at least
one VEVENT and every component has a readable UID. A malformed component with a
readable UID (or conflicting duplicates) protects that UID: it is never marked
missing. A failed download, an unreadable feed, an empty calendar or a rollback
never changes presence. Active views (occurrences, Today, AI context, page list)
exclude both cancelled and source-missing records; Search and the page history
still show them, labelled.

## Events vs. occurrences (MRK-40)

`calendar_events` rows are the durable imported facts: a single event, a recurring
master (RRULE and/or RDATE) or a RECURRENCE-ID override. **Occurrences** are what
actually happens in a window. They are computed at query time by
`modules.calendar.occurrences.get_calendar_occurrences(db, start, end)` and never
stored:

- A window is mandatory: aware bounds, end after start, at most 366 days (the API
  allows 92), plus an occurrence cap. An infinite rule only iterates up to the
  window end.
- Recurring masters expand with `python-dateutil` (`rrule`; no hand-written RRULE
  parsing): FREQ DAILY/WEEKLY/MONTHLY/YEARLY with COUNT, UNTIL (UTC, local or
  DATE form), INTERVAL, BYDAY etc. DTSTART is always the first instance. RDATE
  adds instances, EXDATE removes them (stored as normalized UTC instants/dates so
  their TZID is not lost; older raw values are still understood). Sub-daily rules
  are not expanded: only the stored first instance is shown.
- A present override replaces the generated instance with the same
  RECURRENCE-ID (moved occurrence); a cancelled override removes it. An override
  that went source-missing no longer applies, so the generated instance returns.
  A cancelled or source-missing master hides the whole series.
- **DST:** expansion runs in the event's own timezone (its TZID), so a weekly
  10:00 Europe/Prague lecture stays 10:00 local across CET/CEST (08:00 UTC in
  summer, 09:00 UTC in winter), never "+7 days in UTC". Per RFC 5545 §3.3.5,
  a generated wall time inside the spring gap uses the offset before the gap
  (02:30 → 03:30 CEST), and an ambiguous autumn time is its first occurrence
  (CEST). An imported DTSTART inside a gap is still rejected as before. A rule
  written in UTC (`Z`) recurs in UTC, as the RFC requires.
- All-day instances are dates: they keep `starts_on` and an exclusive `ends_on`,
  and overlap windows by Prague days, never shifting across DST or source zones.
- Timed instance duration is the master's exact elapsed duration.

`GET /calendar/occurrences?start=YYYY-MM-DD&end=YYYY-MM-DD` returns active
occurrences for local days `[start, end)` (max 92 days; invalid or too large
window → 422; normal auth and module gate). Each item has the event `id`, a
stable per-instance `key`, times/dates, title, location and a `recurring` flag.
No rule text or internal recurrence key is exposed in page payloads.

Not covered: RANGE=THISANDFUTURE overrides (rejected at import), VTODO/VJOURNAL,
sub-daily expansion, per-occurrence editing.

## Framework and UI

Backend and frontend manifests register only implemented capabilities: nav,
Search, Today and AI context. Routers, refs and change providers are module
contributions. No Calendar branch is added to global aggregators.

- Today: active **occurrences** today (all-day has no time) and occurrences
  starting in the next seven days (upcoming). A generated instance has the ref
  `calendar_event:<id>@<instance>` so global dedupe keeps each instance; links go
  to `/calendar?event=<id>`. Global limits/order/dedupe apply.
- Search: event definitions (not generated instances), title/location through
  existing global matching and Czech normalization; recurring, cancelled and
  source-missing records are labelled. Results use `/calendar?event=<id>`; an
  out-of-window target is returned as `selected`, never mixed into active lists.
- AI context: a small snapshot of actual occurrences for today and the next
  seven days, no descriptions or tools.
  All context generation is deterministic, no LLM calls.
- What Changed: created, updated, cancelled, source-missing and restored via the
  module change provider. Domain types: `calendar.event.created`, `.updated`,
  `.cancelled`, `.source_missing`, `.restored`; payload has only IDs, status,
  schedule and all-day flag. Activity is the same-transaction projection (one
  visible item per fact).
- `/calendar`: today/upcoming/recent occurrences (each recurring instance on its
  own date, labelled), a selected out-of-window record, and a history list of
  cancelled/source-missing records; source/status badges, empty/
  loading/error states and manual sync. Shared route guard and backend module
  gate hide the disabled module, preserving its stored data. A source disabled
  for sync retains its events for reading.

## Secret boundary and local connection later

Cloud uses synthetic fixtures only. Do not send/paste the actual private feed
URL/token to Codex, an issue, logs, screenshots or the frontend.

On the local host, keep the existing `MOODLE_ICS_URL` entry in the untracked
`backend/.env`; it has precedence over optional `CALENDAR_MOODLE_ICS_URL`.
The template contains blank commented entries only. Restart backend after env
changes, apply the migration to the intended local DB, and use **Synchronizovat**
on Calendar (authenticated `POST /calendar/sync`). No URL is accepted in its
request body. If the secret is absent, sync returns `feed_not_configured`; a
configured flag reveals only presence, never value. If source sync is disabled,
it returns `source_disabled` and doesn't fetch.

The server fetcher requires HTTPS with normal TLS verification, rejects redirects
and userinfo/fragment URLs, limits response size and uses a 15-second timeout.
Standard-library fetching avoids HTTP-client URL logging. Failures are reduced
to allowlisted categories; neither raw exception strings nor ICS content are
logged. API list DTOs expose no source configuration, external UID or description.
URLs are server-trusted env configuration, not user-supplied import targets.
Confirm source correctness locally before using reminders or planning; this branch
does not need a Windows PC, Tailscale, phone or real Moodle request to validate.

## Verification and next steps

Synthetic fixtures cover timed/UTC/TZID/all-day events, escaped text, changed and
cancelled messages, malformed events, duplicate UIDs and recurrence overrides.
Backend tests cover repeated imports, retained IDs/history, no unchanged-event
noise, stale cache/revision handling, rollback, auth, disabled module, Today,
Search, AI, What Changed, secret-safe failures and SQLite migration parity.
Frontend tests exercise grouping, exclusive all-day end, Prague formatting,
cancelled/empty rendering and disabled module routing.

Run from root with backend development dependencies:

```sh
python -m pytest backend/tests/test_calendar.py --disable-socket --allow-unix-socket -q
python -m pyflakes backend/*.py backend/modules/calendar/*.py backend/scripts/*.py
```

Use the CI dummy environment (README) for full backend tests. Frontend checks from
`frontend/`: `npm run lint`, `npx tsc --noEmit`, `npm test`, `npm run build`.
Migration checks require a **scratch** PostgreSQL DB: upgrade head, downgrade -1,
upgrade head, then opt-in `tests/test_migration_postgres.py` schema comparison.
Never use the production DB for a downgrade drill. No real Groq request is needed.

Next: validate the real feed locally without sharing its secret; then free-block
integration (MRK-32) on top of `get_calendar_occurrences`. Full calendar UI, editing,
background sync, Calendar AI actions and planner behavior remain separate work.

Cloud evidence (2026-10-09): focused Calendar **24 passed**; full backend
**915 passed, 8 skipped, 412 subtests passed**; frontend **341 passed**; lint,
TypeScript, pyflakes, dependency consistency and default Turbopack build passed
(24 routes). Existing backend deprecation warnings remain. PostgreSQL 16 scratch
upgrade/downgrade/upgrade and schema parity passed (**1 passed**, head
`0019_calendar`). Injected-fake-fetch PostgreSQL concurrency drill produced one
source/three records across two simultaneous first syncs; stale cached source
revision was rejected. Independent read-only review found no remaining blocker.

Latest main advanced to `068705b` during verification only in browser-check
scripts, with no model/migration change; the branch is rebased onto that baseline.
No real feed or production DB was used; **real Groq request count: 0**.

MRK-40 cloud evidence (2026-10-09, base main `36e933c`): recurrence/presence tests
**17 passed** (`test_calendar_occurrences.py`) plus Calendar **25**; full backend
**938 passed, 8 skipped**; frontend **344 passed**; lint, TypeScript, pyflakes and
production build passed. PostgreSQL 16 scratch: upgrade/downgrade -1/upgrade and
schema parity passed (head `0020_calendar_source_presence`). PostgreSQL
concurrency drill with injected synthetic fetches: 6 simultaneous first syncs →
1 source/2 events; 6 simultaneous "event dropped" syncs → exactly 1
`source_missing`; 6 simultaneous "event back" syncs → exactly 1 `restored`, same
row; 12 interleaved syncs → presence facts strictly alternate, Activity rows =
domain events, no errors, no secret-canary leak. Synthetic feeds only; **real
Groq request count: 0**.
