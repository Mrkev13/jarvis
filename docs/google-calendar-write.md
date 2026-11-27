# Zápis z Hubu do Google Kalendáře – rozhodnutí a návrh (MRK-88)

Stav: **návrh k review**. Implementace patří do navazujících issues (viz konec dokumentu).
Tento dokument nic neimplementuje a nemění kód.

## 1. Výchozí stav

- Google Kalendář Hub dnes jen čte, a to přes tajnou ICS adresu (`GOOGLE_ICS_URL`, MRK-77). Adresa je jen pro čtení.
- Hub vlastní data, která v Googlu chybí: ruční rozvrh (MRK-41) a školní termíny z Moodlu (MRK-76).
- Standa chce vidět, co má Hub, i v Google Kalendáři v telefonu. Proto „bylo by dobrý i zapisovat“.

## 2. Rozhodnutí

1. **Směr: jen Hub → Google, do jednoho vyhrazeného kalendáře.** Hub si v Google účtu vytvoří vedlejší kalendář
   „Standa Hub“ a zapisuje jen do něj. Do primárního kalendáře ani do jiných kalendářů Hub nezapisuje.
2. **Rozdělení zdrojů pravdy:**
   - Vlastní události v Googlu (primární a další Standovy kalendáře) mají zdroj pravdy **Google**. Hub je dál
     čte přes ICS a nemění je.
   - Pro data Hubu (rozvrh, školní termíny) je zdrojem pravdy **Hub**. Kalendář „Standa Hub“ v Googlu
     je jen jejich **projekce**: kopie pro zobrazení, ne druhý zdroj.
3. **Úpravy přímo v Googlu se nepřebírají.** Když Standa v Googlu upraví nebo smaže událost v kalendáři
   „Standa Hub“, další synchronizace ji vrátí podle Hubu. Hub to zapíše do Aktivity („přepsáno podle Hubu“). Upravovat
   se má v Hubu. Obousměrná synchronizace se slučováním změn se **nezavádí**, protože by vytvořila dva konkurenční
   zdroje pravdy (`home-server.md` §4 bod 1).
4. **Žádná smyčka.** ICS import čte jen kalendáře, jejichž tajnou adresu má v env souboru. Adresa kalendáře
   „Standa Hub“ se do `SOURCES` nikdy nepřidává, takže se projekce do Hubu nevrátí jako duplicitní události.
   Implementace to hlídá testem: zdroj `google` nesmí obsahovat UID s doménou Hubu (viz §5).
5. **Nejužší oprávnění.** OAuth scope `https://www.googleapis.com/auth/calendar.app.created`. Aplikace s ním smí
   vytvořit vlastní vedlejší kalendáře a spravovat události jen v nich. Primární kalendář ani ostatní kalendáře
   nevidí a nemůže je změnit. Širší scope (`calendar.events`, `calendar`) se nepoužívá.

## 3. Co se zapisuje

| Data Hubu | Jak v Googlu | Fáze |
| --- | --- | --- |
| Ruční rozvrh (MRK-41, zdroj `timetable`) | Opakovaná událost s `RRULE` až do „Platí do“. Zrušená hodina se zruší jen v daném výskytu (instance `cancelled`), přesunutá hodina se uloží jako upravený výskyt. Název = předmět + druh, místo = místnost. | 1 |
| Školní termíny z Moodlu (odevzdání, zkoušky) | Jednorázová událost (celodenní nebo s časem podle zdroje). Popis jen název předmětu a odkaz do Hubu, ne obsah zadání. | 2 |
| Připomínky | **Nezapisují se** (rozhodnutí Standy, 2026-11-27). | – |
| Finance, práce, cíle, zdraví, hry | **Nezapisují se.** Finance mimo Hub nejdou (MRK-60). U ostatních to zatím není potřeba. | – |

Co se zapisuje, určuje allowlist kategorií v kódu (stejně jako `SOURCES` pro čtení). Klient posílá jen klíč
kategorie, nikdy Google ID kalendáře ani obecné API volání.

## 4. Potvrzení a audit

Zápis vždy prochází potvrzovacím tokem Hubu. Obecný nástroj „zavolej Google API“ neexistuje.

- **Zapnutí projekce kategorie** (například „rozvrh → Google“) je potvrzená akce. V UI je to přepínač s potvrzením;
  Jarvis může zapnutí jen navrhnout jako pending action (návrh → potvrzení → stale check → provedení → audit → undo
  = vypnutí). Zapnutí, vypnutí i připojení účtu se zapisují do Aktivity.
- **Průběžná synchronizace zapnuté kategorie** už jednotlivé změny znovu nepotvrzuje. Standa je potvrdil úpravou
  v Hubu (rozvrh, termín) a projekce jen kopíruje potvrzený stav. Každý běh, který něco změní, zapíše do Aktivity
  jeden souhrnný řádek (počty vytvořeno / upraveno / smazáno / přepsáno), ne obsah událostí.
- **Jarvis nedostane Google token, ID kalendáře ani odpovědi Google API.** Do kontextu jde nanejvýš stav
  („projekce rozvrhu zapnutá, poslední synchronizace v 10:05, OK“).
- **Jednorázové události do primárního kalendáře** („dej mi to do kalendáře“) nejsou ve fázi 1 ani 2. Potřebovaly by
  širší scope. Pokud budou potřeba, vznikne samostatný issue: pending action pro každou jednotlivou událost a scope
  `calendar.events` jen pro primární kalendář.

## 5. Technický návrh (pro implementační issue)

**Připojení účtu a tokeny**

