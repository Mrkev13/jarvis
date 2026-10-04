# Lokální herní obrázky (necommitují se)

Tuhle složku plní `node scripts/fetch-game-assets.mjs` (viz `docs/game-assets.md`):

- `wot/tanks/<slug>.png` – ikony tanků z oficiálního Wargaming Tankopedia API,
- `wot/resources/<klíč>.<přípona>` – ikony měn z URL v `scripts/game-assets.sources.json`,
- `mff/characters/<slug>.<přípona>` – portréty z URL v `scripts/game-assets.sources.json`,
- `manifest.json` – seznam dostupných souborů (aplikace bez něj ukáže záložní monogramy).

Obrázky jsou majetkem Wargaming.net, resp. Netmarble / Marvel – jen pro osobní použití, neukládat do Gitu.
