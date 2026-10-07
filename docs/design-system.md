# Standa Hub – Design System & Jarvis Visual Language (Roadmap 4A + 4B)

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
| `Drawer` (4B) | side panel over the page: mobile menu, notification panel. `title`, `description`, header `actions`, `width="sm"\|"md"`, `restoreFocus`, `initialFocus` | page content that should be a route; nested drawers |
| `FilterBar` + `FilterSelect` + `FilterChips` (4B) | filtered lists: search field, labelled selects, multi-select chips (`aria-pressed`), result count (`aria-live`), "Zrušit filtry (n)" | page navigation; filters with no list under them |
| `AreaBadge` (4B) | area identity (Škola, Práce, WoT…) from `lib/areas.ts` | status (use `StatusBadge`) |
| `useApiResource(path, {refreshMs, debounceMs})` | any GET: loading starts true, refresh keeps data, abort + stale guard, server error detail | hand-written `useEffect` loaders |

Overlays (`Drawer`, `ConfirmDialog`) share `useModal` (scroll lock, initial focus, Tab trap, Escape unless busy,
focus restore) and render through a portal into `<body>` — an ancestor with `transform` or `backdrop-filter`
(sticky header, page transition) would otherwise clip `position: fixed`.

Pure page logic lives next to the primitives in `lib/` with `node:test` tests: `filters.ts` (query building,
active count), `activity.ts`, `memory.ts`, `goals.ts` (Czech status/tracking/source labels), `school.ts`, `work.ts`,
`wot.ts`, `mff.ts`, `areas.ts`. `lib/format.ts` adds `parseApiInstant` (naive API timestamps are UTC),
`formatTime`, `pragueDayKey`, `pragueDayStartIso/EndIso` (date filters as Prague-day bounds in UTC).

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
- Every interactive element has a visible focus ring (`focus-visible:ring-accent/70`). Touch targets: buttons and
  tabs are ≥ 36 px with a mouse and grow to 44 px on touch (`pointer-coarse:min-h-11`); `TextLink` and short
  link titles extend their hit area with an `::after` overlay (≥ 40 px) instead of growing the layout.
- Authenticated pages have a skip link „Přeskočit na obsah" → `<main id="main-content" tabIndex={-1}>`.
- Dialogs: `role="dialog"`, `aria-modal`, labelled, focus trap, Escape (not while busy), focus restored.
- Loading = `role="status"` with text; errors = `role="alert"`; busy buttons = `aria-busy` + disabled.
- Progress bars have labels; icons are `aria-hidden`; counts in icon buttons are in `aria-label`.
- Verify with `node frontend/scripts/ui-check.mjs` (see script header) at 1920/1366/820/390 px, light & dark OS
  theme and reduced motion.

## 8. Language

User-facing UI is Czech. Allowed English: proper names (World of Tanks, Marvel Future Fight), technical micro-labels
where deliberate, and the bilingual forecast label "Odhad / Forecast". Backend-generated text (e.g. planner reasons)
is shown as delivered — fix copy at the source.

### Internal values vs. user-facing labels (Roadmap 4B.1)

- **Stored values never change for presentation.** Database values, API fields, enum values, dedupe keys and
  payloads stay as they are; only the label shown to the user is translated.
- **One mapping per kind of value, in `lib/labels.ts`:** `entityTypeLabel`/`entityRefLabel` (audit entity types and
  AI tool names), `fieldLabel` + `fieldValueLabel` (change-detail fields and values), `financeCategoryLabel`,
  `memoryCategoryLabel`, `activitySourceLabel`. Module-specific enums keep their helpers in `lib/<module>.ts`
  (`goals.ts`, `school.ts`, `wot.ts`, `mff.ts`). Pages never hardcode their own copies.
- **Unknown values fall back gracefully:** shown trimmed with a capital first letter (categories) or unchanged
  (entity types) — never dropped, never "undefined".
- **Free text the user typed is data, not an internal value** (e.g. a finance category "food" typed by the user is
  translated in the UI for convenience, but kept as typed in backend activity text). System-generated values
  (category `work` from the Work → Finance sync) are named in Czech at the source.
- **Backend copy** (activity summaries, planner reasons, notifications) is built with `backend/text_utils.py`:
  `format_num_cz`, `format_hours_cz`, `format_czk_cz`, `finance_summary_cz`, `memory_count_cz`, `plural_cz`,
  `format_date_cz` — decimal comma, correct plurals, no ISO dates, no English module names. Existing audit rows keep
  the text they were written with.