- OAuth klient (Google Cloud projekt na Standův účet, typ Desktop / loopback). `GOOGLE_OAUTH_CLIENT_ID` a
  `GOOGLE_OAUTH_CLIENT_SECRET` jsou jen v chráněném env souboru backendu.
- Jednorázová autorizace serverovým skriptem (`scripts/google_calendar_authorize.py`, loopback přes SSH tunel nebo
  zkopírování kódu). Refresh token se uloží do souboru s právy `0600` v datovém adresáři backendu, **mimo DB**, aby
  nebyl v zálohách DB ani v dumpech. Frontend ani API ho nikdy nevrací. `GET /calendar` vrací jen
  `google_write: {connected, calendar_ready, last_sync_at, error}`.
- OAuth aplikace musí být ve stavu „In production“, jinak refresh token po 7 dnech vyprší (Google omezuje
  aplikace v režimu Testing). Neověřená aplikace pro jednoho uživatele stačí, jen se při autorizaci zobrazí
  varování. Při implementaci to ověřit.
- `invalid_grant` (odvolaný nebo prošlý token) → stav „odpojeno“, synchronizace se zastaví, UI ukáže
  „Znovu připojit“. Nic se tiše nezahodí.

**Mapování a idempotence**

- Nová tabulka (migrace v implementačním issue, aditivní) `calendar_google_links`: `kind`, `hub_id`,
  `google_event_id`, `content_hash`, `etag`, `synced_at`, `status` (`active` / `deleted` / `error`). Unikátní
  `(kind, hub_id)`.
- Google dovoluje vlastní ID události (znaky `a–v0–9`, 5–1024 znaků). Hub ho odvodí deterministicky z `(kind, hub_id)`
  (base32hex hash). Opakovaný pokus po výpadku tak nevytvoří duplikát: druhý `insert` vrátí `409` a Hub přejde na
  `update`.
- Každá událost nese v `extendedProperties.private` `hub_kind` a `hub_id`. Podle toho se pozná, co patří Hubu.
- Zapisuje se jen při rozdílu `content_hash` (název, čas, místo, opakování, výjimky). Rozdílný `etag` při
  nezměněném hashi znamená úpravu v Googlu → přepsání podle Hubu a řádek „přepsáno“ v Aktivitě.

**Fronta a výpadky (outbox)**

- Změny v Hubu (vytvoření, úprava, výjimka, zrušení hodiny rozvrhu nebo termínu) jdou přes doménové události.
  Kde zatím chybí, doplní je implementační issue (deklarace v `docs/domain-events.md`). Projekce je čte z `domain_events` od posledního zpracovaného ID. Vlastní fronta ani druhý zápis v transakci tak
  nejsou potřeba a událost se neztratí ani při výpadku Googlu.
- Synchronizaci spouští scheduler (např. každých 5 minut) a ruční tlačítko „Synchronizovat do Googlu“. Při chybě se
  pozice ve frontě neposune a další běh to zkusí znovu s rostoucí prodlevou. `429` / `5xx` jsou dočasné chyby.
- Výpadek Googlu = „Google nedostupný“ v UI a v Aktivitě (jen kategorie chyby, nikdy text odpovědi). Žádný falešný
  úspěch, žádné hádání.
- Jednou denně proběhne úplné porovnání (list událostí kalendáře „Standa Hub“ proti Hubu). Opraví ruční zásahy
  v Googlu a smaže události, které v Hubu už nejsou.

**Mazání**

- Zrušení nebo smazání v Hubu → `events.delete` v Googlu, odkaz `status=deleted`.
- Vypnutí kategorie → smažou se všechny její události v kalendáři „Standa Hub“ (potvrzená akce s počtem v textu
  potvrzení). Kalendář jako celek se nemaže.
- Odpojení účtu → Hub zapomene token. Kalendář „Standa Hub“ v Googlu zůstane a Standa ho může smazat ručně.

**Testy**

- Fake Google klient v `tests/fakes.py`. Žádná síť (pytest-socket), fake hodiny.
- Testy pokrývají: idempotentní ID, retry po výpadku bez duplikátů, přepsání ruční úpravy, výjimky rozvrhu jako
  instance, smazání, `invalid_grant`, absenci tokenu v odpovědích API i v logu, a že ICS import nepřevezme
  události s doménou Hubu.

## 6. Úprava tabulky zdrojů pravdy

Řádek „Kalendář a školní plánování“ v `docs/home-server.md` §3 se mění tímto PR (architektonické rozhodnutí,
review). Viz diff v `home-server.md`.

## 7. Navazující issues (založit po schválení tohoto PR)

1. **Google Calendar: připojení účtu a vyhrazený kalendář.** OAuth skript, uložení tokenu mimo DB, vytvoření
   kalendáře „Standa Hub“, stav v `GET /calendar` a v UI, odpojení. Bez zápisu událostí.
2. **Google Calendar: projekce rozvrhu (fáze 1).** Migrace `calendar_google_links`, synchronizace z doménových
   událostí, scheduler, denní porovnání, potvrzené zapnutí a vypnutí, Aktivita.
3. **Google Calendar: školní termíny (fáze 2).**
4. *(Jen pokud bude potřeba)* Jednorázová událost do primárního kalendáře přes pending action a širší scope.

## 8. Rozhodnutí Standy (2026-11-27)

- Název kalendáře: na názvu nezáleží, zůstává „Standa Hub“ (barva výchozí).
- Do Googlu jde **jen rozvrh a školní termíny**. Připomínky ne.
- Upozornění v Googlu: **žádná** (události se zakládají bez `reminders`, `useDefault: false`).
