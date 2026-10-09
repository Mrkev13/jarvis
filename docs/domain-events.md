# Domain events, transactional outbox and SSE (MRK-19, Platform 2.0 B)

## Domain event vs. Activity log

| | `domain_events` (this) | `activity_logs` + business tables |
|---|---|---|
| Role | authoritative **fact** + transport (outbox) | durable, human-readable **history** |
| Written | in the business transaction (`append_domain_event`) | pilot flows: as a projection of the event, same transaction |
| Lifetime | **finite** – retention 180 days (90–365) | permanent (MRK-29: completed facts remain history) |
| Consumers | SSE, future Desktop Jarvis / Home Assistant / notifications | Aktivita page, undo, Year in Review |

**Future Year in Review / retrospectives must not depend on `domain_events` alone** – it is a replay/transport log
that is pruned. Long-term history lives in `activity_logs` and the business tables (completion fields,
`habit_entries`, goal history…), per [architecture-principles.md §19](architecture-principles.md).

## Transactional outbox guarantee

```
business change ─┐
append_domain_event(db, …)   ← same Session, flush (id), never commits
  └─ ActivityProjection → log_activity(…, dedupe_key="event:<id>")   ← in-transaction consumer
db.commit()      ─┘  → business row + event + activity row are stored together, or none of them (rollback)
after_commit hook   → static after-commit consumers get immutable snapshots (SSE wake-up)
```

- The helper uses the caller's session, opens no transaction of its own and never commits.
- A rollback (explicit or by exception) removes the business write, the event and the activity row together.
- After-commit consumers run only after a successful commit, outside the transaction. A failing consumer is logged
  with its exception **type only** (no payload, no message) and never affects the stored write.
- Registrations are static (`domain_events.register_after_commit`) – no plugin scanning.

## Schema (migration `0018_domain_events`, after `0017_habits`)

| column | type | notes |
|---|---|---|
| `id` | bigint PK (integer on SQLite) | monotonic, = SSE `id` |
| `event_type` | varchar(100), indexed | `<module>.<aggregate>.<action>` |
| `aggregate_type` | varchar(50) | lowercase identifier (`assignment`, `exam`, `entry`, `module`) |
| `aggregate_id` | varchar(64) null | stable textual id |
| `module_id` | varchar(50) null, indexed | owner module; `NULL` = core (`system.*`) |
| `occurred_at` | timestamptz, indexed | UTC |
| `payload` | JSON, default `{}` | small, privacy-safe |

Append-only: application code never updates rows; only retention deletes old ones. Ids are never reused (SQLite
`AUTOINCREMENT`, PostgreSQL sequence), so the projection key `event:<id>` cannot collide after retention.

## Naming convention

`<module>.<aggregate>.<action>` – lowercase letters, digits, `_`; exactly three parts; the first part is the owner
module id (`school`, `habits`), core uses `system`. Actions are past-tense facts.

Every type must be **declared**: module types in `ModuleDef.event_types` (`module_registry.py`), core types in
`domain_events.CORE_EVENT_TYPES`. `append_domain_event` rejects undeclared types and derives `module_id` from the
declaration. Pilot types:

| type | producer | payload |
|---|---|---|
| `school.assignment.completed` / `.reopened` | `school_service` | `assignment_id`, `subject_id`, `completed_at` / `previous_completed_at` |
| `school.exam.closed` / `.reopened` | `school_service` | `exam_id`, `subject_id`, `outcome`, `result_type`, `completed_at` / `previous_outcome` |
| `habits.entry.done` / `.skipped` | `modules/habits/service.set_entry` (only when the state changes; a note/value edit is Activity history only) | `habit_id`, `entry_id`, `date`, `state`, `previous_state` |
| `fitness.exercise.created` / `.updated` / `.archived` / `.restored` | `modules/fitness/service` | `id`, `active` |
| `fitness.rehab_exercise.created` / `.updated` / `.archived` / `.restored` | `modules/fitness/service` | `id`, `active` |
| `fitness.workout.created` / `.updated` | `modules/fitness/service` | `id`, `date`, `count` |
| `fitness.rehab_session.created` / `.updated` | `modules/fitness/service` | `id`, `date`, `count` |
| `system.module.enabled` / `.disabled` | `PUT /modules/{id}` | `module_id`, `enabled`, `previous` |

**Payload rules:** a JSON object of ids, states, dates and ISO times only – at most 3 levels, 2 KB. No ORM objects,
no datetimes (use ISO strings), no names/notes/free text, no secrets. Text for people belongs to the
`ActivityProjection`, not to the transported event.

