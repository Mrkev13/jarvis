# World of Warcraft (MRK-127)

Přehled altů z Blizzard Battle.net API: level, třída, rasa, frakce, spec, item level (kde ho verze hry nabízí),
profese a postup k cílovému levelu. Modul `wow` (`backend/modules/wow/`, `frontend/modules/wow/`, stránka `/wow`
ve skupině „Další“). Data jsou **snapshot** – Hub API jen čte, ve hře nic nemění.

## Jak to funguje

- Standa přidá postavu (jméno + realm, volitelně cílový level). Hub ji hned načte z API.
- **WoW Forever (MRK-130)** nemá realmy (jeden megaserver, rozdělený jen podle pravidel). Postava = **jméno +
  příjmení** („Zareth Malgrave“, API cesta `/profile/wow/character/zareth-malgrave`, namespace `profile-forever-eu`).
  V DB `realm_slug = "forever"`, místo realmu se ukáže `Forever · <ruleset>` z API. Při `WOW_NAMESPACE=profile-forever-…`
  formulář pole Realm skryje. Blizzard Forever postavu ukáže až od levelu 10 a po odhlášení ze hry (do té doby 404).
  Jméno + příjmení dohromady nejvýš 23 písmen (sloupec `name_key` má 24 znaků, bez migrace).
- Hodinový krok (`ScheduledStep "wow character sync"`) obnoví postavu nejvýš jednou za 6 h a nejvýš 10 postav za běh;
  na 401/429 dávku ukončí. Tlačítka *Obnovit* / *Obnovit vše* načtou hned.
- Výpadek API nechá poslední známý stav (`sync_status` `error` / `not_found`, text u postavy).
- Vyšší level = doménová událost `wow.character.level_up` (Aktivita, Co se změnilo) a přepočet automatických cílů.
- Cíle (automatické zdroje, deterministicky ze snapshotu): `wow_characters_at_target` (postavy na cílovém levelu),
  `wow_max_level` (nejvyšší level).
- Vyhledávání: postavy (`/wow?wowchar=<id>`); AI kontext: krátký seznam „jméno třída lvl X/cíl“ (žádné API volání).

## Hrdinské karty (MRK-139)

- Synchronizace načte i `character-media` (avatar + celý render, migrace `0032_wow_character_media`). Ukládají se
  jen URL z oficiálních hostů `render(-eu|-us|-kr|-tw).worldofwarcraft.com` (https, bez query); výpadek obrázků
  synchronizaci neshodí a nechá poslední známé. Obrázky nejsou změna snapshotu pro Aktivitu.
- Karta: render vpravo jako vrstva pozadí, barva třídy (oficiální barvy), tónování frakce, prstenec levelu
  s avatarem; nahoře „flotila“ avatarů. Prohlížeč načítá obrázky přímo z CDN Blizzardu bez referreru.

## Sbírka a „chci získat“ (MRK-128)

- Hodinový krok (po postavách, nejvýš jednou za 6 h; *Obnovit vše* / *Obnovit sbírku* hned) načte přes postavu
  s nejvyšším levelem a stavem `ok` tři endpointy: `collections/mounts`, `collections/pets` a `achievements`
  (mounti, pets i body jsou účtové). Uloží **denní snapshot** počtů (`wow_collection_snapshots`, jeden řádek na den
  v Europe/Prague, migrace `0033_wow_collections`). Výpadek jednoho endpointu nechá u jeho čísla poslední stav.
  Seznam achievementů retail účtu má jednotky MB → limit odpovědi pro sbírky 8 MB (profil dál 512 KB).
- Vývoj: „za týden“ = poslední snapshot proti stavu před 7 dny (nebo nejstaršímu), sparkline za 30 dní.
  Achievementy = jen dokončené (`completed_timestamp`).
- **Chci získat** (`wow_wishes`): mount / mazlíček / achievement, název anglicky jak ho píše hra. Shoda bez velikosti
  písmen, s jednou mezerou a rovnými apostrofy. Když ho API ukáže, položka se odškrtne sama → doménová událost
  `wow.collection.acquired` (Aktivita, Co se změnilo, „Mise splněna“). Položka, kterou už máš, se při přidání
  odškrtne hned (jeden dotaz na API) a bez události.
- Cíle: `wow_mounts`, `wow_pets`, `wow_achievement_points` (poslední snapshot; bez snapshotu = neznámá hodnota).
- Řídicí centrum: karta Hry má blok WoW (mounti a body s týdenní změnou, počet přání). Vyhledávání:
  `/wow?wowwish=<id>`; AI kontext: počty s trendem a otevřená přání (bez API).

## Konfigurace (jen server, `.env.production`)

| Proměnná | Význam |
| --- | --- |
| `BATTLENET_CLIENT_ID`, `BATTLENET_CLIENT_SECRET` | API client z develop.battle.net (client credentials, zdarma) |
| `WOW_REGION` | `eu` (výchozí), `us`, `kr`, `tw` |
| `WOW_NAMESPACE` | verze hry: retail `profile-eu`; Classic např. `profile-classic1x-eu` (Era), `profile-classicann-eu`; WoW Forever `profile-forever-eu` |
| `WOW_LOCALE` | výchozí `en_GB` (Blizzard češtinu nemá) |

Bez klíčů modul funguje (postavy jdou přidat), jen nic nenačte a stránka ukáže návod. Neplatný region/namespace =
jako bez klíčů (`config.configured=false`).

**Který namespace?** Na serveru (v backend kontejneru):

```bash
sudo docker exec -it standa-hub-backend python scripts/check_battlenet.py --realm "<realm>" --name "<postava>"
sudo docker exec -it standa-hub-backend python scripts/check_battlenet.py --name "<Jméno Příjmení>"   # WoW Forever
```

Vypíše jen stavy – token, pro každý kandidátní namespace HTTP stav postavy, dostupná pole, profese, mounty,
achievementy – a `DOPORUČENÍ: WOW_NAMESPACE=…`. Nikdy klíče, token, jméno ani realm. Po změně `.env.production`
restart přes `restart-v3.sh` (deploy/v3/README.md).

## Bezpečnost

- HTTPS jen na pevné hosty Blizzardu (`oauth.battle.net`, `<region>.api.blizzard.com`), bez přesměrování, timeout
  10 s, odpověď max 512 KB (sbírky 8 MB); token jen v paměti procesu.
- Chyby nesou jen kód (`not_found`, `unauthorized`, `rate_limited`, `unavailable`, `invalid_response`), nikdy URL,
  token ani odpověď serveru. Do DB se ukládají jen známá pole (bez surového JSON).
- AI do WoW nezapisuje (jen čte snapshot v kontextu).

## Navazuje

Sbírka je hotová (MRK-128). Classic namespace, který endpointy sbírek nemá, uloží snapshot jen z těch, které
odpoví; když nedá nic, stav je `unavailable` a stránka ukáže prázdnou sbírku.
