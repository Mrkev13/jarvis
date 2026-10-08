# MRK-22 verification

Source: MRK-22 issue text supplied in the task (Linear connector unavailable).
Baseline: `b386e86bf1219f0a50ba649dfa3508b4090e6202`, latest origin/main at start.
No merge into main. No production secrets or real LLM calls were used.

## Local results

- Backend requirements installed into a fresh Python 3.12 environment; pinned
  dev dependencies: pytest 9.1.1, pytest-socket 0.8.1, pyflakes 4.0.3.
- `python -m pyflakes backend/*.py backend/scripts/*.py`: passed.
- `python -m pytest backend/tests --disable-socket --allow-unix-socket -x -q`:
  **670 passed, 8 skipped, 345 subtests passed**. Existing deprecation warnings
  remain. Seven skips are Windows-only speech evaluations; one is the PostgreSQL
  opt-in test, run separately below.
- PostgreSQL 16 disposable container: `python -m alembic upgrade head`,
  `python -m alembic downgrade -1`, `python -m alembic upgrade head` passed.
  Final revision: `0014_wot_replays`. With TEST_POSTGRES_URL set,
  `python -m pytest tests/test_migration_postgres.py -x -q`: **1 passed**, no schema
  drift. The local database port was 55432 instead of the workflow's 5432.
- Frontend fresh `npm ci`, `npm run lint`, `npx tsc --noEmit`, `npm test`: passed.
  The runner reported 40 passing test files; a direct run with
  `node --test --test-isolation=none --no-warnings "lib/**/*.test.mjs"`
  confirmed **280 passing assertions**.
- Full default `npm run build` (Next.js 16.3.4 / Turbopack): **passed** in a
  disposable Node 24 container with the same source/dependencies, generating all
  20 pages. Direct cloud execution failed because its process sandbox forbids
  Turbopack's local CSS-worker port binding. Full `npm run build -- --webpack`
  also passed directly. CI keeps the default build and does not suppress failures.
- YAML parsed and actionlint 1.7.7 passed; `git diff --check` and `pip check` passed.

## Existing failure fixed

Current main failed
`ChangesNoiseTestCase.test_technical_activity_is_filtered_but_user_changes_stay`.
Its snapshot is fixed at October 6, 2026, but the seeded reminder audit row used
the actual wall clock. Once the real date advanced, that entry displaced one of
four expected changes and also changed the area counts. The fixture now explicitly
places reminder creation before the snapshot's 24-hour window after flushing the
pending audit row. All original assertions remain; production briefing behavior
is unchanged. No tests were deselected or marked xfail to obtain a green suite.

## Build determinism

The layout used `next/font/google` for Geist and Geist Mono. The same font families
are now loaded with `next/font/local` from bundled, unmodified variable fonts,
including their OFL licenses and source links. Existing CSS variables remain.
This removes the Google Fonts build dependency; the build still runs compilation,
type checking and static generation normally.

## Failure and network probes

A temporary deliberately broken pytest assertion, outside the repository, was
run with the workflow's pytest options and returned **exit code 1** with the first
failure reported. It was not committed. This simulates local test-step failure;
it is not a hosted failing PR simulation. A second temporary probe verified that
pytest-socket rejects an AF_INET socket before a TCP request can be sent.

CI uses an SDK initialization placeholder and a dead loopback GROQ_BASE_URL;
the backend pytest command blocks TCP sockets. Tests supply fake clients and
HTTP transports. Migration checks need only their disposable database credentials;
frontend checks need only a local API URL. **Exact real Groq request count: 0.**

## Remaining hosted verification

GitHub CLI/API calls are unavailable: the injected GH_TOKEN is invalid/API requests
are forbidden. Git transport can push the branch, but hosted workflow runs and PR
creation cannot be verified from this session. After push, inspect the three jobs
on GitHub: Backend tests and pyflakes; PostgreSQL migration round-trip; Frontend
lint, types, tests and build. Configure them as required checks in repository branch
protection/rulesets if desired. No ruleset, secrets or main branch was modified.

CI uses Python 3.12, Node 24 and PostgreSQL 16 without a matrix. Setup actions cache
pip downloads based on both requirements files and npm downloads based on the
frontend lockfile. Third-party registries/actions/image downloads still require
ordinary GitHub runner network access. Existing backend transitive dependencies
are resolved by pip; the direct requirements and dev tools are pinned.
