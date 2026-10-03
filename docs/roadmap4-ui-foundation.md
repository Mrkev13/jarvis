# Roadmap 4 – UI Foundation (preparation)

Input for Roadmap 4. **Status (Roadmap 4A):** the foundation is implemented — see
[design-system.md](design-system.md) and the status table below. Evidence comes from the Roadmap 3.5 frontend audit
(see [architecture-audit.md](architecture-audit.md), R1–R10). Recommendation: start Roadmap 4 with a
**Design System Audit/Foundation** (primitives + data-fetching hook), then migrate pages one at a time, then
visual polish.

## Status after Roadmap 4A

| Item | Status |
|---|---|
| Design tokens (`app/tokens.css`), HUD layer (`app/hud.css`) | ✅ done |
| `lib/format.ts` (formatNumber/Czk/Hours/Percent/Date/DateTime, plurals) | ✅ done; local `formatNumber` copies in goals/work/wot/finance replaced |
| `apiJson` / `readErrorDetail` / `ApiError` / `errorMessage` in `lib/api.ts` | ✅ done |
| `useApiResource` (loading true, refresh keeps data, abort, stale guard, debounce, polling) | ✅ done |
| AppShell: one `NotificationsBell`, no shell `<h1>`, shared scroll lock, Czech navigation | ✅ done (`Sidebar.tsx`, `layout.tsx`) |
| `PageHeader`, `PageSection`, `Card`, `MetricCard`/`StatGrid`, `StatusBadge`, `Progress`, `EntityList/Row`, `EmptyState`/`ErrorState`/`Skeleton`/`LoadingState`, `Button`, `FormField`, `Tabs`, HUD accents | ✅ done (`components/ui`) |
| `ConfirmDialog` rebuild (role, aria-modal, focus trap, busy, Escape, focus restore) | ✅ done; old import path re-exports it |
| Reduced motion for Tailwind `animate-*` | ✅ done |
| Migrated pages: dashboard (Řídicí centrum), reminders, weekly review (+ Daily Briefing / weekly cards, PushSettings) | ✅ done |
| Browser checks: `frontend/scripts/ui-check.mjs` + fixture mock API | ✅ done |
| `FilterBar`, `Modal`/`Drawer` | ⏳ not needed by the migrated pages – build with their first real user (activity/memory filters, notification panel) |
| Remaining pages: school, finance, work, goals, wot, mff, planner, activity, memory, login, AI | ⏳ Roadmap 4B (AI assistant: 4G) |
| Search debounce on activity/memory | ⏳ comes free with `useApiResource({debounceMs})` when those pages migrate |
| `middleware.ts` → `proxy.ts` (Next 16), one `API_URL` constant | ⏳ 4B (touches auth; do it with a login regression check) |
| Notification panel (inside the bell), planner cards, `/activity` light-theme cards | ⏳ 4B |
| Backend copy in English (e.g. planner "Vyřešit overdue úkol") | ⏳ fix at the source (backend) |

## Status after Roadmap 4B

| Item | Status |
|---|---|
| Login shell without navigation/bell/polling, labelled PIN | ✅ `components/AppShell.tsx`, `lib/shell.ts`, `app/login/page.tsx` |
| Mobile menu: dialog, focus into menu, Escape + focus return, focus to content after navigation, skip link | ✅ `Sidebar.tsx`, `Drawer` |
| `Drawer` (+ shared `useModal`, portal) | ✅ used by mobile menu and notification panel |
| Notification panel in the design system | ✅ `NotificationsBell.tsx` |
| `FilterBar` / `FilterSelect` / `FilterChips` | ✅ used by activity, memory, MFF |
| Touch targets (TextLink hit area, 44 px buttons/tabs on touch) | ✅ checked by ui-check |
| Dashboard wide layout (no empty column, no stretched cards) | ✅ |
| Raw ISO dates / English in planner reasons and notifications | ✅ fixed in the backend (`text_utils.py`) |
| Naive UTC timestamps shown as local time | ✅ `parseApiInstant` |
| Migrated pages: planner (+cards), school, work, finance, goals, activity, memory, WoT, MFF, login | ✅ |
| Activity bugs: date filter ignored (`from`/`to` vs `from_date`/`to_date`), multi-area returned nothing, empty change detail | ✅ fixed |
| `Modal` primitive | ⏳ not needed (ConfirmDialog + Drawer cover all current uses) |
| `/ai` assistant redesign / split | ✅ Roadmap 4C |
| `middleware.ts` → `proxy.ts` (Next 16) | ✅ Roadmap 4C |
| Light theme | ⏳ out of scope (Themes phase) |

## Status after Roadmap 4F (Custom Dashboard / Command Center)