### Rounding & display consistency

- If rows on a screen add up to a visible total, show amounts so they reconcile: `formatCzkExact` (whole crowns
  without decimals, otherwise to the haléř: 2 437,50 + 2 437,50 = 4 875 Kč). Used on Work and Finance.
- Aggregates shown alone (dashboard metrics) may use `formatCzk` (rounded to whole crowns ≥ 100 Kč).
- Never round stored values or recompute business numbers in the UI — formatting only.

### Unfinished UI

Hide sections that have no real functionality yet instead of showing large placeholders ("Připravujeme" tiles,
empty panels, fake data). A feature appears in the UI when it works. A one-line hint is acceptable only when it
helps the user act now.

## 9. Migration conventions (Roadmap 4B)

Every migrated page follows the same skeleton:

```tsx
<ContentContainer width="default|narrow">           // <main id="main-content">
  <PageHeader eyebrow={<HudLabel>Modul · …</HudLabel>} title="…" subtitle="…" actions={…} />
  {/* key numbers */} <StatGrid><MetricCard … /></StatGrid>
  {/* lists */}      <PageSection title="…"> EntityList / Card rows </PageSection>
  <ConfirmDialog … />
</ContentContainer>
```

- Data: `useApiResource` (filters/search with `debounceMs: 300`); mutations via `apiJson` + `jsonBody`, then
  `reload()`. The first load shows `LoadingState`, a failed load `ErrorState` with retry, a failed refresh keeps the
  data and shows an `ErrorState` above it. Never show an empty state before the first response.
- Forms: `FormField` with visible Czech labels, inline validation messages under the field, one primary submit with
  `busy`. Disclosure buttons ("Přidat …") carry `aria-expanded`/`aria-controls`.
- Row-level destructive buttons are `ghost` ("Smazat" + `aria-label` naming the record); the `ConfirmDialog` carries
  the danger styling. Reminders (4A) keep their danger "Zrušit".
- Enum values from the API never reach the UI: map them to Czech labels in `lib/<module>.ts` (values in payloads stay
  unchanged).
- Dates: date-only (`YYYY-MM-DD`) via `formatDate` without timezone conversion; instants via
  `formatDateTime`/`formatTime` (naive API values are UTC → shown in Europe/Prague). Group by day with
  `pragueDayKey`. Never `new Date(x).toLocale…` on API values.
- Lists instead of admin tables: rows wrap with `flex-wrap`/`min-w-0`/`break-words`; nothing overflows at 390 px.

## 10. Page exceptions & game-module rules

- **World of Tanks / Marvel Future Fight** keep their identity only through the area colour (`AreaBadge`, a thin
  top accent on one card) and their own terms (tank and character names, T4, Uniform, CTP, ISO-8, Free XP). No neon,
  no gauges/dials, no glow, no new mechanics. Numbers are MetricCards; build completeness is a plain `Progress`.
- **Goals** are progress-oriented: Progress + percent + target date. No XP, streaks, trophies or confetti
  (only the existing subtle completion pulse at 100 %).
- **Finance** uses semantic colour sparingly: balance by sign, income green, expenses neutral; amounts are signed
  with a real minus and tabular figures.
- **Activity** is the audit log: neutral rows, Czech action labels, the change detail (`/activity/{id}` → delta) loads
  on demand. Only `error` (danger) and `delete`/`reject` (warning) get colour.
- **AI assistant** (`/ai`): see §13 (Roadmap 4C).

## 11. Notification panel

- One bell in the whole app (desktop sidebar or mobile header, chosen by `useMediaQuery`), `aria-label` includes the
  unread count, `aria-haspopup="dialog"`, `aria-expanded`. Summary polling every 30 s; the badge pulses only when
  the count increases.
- Opening runs `POST /notifications/generate` and loads the list into a `Drawer` titled „Notifikace" (summary of
  unread/important/warnings in the description, „Přečíst vše" in the header).
- Items: new/read state in text („Nové"/„Přečteno"), severity (`StatusBadge`), area (`AreaBadge`), time in Prague,
  actions „Otevřít" (closes the panel and navigates), „Přečteno", „Vyřešit" with busy state.
- Escape or the backdrop closes it and focus returns to the bell; reduced motion disables the slide-in.

## 12. Login shell & mobile navigation

