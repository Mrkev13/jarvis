# MRK-12: duplicate WoT records — Windows verification

Source of truth: the MRK-12 issue supplied in this task. Baseline: main
`b386e86bf1219f0a50ba649dfa3508b4090e6202`.

Current main already allows multiple milestones for the same tank, including
Ace Tanker and memorable battles without a mastery badge. The reported tank
restriction is **not reproducible** against the canonical model/service/schema.
This branch adds tests and documentation only. No migration is required by the
repository schema. No production behavior or WotGrind constraint was changed.
Local/production schema drift or an outdated frontend/backend build remains a
suspected cause, not a confirmed diagnosis. Local Claude must verify the real
Windows environment before proposing a fix.

## Paths inspected

- `frontend/app/wot/page.tsx`: new-record action, API list, sorting, ID-based cards,
  edit/delete, unique tank suggestions (suggestions alone are deduplicated).
- `frontend/components/wot/MilestoneForm.tsx` and `frontend/lib/wot.ts`: field
  validation and POST/PATCH selection; no existing-tank rejection.
- `frontend/components/wot/MilestoneCard.tsx`: ID-based record and replay links.
- `frontend/components/wot/replays/ReplayForm.tsx`, `ReplayDetail.tsx`,
  `frontend/app/wot/replays/page.tsx`, `frontend/lib/wotReplays.ts`: replay metadata,
  milestone selection and filters.
- `frontend/components/games/GameImage.tsx`, `frontend/lib/gameAssets.ts`: image
  mapping by tank does not determine record identity.
- `backend/main.py`: WotMilestoneRequest (Pydantic), create/update/delete endpoints,
  WotGrindRequest/upsert, replay upload and error handling.
- `backend/schemas.py`: no separate milestone uniqueness validator.
- `backend/wot_service.py`: validation, insert, ID-scoped CRUD, completion history.
- `backend/wot_replay_service.py`: SHA-256 duplicate detection, ID-based links,
  one linked milestone per replay, create-from-replay and filtering.
- `backend/models.py`, migrations `0001_initial_baseline.py`,
  `0013_wot_milestones.py`, `0014_wot_replays.py`: only grind tank is unique;
  milestone/completion tank and replay tank are not unique.
- `backend/search_service.py`: existing search indexes grinds and replays;
  milestones do not have a separate global-search entry on this baseline.

The correct retained restrictions are one grind row per exact tank name (POST
updates the existing row), duplicate replay bytes by SHA-256, and refusal to
create another milestone from an already linked replay. Repeated grind cycles
produce independent completion history. A dedicated `memorable` milestone type
does not exist: memorable battles use the existing milestone type with optional
mastery and notes/favorite. No new record types were introduced.

## Local Claude checklist

1. Record the running frontend/backend process working directories, command
   lines and commit IDs (`git rev-parse HEAD`, `git status --short`). Confirm which
   backend the browser actually calls in Network and that its configured DB is
   the intended PostgreSQL instance. Do not print connection credentials. Preserve
   MRK-16's worktree/processes and existing WoT data.
2. Connect read-only to the actual DB and run the SQL below. Record database,
   schema, Alembic revision, constraints, unique indexes, and existing tank rows.
   Replace `public` if the app uses another schema. Expected revision on this
   baseline is `0014_wot_replays`; expected UNIQUE(tank) is on wot_grinds only.
   Inspect indexes as well as constraints: a standalone unique index can reject
   duplicates even without an entry in pg_constraint.

   ```sql
   SELECT current_database(), current_schema();
   SHOW search_path;
   SELECT version_num FROM public.alembic_version;
   SELECT n.nspname, t.relname, c.conname, c.contype,
          pg_get_constraintdef(c.oid)
   FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
   JOIN pg_namespace n ON n.oid = t.relnamespace
   WHERE t.relname IN ('wot_milestones', 'wot_grinds',
                       'wot_grind_completions', 'wot_replays')
   ORDER BY n.nspname, t.relname, c.conname;
   SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes
   WHERE tablename IN ('wot_milestones', 'wot_grinds',
                       'wot_grind_completions', 'wot_replays')
   ORDER BY schemaname, tablename, indexname;
   SELECT id, tank, milestone_type, mastery, played_on, notes
   FROM public.wot_milestones WHERE tank = 'Progetto 65' ORDER BY id;
   SELECT id, tank_name, linked_milestone_id FROM public.wot_replays
   WHERE tank_name = 'Progetto 65' ORDER BY id;
   ```