| Item | Status |
|---|---|
| Explicit typed widget registry (11 widgets, stable ids) | ✅ design-system §16 |
| Layout `{version, widgets[{id, visible, order, size}]}` + validation | ✅ `lib/dashboardLayout.ts`, tests |
| Persistence | ✅ localStorage `standa-hub:dashboard-layout:v1` (no backend preference store exists) |
| Customize mode: reorder (buttons), hide/restore, semantic sizes, reset with confirm | ✅ |
| Default layout identical to the 4B.1 balance (desktop, tablet, mobile) | ✅ before/after screenshots |
| No refetch on edits; hidden widgets fetch nothing | ✅ |
| Dashboard widget integration step for modules | ✅ `module-integration-checklist.md` §8 |
| Drag and drop | ⏳ not in 4F (buttons cover mouse, touch, keyboard) |
| Dashboard presets / backend-synced layout | ⏳ later |

## Status after Roadmap 4E (Smart Quick Add)

| Item | Status |
|---|---|
| Global Quick Add (Ctrl/Cmd+Shift+K, sidebar "+ Rychlé přidání", mobile header "+") | ✅ design-system §15 |
| Deterministic Czech parser: reminder, finance, work, exam, assignment (no LLM, no writes) | ✅ `quick_add_service.py`, tests |
| Preview → edit → explicit "Uložit" via existing pending action + `/actions/confirm` | ✅ `prepare_write_action(source="quick_add")` |
| Activity source "Rychlé přidání" | ✅ `user_context="quick_add"` |
| Ambiguity as questions, confidence in words | ✅ |
| Quick Add integration step for modules | ✅ `module-integration-checklist.md` §7 |
| AI fallback for unknown text | ❌ by design (boundary documented in design-system §15) |

## Status after Roadmap 4D (Global Search / Ctrl+K)

| Item | Status |
|---|---|
| Command palette (Ctrl/Cmd+K, sidebar field, mobile header button) | ✅ design-system §14 |
| `GET /search` – deterministic, authenticated, bounded, Czech subtitles | ✅ `search_service.py`, tests |
| Czech normalisation + ranking shared by backend and frontend | ✅ `lib/search.ts` ↔ `search_service.py` |
| Deep links to records with focus + highlight on 8 modules | ✅ `SearchHighlighter`, `data-search-target` |
| Search integration step for future modules | ✅ `module-integration-checklist.md` §6 |
| Mutations from the palette | ❌ by design – Smart Quick Add (Roadmap 4E, ✅) |

## Status after Roadmap 4C (AI assistant)

| Item | Status |
|---|---|
| `/ai` decomposed (2150 → ~190 lines page; `lib/ai*`, 3 hooks, 10 components) | ✅ see design-system §13 |
| Design system on `/ai` (rail/Drawer, message variants, pending/undo cards, composer) | ✅ |
| AI action wording (UI + Activity) | ✅ `aiToolMeta`, `text_utils.ai_action_summary` |
| `/ai` a11y: labelled textarea/select, h1, Drawer, no `window.prompt/confirm` | ✅ |
| `middleware.ts` → `proxy.ts` (Next 16) | ✅ `lib/authGate.ts` + tests, browser redirect/login checks |
| Planner card disappeared after an answer (messages reloaded from the server) | ✅ fixed (only the list refreshes) |
| Streaming answers | ⏳ not present before 4C, not added |

## Status after Roadmap 4B.1 (polish)

| Item | Status |
|---|---|
| Dashboard column balance (Dnes under the briefing on xl, Hry as a full-width strip, no stretched rows on tablet) | ✅ |
| Backend copy: work/memory/finance activity summaries, planner weekly summary, work-behind texts | ✅ `text_utils.py` |
| Presentation mapping layer `lib/labels.ts` (entities, fields, values, categories, sources) | ✅ used by Activity, Finance, Memory |
| Work/Finance amounts reconcile (`formatCzkExact`) | ✅ |
| WoT "Připravujeme" placeholder | ✅ removed |
| AI approval summaries ("Potvrzena akce add_work_session (date=…)") | ⏳ AI Assistant phase |

## What existed before 4A

- Dark theme by convention (`bg-zinc-950` body, `bg-zinc-900 border-zinc-800 rounded-2xl` cards) — but the card
  class string is copied ~60× across 18 files, page headers 13×, badges with 4 different area palettes,
  `formatNumber` 5×, `formatDate` 3×, two error-banner styles, three empty-state styles.
- One local `Card` (dashboard only), one shared `ConfirmDialog`, a solid motion system (`motion.css` tokens,
  `staggerStyle`, reduced-motion block).