- `/login` is a bare route (`lib/shell.ts` → `isBareRoute`): no sidebar, no bell, no polling, no authenticated
  requests (so no 401 noise). The PIN field has a real `<label>`, a hint (`aria-describedby`) and `aria-invalid`.
- Mobile menu = `Drawer` titled „Menu": focus starts on the current page link, Tab is trapped, Escape closes and
  returns focus to ☰. Choosing another page closes the menu and moves focus to the new page's `#main-content`
  (choosing the current page just closes it).

## 13. AI assistant (Roadmap 4C)

**Structure** – `app/ai/page.tsx` only composes; logic and UI are bounded:

| Layer | Pieces |
|---|---|
| Pure logic (`lib/`, node tests) | `aiActions.ts` (pending action → view model), `aiChat.ts` (API mapping, error kinds, message variants), `markdown.ts` (answer → blocks), `labels.ts` `aiToolMeta` |
| State (`hooks/`) | `useConversations` (list, active, create/rename/delete), `useAiChat` (history, /chat, confirm/reject/undo, outcomes), `useAiVoice` (dictation, Ctrl+Shift+M, read-aloud) |
| UI (`components/ai/`) | `ChatHeader` (the only h1), `ConversationPanel` (rail ≥ lg, `Drawer` below), `MessageList`, `MessageItem`, `Markdown`, `PendingActionCard`, `ActionOutcomeCard`, `Composer`, `EmptyConversation` |

**Layout** – full-height chat (`100dvh` minus `--mobile-header-h` on mobile); header, messages and composer share one
centred `max-w-4xl` column; the conversation rail is visible from `lg`, below that it opens in a `Drawer`
(focus trap, Escape, focus return; choosing a conversation closes it and focuses the composer).

**Message variants** – user: restrained surface on the right; assistant: plain text (Markdown) without a bubble,
the "Standa AI" micro-label only on the first message of a group; status (✅ / ⚠️ / ❌ texts such as action
results and errors): compact semantic row (headline + details on one line); planner results: the Planner
components (`PlannerCardRenderer`, legacy JSON plans via `WeeklyPlanCard`). Violet (`accent-2`) marks only the AI
author/indicator; actions use cyan.

**Pending actions** – the card is the confirmation step (no extra dialog): status line ("Čeká na tvé potvrzení" /
"Provádím změnu…" / "Provedení selhalo"), kind badge (Nový záznam / Úprava / Smazání / Dokončení / Vrácení změny),
area badge, record count, title, new values (create) or every record with old → new (preview from the backend,
max. 10 shown + "a dalších N"), warnings, highlighted footer (earnings, amount, count), "Potvrdit" (busy) and
"Zamítnout". Semantics are unchanged: confirm `POST /actions/confirm`, reject `POST /ai/reject/{id}`.
**Undo** – only when the backend returns `result.undo_available`; the outcome row shows "Vrátit" with a 20 s timer
bar (static under reduced motion); undo is itself a pending action with a preview.

