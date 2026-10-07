# WoT Replay Library (Game Enrichment C)

A personal archive of original `.wotreplay` files for memorable battles. It builds on Game Enrichment A (tank
images) and B (milestones / "Mka", screenshot storage). It is **not** AI replay analysis, coaching, video, a generic
file manager or gamification.

- Page: **`/wot/replays`**. `/wot` only shows a "Knihovna replayů" link card; milestone cards with a linked replay
  show "▶ Replay bitvy".
- Detail: `/wot/replays?replay=ID` (side drawer). This is also the Global Search target.

## Flow

1. "Nahrát replay" → pick a `.wotreplay` file (client checks the extension and size).
2. The backend validates the file, computes SHA-256, rejects duplicates, runs the parser and stores the original file
   unchanged.
3. The review drawer ("Zkontroluj údaje replaye") opens with what the parser found (status badge + hint), the tank
   name pre-filled from A's manifest (see *Tank names*), stats, mastery and result.
4. The user corrects or adds fields, tags, a milestone link and a note → "Uložit údaje" (`PATCH`).
5. The replay is in the library. Closing the drawer ("Doplnit později") loses nothing – the replay is already saved.

If parsing fails, the replay is **still stored** (status `unsupported`, "Metadata nenačtena") and everything can be
filled in manually. Only a file that is not a replay at all is rejected.

## API (all behind the normal login)

| Method | Path | Notes |
|---|---|---|
| GET | `/wot/replays` | `q`, `tank`, `map`, `tag`, `favorite`, `mastery` (`ace…third` or `none`), `result`, `parser_status`, `sort` (`played_desc` default, `played_asc`, `uploaded_desc`). Returns `{items, total, facets: {tanks, maps, tags}, preset_tags, statuses}` |
| POST | `/wot/replays?filename=…` | raw file as the request body (no multipart) |
| GET | `/wot/replays/{id}` | detail incl. the linked milestone and its screenshots |
| PATCH | `/wot/replays/{id}` | any of: `tank_name`, `map_name`, `played_at` (`YYYY-MM-DD` → Prague noon, or ISO time), `damage`, `assist`, `kills`, `base_xp`, `mastery`, `battle_result` (`win`/`loss`/`draw`), `notes`, `tags`, `favorite`, `linked_milestone_id` (or `null`) |
| DELETE | `/wot/replays/{id}` | removes the row, then the file |
| GET | `/wot/replays/{id}/file` | original file as an attachment |

Errors use the B shape: `{"detail": {"error": "<code>", "message": "…"}}` (`invalid_file`, `invalid_<field>`,
`invalid_tags`, `not_found`, `milestone_not_found`, `duplicate`).

## Storage

- Files: **`MEDIA_DIR/wot-replays/<uuid4 hex>.wotreplay`**. This reuses B's `backend/media_storage.py`
  (`save_bytes`, `path_for`, `delete_file`) and only adds `wotreplay` to the stored-name pattern. `MEDIA_DIR` defaults
  to `./media` (gitignored).
- Metadata: table `wot_replays` (see *Schema*). Replay binaries are never stored in the database.
- The server generates the file name. The original name is cleaned (no path, no control characters) and kept only as
  display metadata and the download name. Files are served **only by DB id**: the stored name is re-checked against
  `^[0-9a-f]{32}\.wotreplay$` and must resolve inside the folder. Responses never contain filesystem paths.
- Delete: the row is committed first, then the file is removed. A failed commit after writing a file removes the file
  again.
- Download: `Content-Disposition: attachment` (quotes, slashes and `;` are stripped from the name),
  `application/octet-stream`, `nosniff`, `CSP default-src 'none'`, `Cache-Control: private, no-store`.

### Limits and validation

- Extension must be `.wotreplay` (the `filename` parameter is required).
- Size: `WOT_REPLAY_MAX_MB` (default **50 MB**, hard cap 200). Checked against `Content-Length` before reading and
  again on the bytes → `413`. Empty file → `400`.
- Structure: see *Parser*. A file with neither the replay signature nor a readable header block → `400 invalid_file`
  (e.g. a PNG renamed to `.wotreplay`).

### Backup implications

**Replay files (and B's screenshots) under `MEDIA_DIR` are not part of the database backup** (`backup_service.py`
dumps the DB only). Until the backup script includes `MEDIA_DIR`, back the folder up separately. Restoring only the
DB leaves rows whose download returns 404 (the UI keeps working; the files are simply missing).

## Duplicate detection

- SHA-256 of the full file content, stored in `wot_replays.sha256` (**unique**).
- The same content (whatever the file name) → `409 {"error": "duplicate", "replay_id": <existing>}`. Nothing is
  written – no second file, no second row. The UI shows "Tenhle replay už v knihovně je" with "Otevřít existující".
- The same name with different content is a different replay. Concurrent uploads of one file are caught by the unique
  constraint and answered with the same 409.
