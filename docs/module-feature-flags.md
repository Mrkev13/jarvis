# Module feature flags (Roadmap 6C)

Deterministic on/off switches for Standa Hub modules. **Not** an experimentation platform: no percentages,
cohorts, remote config or dependency graphs. Flags control **availability**, never **permissions** – auth runs
first everywhere and an enabled flag grants nothing.

## Model

| Concept | Where |
|---|---|
| Registry (backend, canonical for data/API/AI) | `backend/module_registry.py` – `MODULES`, `ModuleAccess`, `current_access()` |
| Registry (frontend mirror) | `frontend/lib/modules.ts` – `MODULES`, `createModuleAccess()` |
| Env parsing (backend) | `backend/env_config.py` – `parse_flag` (used by `module_registry.env_override`) |
| Resolver env > DB > default (backend, the only place) | `backend/module_registry.py` – `resolve_states`, `save_override` |
| Stored settings | `module_settings` table (`models.ModuleSetting`, migration `0016_module_settings`) |
| Runtime state (frontend, the only place) | `frontend/lib/moduleRuntime.ts` + `frontend/hooks/useModules.ts` (`useModuleAccess()`) |
| Settings UI | `frontend/app/settings/page.tsx` → `components/modules/ModuleSettings.tsx` |
| Parity FE ↔ BE | `backend/tests/test_module_registry.py::FrontendParityTestCase` |

A module is **available** when it is `implemented` **and** its flag is on. A planned module (`food`, `fitness`,
`habits`, `projects`, `knowledge`, `car`, `travel`, `entertainment`) stays unavailable even with its flag set to
`true` – a flag never exposes an unfinished page.

Everything that belongs to no module is **core** and always available: Řídicí centrum, Dnes, Týdenní přehled,
Plánovač, Připomínky, Aktivita, Paměť, AI asistent, Nastavení, notifications.

### Capabilities

`nav`, `search`, `quick_add`, `today`, `dashboard`, `ai_context`. A capability is allowed only if the module
declares it **and** is available. The canonical question is always one call:

```python
current_access().allows("food", "ai_context")      # backend
```
```ts
MODULE_ACCESS.allows("food", "ai_context")          // frontend
```

Helpers map the things the app already has onto modules: `allows_entity(type, cap)` (search result type, ref
prefix), `allows_ref("exam:12", cap)`, `allows_context_area(area)`, `allows_quick_add_kind(kind)`,
`allows_path(path)` (backend API prefixes / frontend routes). Unknown types/areas/paths = core = allowed.

Gating is by **entity type / ref**, not by the `area` label: `fitness`, `travel` etc. are already used as labels
on memories and goals, and those must not disappear when the future Fitness module is off.

## Configuration (MRK-18 A2: runtime, env > DB > default)

One backend resolver (`module_registry.resolve_states`) decides whether a module is enabled:

| Priority | Source | Where | Change takes effect | Settings toggle |
|---|---|---|---|---|
| 1 | **env override** | `MODULE_<ID>_ENABLED` in `backend/.env` | backend restart (dotenv loads once) | **locked** ("Vynuceno konfigurací serveru"), `PUT` → **409** |
| 2 | **DB setting** | `module_settings` row (Nastavení → Moduly) | immediately, no rebuild/restart | editable |
| 3 | **manifest default** | `ModuleDef.default_enabled` | release | editable |

`implemented=False` always wins: a planned module stays unavailable whatever the source says.

**What counts as an env override:** the variable is present **and** holds a valid boolean
(`1/true/yes/on`, `0/false/no/off`, trimmed, case-insensitive). Absent or blank = no override.
**Malformed** (`ture`, `maybe`) = **no override** (A1 policy: a typo must neither hide nor force a module) –
logged once as a warning, then DB/default apply.

**DB settings** hold only explicit deviations: one row per module whose chosen state differs from the manifest.
Choosing the default value (or `enabled: null`) deletes the row – defaults are never duplicated into the DB.
The backend caches the rows in-process (single uvicorn worker) and refreshes on every `PUT`; a 30 s TTL covers
manual DB edits. A DB error (e.g. table missing before migration) falls back to the last known state, otherwise
env/manifest – request gating never raises because of settings.

