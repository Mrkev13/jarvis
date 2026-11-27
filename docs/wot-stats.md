# WoT statistiky po bitvách (MRK-153)

Statistiky bitev, hodnocení a zdrojů v čase – automaticky z Wargaming API, bez replaye. Stránka `/wot/stats`,
na přehledu `/wot` karta „Dnes ve WoT“.

## Odkud data jsou

| Co | Zdroj | Kdy se ukládá |
| --- | --- | --- |
| Bitvy, výhry, damage, zničení, XP, přežití po tancích | `tanks/stats` (`all.*`, kumulativní) | hodinová synchronizace M-ek (`wot_mastery_service.sync`), řádek jen u tanku se změněným počtem bitev |
| Osobní hodnocení Wargamingu | `account/info.global_rating` (veřejné) | tamtéž, jen při změně |
| Kredity, zlato, Free XP, bondy | propojený účet (MRK-105) | synchronizace zdrojů (`wot_account_service.sync`), jen při změně |

Tabulky `wot_tank_snapshots` a `wot_account_snapshots` (migrace `0036_wot_stats_snapshots`, aditivní).

## Jak se počítá

- Období: dnes / 3 dny / týden / měsíc / půl roku (od pražské půlnoci prvního dne) a celkově.
- Odehrané bitvy za období = rozdíl kumulativních součtů tanku teď a na začátku období (stav v čase t = poslední
  snímek ≤ t). Tank zachycený už první synchronizací má první snímek jako základ (nic z dřívějška se nepřipisuje);
  tank, který přibyl později, začíná od nuly.
- „Celkově“ = poslední snímky všech tanků = celkové statistiky účtu.
- `partial` = Hub začal ukládat až po začátku období – UI to přizná („ukládá od …“). Období se plní postupně.
- Nejlepší tank = nejvyšší průměrný damage mezi tanky s aspoň 3 bitvami za období.
- AI kontext WoT dostane jen výsledek: „WoT dnes / týden: N bitev, výhry X %, průměrný damage Y“.

## Grafy

Jedna veličina = jeden graf (různá měřítka, nikdy dvě osy): hodnocení, každá měna zvlášť (schodovitá čára – stav se
mění skokem při synchronizaci), bitvy po dnech (sloupce). Jedna barva řady (`#d28e05`, dataviz validace na
tmavém povrchu), tooltip při najetí / dotyku, tabulka pod každým grafem.

## Později

WN8 – Wargaming API ho nedává; potřebuje komunitní tabulku očekávaných hodnot (samostatný issue).
