# WoT progress, completion & milestones (Game Enrichment B)

Builds on Game Enrichment A (`docs/game-assets.md`): every tank shown here – active grind, completed history,
milestone card, the milestone form preview – goes through `GameImage kind="tank"`, so a tank name that resolves in
the Tankopedia manifest gets its picture automatically. No extra mapping is needed.

Page order on `/wot`: **Zdroje → Grindy tanků (active) → Splněné grindy → Mka & nejlepší bitvy**.

## Grind lifecycle

| State | How it gets there | Shown |
|---|---|---|
| `active` | `POST /wot/grind` (new tank) | active list, progress bar when a baseline exists |
| `paused` | grind form | active list area (as before) |
| `completed` | **explicit** "Splněno" → confirm → `POST /wot/grind/{id}/complete`, or status "Dokončeno" in the grind form | completed history |

- Completion is **never inferred** from XP. `xp_remaining = 0` alone does nothing; only the explicit action
  (or the explicit status in the form) completes a grind.
- On completion the grind is set to `status=completed`, `xp_remaining=0` (progress 100 %), and a row is written to
  `wot_grind_completions` with the completion timestamp. Nothing is deleted.
- Double completion → `409 already_completed` (conditional `UPDATE … WHERE status <> 'completed'`, safe across
  tabs; the UI just reloads). Missing grind → `404 not_found`.
- **Progress baseline**: `wot_grinds.xp_start` (+ `started_at`) is set when a grind is created, and reset when a
  completed grind is reactivated. Progress = `(xp_start − xp_remaining) / xp_start`. Grinds that existed before the
  migration got `xp_start = xp_remaining` (their progress starts at 0 % from the upgrade; no invented history).
  Grinds without a baseline show no progress bar rather than a guessed one.
- Deleting a grind keeps its history: completions are detached (`grind_id → NULL`, explicitly in code because
  SQLite does not enforce `ON DELETE SET NULL`). The AI delete path does the same.

## Completed history

`GET /wot/grinds/completed` – newest first. Each item: stable id `completion:{id}` (or `grind:{id}` for a grind that
was already `completed` before this phase and has no completion row – shown as "datum neznámé"), `tank`,
`completed_at`, `started_at`, `xp_start`, `xp_remaining_before`, `duration_days`, `source` (`manual`), `legacy`.
UI: compact list (latest 5, "Zobrazit všechny (N)"), xs tank image, date, duration, XP. The just-completed entry is
highlighted.

## Celebration

After a successful completion the row shows **GRIND COMPLETE** with a cyan pulse/glow (`motion-grind-complete`,
`motion.css`, 1.3 s, pure CSS – no confetti, no library), progress 100 %, no actions. Then the lists reload and the
grind moves to history. A `role=status` notice ("Grind complete – X je splněný") stays for screen readers.

- The server write happens **before** the animation; the animation never blocks navigation or other requests (no
  overlay, no modal; leaving the page cancels the timer).
- `prefers-reduced-motion: reduce` → no animation (`celebrationDuration(true) = 0`, and both classes are in the
  reduced-motion `animation: none` list): the grind goes straight to history and only the text notice appears.

## `wot_grind_completed` (event concept)

No event bus. A completion writes one `activity_log` row through the existing `log_activity`:
`area="wot"`, `action_type="complete"`, `entity_type="WotGrind"`, `user_context="manual"`,
`delta = {"event": "wot_grind_completed", "completion_id", "tank", "xp_start", "xp_remaining_before"}`,
`dedupe_key = "wot_grind_completed:{completion_id}"`. Future consumers (briefing, review, gamification) can read it
from activity. No XP, badges or streaks are computed now.

## Milestones ("Mka")

Table `wot_milestones` – intentionally WoT-specific, not a generic "achievement" model:

| Column | Type | Notes |
|---|---|---|
| `id` | int | stable |
| `milestone_type` | str(30) | `mastery` (only value now) |
| `mastery` | str(20)? | `ace` (Mistr/Mko), `first`, `second`, `third` |
| `tank` | str(100) | **only required field**; resolved to an image via Game Enrichment A |
| `map_name` | str(100)? | |
| `played_on` | date? | not in the future, ≥ 2010 |
| `damage`, `assist` | int? | 0–100 000 |
| `kills` | int? | 0–15 |
| `base_xp` | int? | 0–10 000 |
| `notes` | text? | ≤ 2000 chars |
| `favorite` | bool | "Legendární" marker, no ranking |
| `created_at`, `updated_at` | datetime | naive UTC |