- The app is single-user (there is no user table; auth = the PIN session), so "same user" means the whole library.

## Parser (`backend/replay_parser.py`, version `1`)

Deterministic, no AI, no external services. `parse_replay(bytes) -> ReplayParseResult(status, metadata, warnings,
parser_version)`.

**Format basis.** Wargaming does not publish a `.wotreplay` specification. The parser reads only the unencrypted
header, as described by community tools (open-source replay → JSON converters / `wotreplay-parser`):

```
[4 B signature 12 32 34 11][uint32 LE block count N]
N × [uint32 LE length][UTF-8 JSON block]
[rest: encrypted + compressed battle stream – never read]
```

- Block 1 (battle start): `playerVehicle` ("nation-Tag"), `mapDisplayName` (localized as the game client),
  `mapName`, `dateTime` (`dd.mm.yyyy hh:mm:ss`, client local time), `clientVersionFromExe`/`FromXml`, `playerName`,
  `vehicles`.
- Block 2 (only for battles played to the end): a JSON array whose first element is the battle result –
  `common.winnerTeam`, `common.arenaCreateTime` and `personal` (either the stats directly, or per vehicle with
  `damageDealt`, `damageAssistedRadio`, `damageAssistedTrack`, `kills`, `originalXP`, `markOfMastery`, `team`).

**Field mapping**

| Field | Source | Rule |
|---|---|---|
| `tank_tag` | `playerVehicle` "italy-It13_Progetto_M35_mod_46" | → "italy:It13_Progetto_M35_mod_46"; the human name is not in the replay (see *Tank names*) |
| `map_name` | `mapDisplayName` | missing → warning (the internal code is only mentioned) |
| `played_at` | `common.arenaCreateTime` (UTC) | fallback `dateTime` read as Europe/Prague local time |
| `game_version` | `clientVersionFromExe` "1, 26, 0, 0" → "1.26.0.0" | fallback: version from the XML string |
| `damage` / `kills` / `base_xp` | `damageDealt` / `kills` / `originalXP` | must be an integer within the milestone limits (100 000 / 15 / 10 000), otherwise dropped with a warning |
| `assist` | `damageAssistedRadio + damageAssistedTrack` | stun assistance is not included |
| `mastery` | `markOfMastery` 4/3/2/1 | → ace/first/second/third; 0 = no badge (no warning) |
| `battle_result` | `winnerTeam` vs the player's `team` | 0 → draw |

**Statuses**

- `parsed` – header and battle result read, all main fields present.
- `partial` – the header was read but the battle result is missing (battle left early / different layout), or some
  values were missing or out of range.
- `unsupported` – the signature matches but the header can't be read (new format version). The file is kept and the
  metadata is manual.
- `invalid` – not a replay. The upload is refused.

Hostile input (huge block lengths, truncated files, wrong types, `../` in `playerVehicle`) never crashes the parser;
the bad value is just not used. The warnings are stored (`parser_warnings`) and shown in the detail for
partial/unsupported replays.

### Parser limitations (important)

- **No real replay was available while building this.** The parser is tested only against synthetic files built to
  the community-documented layout (`backend/tests/replay_fixtures.py`). Whether real files from the current client
  parse as `parsed` – and especially whether `originalXP` equals the base XP the game shows and whether assistance =
  radio + track – **must be verified locally** with a few real replays (see the checklist).
- If a game update changes the header, files degrade to `partial`/`unsupported`, never to wrong data. Bump
  `PARSER_VERSION` when the mapping changes.
- The parser never decrypts the battle stream (no positions, shots, chat, timeline).
- `mapDisplayName` follows the game client's language, so map names may be Czech or English depending on the client.
- `played_at` from `dateTime` (only when `arenaCreateTime` is missing) assumes the client clock is in Europe/Prague.
- The player name is read only to find the team; it is not stored.

## Tank names (Game Enrichment A integration)

A replay contains the vehicle **tag**, not its name. A's manifest stores every vehicle's Tankopedia image URL, whose
file name is `<nation>-<tag>.png` – the same tag. `resolveTankTag` (`frontend/lib/gameAssets.ts`) uses this to map
"sweden:S16_Kranvagn" → "Kranvagn" without any registry. The review form pre-fills that name. List and detail show
manual name → manifest name → raw tag → file name, and `GameImage` gets the name, so images appear automatically. An
unknown tag shows the raw tag and a monogram – nothing is guessed. The backend stores only `tank_tag` plus the
user-confirmed `tank_name`.

## Tags

- Presets: `mko`, `carry`, `spotting`, `record`, `mistake`, `fun`, `close-game` (shown as Mko, Carry, Spotování,
  Rekord, Chyba, Zábava, Těsná bitva).
- Custom tags: lower-cased, spaces collapsed, 1–24 characters (letters, digits, space, `-`, `_`), at most 8 per
  replay, de-duplicated.
