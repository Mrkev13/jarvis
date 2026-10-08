# MRK-29 — completed-record history audit

Baseline: `origin/main` at `cf783a0` (2026-10-08). Repository audit only; no real DB,
user records or Groq inspected. Linear was unavailable; the supplied issue is the
scope. SAFE applies to the named path, not every write in that module.

## Inventory and classification

| Module | Record | Completion/history fields | Delete behavior | Overwrite risk | Recommendation |
| --- | --- | --- | --- | --- | --- |
| School | Assignment | `status`, `completed_at`; completion/reopen ActivityLog | Manual and generic mutation hard-delete; delete delta omits `completed_at`; generic undo carries full row | Generic create/status update can produce done without completion time; generic reopen/undo may clear time without preserving it in audit | **SAFE** first dedicated completion/reopen (repeat-cycle dedupe is follow-up); **FOLLOW-UP NEEDED** generic parity + delete metadata, respecting MRK-14 ownership |
| School | Exam/result | `status`, `completed_at`, `result_type/value`; close/reopen delta retains original result | Hard-delete; manual/generic delete audit omits result/time; generic undo holds full row | Generic status updates bypass close/reopen rules; history relies on ActivityLog | **SAFE** first dedicated close/reopen (repeat-cycle dedupe is follow-up); **FOLLOW-UP NEEDED** generic parity and durable deleted-result snapshot |
| Goals | Goal/progress | Current `progress/status`; `GoalProgressHistory(progress,current_value,recorded_at)`; ActivityLog | Hard-delete; DB FK cascades all progress rows; latest goal fields in audit, not the series | Snapshots committed separately after manual/tool updates; generic goal mutations don't record progress snapshot; closed automatic goals may recalculate | **SAFE** append/dedupe snapshot helper; **FOLLOW-UP NEEDED** archive deleted series, atomic snapshot parity and closed-goal policy |
| WoT | Grind/completion | Current XP/status/start; independent `WotGrindCompletion` copies tank, XP/start/completion time | Manual/AI delete explicitly detaches completion FK; DB SET NULL; completion rows survive | Generic mutation `status=completed` bypasses record_completion; old completed rows have no invented date; tools reactivation lacks manual start reset | **SAFE** explicit complete, form/tool completion and detach; **FOLLOW-UP NEEDED** generic completion/undo parity and legacy archive policy |
| WoT | Milestone/replay | Battle date/stats, milestone ID; independent replay link; activity labels | Milestone hard-delete removes screenshots, unlinks but preserves replay; replay delete removes file | Milestone edits/deletes log labels, not full old battle stats; replay metadata/file history not recoverable from audit alone | **SAFE** independent replay/link lifecycle; **FOLLOW-UP NEEDED** explicit archival/deletion policy for battle facts and media |
| MFF | Character/build | Current tier/gear/roles/build completeness/status, `updated_at`; partial audit | Hard-delete; original delete audit contained only tier/completeness/status/priority | Same-name upsert overwrites gear/supports; edit audit partial; repeated summary dedupe can suppress later changes | **CHEAP FIX** preserve complete current build in manual delete delta; **FOLLOW-UP NEEDED** build-version and edit-event policy |
| Reminders | Reminder/occurrence | `status`, due/last_fired/updated times, `fire_count`; completion/cancel ActivityLog; deduped occurrence notifications | No reminder hard-delete route; done/cancelled retained; active guard prevents edits | Recurring series advances due time; missed occurrences deliberately coalesced; no immutable per-occurrence completion ledger | **SAFE** retain terminal rows and reject editing them; **FOLLOW-UP NEEDED** decide whether occurrence-level analytics warrant a ledger |
| Work | Work session | Business `date`, hours/rate/project; finance FK/sync flag; mutation deltas | Manual hard-delete keeps finance transaction; previous audit omitted link/sync flag; AI undo stores row | AI editing hours/rate rewrites linked income with amount delta; deletions aren't current-query facts; no period-close model | **CHEAP FIX** retain link/sync flag in manual delete audit; **SAFE** first distinct-summary amount delta (repeat dedupe is follow-up); **FOLLOW-UP NEEDED** closed-period/correction semantics if required |
| Finance | Transaction | `created_at`, amount/category/type/description; mutation audit | Manual hard-delete unlinks work; previous delta omitted original transaction timestamp; AI undo stores full row | AI edits replace financial values with old/new audit; deletion moves surviving evidence to deletion time unless original date retained | **CHEAP FIX** preserve `created_at` in manual delete audit; **FOLLOW-UP NEEDED** correction/void policy and generic deletion audit parity |

## Cheap-fix boundary