API: `GET/POST /wot/milestones`, `PATCH/DELETE /wot/milestones/{id}`. Validation errors are `400` with
`{"detail": {"error": "invalid_<field>", "message": "…"}}`. List order: favorites first, then `played_on` newest.
Deleting a milestone requires an explicit confirm in the UI and removes its screenshots (rows + files).

## Screenshot storage

Table `wot_milestone_screenshots`: `id`, `milestone_id` (FK, cascade), `stored_name` (unique, server-generated),
`original_name` (display only), `content_type`, `size_bytes`, `caption` (≤ 300), `position` (order), `created_at`.

- **Location**: `MEDIA_DIR/wot-screenshots/` – `MEDIA_DIR` defaults to `./media` relative to the backend working
  directory (`backend/media/…` when started from `backend/`). Gitignored. Change via `MEDIA_DIR` in `backend/.env`.
- Metadata in the DB, files on disk; **files are not part of the DB backup** – back up `MEDIA_DIR` separately.
- Module: `backend/media_storage.py` (smallest safe local store; no S3/cloud).

### Upload limits / security

- `POST /wot/milestones/{id}/screenshots?filename=…&caption=…` with the **raw image as the request body**
  (no multipart dependency). One file per request; the UI uploads them one after another after saving the milestone.
- Types: PNG, JPEG, WebP, detected from the **file signature** (Content-Type and extension are not trusted); a
  present extension must match the content.
- Size: `WOT_SCREENSHOT_MAX_MB` (default 10, hard cap 50) → `413`; checked from `Content-Length` before reading and
  again on the bytes. Max 20 screenshots per milestone.
- Stored name = `uuid4().hex + .png|.jpg|.webp`, created exclusively (never overwrites). The original filename is
  stripped of paths/control chars and only stored as metadata.
- Serving: `GET /wot/screenshots/{id}/file` looks the file up **by DB id only**; the stored name is re-validated
  against `^[0-9a-f]{32}\.(png|jpg|webp)$` and must resolve inside the folder (no traversal, no arbitrary paths).
  Response: correct `Content-Type`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'`,
  `Cache-Control: private`. Behind the normal auth like every other endpoint.
- `PATCH /wot/screenshots/{id}` (caption, position), `DELETE /wot/screenshots/{id}` (row + file). A failed DB commit
  after writing a file removes the file again.

## Gallery UI

`components/wot/MilestoneGallery.tsx` – 16:9 thumbnails (lazy, `object-cover`), up to 4 with "+N", click/tap opens a
lightbox dialog (`object-contain`, keeps aspect ratio) with caption, `i / n`, ←/→ buttons and arrow keys, Esc /
Zavřít returns focus to the thumbnail. A missing file shows "Obrázek se nepodařilo načíst" instead of a broken image.
No screenshots → no gallery. Mobile: 2 thumbnails per row, lightbox full width.

## Migration

`0013_wot_milestones` (down_revision `0012_weekly_reviews`): adds `wot_grinds.xp_start`, `wot_grinds.started_at`
(backfill above), creates `wot_grind_completions`, `wot_milestones`, `wot_milestone_screenshots`. Additive; full
downgrade. Production tables only via Alembic.

## Test data

The Progetto 65 (Útesy) and ELC EVEN 90 (Karelia) Mka exist only in `backend/tests/test_wot_milestones.py` and the
UI fixtures (`frontend/scripts/fixtures/wot-*.json`, generated from the real `wot_service`). Nothing is written to a
real database. Fixture screenshots are neutral one-colour PNGs, not game art.

## Deferred

Replay library and replay parsing, best-moments page across games, MFF progression/T4 events, gamification (XP,
badges, streaks) on top of `wot_grind_completed`, screenshot reordering by drag & drop (API supports `position`),
image thumbnails/resizing on the server, including `MEDIA_DIR` in the backup script.