**Action labels** – one mapping per side, internal tool names never reach the user:
`lib/labels.ts` `aiToolMeta(tool)` → `{action: "Přidat pracovní záznam", done: "Přidán pracovní záznam", area}`;
backend `text_utils.AI_TOOL_LABELS_CZ` + `ai_action_summary()` for Activity ("Přidán pracovní záznam (AI):
2. 10. 2026 · 6,5 h · Klient XYZ"). A backend test fails when a new WRITE tool has no label.

**Composer & a11y** – labelled textarea (grows to ~8 lines), Enter sends, Shift+Enter new line (IME-safe), send
disabled when empty, busy "Odesílám…", failure notice (`role=alert`) with retry – none for the daily limit;
voice settings behind a labelled disclosure, the locale `<select>` has a label; icon buttons have names;
conversation actions are labelled and visible on focus/hover (always on touch).
**Scrolling** – new content scrolls into view only while the user is near the bottom; sending or switching
conversations always jumps to the latest message.

## 14. Global Search / Ctrl+K (Roadmap 4D)

**What it is** – one command palette for the whole authenticated app (not on `/login`): find a page or a record
and open it. It **only navigates**; creating data is Smart Quick Add (§15), never the palette.
Conversation history stays inside the AI assistant.

**Architecture** – deterministic, no LLM, no index:
- pages: `lib/navigation.ts` (Czech label + keywords, shared with the sidebar), matched locally and instantly;
- records: `GET /search?q=` (`backend/search_service.py`), behind the global session auth, query not logged,
  bounded reads (500 rows/table), max. 6 per type and 30 total, min. 2 characters;
- UI: `SearchProvider` (Ctrl/Cmd+K, rendered by `AppShell`), `CommandPalette`, `useGlobalSearch`
  (180 ms debounce via `useApiResource`, stale requests aborted, responses checked against the current query),
  `SearchButton` (sidebar field with the shortcut hint, mobile header icon), `SearchHighlighter` (deep links).

**Result model** – `{id: "exam:12", type, title, subtitle, area, href, score}`; subtitle is Czech context built by
the backend ("Test · Fyzika · 3. 10. 2026", "Výdaj · 189,90 Kč · Jídlo"). Indexed: subjects, assignments,
exams, active reminders, work sessions, transactions, goals, active memories, WoT grinds, MFF characters.

**Ranking** (same numbers in `lib/search.ts` and `search_service.py`, tested): normalise (lower case, no
diacritics – "zkouska" finds "Zkouška"), then exact 100 > title prefix 85 > word prefix 70 > substring 55 >
all query words anywhere 45 > match in other fields 30. Pages get +5; page keywords score one step below the
name. Groups (Navigace, Škola, Připomínky, Práce, Finance, Cíle, Paměť, World of Tanks, Marvel FF) appear only
when non-empty, the group with the best hit first, so Enter opens the best result.

**Keyboard** – Ctrl+K / Cmd+K toggles (works in forms too – a deliberate app shortcut); focus starts in the
input (`role=combobox`, `aria-activedescendant`); ↑/↓ move through all rows (wrapping), Enter opens, Esc or
the backdrop closes and focus returns to where it was; Tab stays inside the dialog. The status line
(`role=status`) announces "Hledám…", the result count, "Nic nenalezeno." or an error.

**States** – empty query: "Nedávno otevřené" (last 5 destinations in localStorage – destinations, never
queries) + all pages; searching: pulse in the input, pages still visible; error: retry, pages still work;
no results only after the answer arrives.

**Mobile** – the header magnifier opens a full-screen palette with the input on top, rows ≥ 44 px, "Zavřít".

**Deep links** – `href` opens the module page with a record param (`/school?exam=12`, `/mff?character=3`, …);
`SearchHighlighter` waits for `[data-search-target="exam-12"]`, scrolls it to the centre, focuses it and
outlines it for ~2 s (static under reduced motion). If the record is not on the page, the module page stays.

**Look** – compact elevated panel near the top, a thin cyan line on its top edge, cyan rail on the selected
row, mono group labels; no badges per row (the group names the area), no glow.

## 15. Smart Quick Add (Roadmap 4E)

**What it is** – one global entry point for creating a record from a short Czech sentence, available only in
the authenticated shell: **Ctrl/Cmd+Shift+K**, the "+ Rychlé přidání" button under the search field in the
sidebar, and the "+" icon in the mobile header. Search (Ctrl+K) only navigates; Quick Add only creates –
the two never share a shortcut or a surface.

**Supported types (only these)** – reminder, finance (expense/income), work session, school exam,
school assignment. Goals, WoT, MFF and memory are deliberately not supported.

**Architecture** – deterministic, no LLM, no DB writes while parsing:
- `POST /quick-add/parse {text}` → `quick_add_service.parse()` → preview (read-only, < 1 ms per call;
  the test budget is 50 ms);
- `POST /quick-add/prepare {kind, fields}` → `to_tool_call()` re-validates the (possibly edited) fields on the
  server and turns them into an existing WRITE tool call, then `ai.prepare_write_action(..., source="quick_add")`
  stores a **normal pending action** (same table, TTL, atomic claim);
- the UI then calls the existing `POST /actions/confirm` – the same executor, audit and expiry as AI proposals.
  Nothing new executes mutations.
- Frontend: `lib/quickAdd.ts` (field definitions, readiness, shortcut, examples – unit-tested),
  `QuickAddProvider` (shortcut, rendered by `AppShell`), `QuickAddDialog`, `QuickAddButton`.

**Preview model** – `{kind, confidence: high|medium|low, fields, display: {title, subtitle, area}, warnings[],
needs_input: [{field, question}], errors: [{field, message}], ready, subjects?}`. Confidence is shown in words
("Rozpoznáno" / "Zkontroluj" / "Nejisté"), never as a number.

**Parser rules** (`backend/quick_add_service.py`) – normalise (lower case, no diacritics, same length so spans map
back to the original), then classify by fixed priority: explicit reminder word ("připomeň", "nezapomeň") > exam
word (test, zkouška, kvíz, zápočet) > assignment word (úkol, deadline, odevzdat) > work word or rate "Kč/h" >
hours without a work word (work, *medium*) > relative time "za 2 hodiny" or a clock time > money / income /
expense words > a bare number (finance, asks). Dates and times use the Prague calendar (`time_utils`): dnes /
zítra / pozítří, weekdays ("v pátek" = nearest, "příští pátek" = next calendar week), "18. 10." (rolls to next year
if already past), ISO dates; reminders without a time get 09:00 (shown as a warning); a time that already passed
today moves to tomorrow (warning). Finance categories only from explicit words (Albert/Lidl → Potraviny,
oběd/káva → Jídlo, MHD/benzín → Doprava, …); otherwise "Ostatní" with a visible warning. Subjects match by full
name or code first, then by the stem of the first word ("z práva" → Právo); more candidates = no choice made.

**Ambiguity – never guess silently** – "Albert 820" asks "Je to 820 Kč?" (one "Ano" resolves it); "test z práva"
without a date asks "Kdy je termín?"; an unknown subject asks "Ke kterému předmětu to patří?" with a select;
"2 h Servind" is work with *medium* confidence and a "zkontroluj" warning; no hourly rate is invented (0 Kč with a
warning). Errors ("-500 Kč", "40 h práce", "31. 2.") are shown at the field and block saving.

**Safe write** – "Uložit" is enabled only when every required field is filled, every question is resolved
(edited or acknowledged) and no unedited field has an error. Enter in the input only re-parses, it never saves.
A failed confirm keeps the same pending action, so "Zkusit znovu" cannot create a duplicate; changing the text or
a field (or closing the dialog) rejects the stale pending action. Server-side validation: amount 0–10 M Kč,
hours 0–24, rate 0–100 000 Kč/h, dates within a year, reminder in the future, subject must exist.

**Source label** – the tools write their Activity entry with `user_context="quick_add"`, shown as "zdroj: Rychlé
přidání" (`lib/labels.ts`); the executor skips the "AI approve" log because it is not an AI action.

**Undo** – creates have no undo (same as AI creates), so none is offered; edits/deletes stay on the module pages.

**States** – empty: hint + clickable examples; parsing: pulse in the input, previous preview dimmed; unknown:
"Tomu zatím nerozumím." + examples; parse error: ErrorState with retry; saved: "Uloženo" card with "Přidat další"
(focus back in the input) and a link to the module page.

**Mobile** – the "+" in the header opens a full-screen surface: input on top, preview and fields stacked below,
"Zrušit / Uložit" pinned at the bottom (≥ 44 px, safe-area aware), no horizontal overflow.

**Future AI fallback boundary** – unknown text is never sent to an LLM. If a fallback is added later it must be
an explicit user action ("Zeptat se AI") on the "unknown" state that hands the text to the AI assistant, whose
proposals still go through pending actions; the deterministic parser stays first and authoritative.

## 16. Custom Dashboard / Command Center (Roadmap 4F)

**What it is** – the dashboard (`/`) is built from an explicit widget registry and a per-user layout:
which widgets are visible, in what order, at what size. With no customization it looks exactly like the 4B.1
dashboard.

**Widget registry** (`frontend/lib/dashboardLayout.ts`, `WIDGETS`) – typed, explicit, no runtime discovery:
`{id, title, area, defaultVisible, defaultOrder, defaultSize, allowedSizes, usesDashboardData}`. Components
live in `components/dashboard/widgets.tsx` as `WIDGET_COMPONENTS: Record<WidgetId, …>` (TypeScript fails the
build if an id has no component). Current ids (stable, persisted – never rename, never reuse):

| id | widget | default | allowed |
|---|---|---|---|
| `daily_briefing` | Denní přehled | large | medium, large, full |
| `weekly_review` | Týdenní přehled | small | small, medium |
| `today` | Dnes | large | medium, large, full |
| `attention` | Vyžaduje pozornost | small | small, medium, large |
| `key_metrics` | Klíčová čísla | full | large, full |
| `goals` | Cíle | small | small, medium, large |
| `upcoming` | Nadcházející | small | small, medium, large |
| `work` | Práce | small | small, medium |
| `finance` | Finance | small | small, medium |
| `games` | Hry | full | medium, large, full |
| `quick_actions` | Rychlé akce | full | large, full |

**Layout schema** – `{version: 1, widgets: [{id, visible, order, size}]}`. Semantic only: no pixels, no CSS,
no per-breakpoint layouts, no free placement.

**Persistence** – `localStorage` key `standa-hub:dashboard-layout:v1`. The backend has no user-preference
storage and a single-user app does not justify a schema change for this; moving to a backend preference later
only needs a new storage adapter behind `useDashboardLayout`. Reads go through `useSyncExternalStore`: the
server and the hydration pass render a skeleton, then the *stored* layout appears (no flash of the default,
no hydration mismatch). Storage unavailable (private window) → layout works in memory until reload.

**Validation** (`normalizeLayout`, never throws) – other/missing version or malformed JSON → default layout;
unknown (obsolete) ids dropped; duplicates keep the first; invalid size → the widget's default size; invalid
visibility → default; widgets missing from the stored layout (e.g. added in a later release) are inserted after
their predecessor in the default order. Valid user choices are always kept.

**Sizes and responsive behaviour** – one DOM for all widths:
- desktop (xl): 6 units – small = 1/3, medium = 1/2, large = 2/3, full = whole row. Rows fill in order; a
  following row whose sizes match the end of the previous row stacks into its columns (`packDesktop`). This keeps
  the 4B.1 balance: Denní přehled + Dnes on the left, Týdenní přehled + Pozornost on the right; Finance under
  Práce. Cards never stretch; columns stack without holes.
- tablet (md): 2 columns, small/medium = half, large/full = whole row, dense packing (small cards pair up).
- mobile: one column in the stored order.
Block and column wrappers are `display: contents` below xl and items carry CSS `order`, so nothing is computed
per breakpoint in JS.

**Customize mode** – "Upravit dashboard" in the page header. Normal mode has no edit chrome at all. In edit mode:
a "Režim úprav" note, a dashed accent outline around each widget with a compact toolbar (title, position "3/11",
↑ / ↓, size select with only allowed sizes, "Skrýt"), widget content is `inert` and dimmed (no accidental
navigation, Tab only through controls), a "Skryté widgety" card with restore buttons, and "Obnovit výchozí
rozložení" (ConfirmDialog, disabled when already default) + "Hotovo".

**Save behaviour** – changes apply and persist immediately (no draft, nothing to lose when leaving edit mode);
"Hotovo" only ends the mode. Reset removes the stored key (future default changes then apply too).

**Reorder** – move buttons only (no drag and drop in 4F: buttons work identically for mouse, touch, keyboard and
screen readers; no DnD dependency). Moves skip hidden widgets; first/last buttons are disabled.

**Accessibility** – each widget in edit mode is a `role=group` named by its title; buttons are named
"Posunout nahoru: Finance", "Skrýt widget: Hry", "Zobrazit widget: Hry"; the size select has a label
"Velikost: Finance"; focus stays on the control after a move (re-found after the widget moves between columns),
moves to the restore button after hiding and back to "Skrýt" after restoring; a polite live region announces
"Finance: pozice 3 z 11."; no global shortcuts are added (Ctrl+K, Ctrl+Shift+K untouched).

**Empty state** – all widgets hidden → "Všechny widgety jsou skryté." with "Upravit dashboard".

**Data fetching** – the page owns the three requests: `GET /dashboard` once for all widgets that read it (only if
at least one is visible), `/briefing/today` only if Denní přehled is visible, `/weekly-review` only if Týdenní
přehled is visible. Widgets are pure renderers, so moving, resizing or toggling edit mode never refetches.
Loading / error / empty states stay inside each widget as before; a failing request does not affect editing.

## 17. Today Mode (Roadmap 4G)

**Purpose** – `/today` ("Dnes" in the sidebar, right under Řídicí centrum) answers *"What needs my attention
today?"*. The **dashboard** answers *"What is happening across my life?"* (all modules, customizable grid);
**Today** is one focused column of what matters today only – no finance history, goals list, work totals,
games or weekly review. It does not reuse the dashboard layout or customization and is not a second dashboard.

**Architecture** – hybrid: a dedicated route fed by one deterministic `GET /today` (`backend/today_service.py`)
that composes existing services – reminders (`reminder_service`), school status rules (`statuses.py`), the
dashboard's attention source (unread unresolved notifications) and the daily planner (`generate_plan`, unchanged
algorithm; actions now carry `ref`). One request instead of 4–5 frontend calls plus duplicated Prague-date and
dedup logic. No LLM, no writes except the planner's existing recommendation history.

