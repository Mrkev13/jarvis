# „Co se změnilo" (MRK-28)

A deterministic, LLM-free overview of what changed across modules in a period: the page `/changes` ("Co se změnilo",
core navigation right before Aktivita) and `GET /changes`. It builds on the domain events of MRK-19
([domain-events.md](domain-events.md)) and the MRK-20 module framework.

## Sources and precedence

| source | used for | title for people |
|---|---|---|
| `domain_events` (preferred) | flows converted to events (School completion/reopen, Habits done/skipped) | the summary of the event's Activity projection (`dedupe_key = event:<id>`) – the event payload carries no names |
| `activity_logs` (fallback) | legacy flows without events, and events already pruned by retention | the Activity summary |

An Activity row that is the projection of an event loaded for the same window is **consumed** by that event – one
change, never two. After retention (180 days by default) removes the event, the same Activity row becomes the
fallback, so nothing silently disappears.

## Module-owned providers

Each module maps its own changes in its `*_integrations.py` (`ModuleIntegrations.changes`, a
`module_contracts.ChangeSource`):

- `from_event(event, projection_title)` – for events whose `module_id` is the module,
- `from_activity(row)` – for Activity rows of the module's `areas`.

Most modules use the shared helpers `activity_changes({entity_type: href template}, default_href)` and
`event_changes({aggregate_type: href template}, fallback_titles)`. Core contributes reminders and memory through
`CORE_INTEGRATIONS`. The central `change_feed.py` knows no module ids (a test enforces it); it only collects,
dedupes, filters noise, hides disabled modules, sorts, derives filters and caps. A provider that raises is skipped
(logged by exception type only).

## Noise policy

The same as the morning briefing (`briefing_snapshot.meaningful_activity`):

- areas `ai`, `system`, `auth`, `backup`, `scheduler`, `maintenance`, `migration`;
- actions `snapshot`, `sync`, `cleanup`, `error`, …;
- test/verification contexts and `[test]` summaries;
- a record created **and** deleted within the window (no net effect).

The policy applies to the Activity projections of events too. An event whose projection is noise, or which belongs
to a record created and deleted in the window, is not shown. Operational areas and actions are excluded already in
SQL, so they never use up the scan cap. Core `system.*` events (module toggles) are operations, not changes for
people.

A projection is consumed only by an event that its owner can show (a `ChangeSource.from_event`). A test requires
every module that declares `event_types` to provide one. Otherwise its changes would vanish.

## `GET /changes`

| parameter | default | rules |
|---|---|---|
| `since` | now − 7 days | ISO 8601 (`Z` or offset); older than 90 days is clamped to 90; future or invalid → 422 |
| `module` | all | comma list of module ids, `core` for reminders/memory; invalid token → 422 |
| `limit` | 50 | clamped to 1–200 (non-number → 422) |

```json
{
  "since": "2026-10-01T12:00:00Z",
  "items": [
    {"id": "event:41", "occurred_at": "2026-10-08T11:00:00Z", "module_id": "school",
     "entity_type": "assignment", "entity_id": "12", "kind": "completed",
     "title": "Úkol splněn: Sada 4", "summary": "", "href": "/school?assignment=12", "source": "event"}
  ],
  "total": 6,
  "truncated": false,
  "filters": [{"id": "core", "label": "Obecné", "count": 1}, {"id": "school", "label": "Škola", "count": 2}]
}
```

- `ChangeItem` fields:
  - `id` – `event:<id>` or `activity:<id>`;
  - `module_id` – `null` means core;
  - `kind` – the event action (`completed`, `done`, …) or the normalised Activity action (`created`, `updated`,
    `deleted`, …);
  - `href` – a deep link, or `null` when the record can no longer be opened (deleted).
- `filters` are derived from the whole window. They are independent of `module`, so a selected filter can always be
  turned off again.
- `truncated` is set when more than `limit` items match, or when the scan cap of 2000 events / Activity rows per
  request was reached. That happens after a very long absence. The page then says "… a dalších N změn", or, when only the scan cap was hit,
that older changes were not loaded.
- The endpoint uses the global session auth. It never calls an LLM.

## Page

- **Filters:** period (24 h / 7 days / 30 days) and module chips. The chips are derived from the response and
  shown only when there is more than one module.
- **List:** grouped by Prague day, newest first, with Czech kind labels and deep links.
- **Realtime:** any domain event or stream reset (the shared MRK-19 SSE connection) triggers one debounced refetch.
  There is no polling. A change completed on another device appears without a reload.

## Privacy

`/changes` shows only what Aktivita already shows to the same authenticated user. It returns no delta values and
no event payloads. Disabled modules contribute nothing.

## Not in this step

- A per-device "since last visit" marker and a Dashboard/Today card. These can be added client-side on top of
  `since` without a schema change.
- An optional one-sentence LLM phrasing on top of the deterministic list (P7).
