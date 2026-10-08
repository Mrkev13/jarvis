# Module feature flags (Roadmap 6C)

Deterministic on/off switches for Standa Hub modules. **Not** an experimentation platform: no percentages,
cohorts, remote config or dependency graphs. Flags control **availability**, never **permissions** – auth runs
first everywhere and an enabled flag grants nothing.

## Model

| Concept | Where |
|---|---|
| Registry (backend, canonical for data/API/AI) | `backend/module_registry.py` – `MODULES`, `ModuleAccess`, `current_access()` |
| Registry (frontend mirror) | `frontend/lib/modules.ts` – `MODULES`, `createModuleAccess()` |
| Env parsing (backend) | `backend/env_config.py` – `parse_flag` / `env_flag` |
| Env reading (frontend, the only place) | `frontend/lib/moduleConfig.ts` – `MODULE_FLAGS`, `MODULE_ACCESS` |
| Parity FE ↔ BE | `backend/tests/test_module_registry.py::FrontendParityTestCase` |

A module is **available** when it is `implemented` **and** its flag is on. A planned module (`food`, `fitness`,
`habits`, `projects`, `knowledge`, `car`, `travel`, `entertainment`) stays unavailable even with its flag set to
`true` – a flag never exposes an unfinished page.

Everything that belongs to no module is **core** and always available: Řídicí centrum, Dnes, Týdenní přehled,
Plánovač, Připomínky, Aktivita, Paměť, AI asistent, notifications.

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

## Configuration

| Side | Variable | Read | Change takes effect |
|---|---|---|---|
| Backend | `MODULE_<ID>_ENABLED` in `backend/.env` | per call (`current_access()`) | restart (dotenv loads once) |
| Frontend | `NEXT_PUBLIC_MODULE_<ID>_ENABLED` in `frontend/.env.local` | inlined at `next build` | rebuild |

Values: `1/true/yes/on`, `0/false/no/off` (trimmed, case-insensitive). Missing, blank **or invalid** = the
module's default (a typo never hides a shipped module or enables a future one; the backend logs a warning once).
Unlike `env_bool`, invalid is not `false` on purpose.

Set both sides the same. If they drift, it still fails cleanly: the backend is authoritative for data (search,
Today, Quick Add, AI, REST 404), the frontend additionally filters what it renders (search results, Quick Add
parse result, recent items) so a mismatched build never shows a disabled module's records.

Client exposure: only the 14 boolean `NEXT_PUBLIC_MODULE_*` values are inlined (literal references in
`moduleConfig.ts`; dynamic `process.env[name]` would not be). Flags are not secrets. `GET /modules` (auth
required) returns `{id, label, available, capabilities}` only – no env values.

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

1. **Registry (both sides, one line each):**
   - `backend/module_registry.py`: replace `_planned("food", "Jídlo")` with a full `ModuleDef(...)` –
     `implemented=True`, `default_enabled` (usually `False` until ready), `capabilities`, `entity_types`
     (search result types / ref prefixes), `context_areas`, `api_prefixes`, `quick_add_kinds`.
   - `frontend/lib/modules.ts`: the same entry on one line (`routes` instead of `api_prefixes`).
   - Brand-new id (not in the list yet): also add the literal line to `frontend/lib/moduleConfig.ts` and the
     templates (`backend/.env.template`, `frontend/.env.template`). Tests fail if `moduleConfig.ts` misses it.
2. **Navigation / search page:** add the page to `NAV_PAGES` with `module: "<id>"`.
3. **Search records:** add the source to `search_service._candidates()` with a type listed in `entity_types` –
   filtering is automatic.
4. **Dashboard widget:** `WIDGETS` entry with `modules: ["<id>"]`; the `/dashboard` section guarded by
   `shows("<id>")` in `main.dashboard_get`.
5. **Today:** items with ref `"<entity_type>:<id>"` – gating is automatic.
6. **Quick Add:** kind in `quick_add_kinds` (backend + frontend); parser per the integration checklist.
7. **AI:** context area in `context_areas`; tools with that area in `tool_registry` – gating is automatic.
8. **Routes:** page under `frontend/app/<route>/`, REST under the declared prefix – both gated automatically.
9. **Tests:** `test_module_registry.py` parity passes; add the module to the browser check if it has a page.

Nothing else should need an `if (FOOD_ENABLED)` check. If a component needs one, ask `MODULE_ACCESS.allows(id, cap)`.

## Future: user-level preferences (not implemented)

`ModuleAccess` takes a plain flags mapping. A per-user layer would narrow it before construction:

```python
effective = {mid: app_flags[mid] and user_prefs.get(mid, True) for mid in app_flags}
access = ModuleAccess(effective)
```

Rule: a user can only turn a module **off**, never on something the app disabled. On the frontend the same
narrowing would happen after loading the preference (e.g. from `GET /modules` extended with user data);
`createModuleAccess(flags)` already accepts any mapping. DB storage, an endpoint and a settings UI are out of scope.

## A1 vs. A2 (MRK-18)

This is **A1**: flags come from the environment only, and the frontend needs a rebuild after a change.
- Backend: `MODULE_<ID>_ENABLED`.
- Frontend: `NEXT_PUBLIC_MODULE_<ID>_ENABLED`, inlined at build time. Set both the same.

`GET /modules` already reports availability. **A2** will:
- add a DB `module_settings` table and a Settings toggle;
- resolve flags as env > DB > default;
- switch the frontend from build-time `NEXT_PUBLIC_MODULE_*` to runtime `GET /modules`.

None of that is implemented yet.

## Verification

- Unit: `backend/tests/test_module_registry.py`, `frontend/lib/modules.test.mjs`.
- Browser: `frontend/scripts/module-flags-check.mjs` (incl. Replay Library routes/deep links, replay search, Quick Add
  time parsing, School completion action, Jarvis companion, Today links) against a default build and a build with
  `NEXT_PUBLIC_MODULE_WOT_ENABLED=false NEXT_PUBLIC_MODULE_FINANCE_ENABLED=false` (`UI_FLAGS_DISABLED=wot,finance`).