**Date semantics** – today = 00:00–24:00 Europe/Prague via `time_utils` (`local_day_bounds_utc`; 23/25-hour DST
days handled). Never the server or browser UTC date; the page shows the server's Prague date and time.

**Item model** (`TodayItem`, only for this view) – `{id (ref "reminder:5"), type, title, subtitle, area, date,
time (Prague HH:MM or null), status, priority (planner rank badge), severity (notification badge), href}`.
Status: `upcoming` (later today), `due` (fired, still to handle), `past` (recurring occurrence already fired),
`done`, `open` (date-only today), `overdue` (before today, not done). Always shown as a word, never by colour only.

**Sections** (in this order)
1. *Souhrn* – "Teď 14:30", "Další: Fyzioterapie v 18:30 · za 4 h" (first timed upcoming item, computed once at
   load – no ticking clock), counts *zbývá dnes / pozornost / hotovo*.
2. *Vyžaduje pozornost* – overdue assignments, past exams still open ("zapiš výsledek"), fired reminders from
   before today, plus unread unresolved notifications (dashboard semantics). Notifications about a listed record
   merge into it (keeping the higher severity). Max 8, most severe first.
3. *Dnešní plán* – daily planner actions that are not already shown above or in the timeline.
4. *Časová osa* – today's reminders (by time), then "Během dne" (exams and assignments due today, date only), then
   a collapsed "Hotovo (n)". Past/finished rows are dimmed; the next item has a "Další" label, accent border and
   `aria-current`.
