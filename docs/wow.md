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
  10 s, odpověď max 512 KB; token jen v paměti procesu.
- Chyby nesou jen kód (`not_found`, `unauthorized`, `rate_limited`, `unavailable`, `invalid_response`), nikdy URL,
  token ani odpověď serveru. Do DB se ukládají jen známá pole (bez surového JSON).
- AI do WoW nezapisuje (jen čte snapshot v kontextu).

## Navazuje

MRK-128 – mounty, pety, achievementy a seznam „chci získat“. Endpointy kolekcí má jen retail API; pro Classic
namespace se krok zúží (rozhodne výstup `check_battlenet.py`).