**Legacy paths:** every other `log_activity` call site is unchanged (no event). Reminders are not converted yet.
Broader adoption is MRK-20+ work, one flow at a time when it is touched.

## SSE contract – `GET /events/stream`

Authenticated by the normal session cookie (global auth dependency); `EventSource(url, { withCredentials: true })`.

```
retry: 3000

id: 41
event: ready
data: {"latest_id":41}

id: 42
event: domain_event
data: {"id":42,"type":"habits.entry.done","module_id":"habits","aggregate_type":"entry",
       "aggregate_id":"7","occurred_at":"2026-10-08T12:00:00Z","payload":{"habit_id":3,...}}

id: 57
event: reset
data: {"reason":"retention","latest_id":57}

: keepalive
```

- The first frame after `retry` is `ready` (`id` = the stream position: the client's cursor, or the newest stored id
  when there is none; `0` for an empty table) – or a `reset` instead. The browser therefore knows its position before
  the first event, and a reconnect in that window replays instead of starting "from now".
- Events are emitted in ascending `id` order; `id` = `domain_events.id`.
- `: keepalive` comment after ~15 s without output; the connection ends when the client disconnects.
- The session is re-validated about every 15 s; after logout, revocation or expiry the open stream ends.
- Events of **disabled modules are never streamed** (the cursor still moves past them). Optional filters:
  `?modules=school,system&types=habits.entry.done`.
- In-flight safety: if the next stored id is not `cursor + 1` and the newer event is younger than 5 s, the stream
  waits (a lower-id transaction may still commit); after 5 s the gap is treated as a rollback and skipped.

### Last-Event-ID and replay

Position = `Last-Event-ID` header (sent automatically by `EventSource` on reconnect) or `?last_event_id=`.

| situation | behaviour |
|---|---|
| no position | live only – no history |
| position with ≤ 200 newer retained events | replay them ascending, then continue live – no gap, no duplicate |
| position older than the oldest retained event (pruned) | one `reset` (`reason: retention`) |
| more than 200 newer events | one `reset` (`reason: overflow`) |
| position ahead of the newest event | one `reset` (`reason: unknown_cursor`) |

A `reset` carries `id` = newest stored id; the client re-fetches its state through REST and continues live from
there. The client honours a reset even to a **lower** id (e.g. a restored database), so new events are not dropped. (The retention check is conservative: a rolled-back id right after a pruned range can cause an extra,
harmless reset.)

## Retention

`DOMAIN_EVENTS_RETENTION_DAYS` – default **180**, allowed **90–365**; out-of-range values are clamped to the nearest
bound and non-numeric values fall back to 180 (both logged). `cleanup_domain_events` deletes only rows with
`occurred_at < now − days` (an event exactly at the threshold is kept), at most 5000 per run, and runs as a global
infrastructure step of the hourly scheduler job. It never touches `activity_logs`, `habit_entries`, School
completion fields, goal history or any other business table.

## Frontend

- `lib/domainEvents.ts` – SSE parser, payload validation, at-most-once tracker (monotonic ids), reset handling,
  `createDomainEventClient` over an injectable `EventSource` (automatic reconnect with `Last-Event-ID`; a closed
  connection is reopened with `?last_event_id=` and back-off 1/3/10/30 s), and the single Jarvis mapping table.
- `hooks/useDomainEvents.ts` – one shared connection for the whole app; opens with the first listener, closes with
  the last. The position is not persisted across page reloads (a reload starts live-only).
- `components/events/DomainEventsBridge.tsx` (in `AppShell`):
  - `system.module.enabled/disabled` → `refreshModules()` – another tab/device toggling a module updates navigation
    and routes immediately, without reload or polling (fixes the MRK-18 limitation);
  - `reset` → `refreshModules()`;
  - fresh School completions (< 2 min) → Jarvis success pulse.

## What remains (MRK-20 and later)

- Convert further flows one by one (reminders incl. time events with a dedupe key, goals, work/finance, WoT).
- More realtime consumers (notifications, Desktop Jarvis MRK-17, Home Assistant) via `register_after_commit`
  or the SSE stream – never a second stream.
- Pending snapshots are cleared at the end of the root transaction (rollback or `close()`); a savepoint rollback keeps
  them. Today's only after-commit consumer (the SSE wake-up) reads from the DB, so the snapshot contents are advisory.
- The 5 s in-flight grace is measured from `occurred_at` (set at flush): a transaction committing more than 5 s after
  its append with a lower id than an already streamed event would be skipped. Pilot writers commit immediately.
- The in-process dispatcher assumes the single uvicorn worker; multiple processes would rely on the SSE DB poll
  (≤ 1 s) for cross-process delivery.