5. *Potom* – up to 3 items in the next 7 days not shown elsewhere.

**Deduplication** – one record, one place: timeline > attention > plan > potom. Information from a dropped
duplicate moves to the kept row as a badge ("Plán #2", "Důležité"). Tested in `tests/test_today.py`.

**Navigation** – every row is a link with the existing deep links (`/school?assignment=1`, `/school?exam=3`,
`/reminders?reminder=5`, `/goals?goal=7`) – the record opens focused and highlighted (`SearchHighlighter`).

**Quick Add** – "+ Přidat" in the header (and in the empty state) opens the global Quick Add; no second implementation.

**Empty day** – "Dnes nemáš nic naplánovaného." with "+ Přidat", "Plánovač →" and, if any, Potom.

**Partial failure** – each section is computed separately on the server; a failing source returns
`errors.<section>` and only that card shows an ErrorState. Whole request failed → page ErrorState with retry.

**Daily Briefing** – deliberately not embedded: it stays the dashboard's AI summary; Today is deterministic.

**Direct actions** – see §18 (Roadmap 4H).

**Look** – narrow single column (`ContentContainer width="narrow"`), one accent-lined summary card, charcoal
cards, mono times, semantic red/amber only for overdue/attention. Mobile: next item in the first viewport,
rows ≥ 44 px, Quick Add in the header and page header.

