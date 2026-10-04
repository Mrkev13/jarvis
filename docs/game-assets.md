# Game visual assets (Game Enrichment A)

Tank thumbnails and WoT currency icons on `/wot`, character portraits on `/mff`. Images help recognition;
text (names, numbers, statuses) always stays next to them and the app works with **zero** images.

## Sources

| Asset | Source | How | Notes |
|---|---|---|---|
| Tank icons | **Official Wargaming Tankopedia API** – `https://api.worldoftanks.{eu,com,asia}/wot/encyclopedia/vehicles/?application_id=…&fields=tank_id,name,short_name,nation,tier,images` → `images.big_icon` (160 × 100 transparent PNG; the API returns it as `http://` on the same API host – the script upgrades it to `https://`, official hosts only) | `scripts/fetch-game-assets.mjs` mirrors **every** vehicle; the app matches grind names at runtime | Needs a free `application_id` from https://developers.wargaming.net. No tank list in code. |
| Currency icons (Credits, Gold, Bonds, Free XP) | **Official WoT portal stylesheet** (`eu-wotp.wgcdn.co/static/<version>/wotp_static/css/main.css`) – the portal embeds its currency icons there as SVG data URIs. The Tankopedia API has no currency icons (only medals and personal-reserve icons, which depict boosters, not currencies). | the script finds the current stylesheet on `worldoftanks.eu/en/tankopedia/` (fallback: pinned URL in `game-assets.sources.json`), extracts the icon for an exact CSS selector and checks it is static SVG | Selectors: credits `.currency__silver::after` (WoT calls credits "silver"), gold `.currency__gold::after`, free XP `.experience__free::after`, bonds `.modules_info-box-text__bonds-farmer::after` (the portal's bonds icon, used in its bonds info box). |
| MFF portraits | Official Netmarble / Marvel sources (no public API exists) | explicit https URLs in `game-assets.sources.json` → `characters` | Still empty – monograms until an official source is chosen. |
| Your own files | any image you are allowed to use | copy `<slug>.png|webp|jpg|svg` into `wot/resources` or `mff/characters`, run `--manifest-only` | Slugs are the keys in `frontend/lib/gameAssets.ts`. |

Rejected: random search results, fan-wiki hotlinking (unstable, unclear rights), user-upload hosts, any AI-generated
"lookalike" tanks, portraits or currencies.

## Licensing / attribution

Tank renders and currency art are © Wargaming.net; MFF portraits © Netmarble Corp. / © Marvel. They are used for
personal, non-commercial display only and are **never committed** to this repository (`frontend/public/game-assets/*`
is gitignored, only its README is tracked). The manifest records `source` and `attribution` for every downloaded
file. Do not redistribute the cache folder.

## Storage strategy – mirror all of Tankopedia locally

Measured (EU, game version 2.77): **1028 vehicles**, every one with an icon, 1028 distinct URLs, 12–15 kB each →
**12.6 MB** cache, about 10 s for the first download (6 parallel requests), ~6 s for a refresh. 32 renders are shared
between a vehicle and its Frontline copy (`T30` / `T30 FL`) – kept as separate files (≈0.4 MB, not worth the logic).

Choice: download **all** vehicles. It is the simpler option – no knowledge of the app's data in the script, no
on-demand download path, no runtime proxy – and the size is small. Any tank a user adds later already has its image.
The browser still loads only the images it displays (`loading="lazy"`), plus one manifest.

1. `WG_APPLICATION_ID=… WG_REGION=eu node scripts/fetch-game-assets.mjs` writes
   `frontend/public/game-assets/wot/tanks/<tank_id>.png`, `wot/resources/<key>.svg`, `mff/characters/<slug>.<ext>`.
2. It writes `public/game-assets/manifest.json` (gitignored), version 2:

   ```json
   {
     "version": 2,
     "generated_at": "…",
     "assets": { "resource/credits": { "file": "wot/resources/credits.svg", "source": "<stylesheet URL> <selector>", "attribution": "© Wargaming.net" } },
     "wot_tanks": {
       "2929": { "name": "Vz. 55", "short_name": "Vz. 55", "nation": "czech", "tier": 10,
                 "path": "wot/tanks/2929.png", "source": "https://api.worldoftanks.eu/static/…/czech-Cz17_Vz_55.png",
                 "attribution": "© Wargaming.net" }
     }
   }
   ```

   Tanks are keyed by Tankopedia `tank_id`, not by normalized name, because names collide (two vehicles called
   `IS-2`, `T-34-85 Rudy` in two nations). Size: ~245 kB raw, **32 kB gzip / 24 kB brotli**.
3. The app fetches the manifest once per load (`useGameAssetManifest`), validates it and builds the lookup index once.

### Refresh workflow

```
WG_APPLICATION_ID=… WG_REGION=eu node scripts/fetch-game-assets.mjs   # refresh metadata, add new vehicles, re-extract icons
… --force                                                             # re-download images that are already cached
node scripts/fetch-game-assets.mjs --manifest-only                      # rebuild the manifest from files present
```

A refresh re-reads Tankopedia, downloads only vehicles without a cached file, removes files of vehicles that left
Tankopedia, re-extracts the currency icons and rebuilds the manifest. Without `WG_APPLICATION_ID` (or with
`--manifest-only`) the previous tank entries are kept. **A new grind tank needs no code change** – if it is in
Tankopedia it is already in the manifest. Never put the application id in a committed file; the script refuses to
write a manifest that would contain it.

## Matching (`resolveTank` in `lib/gameAssets.ts`)

Names are compared after `normalizeGameName`: no diacritics/punctuation, lower case, `Obj.` = `Object`, `Dr.` =
`Doctor`, standalone roman numerals → digits (`ST-II` = `ST 2`), `Version`/`Ver.` = `V`. Order:

1. exact normalized Tankopedia **name** (`Hirschkafer` = `Hirschkäfer`, `VZ.55` = `Vz. 55`);
2. exact normalized **short_name** (`CAV 71` → *CAV mod. 71*, `Object 279 (e)` → *Object 279 early*);
3. manual **alias** (`TANK_ALIASES`);
4. separator-insensitive match (spaces and dashes ignored) **only if it identifies exactly one vehicle**
   (`T34/100` → *Konštrukta T-34/100*);
5. otherwise the fallback monogram.

Tier 4 never merges different tanks that differ only by a dash: `T34` (US heavy) and `T-34` (Soviet medium) are
already distinguished in tier 1. A tier that matches several vehicles stops the search (`IS-2` → monogram) – never a
guessed image of another tank. The script lists such ambiguous names after each run.

Manual aliases exist only for spellings that none of the tiers can resolve: `268 V4`, `279e`, `FV 183`, `TVP 50/51`
and `T57 Heavy Tank` (an older official name of *T57 Heavy*). MFF characters and currencies are small fixed sets with
slugs (`CHARACTERS` / `RESOURCES`); `Luna` is an alias of `Luna Snow`.

## Security

- The script downloads over **https only**; `http://` Tankopedia icons are upgraded only for the exact API hosts
  (`api.worldoftanks.eu|com|asia`); any other http URL is refused.
- Tank images must come from those hosts (checked again after redirects); the portal stylesheet only from
  `worldoftanks.eu` / `eu-wotp.wgcdn.co`. Image MIME types only, max 600 kB per file.
- Currency SVGs must be static graphics (`isSafeSvg`): no scripts, event handlers, external `href`/`url()`,
  `foreignObject`, DOCTYPE/entities; max 64 kB.
- The manifest holds relative paths only (no URLs, no `..`, tanks only under `wot/tanks/`); the app re-validates it.
- No runtime proxy and no remote image hosts: the app serves only same-origin files from `/game-assets/…`.

## Fallback

`GameImage` always renders the same fixed frame. Unknown or ambiguous name, missing file, manifest missing/invalid
(including the old version-1 manifest – rerun the script), or an image load error → a readable monogram (`KR`, `O279`,
`LS`, currency `CR`/`G`/`B`/`XP`) in neutral charcoal. Never a broken image icon.

## Sizes

Tokens (`GAME_IMAGE_SIZES`): `xs` 24, `sm` 40, `md` 56, `lg` 88 px height; tanks are 1.6 : 1 (Tankopedia icon ratio),
portraits and icons square. `mobileSize` gives a smaller frame below `md`. Used: currency `xs`, tank rows `sm`
(64 × 40), MFF cards `md` (`sm` on mobile). Tanks and currency icons are `object-contain`, portraits `object-cover`.

## Accessibility

Tank and portrait images carry identity: `alt="Tank Kranvagn"`, `alt="Portrét: Luna Snow"` (fallback: `role="img"` with
the same label). Currency icons sit next to the visible label and are decorative (`alt=""` / `aria-hidden`).

## Future (Game Enrichment B/C – not built yet)

User-uploaded screenshots (Mastery/"Mko" gallery), replay thumbnails and milestone galleries will need uploads with a
server-side store. `GameImage` already takes any same-origin file through the manifest; uploads should get their own
validated store (size/type checks, per-file records) instead of `public/`, and reuse the frame, size tokens and
fallback. Grind completion, `wot_grind_completed`, replay library and MFF T4 events are separate phases.
