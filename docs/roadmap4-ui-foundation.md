# Roadmap 4 – UI Foundation (preparation)

Input for Roadmap 4. **Nothing here is implemented yet.** Evidence comes from the Roadmap 3.5 frontend audit
(see [architecture-audit.md](architecture-audit.md), R1–R10). Recommendation: start Roadmap 4 with a
**Design System Audit/Foundation** (primitives + data-fetching hook), then migrate pages one at a time, then
visual polish.

## What exists today

- Dark theme by convention (`bg-zinc-950` body, `bg-zinc-900 border-zinc-800 rounded-2xl` cards) — but the card
  class string is copied ~60× across 18 files, page headers 13×, badges with 4 different area palettes,
  `formatNumber` 5×, `formatDate` 3×, two error-banner styles, three empty-state styles.
- One local `Card` (dashboard only), one shared `ConfirmDialog`, a solid motion system (`motion.css` tokens,
  `staggerStyle`, reduced-motion block).
- Container widths vary from `max-w-4xl` to `max-w-7xl`; vertical spacing from `space-y-4` to `space-y-10`.

## Primitives to create (in this order)

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