## 18. Act from Today (Roadmap 4H)

Today stays read-mostly: a row gets at most one primary action and one secondary one, only where the backend
already has clean semantics. The backend decides (`TodayItem.actions`); the UI never guesses from the title.

| Row | Actions | Path (reused, not new) |
|---|---|---|
| One-off reminder, active (today or overdue) | **Hotovo**; **Odložit** only once it has rung (snooze counts from now, so on a future reminder it would pull it earlier) | `POST /reminders/{id}/done` · `/snooze` with `?source=today` (same as the Reminders page) |
| Open assignment (today, overdue, or a planner row with `ref assignment:N`) | **Hotovo** | `POST /today/actions/prepare` → existing `modify_records` complete pending action → `POST /actions/confirm` |
| Past exam still open | **Zapsat výsledek →** (link) | navigates to `/school?exam=N`; no exam editor in Today |
| Recurring reminder, done/past rows, notifications, Potom | none | – |

**Skipped on purpose** – recurring reminders (their "done" confirms the occurrence without moving it and snooze
only shifts one occurrence – the Reminders page handles that), exam results/status (no simple unambiguous
flow), assignment editing, free-text snooze.

**Confirmation policy** – proportional to risk and identical to existing surfaces: reminder Hotovo is
immediate (as on the Reminders page); Odložit is an explicit choice from a small inline group; assignment
Hotovo is one click that runs the safe pending-action pipeline (snapshot stale check, audit, undo) – the
click is the confirmation, as in Quick Add.

