# Lokální herní obrázky (necommitují se)

Tuhle složku plní `node scripts/fetch-game-assets.mjs` (viz `docs/game-assets.md`):

- `wot/tanks/<tank_id>.png` – ikony všech vozidel z oficiálního Wargaming Tankopedia API,
- `wot/resources/<klíč>.svg` – ikony měn z oficiálního stylu portálu worldoftanks.eu,
- `mff/characters/<slug>.<přípona>` – portréty z URL v `scripts/game-assets.sources.json`,
- `manifest.json` – seznam souborů a metadata vozidel z Tankopedie (aplikace bez něj ukáže záložní monogramy).

Obrázky jsou majetkem Wargaming.net, resp. Netmarble / Marvel – jen pro osobní použití, neukládat do Gitu.