**Frontend has no module flags.** It loads runtime state from `GET /modules` (`hooks/useModules.ts`, started by
`ModuleRuntimeLoader` in `AppShell`, refreshed when the window becomes visible and after each Settings change),
caches it in localStorage (`standa-hub:modules:v1`) so a returning visit renders without a flash, and stays
**conservative** while the state is unknown or unavailable: only core pages in nav/Ctrl+K, module routes show a
loading/error state (never content), module widgets hidden. The backend remains authoritative for data
(search, Today, Quick Add, AI, REST 404); the frontend additionally filters what it renders.

### API

`GET /modules` (auth) – per module: `id`, `label`, `available` (implemented && enabled), `enabled`, `source`
(`env | db | default`), `locked` (= `source == "env"`), `implemented`, `default_enabled`, `depends_on` (empty for now),
`capabilities` (only when available). Booleans and enums only – never env values.

`PUT /modules/{id}` (auth), body `{"enabled": true | false | null}` (`null` = back to default):
- `200` → the module's new `GET /modules` entry; writes only `module_settings` (module data is never touched);
  each real change is audited as `system` / `module.enabled` | `module.disabled`;
- `404` unknown module · `409` env-forced (`{"detail": {"message": "Vynuceno konfigurací serveru.", "module": id}}`)
  · `422` planned/unimplemented module or invalid body.

Core (Řídicí centrum, Dnes, Plánovač, Připomínky, Paměť, AI, Nastavení…) is not in the registry and cannot be disabled.

## Behaviour per surface

| Surface | Disabled module |
|---|---|
| Sidebar + mobile menu | No link (`navPagesFor(access)` in `Sidebar.tsx`; both menus use the same component). |
| Global Search (Ctrl+K) | Pages filtered from navigation results; records filtered on the backend (`search_service.search`, by `SearchResult.type`) and again on the frontend (`filterAvailable`, also for “Nedávno otevřené”). Ranking unchanged. |
| Dashboard | Widget not in the layout: not rendered, not among hidden widgets, no fetch. Mixed widgets render only available parts (Hry = WoT/MFF, Klíčová čísla = Práce/Finance, Rychlé akce links). `GET /dashboard` skips disabled sections (`null`) and planner items. |
| Dashboard storage | Stored entries of disabled widgets are kept untouched when the user edits the layout (`preserveUnavailable`); re-enabling restores position, visibility and size. With no stored entry the existing “new widget after its predecessor” rule applies. “Obnovit výchozí” clears everything (as before). |
| Quick Add | `parse` returns `unknown` for a disabled kind (no fields, nothing to save); `prepare` refuses it with 422 even if a client sends it. Frontend hides its examples/hint and treats such a parse as unknown. Future modules: register `quick_add_kinds`; no parser is needed for the gate. |
| Today | Items whose ref belongs to a module without `today` are dropped from every section (`today_service.gate_items`); `POST /today/actions/prepare` returns 404 for such a ref. |
| AI context | CURRENT STATE sections of modules without `ai_context` are not built (`context_service`); tools whose every area belongs to such modules are not offered (`tool_router._ordered`). The multi-area tool `modify_records` stays offered, but `mutation_service` refuses entities of a disabled module (`module_unavailable` at proposal time; a module switched off before confirm/undo = stale target, nothing changes). |
| Routes (frontend) | `ModuleRouteGuard` (in `AppShell`) renders “Modul není dostupný” with a link to Řídicí centrum; the page component is never mounted, so it fetches nothing. |
| Routes (backend API) | Global dependency `require_module_available` → `404 {"detail": {"message": "Modul není dostupný.", "module": id}}`, evaluated **after** `require_auth` (unauthenticated callers still get 401). |

### Main-era coverage (MRK-7)

The flags branch predates Game Enrichment B/C, Motion, Jarvis, School completion and Quick Add time parsing. When it
was ported onto current `main`:

