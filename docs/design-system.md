# Standa Hub – Design System & Jarvis Visual Language (Roadmap 4A)

> **A futuristic Jarvis/HUD personal operating system designed as a professional daily-use product.**
> Readability always wins over effects. If sci-fi styling ever fights clarity, hierarchy, accessibility or fast
> orientation, choose clarity.

Code: tokens `frontend/app/tokens.css`, HUD layer `frontend/app/hud.css`, motion `frontend/app/motion.css`,
primitives `frontend/components/ui/*` (barrel `@/components/ui`), logic `frontend/lib/{ui,format,api,resource,dialog}.ts`,
data hook `frontend/hooks/useApiResource.ts`. Migrated reference pages: `/` (Řídicí centrum), `/reminders`, `/review`.

---

## 1. Tokens

Tailwind 4 `@theme` variables → utilities (`bg-surface`, `border-line`, `text-ink-muted`, `bg-accent/10`, `rounded-card`,
`shadow-glow`). The app is **always dark**, independent of the OS theme.

| Group | Token → utility | Use |
|---|---|---|
| Surfaces | `app` #07090d · `surface` #0d1117 · `surface-2` #121821 · `elevated` #171e29 · `hover` #1c2431 | page · card · nested row/metric · dialog · hover |
| Lines | `line` #242c39 · `line-subtle` #1a212c | card border · inner rows/dividers |
| Text | `ink` · `ink-2` · `ink-muted` · `ink-faint` | primary · body · secondary/meta · decoration/disabled only |
| Accents | `accent` cyan #22d3ee (+`accent-strong`) · `accent-2` violet #a78bfa | primary action, active state · AI / forecasts |
| Semantic | `success` · `warning` · `danger` · `info` · `neutral` | only where something *means* that |
| Shape | `rounded-card` (1 rem) · `rounded-[var(--radius-control)]` (0.75 rem) | cards/dialogs · buttons/inputs/rows |
| Effects | `shadow-card` · `shadow-[var(--shadow-elevated)]` · `shadow-glow` / `shadow-glow-violet` | default · dialogs · *rare* active highlight |
| Layout | `--page-max` 76 rem · `--page-max-narrow` 56 rem · gutters 1 / 2 rem | `ContentContainer` |
| HUD | `--hud-line-opacity` 0.035 · `--hud-corner*` | grid background, frame corners |
| Motion | `--motion-fast` 140 ms · `--motion-normal` 240 ms · `--motion-pulse-duration` 2.4 s | interactions · entries · live pulse |

**Contrast (WCAG):** on every surface `ink` ≥ 15:1, `ink-2` ≥ 10:1, `ink-muted` ≥ 5.6:1, accents/semantic ≥ 6:1.
`ink-faint` (3–3.5:1) is **never** used for text that must be read (only placeholders, decoration, disabled).

## 2. Semantic colours

- **Cyan (accent):** the one primary action per area, active navigation, the main live panel. Not decoration.
- **Violet (accent-2):** AI-generated estimates and forecasts (`tone="ai"`), never facts.
- **Green / amber / red:** done & improvements / needs attention soon / overdue, failed, destructive.
  Attention colours appear only for real attention (due reminders, overdue items, errors).
- **Area colours** (`areaMeta` in `PlannerCards.tsx`) are *identity* chips (Škola, Finance…), not status.
- Status is never colour-only: badges carry text, trends carry a sign (`+12 %`, `−4 h`).

## 3. Typography & spacing

- Font: Geist (sans) for UI, Geist Mono only for technical micro-labels (`HudLabel`) and counters.
- Hierarchy: page `h1` (PageHeader, `text-2xl md:text-3xl`), sections/cards `h2` (`text-base/lg`), inner blocks `h3`
  (`text-sm`). One `h1` per page; the shell has none.
- Numbers: `tabular-nums`; formatting only via `lib/format.ts` (cs-CZ, real minus sign, Czech plurals,
  instants shown in Europe/Prague, date-only values never shifted).
- Spacing: sections `space-y-6 md:space-y-8`; cards `p-4 md:p-5`; inside cards `gap-3`/`space-y-2`.

## 4. Primitives – when to use what