**Snooze** – options come from `GET /today` (`snooze_options`), computed on the server in Europe/Prague:
+15 min, +1 h, +3 h (added to the UTC instant, so DST cannot skip or repeat time) and "Zítra 8:00" = the next
Prague calendar day at 08:00 (also right after midnight). No browser dates, no free text.

**Undo** – only where the backend supports it: completing an assignment shows "Vrátit" in the notice (existing
`/actions/undo` + confirm). Reminder actions have no undo, so none is shown.

**Refresh and focus** – one action at a time; after it exactly one `GET /today` (no page reload, no polling).
Focus moves to the next actionable row in the same list (else the previous one, else the notice). The notice
(`role=status`) announces "Připomínka „Fyzioterapie“ je hotová." / "Odloženo: …" / "Vráceno: …".

**Stale and errors** – already done / changed / deleted elsewhere (HTTP 400/404/409, `no_change`, snapshot
mismatch, already processed) → warning notice "… Stav jsem obnovil." and a refresh, no retry. Any other failure
→ the row stays with an inline alert and "Zkusit znovu"; for assignments the retry re-confirms the SAME
pending action, so a double click or retry never creates a second change. The rest of the page keeps working.
Notifications about a record that is already finished are not shown in Vyžaduje pozornost (read-only twin of
the notification generator's relevance rule), so a completed item disappears immediately.

**Source attribution** – Activity `user_context="today"`, shown as "zdroj: Dnes"; never labelled as AI. The
caller cannot spoof it (`?source=` accepts only `today`, pending-action sources are set server-side, an undo
inherits the source stored with the original action).

**Accessibility** – controls are named with the record ("Dokončit připomínku: Fyzioterapie", "Odložit
připomínku: …", "Zapsat výsledek zkoušky: …"); "Odložit" is a disclosure (`aria-expanded`, `aria-controls`)
opening a labelled group, Esc closes it and returns focus; busy state is text ("Ukládám…"); errors are
`role=alert`; nothing is conveyed by colour only. Mobile: actions sit under the title, all ≥ 44 px.

## 19. Game images (Game Enrichment A)

`components/games/GameImage` – tank thumbnail, MFF portrait or WoT currency icon in a fixed frame (`xs` 24 / `sm` 40 /
`md` 56 / `lg` 88 px; tanks 1.6 : 1; optional smaller `mobileSize`). Charcoal frame with `border-line-subtle`, control
radius, no glow, no splash art: the image is a small recognition anchor, text stays primary. Tank renders from Tankopedia
are dark and transparent, so the tank frame adds a soft centered `ink-2` backdrop and the image a mild brightness lift
(presentation only – source art is never modified). Missing/failed → neutral
monogram in the same frame. Assets are local (gitignored cache + runtime manifest), see `docs/game-assets.md`.
Placement: WoT grind rows (`EntityRow leading`, `sm`), WoT currency labels (`xs`, decorative), MFF character cards
(`md`, `sm` on mobile), completed-grind history (`xs`), milestone cards and the milestone form (`sm`). Do not add
images to small stat rows or turn modules into galleries.

## 20. Completion celebration and milestone gallery (Game Enrichment B)

- **Completion** – an explicit, confirmed action (`ConfirmDialog danger={false}`, confirm label = the action). The
  row then shows "GRIND COMPLETE" (mono, uppercase, `accent-strong`) with `motion-grind-complete`: one cyan
  box-shadow pulse, 1.3 s, CSS only. No confetti, no overlay, never blocks navigation; the server write happens first.
  Reduced motion → no animation, the row moves straight to history; the `role=status` text notice is always there.
- **Favorite** – "★ Legendární" `StatusBadge` (warning tone) + warning border on the card; a toggle button with
  `aria-pressed`. Not a ranking.
- **Gallery** – `MilestoneGallery`: 16:9 thumbnail buttons (`aspect-video`, `object-cover`, lazy) named
  "Zvětšit: Screenshot i z n – caption"; lightbox = portal dialog via `useModal` (focus on Zavřít, Esc, ←/→,
  `object-contain` so the aspect ratio is kept). Missing file → text placeholder in the same frame, never a broken
  image. No screenshots → nothing rendered (no empty placeholder tiles).

