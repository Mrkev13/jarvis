# Game visual assets (Game Enrichment A)

Tank thumbnails and WoT currency icons on `/wot`, character portraits on `/mff`. Images help recognition;
text (names, numbers, statuses) always stays next to them and the app works with **zero** images.

## Sources

| Asset | Source | How | Notes |
|---|---|---|---|
| Tank icons | **Official Wargaming Tankopedia API** – `https://api.worldoftanks.{eu,com,asia}/wot/encyclopedia/vehicles/?application_id=…&fields=name,short_name,images` → `images.big_icon` (160 × 100 transparent PNG; the API returns it as `http://` on the same API host – the script upgrades it to `https://`, official hosts only) | `scripts/fetch-game-assets.mjs` matches every tank in the registry by official name / aliases | Needs a free `application_id` from https://developers.wargaming.net. Stable, versioned by Wargaming. |
| Currency icons (Credits, Gold, Bonds, Free XP) | Official Wargaming sources (the API does not expose them) | explicit https URLs in `frontend/scripts/game-assets.sources.json` → `resources` | Leave empty to keep the neutral monogram. |
| MFF portraits | Official Netmarble / Marvel sources (no public API exists) | explicit https URLs in `game-assets.sources.json` → `characters` | Leave empty to keep the monogram. |
| Your own files | any image you are allowed to use | copy `<slug>.png|webp|jpg|svg` into the folder, run `--manifest-only` | Slugs are the keys in `frontend/lib/gameAssets.ts`. |

Rejected: random search results, fan-wiki hotlinking (unstable, unclear rights), user-upload hosts, any AI-generated
"lookalike" tanks, portraits or currencies.

## Licensing / attribution

Tank renders and currency art are © Wargaming.net; MFF portraits © Netmarble Corp. / © Marvel. They are used for
personal, non-commercial display only and are **never committed** to this repository (`frontend/public/game-assets/*`
is gitignored, only its README is tracked). The manifest records `source` and `attribution` for every downloaded
file. Do not redistribute the cache folder.

## Storage strategy – local cache (B + C)

1. `node scripts/fetch-game-assets.mjs` (with `WG_APPLICATION_ID`, optional `WG_REGION=eu|com|asia`) downloads into
   `frontend/public/game-assets/{wot/tanks,wot/resources,mff/characters}/<slug>.<ext>`; https only, image MIME types
   only, max 600 kB per file.
2. It writes `public/game-assets/manifest.json`: `{version: 1, generated_at, assets: {"tank/kranvagn": {file, source,
   attribution}}}`. `--manifest-only` rebuilds it from the files present (manual copies).
3. The app fetches the manifest once per load (`useGameAssetManifest`), validates it (known key shape, relative image
   paths only – no URLs, no `..`) and serves images **same-origin** from `/game-assets/…`.

Why: no runtime dependency on game CDNs (offline / host outage → still works), no remote image hosts in Next config,
no copyrighted files in Git, stable human-readable file names, assets update by re-running the script.

**Update process**: add the entity to the registry (`TANKS` / `CHARACTERS` in `lib/gameAssets.ts`, official name +
aliases) → for MFF/currencies add the URL to `game-assets.sources.json` → run the script → reload.

## Mapping and normalization

`lib/gameAssets.ts` is the single explicit registry (also imported by the script). Names from the app are matched by
`normalizeGameName`: no diacritics/punctuation, lower case, `Obj.` = `Object`, `Dr.` = `Doctor`, standalone roman
numerals → digits (`ST-II` = `ST 2`), `Version`/`Ver.` = `V`, spaces ignored (`WZ-111 5A` = `WZ111 5A`). Aliases cover
the user's spellings (`Progetto 65` → `Progetto M40 mod. 65`, `Obj. 268 V4` → `Object 268 Version 4`, `FV215b 183`).
Unknown names simply get the fallback – never a guessed image of another tank.

## Fallback

`GameImage` always renders the same fixed frame. Unknown entity, missing file, manifest missing/invalid, or an image
load error → a readable monogram (`KR`, `O279`, `LS`, currency `CR`/`G`/`B`/`XP`) in neutral charcoal. Never a broken
image icon; no console errors from missing files because nothing absent is requested.

## Sizes

Tokens (`GAME_IMAGE_SIZES`): `xs` 24, `sm` 40, `md` 56, `lg` 88 px height; tanks are 1.6 : 1 (Tankopedia icon ratio),
portraits and icons square. `mobileSize` gives a smaller frame below `md`. Used: currency `xs`, tank rows `sm`
(64 × 40), MFF cards `md` (`sm` on mobile).

## Accessibility

Tank and portrait images carry identity: `alt="Tank Kranvagn"`, `alt="Portrét: Luna Snow"` (fallback: `role="img"` with
the same label). Currency icons sit next to the visible label and are decorative (`alt=""` / `aria-hidden`).

## Future (Game Enrichment B/C – not built yet)

User-uploaded screenshots (Mastery/"Mko" gallery), replay thumbnails and milestone galleries will need uploads with a
server-side store. `GameImage` already takes any same-origin file through the manifest-style `{file}` contract; uploads
should get their own validated store (size/type checks, per-file records) instead of `public/`, and reuse the frame,
size tokens and fallback. Grind completion, `wot_grind_completed`, replay library and MFF T4 events are separate phases.