3. Confirm the running build corresponds to the recorded checkout. For a Next
   production process, inspect `.next/BUILD_ID` and build/start timestamps; an
   updated checkout does not prove the running bundle is current. Compare the
   actual page/form with the inspected sources. Capture evidence before any
   approved rebuild/restart; then hard reload and retest. Do not alter migrations
   or constraints merely because a build is old.
4. Prefer a restored DB/media copy for write verification. Through **Mka & nejlepší
   bitvy → Přidat Mko**, create two Progetto 65 Ace entries with distinct diagnostic
   notes/dates. Record both POST `/wot/milestones` requests, status codes, response
   bodies and returned IDs. Repeat for no-badge memorable battles if relevant.
   Ensure this action did not use **Přidat grind** or reuse an already linked replay.
5. GET `/wot/milestones`, rerun the tank-row SQL and verify two distinct IDs appear
   in DB, response and cards after reload. If creation fails, capture exact backend
   exception/constraint name and response. If both DB/API records exist but one
   card is absent, inspect the frontend bundle/state/rendering rather than schema.
6. Link two different replay files (different SHA-256) to the two milestone IDs.
   Verify each replay detail and milestone `replay_ids`, tank/mastery filters and
   replay search keep both. Verify GameImage resolves the same tank for both cards.
   Edit one milestone; verify the other's fields/link are unchanged. Delete only
   a recorded diagnostic milestone; its replay remains unlinked and the second
   milestone/replay remains linked. Preserve all pre-existing records/files.
7. On the test copy, POST the same active grind twice: one grind row/ID remains,
   its XP updates, and no historical milestone is overwritten. Complete/reactivate/
   complete it and verify two completion-history IDs. Do not test by overwriting a
   user's live grind. Clean up only the diagnostic IDs if cleanup is authorized.
8. Report the exact affected entity, failing request, constraint/index (if any),
   running commits/build ID, revision, before/after row IDs and API/UI evidence.
   Classify the cause as old build, wrong DB/API target, stale migration/schema
   drift, or unreproduced. A future migration requires evidence of a real incorrect
   constraint and validation against a restored copy; this branch has none.

## Regression commands and scope

```powershell
python -m unittest discover -s backend/tests -p test_wot_duplicate_records.py -v
python -m unittest discover -s backend/tests -p test_wot_milestones.py -v
python -m unittest discover -s backend/tests -p test_wot_replays.py -v
python -m unittest discover -s backend/tests -p test_alembic_migration.py -v
cd frontend
npm test
node --test --test-isolation=none --no-warnings "lib/**/*.test.mjs"
```

New backend tests use the real Pydantic/endpoint/service paths with fresh SQLite
and temporary replay files. They block network connections; 0 Groq requests.
Frontend tests run the actual WoT page list with mocked resource data and inert UI
shells, plus real form validation/sorting. They cover record retention, not browser
interactions/auth or the real PostgreSQL deployment. Milestones currently have no
UI filter; replay tank/mastery filtering is covered in backend regressions.

Cloud verification: 62 WoT tests passed (including four new tests), 15 Alembic
tests passed, and 282 frontend assertions passed across 41 test files (including
two new assertions). `git diff --check` passed. Existing HTTP tests required an
unsandboxed run because sandboxed TestClient calls hung before WoT handling.
The migration startup test emitted existing deprecation warnings and scheduler
errors about missing tables in its in-memory test DB; the suite passed. No real
PostgreSQL deployment or Windows UI was tested in cloud, and no Groq requests
were made. No merge was performed.