Only extend the **existing manual DELETE audit field lists** for MFF, work and
finance. Preserve hard-delete responses, work/finance unlink behavior, calculation
rules and transaction boundaries. No MRK-14 implementation, completion transitions,
models, migrations, generic mutation/undo logic, scheduler or frontend changes.
ActivityLog is independent of the deleted row and written before deletion in the
same transaction. This preserves the final record's facts in existing audit; it
is not a new archive API or a guarantee of a complete lifetime history.

## Paths inspected

- Schema: `backend/models.py`; Alembic `0001_initial_baseline`,
  `0009_reminders`, `0007_reconcile_schema_drift`, `0013_wot_milestones`,
  `0014_wot_replays`, `0015_school_completion` (plus migration-chain inventory).
- Manual endpoints: `backend/main.py` school create/complete/close/reopen/delete,
  goal create/update/delete, work create/delete, finance create/delete, MFF
  upsert/delete, WoT grind form/complete/delete and milestone/replay endpoints.
- Legacy tool writes: `backend/tools.py` add_school_assignment/exam,
  upsert_goal/mff_character/wot_grind, add_work_session/add_finance_transaction.
- Services: `school_service.py`, `goal_history_service.py`, `wot_service.py`,
  `wot_replay_service.py`, `reminder_service.py`, `activity_service.py`.
- AI/Today mutation and undo: `mutation_service.py` entity fields/snapshots,
  `_apply_one`, apply/undo paths and undo exclusions; `tool_registry.py` bindings,
  `ai.py` orchestration. AI wrappers do not make history immutable.
- Reads/consumers: `tools.py` history/current-state reads, scheduler goal snapshots,
  `briefing_snapshot.py`, `weekly_snapshot.py`, `statuses.py`.

## Separate issue recommendations

1. **School mutation parity (coordinate with MRK-14):** completion timestamps and
   result snapshots for generic create/update/delete/undo. Reopen remains a valid
   user action; preserve previous closure rather than blocking correction.
2. **Deleted goal archive:** PostgreSQL `ON DELETE CASCADE` destroys progress rows;
   SQLite without FK enforcement can instead leave orphans. Define archive/soft
   delete plus reader/restore semantics before changing schema. Generic undo
   already explicitly refuses goal deletion because the history cannot be restored.
3. **Progress snapshot transaction parity:** goal mutations/source deletions should
   retain appropriate before/after snapshots atomically. Decide whether closed
   automatic goal values are frozen or intentionally recomputed.
4. **WoT generic mutation parity:** confirmed status updates and their undo must
   follow the same completion-row rules as explicit/form completion. Preserve
   independent completions and keep the intentional unique active tank slot.
5. **MFF build history:** preserve old gear, roles/supports and completion facts on
   every update; avoid default upsert values silently erasing omitted fields.
   Decide versioning versus complete audit snapshots in its own issue.
6. **Audit dedupe/retention contract:** default key hashes only summary/entity/action,
   so repeated same-summary edits or reopen/complete cycles can suppress distinct
   facts; deletion keys can also collide when IDs are reused (e.g. SQLite re-creation).
   No ActivityLog retention purge was found, but historical consumers need
   an explicit durability contract. PendingAction row dumps/24-hour undo eligibility
   do not substitute for durable, queryable business history.
7. **Milestone/replay and financial/work corrections:** decide archive/void versus
   intentional destructive deletion, including media backup/restore and links.
   Deleted facts survive in audit only to the extent their payload was captured;
   existing current-table queries do not include audit archives automatically.
8. **Reminder occurrence history:** only add it if needed for real analytics;
   preserving every missed occurrence would change current coalescing behavior.

Existing data already overwritten/deleted cannot be reconstructed by these fixes.
Do not backfill fabricated completion dates or results. A Windows/PostgreSQL audit
of real rows, deployed migrations and backups remains a separate local operation.

## Verification

- Focused `test_deleted_record_history.py`: **4 passed, 22 passing subtests**.
  Missing payload fields reproduced on baseline before the fix; regression tests
  verify deletion/link behavior and rollback of audit together with the write.
- Full backend CI-equivalent suite: **700 passed, 8 skipped, 367 passing subtests**.
  Includes school completion, WoT history/replays, goals, MFF, reminders, finance,
  generic mutation/undo and weekly-review consumers.
- `python -m pyflakes backend/*.py backend/scripts/*.py` plus the new test: passed.
  `git diff --check`: passed. Existing datetime/Starlette deprecation warnings remain.
- Both pytest runs used `--disable-socket --allow-unix-socket`, SQLite and dummy
  client values with a dead loopback LLM URL. **Real Groq requests: 0**.
- No frontend or real Windows/PostgreSQL-data verification: frontend/schema
  behavior is unchanged; follow-up choices need real-environment review.
- Independent read-only review found no remaining important implementation issues.