- **WoT**
  - `wot_replay` (Replay Library search results) belongs to `wot.entity_types`.
  - The `/wot` prefix also covers `/wot/replays`, `/wot/milestones`, `/wot/screenshots` and `/wot/grind/{id}/complete`, for both the frontend route guard and the backend API.
  - Milestones and grind completions have no search result type, so they need no entity type.
  - The dashboard "Hry" widget shows its WoT part only when WoT is available.
- **School**: the completion endpoints (`/school/assignment/{id}/complete|reopen`, `/school/exam/{id}/close|reopen`) follow the `school` flag through the `/school` prefix.
- **Core, never gated**: Quick Add clock-time parsing (appointments become reminders), the Jarvis companion and avatar, Motion, the icon system, Today, reminders and the AI page.
- **Parity**: besides ids, defaults, capabilities, entity types and Quick Add kinds, a test now checks that every frontend module route is also a backend API prefix.

Initial rollout is zero-surprise: all six shipped modules (`school`, `work`, `finance`, `goals`, `wot`, `mff`)
default to enabled, all eight future modules default to disabled and have no capabilities.

## How to register a new module

Since MRK-20 a module registers **once**: its `ModuleDef` (backend) / `MODULES` + `MODULE_UI` (frontend) entry and
its providers in `backend/<id>_integrations.py`. Search, Today, `GET /dashboard`, AI context, Quick Add, the hourly
job, navigation and Ctrl+K pick it up and gate it automatically. Step-by-step:
[module-integration-checklist.md](module-integration-checklist.md). Contracts, the list of what stays global and the
remaining legacy places: [module-framework.md](module-framework.md).

- Brand-new id (not in the list yet): also add the commented `MODULE_<ID>_ENABLED` line to `backend/.env.template`.
  The frontend needs nothing else – state arrives at runtime via `GET /modules`.
- Nothing should need an `if (FOOD_ENABLED)` check. If a component needs one, ask
  `useModuleAccess().access.allows(id, cap)` (frontend) or `current_access().allows(id, cap)` (backend).

## Future: user-level preferences (not implemented)

`ModuleAccess` takes a plain flags mapping. A per-user layer would narrow it before construction:

```python
effective = {mid: app_flags[mid] and user_prefs.get(mid, True) for mid in app_flags}
access = ModuleAccess(effective)
```

Rule: a user can only turn a module **off**, never on something the app disabled. On the frontend the same
narrowing would happen after loading the preference (e.g. from `GET /modules` extended with user data);
`createModuleAccess(flags)` already accepts any mapping. DB storage, an endpoint and a settings UI are out of scope.

## A1 vs. A2 (MRK-18) – A2 complete

- **A1 (MRK-7):** registry, capabilities, gating, `GET /modules`; flags from env only, frontend rebuilt per change.
- **A2 (MRK-18):** `module_settings` table (migration `0016_module_settings`), env > DB > default resolver,
  `PUT /modules/{id}` with env lock (409), Settings → Moduly page, frontend runtime state (no `NEXT_PUBLIC_*`
  module flags, `moduleConfig.ts` removed). Disabling a module never deletes its data; re-enabling restores
  records and the stored dashboard layout (`preserveUnavailable`).

**Next: MRK-19** (event bus / outbox) – not started here.

## Verification

- Unit: `backend/tests/test_module_registry.py`, `backend/tests/test_module_settings.py` (precedence, DB cache,
  `PUT`, 409, audit, data intact), `frontend/lib/modules.test.mjs`, `frontend/lib/moduleRuntime.test.mjs`
  (runtime gating, conservative unknown/error state, no `NEXT_PUBLIC_MODULE` dependency).
- Migration: `test_alembic_migration.py` (0016 up/down on SQLite) and `test_migration_postgres.py` (head = models).
- Browser: `frontend/scripts/module-flags-check.mjs` against **one** build – mock API state is switched at runtime:
  default run (plus Settings toggle without rebuild, env-locked toggle + 409, `/modules` unavailable) and
  `UI_FLAGS_DISABLED=wot,finance` (stored-setting simulation; incl. Replay Library, replay search, Quick Add,
  School completion, Jarvis companion, Today links).