- Stored as a JSON list on the replay (no taxonomy tables). Filtering is exact on the normalized tag.

## Favorite

A boolean with a "★ Oblíbený" badge, a highlighted row border and a toggle with `aria-pressed` (in the row and the edit
form). It can be filtered ("★ Jen oblíbené"). There is no ranking or score.

## Milestone linking

- `wot_replays.linked_milestone_id` → `wot_milestones.id` (optional, `ON DELETE SET NULL`). One milestone per replay; a
  milestone may have several replays (`replay_ids` in the milestone API).
- Linking checks that the milestone exists (`404 milestone_not_found`). `null` unlinks.
- Deleting a milestone keeps its replays and only clears the link (done explicitly in `wot_service.delete_milestone`,
  because SQLite does not enforce `SET NULL`). Deleting a replay keeps the milestone.
- The replay detail shows the linked milestone and its screenshots through B's `MilestoneGallery` (no copies). Nobody
  is forced to attach a replay to a Mko.

## Search / filter

- Library: deterministic filtering in `wot_replay_service.list_replays`. Text search (diacritics-insensitive, all
  words) covers tank name, tag, map, notes, file name and tags. Filters: tank, map, tag, favorite, mastery (incl.
  "no badge"), result and parser status. Sorting: played date (undated replays always last) or upload time. Facets
  for the selects come from the whole library.
- Global Search (Ctrl+K): `search_service` yields `wot_replay` results (title = tank name or tag or file name;
  subtitle "Replay · map · date · ★"; tags, notes and file name are searchable) linking to
  `/wot/replays?replay=ID`. The frontend highlight target is `replay-ID`.

## Activity

`log_activity` rows (area `wot`, entity `WotReplay`) with `delta.event`:

- `replay_uploaded` – includes the parser status;
- `replay_deleted`;
- `replay_linked_to_milestone` – includes the milestone id.

Plain metadata edits, tags and favorites are not logged (no Activity spam). There is no gamification.

## Schema – migration `0014_wot_replays` (after `0013_wot_milestones`)

One additive table, `wot_replays`:

- file: `id`, `original_filename`, `stored_filename` (unique), `file_size`, `sha256` (unique), `uploaded_at`;
- battle: `played_at`, `tank_name`, `tank_tag`, `map_name`, `damage`, `assist`, `kills`, `base_xp`, `mastery`,
  `battle_result`, `game_version`;
- user data: `notes`, `tags` (JSON text), `favorite`;
- parser: `parser_status`, `parser_version`, `parser_warnings` (JSON text);
- links and timestamps: `linked_milestone_id` (FK SET NULL, indexed), `created_at`, `updated_at`.

Indexes: `uploaded_at`, `played_at`, `linked_milestone_id`. Full downgrade (milestones and grinds are untouched).

## Test data

`backend/tests/replay_fixtures.py` builds synthetic replays (Progetto 65 / Útesy, ELC EVEN 90 / Karelia, a header-only
Kranvagn, a broken header). The UI fixtures (`frontend/scripts/fixtures/wot-replays*.json`) come from the real service
over those files. `replay-upload.wotreplay` is a ~1.5 kB synthetic file for the browser upload test. None of these
are real user replays.

## Local verification checklist

1. `cd backend && alembic upgrade head` – applies `0014_wot_replays` on top of `0013_wot_milestones` (back up the DB
   first).
2. Check `MEDIA_DIR` is writable; optionally set `WOT_REPLAY_MAX_MB`.
3. Make sure the Tankopedia cache/manifest from Game Enrichment A exists (`frontend/public/game-assets/manifest.json`;
   refresh with `WG_APPLICATION_ID=… node scripts/fetch-game-assets.mjs` if needed) so tags resolve to names and images.
4. Upload 3–5 real replays from `World_of_Tanks/replays/`: one finished normally, one left early, one Mastery battle.
   - Check the status (`parsed` / `partial`) and compare damage, assistance, kills, **base XP**, mastery, result, map
     and date with the in-game results screen.
   - If a value differs systematically, note it – the field mapping may need a parser version bump.
5. Upload the same file again → "už v knihovně", no new file in `MEDIA_DIR/wot-replays/`.
6. Edit metadata, add tags, link to an Mko, toggle favorite, then try the filters and Ctrl+K search.
7. Download → the bytes equal the original (`sha256sum`).
8. Delete → the file disappears from `MEDIA_DIR/wot-replays/` and the linked Mko stays.
9. Add `MEDIA_DIR` to your backup routine.

## Deferred

- Including `MEDIA_DIR` in the backup script.
- Bulk upload / folder import.
- "Create Mko from replay" pre-fill.
- Replay stream decoding (positions, timeline).
- Per-tank stats aggregation.
- A best-moments page across games.
- Generalizing to other games.
- Re-parsing existing replays after a parser version bump (the stored `parser_version` makes this possible).
