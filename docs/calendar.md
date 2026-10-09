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
counted as an error. Missing-from-feed never deletes or cancels anything. A
later active update can reactivate the identity; prior cancellation remains in
Activity/domain history. Activity deltas retain previous title/location/schedule/
status facts. Descriptions are business content, not put into domain payloads or
change-feed summaries; no separate full event version table is introduced.

## Recurrence boundary

RRULE, RECURRENCE-ID, RDATE and EXDATE metadata are preserved. Explicit recurrence
overrides are separate identities. **Rules are not expanded**: the master/first
stored instance and explicitly supplied exceptions are the only listed events.
The list labels a master with a rule as its first occurrence. RANGE overrides
are rejected; no automatic master cancellation propagation or free-block
availability is inferred. Recurrence expansion, exceptions reconciliation and a
complete timetable are later work, before relying on Calendar for recurring
reminders/planning.

## Framework and UI

Backend and frontend manifests register only implemented capabilities: nav,
Search, Today and AI context. Routers, refs and change providers are module
contributions. No Calendar branch is added to global aggregators.

- Today: active overlapping events today (all-day has no time); new events in
  the next seven days contribute to upcoming. Global limits/order/dedupe apply.
- Search: title/location through existing global matching and Czech normalization.
  Results use `/calendar?event=<id>`; selected historical/out-of-window records
  are also loaded and shown, so links do not point to fake detail routes.
- AI context: a small today/near-term schedule snapshot, no descriptions or tools.
  All context generation is deterministic, no LLM calls.
- What Changed: created, updated and cancelled via module change provider. Domain
  types: `calendar.event.created`, `.updated`, `.cancelled`; payload has only IDs,
  status, schedule and all-day flag. Activity is the same-transaction projection.
- `/calendar`: Today/upcoming/recent/cancelled lists, source/status badges, empty/
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

Next: validate the real feed locally without sharing its secret; then recurrence/
timetable completeness and free-block integration. Full calendar UI, editing,
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
