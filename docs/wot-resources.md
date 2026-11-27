# WoT zdroje z Wargaming API (MRK-105)

Kredity, zlato, volné XP a bondy na `/wot` se po propojení Wargaming účtu načítají samy: každou hodinu (scheduler)
a při otevření stránky (nejvýš 1× za 50 min). Ruční „Upravit zdroje“ zůstává jako záloha. U každé hodnoty je vidět,
odkud je („z Wargamingu“ / „ručně“) a kdy byla zapsaná.

## Jak to funguje

1. `/wot` → **Propojit s Wargamingem** → `POST /wot/account/login {origin}`. Backend ověří, že `origin` je
   v `FRONTEND_ORIGINS`, vytvoří jednorázový `state` (10 min, v paměti backendu) a vrátí adresu přihlášení
   Wargaming OpenID (`auth/login`, platnost tokenu 14 dní).
2. Po přihlášení Wargaming vrátí prohlížeč na `<origin>/wot/connect/<state>?status=ok&access_token=…&account_id=…`.
   Stránka adresu hned smaže z historie (`history.replaceState`) a parametry pošle na `POST /wot/account/connect`.
3. Backend ověří `state`, token hned vyzkouší (`account/info` → `private`; cizí nebo neplatný token = chyba) a uloží
   ho **zašifrovaný** (Fernet, klíč `WOT_TOKEN_KEY`) do tabulky `wot_account_links`.
4. Synchronizace (`wot_account_service.sync`): token, kterému zbývají < 3 dny, prodlouží (`auth/prolongate`, POST),
   načte `private.credits|gold|free_xp|bonds` a zapíše je do `wot_resources` se `source="wargaming"`. Změna = jeden
   souhrnný řádek v Aktivitě, beze změny nic.
5. Zrušené / vypršelé přihlášení (`INVALID_ACCESS_TOKEN`, nebo po `expires_at`) = stav **expired** a výzva
   „Propojit znovu“ (jeden řádek v Aktivitě). Výpadek API = stav zůstává, u propojení je vidět chyba, další běh to
   zkusí znovu. **Odpojit** = `auth/logout` (best effort) a smazání tokenu; hodnoty zůstanou.

## Bezpečnost

- Token je jen na backendu, zašifrovaný; ani záloha DB ho nemá v čitelné podobě. Bez `WOT_TOKEN_KEY` se propojení
  vůbec nenabídne (UI napíše, co na serveru chybí).
- Token se posílá Wargamingu jen v těle POST požadavku (ne v URL) na pevný host. API Hubu nevrací token ani
  `account_id`; Aktivita ani AI kontext je neobsahují. Uvicorn access log `access_token=` v URL redaguje (`***`).
- `application_id` je nutně součástí adresy přihlášení u Wargamingu (prohlížeč ji otevírá), jinak se nikam nevrací.

## Nastavení na serveru (jednou)

Proměnné v chráněném env souboru backendu (hodnoty nikdy do chatu, repa ani Linearu):

| Proměnná | Význam |
| --- | --- |
| `WG_APPLICATION_ID`, `WG_REGION` | už nastavené (MRK-106) |
| `WOT_TOKEN_KEY` | klíč pro šifrování tokenu (Fernet, 44 znaků base64). Vygenerovat a zapsat rovnou do env souboru, bez vypsání. Změna klíče = token nejde přečíst → propojit znovu. |
| `FRONTEND_ORIGINS` | už nastavené – adresa Hubu, na kterou se smí vrátit přihlášení |

Migrace `0035_wot_account_link` (aditivní: tabulka `wot_account_links`, sloupce `wot_resources.source` / `updated_at`)
se v produkci pouští ručně (`deploy-migration-v3.sh --check SHA`, pak `--apply SHA`).

## Testy

`backend/tests/test_wot_account.py` (falešný transport, žádná síť), `frontend/lib/wot.test.mjs` (`connectBody`),
UI kontrola sekce 41 v `frontend/scripts/ui-check.mjs` (mock Wargamingu v `mock-api.mjs`).