| Primitive | Use for | Don't |
|---|---|---|
| `ContentContainer` | every page root (width, gutters, section rhythm); `width="narrow"` for forms/reading | nest it |
| `PageHeader` | `eyebrow` (HudLabel), `title`, one-line `subtitle`, optional `meta`, `actions` | put filters here |
| `PageSection` / `SectionHeader` | titled groups of content outside cards | for card titles (use `CardHeader`) |
| `Card` (+`CardHeader`) | a self-contained block; `tone` only if the card reports something; `inset` for nested | colour every card |
| `MetricCard` + `StatGrid` | key numbers: label, value, unit, trend text + `trendTone`, hint | decorative gauges without meaning |
| `StatusBadge` | short state/category with `tone`; `dot` for live-ish states | long sentences (use text) |
| `Progress` | role=progressbar with a label; cyan by default, green at 100 % | fake meters |
| `EntityList` / `EntityRow` | lists of records with badges, title, meta, actions; `tone` for attention rows, `muted` for closed | tables of numbers |
| `Button` / `ButtonLink` / `TextLink` | `primary` (one per area), `secondary`, `ghost`, `danger`, `success`; `busy` + `busyLabel` | raw class strings |
| `FormField` + `fieldClass` | label + input + hint/error with ids wired automatically | placeholder-only labels |
| `Tabs` | switching views of the same list (role=tablist, arrow keys) | navigation between pages |
| `EmptyState` / `ErrorState` / `LoadingState` / `Skeleton` | mandatory states for every data view | flash an empty state while loading |
| `ConfirmDialog` | destructive or costly actions; return a Promise from `onConfirm` for the busy state | `window.confirm` |
| `useApiResource(path, {refreshMs, debounceMs})` | any GET: loading starts true, refresh keeps data, abort + stale guard, server error detail | hand-written `useEffect` loaders |

API helpers: `apiJson(path, jsonBody("POST", body))` throws `ApiError` with the server `detail`;
`errorMessage(err)` turns any error into Czech text. 401 still redirects to `/login` (in `apiFetch`).

## 5. Jarvis / HUD rules

Optional accents (`components/ui/hud.tsx`, `app/hud.css`):

- `HudLabel` – mono uppercase micro-label for metadata ("Denní přehled · 11. 10. 2026", metric labels).
- `AccentLine` – thin cyan→violet line on the top edge of the **main live panel**.
- `HudFrame` – corner marks around a panel; `variant="violet"` for forecasts/AI.
- `StatusPulse` – status dot; `live` adds a slow pulse (static ring under reduced motion). Always next to text.
- `hud-grid` – a very faint grid + glow behind the whole app (simplified on mobile).

Rules:
1. A normal `Card` stays clean. **At most one or two HUD-framed panels per screen** (dashboard: Daily Briefing;
   weekly review: forecasts).
2. Glow is for *active/primary* only (primary button, active nav, live panel). Never on every card.
3. Decoration never covers content, never carries information alone, never adds layout.
4. No fake gauges, no neon text, no decorative lines over data. If a screen starts to look like a game menu, remove
   effects until it looks like a professional tool again.
5. Mobile shows less decoration (no grid lines; fewer frames).

## 6. Motion

- Reuse `motion.css`: `motion-card` (staggered entry via `staggerStyle(i)`), `motion-press`, `motion-hover-lift`,
  `motion-progress`, `motion-attention` (3 pulses for due items) etc.
- Under `prefers-reduced-motion: reduce` every `motion-*`, Tailwind `animate-pulse/bounce/ping/spin` and the HUD pulse
  stop; states remain visible (static skeleton blocks, aria-busy, text labels).
- No infinite animation except the slow `StatusPulse live` for genuinely live states.

## 7. Accessibility checklist (per page)

- One `h1`; sections/cards have headings; landmarks (`main`, `nav`, `aside`) are labelled.
- Every interactive element has a visible focus ring (`focus-visible:ring-accent/70`), touch target ≥ 36–40 px.
- Dialogs: `role="dialog"`, `aria-modal`, labelled, focus trap, Escape (not while busy), focus restored.
- Loading = `role="status"` with text; errors = `role="alert"`; busy buttons = `aria-busy` + disabled.
- Progress bars have labels; icons are `aria-hidden`; counts in icon buttons are in `aria-label`.
- Verify with `node frontend/scripts/ui-check.mjs` (see script header) at 1920/1366/820/390 px, light & dark OS
  theme and reduced motion.

## 8. Language

User-facing UI is Czech. Allowed English: proper names (World of Tanks, Marvel Future Fight), technical micro-labels
where deliberate, and the bilingual forecast label "Odhad / Forecast". Backend-generated text (e.g. planner reasons)
is shown as delivered — fix copy at the source.