- Container widths vary from `max-w-4xl` to `max-w-7xl`; vertical spacing from `space-y-4` to `space-y-10`.

## Primitives (original plan; see status above)

| Primitive | Replaces / notes |
|---|---|
| `useApiResource(path, {deps, debounceMs})` | the 21 hand-written loaders: `loading` starts **true**, `AbortController`, stale-response guard, `error` with server `detail`, `reload()`; debounce for search (activity, memory) |
| `apiJson` / `readError` in `lib/api.ts` | `readError` + 5 inline copies; one `API_URL` (now in api.ts, middleware, login) |
| `AppShell` | layout: one `NotificationsBell` (now two poll in parallel), login without shell, single `<h1>` per page |
| `PageHeader` | 13 copies of h1 + subtitle + actions; consistent action placement |
| `PageSection` | section h2 sizes (`text-lg`…`text-2xl`) and spacing |
| `Card` / `Surface` | the ~60 copied class strings; variants: default, interactive (link), muted |
| `MetricCard` + `StatGrid` | stat tiles on goals, work, mff, finance, dashboard |
| `EntityList` + `EntityRow` | div-card lists on school, wot, mff, goals; consistent actions (edit/delete/complete) |
| `StatusBadge` / `PriorityBadge` / `AreaBadge` | 4 area palettes, 3 priority mappings, 4 status mappings → one semantic map |
| `Progress` | 4 progress-bar implementations |
| `EmptyState` | dashed / p-8 / p-6 variants; short Czech text + optional action |
| `ErrorState` | `bg-red-500/10` vs `bg-red-950/50` banners; `role="alert"`, retry button |
| `Skeleton` | `animate-pulse` blocks vs "Načítám…" texts; reduced-motion safe |
| `ConfirmDialog` (rebuild) | busy/disabled confirm (double-submit today), `role="dialog"`, `aria-modal`, focus trap, shared scroll lock |
| `Modal` / `Drawer` | ad-hoc overlays (NotificationsBell, Sidebar, /ai history), `window.prompt/confirm` on /ai |
| `FormField` + `Input`/`Select`/`Textarea` | 26 + 21 copies of input class strings, 6+ variants |
| `FilterBar` | activity, mff, memory filters |
| `Tabs` | planner modes, mff/school sub-views |
| `format.ts` | `formatNumber`, `formatDate`, `formatDateTime`, `formatCzk`, Prague-time helpers (some exist in `lib/reminders.ts`, `lib/briefing.ts`) |

Rules for primitives: pure presentational, no data fetching inside (except `useApiResource`), Czech copy passed
in, tested helpers in `lib/*.ts` with node tests, no new dependencies unless clearly justified.

## UX principles

1. **One content width** per page type (proposal: `max-w-6xl` for module pages, `max-w-7xl` dashboard,
   `max-w-md` auth) and one spacing scale (`space-y-6 md:space-y-8` between sections, `gap-4` inside).
2. **Page hierarchy:** PageHeader (h1, one-line subtitle, primary action) → sections (h2) → cards. One h1.
3. **Surfaces:** `zinc-950` page, `zinc-900` card, `zinc-800` border/input; radius `rounded-2xl` cards,
   `rounded-xl` inner rows/inputs. No light-theme islands (today `/activity`).
4. **Semantic colours:** success emerald, danger red, warning amber, info sky, AI/forecast violet; area colours
   from one palette. **Attention colours only for real attention** (overdue, failed, needs action).
5. **Mobile first:** layouts start single-column; no fixed `100vh` (use `dvh`); touch targets ≥ 40 px.
6. **States are mandatory:** every data view has loading (skeleton), error (with retry) and empty states;
   no flash of "nothing here" while loading.
7. **No giant placeholders:** hide unfinished modules/sections (WoT "coming soon" blocks) instead of empty panels.
8. **Dense, useful information** over admin-dashboard whitespace; numbers formatted consistently (Czech locale).
9. **Reduced motion:** all animation through `motion-*` classes or `motion-safe:` variants; no plugin-only
   classes (`animate-in` today does nothing).
10. **One language per screen:** Czech UI copy (English only for proper names / game terms).
11. **Destructive actions** always via ConfirmDialog with busy state; AI writes keep the preview/confirm cards.

## Suggested Roadmap 4 sequence

1. Foundation: `format.ts`, `api` helpers, `useApiResource`, `AppShell`, `PageHeader`, `Card`, states,
   rebuilt `ConfirmDialog`, badges; `middleware.ts` → `proxy.ts` (Next 16).
2. Migrate small pages first (reminders, planner, review, activity), then school/finance/work/wot, then goals/mff,
   and split `/ai` (2150 lines) into components last.
3. Visual polish and copy (language cleanup) on top of the primitives.
