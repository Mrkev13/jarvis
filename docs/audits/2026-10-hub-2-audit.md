# Hub 2.0 audit – skutečný stav, nedostatky a plán (MRK-69)

**Typ:** čistě čtecí audit, žádná změna kódu, migrace ani dat. **Groq count: 0.**
**Základ:** `origin/main` @ `e9ce037` (2026-10-21), audit proveden 2026-10-25. Alembic head `0025_finance_ledger`.
**Navazuje na:** [architecture-audit.md](../architecture-audit.md) (Roadmap 3.5, nálezy F/R/L). Ty se zde neopakují;
připomínají se jen tam, kde jsou pořád otevřené a mají dopad na Hub 2.0.

Jak číst odkazy: `soubor:řádek` platí pro `e9ce037`. Co je odhad, je označené **(domněnka)**. Co nejde ověřit bez
reálných dat nebo zařízení, je označené **(ověřit lokálně)**.

---

## 1. Shrnutí

**Doporučený scope jednou větou:** nejdřív Hub zpevnit a zpřístupnit 24/7 i bez PC, pak přivést termíny testů do
Školy a Dnes a nakonec z Řídicího centra udělat jedinou denní obrazovku se zúženou navigací – bez nových modulů.

10 nejdůležitějších zjištění:

1. **Hub je dostupný jen při zapnutém Windows PC (blokující).** Produkční runtime je čistě Windows (Task Scheduler +
   PowerShell, `scripts/windows/register-tasks.ps1:112-129`, `docs/operations.md:3-4`); Linux služba, systemd unit
   ani Docker neexistují. Raspberry Pi 3B je změřeně proveditelný jen s předem sestaveným frontendem (Z1, příloha D).
2. **CI na `main` je od 2026-10-23 červené pro každý nový PR.** Dva testy studijních materiálů závisí na skutečných
   hodinách (`backend/modules/school/integrations.py:56` bere `utc_now()` místo času z požadavku). Reprodukováno,
   zablokuje i Finance v1 PR (Z2).
3. **Moodle události nejsou svázané s předměty.** Parser nečte `CATEGORIES` (`backend/modules/calendar/parser.py:102-167`),
   události nemají vazbu na předmět a Termíny ve Škole berou jen ručně zadané úkoly a zkoušky
   (`backend/school_integrations.py:150-210`). Proto „není vidět, kdy je test" (Z3).
4. **Hranice „Finance mimo AI" má tři úzké díry (bez částek).** Snapshoty automatických finančních cílů se logují jako
   oblast `goals` (`backend/modules/finance/service.py:290`) a projdou filtrem AI aktivity
   (`backend/read_queries.py:234-237`); planner finanční cíle nefiltruje (`backend/planner_service.py:132-206`) a jeho
   odpověď se ukládá do historie chatu; `upsert_goal` smí měnit finanční cíl (Z6).
5. **Potvrzená AI úprava cíle maže nezadaná pole.** `upsert_goal` s `id` přepíše popis, stav, prioritu, progres
   a termín výchozími hodnotami (`backend/tools.py:806-841`) a karta potvrzení neukazuje diff (Z4).
6. **Předměty nejdou upravit ani archivovat.** Existuje jen `GET /school/subjects` a `POST /school/subject`
   (`backend/main.py:1468,1472`); sloupec `Subject.active` používá jen Rychlé přidání (`backend/school_integrations.py:259`) (Z5).
7. **Tři překrývající se „denní" obrazovky, žádná neukazuje vše podstatné.** Řídicí centrum nemá „co hoří", změny ani
   další volný blok; Dnes je má, ale nikdo ho neotevírá; `recent_activity` v `/dashboard` frontend vůbec nečte; výchozí pořadí dává nahoru nepoužívané Klíčová čísla (Z8, Z28).
8. **Navigace má 19 plochých položek a žádný způsob „schovat, ale nechat zapnuté"** (`frontend/lib/navigation.ts:11-37`,
   `frontend/components/Sidebar.tsx:26-60`) (Z9).
9. **Opakovaná připomínka může přijít potichu.** Tag oznámení je na připomínku, ne na výskyt
   (`backend/delivery_service.py:271`), a service worker nepoužívá `renotify` ani `requireInteraction`
   (`frontend/public/sw.js:15-21`) (Z10).
10. **AI vrstva je bezpečná na zápis (vše přes potvrzení), ale má mezery ve spolehlivosti:** falešná shoda „test" → Škola
    (`backend/school_integrations.py:406`, follow-up #1 stále otevřený), read tooly se při provedení nekontrolují proti
    route ani modulu (`backend/ai.py:430-440`), osiřelé pending akce po chybě a chybějící `max_tokens` (Z11, Z12, Z16, Z17).

---

## 2. Matice stavu

Legenda: ✅ funguje · 🟡 částečně · ❌ chybí. „Testy" = backend `backend/tests/` / frontend `*.test.mjs`.

### 2.1 Moduly

| Modul | Backend | Frontend (390 px, stavy) | Integrace (Search / Today / Dashboard / Quick Add / AI / události / Změny) | Testy | Stav |
|---|---|---|---|---|---|
| **Škola** | 🟡 úkoly a zkoušky mají complete/reopen/delete (`backend/main.py:2890-2950`), výsledek zkoušky (`backend/school_service.py:124-145`); **předměty jen GET/POST** (`backend/main.py:1468,1472`) | ✅ `/school` (1084 ř.), stavy OK | Search ✅, Today ✅, Dashboard „upcoming" ✅, Quick Add ✅ exam/assignment, AI ✅ (kontext + tooly), události ✅ `school.assignment.*`/`school.exam.*` | ✅ 14+ testů (`test_school_completion.py`) | 🟡 |
| Škola – studijní materiály | ✅ WS sync, ZIP import (MRK-56), čtení (MRK-44) (`backend/modules/school/router.py:53,59`, `reading.py`) | ✅ `/school/materials` | Search ✅, AI tooly ✅ s gate (`backend/tool_registry.py:120-132`), události ✅ | ✅ 71 testů; **2 padají** (Z2) | 🟡 (reálný ČZU Moodle neověřen – MRK-43) |
| **Kalendář** | 🟡 ICS import, výskyty, volné bloky, týdenní pohled; **jen 1 zdroj (Moodle)** (`backend/modules/calendar/service.py:30-32,196-215`) | ✅ `/calendar` + `WeekView.tsx` | Today ✅ timeline + další volný blok, Search ✅, AI kontext ✅, Změny ✅; **Dashboard ❌** | ✅ 65+ testů | 🟡 |
| **Cíle** | ✅ ruční + automatické zdroje (13 klíčů, `backend/goal_history_service.py:31-126`); **žádný WoT zdroj** | ✅ `/goals`; UI nabízí jen 10 z 13 zdrojů (`frontend/lib/goals.ts:22-33`) | Dashboard ✅, AI ✅, Planner ✅ | 🟡 jen 3 testy automatiky (`test_goals_automatic_v2.py`) | 🟡 |
| **WoT** | ✅ grindy, zdroje, M-ka (víc záznamů na tank, `backend/models.py:259-283`), replaye | ✅ `/wot`, „Přidat Mko" (`frontend/app/wot/page.tsx:501`) | Search ✅, Dashboard „games" ✅; Today ❌ (bez capability, `backend/module_registry.py:120-125`) | ✅ 62 testů | 🟡 (chybí počítadlo M-ek) |
| **Návyky** | ✅ (`backend/modules/habits/`) | ✅ `/habits` | Today ✅, Dashboard widget skrytý ve výchozím stavu (`frontend/modules/habits/manifest.ts:33`) | ✅ 15 testů | ✅ |
| **Fitness & Rehab** | ✅ cviky, tréninky, rehab, archivace cviků (`backend/modules/fitness/service.py:96-101`) | 🟡 zápis řádek po řádku, bez šablon (`frontend/modules/fitness/SessionForm.tsx:34-51`) | Search ✅, Today ✅ | ✅ 13 testů | 🟡 (nepoužíváno) |
| **MFF** | ✅ CRUD postav | ✅ `/mff` | Search ✅, Dashboard ✅, AI ✅ | ✅ 15 testů | ✅ (nepoužíváno) |
| **Práce** | 🟡 jen GET/POST/DELETE, úprava jen přes AI (`backend/mutation_service.py:254`) | ✅ `/work` | Dashboard ✅, AI ✅, Quick Add ✅ | 🟡 bez vlastního souboru | 🟡 (nepoužíváno) |
| **Finance** | 🟡 legacy + Finance v1 backend (MRK-60…63 hotové, import core + mBank GPC, `backend/modules/finance/router.py:16-69`) | 🟡 `/finance` jede na legacy API (`frontend/app/finance/page.tsx:63-64`); import UI chybí (MRK-64) | Mimo AI ✅ (s výhradami Z6); Search/Změny pro nový ledger chybí (MRK-66) | ✅ 47 testů backend, 0 frontend | 🟡 (milník běží) |

### 2.2 Jádrové plochy

| Plocha | Stav | Důkaz |
|---|---|---|
| Řídicí centrum (`/`) | 🟡 rozložení upravitelné, ale jen v `localStorage` zařízení (Z28); widgety: briefing, weekly, „Dnes" (= jen 3 akce planneru), pozornost (= jen notifikace), cíle, upcoming, hry, rychlé akce; **chybí co hoří / změny / volný blok / kalendář** | `frontend/lib/dashboardLayout.ts:63-74`, `frontend/components/dashboard/widgets.tsx:364-391`, `backend/main.py:2460-2527` |
| Dnes (`/today`) | ✅ timeline (připomínky, škola, návyky, fitness, kalendář, další volný blok), pozornost (max 8), priority, nadcházející (max 3) | `backend/today_service.py:33-34,231-276` |
| Týdenní přehled (`/review`) | ✅ AI shrnutí týdne nad deterministickým snapshotem | `backend/weekly_snapshot.py:44-52` |
| Plánovač (`/planner`) | 🟡 max 5 akcí z termínů a stagnace cílů; bez opakování a závislostí; **neřeší dostupnost modulů** | `backend/planner_service.py:415-416`, `backend/main.py:2304-2311` |
| Připomínky | ✅ jednorázové/denní/týdenní, push | `backend/reminder_service.py:38,87-120` |
| Push (PWA) | 🟡 řetězec funguje end-to-end, oznámení se snadno přehlédne | `backend/scheduler_service.py:117-124`, `backend/delivery_service.py:271`, `frontend/public/sw.js:15-21` |
| Paměť | 🟡 CRUD + výběr do promptu (max 3 × 140 znaků); bez expirace a dedupe; hledání vidí jen 79 znaků | `backend/context_service.py:35-36,135-150`, `backend/core_integrations.py:49-55` |
| AI chat | 🟡 bezpečné zápisy, mezery ve spolehlivosti (Z11, Z12, Z16, Z17) | příloha A, B1 |
| Search (Ctrl+K) | 🟡 funguje, ale v Pythonu nad ~500 řádky na zdroj, bez filtru a rychlých akcí | `backend/search_service.py:26-28,72-112` |
| Co se změnilo (`/changes`) | ✅ bez technického šumu, deduplikované události | `backend/change_feed.py:87-164` |
| Aktivita (`/activity`) | ✅ technický log (záměrně) | `backend/main.py:2575-2641` |
| Nastavení | 🟡 jen zapínání modulů; žádná diagnostika ani návod k oznámením | `frontend/app/settings/page.tsx:7-13` |
| Provoz (`/health`, zálohy) | ✅ health, lokální + off-site zálohy; ❌ Linux runtime | `backend/health_service.py:36-93`, `docs/offsite-backups.md` |

### 2.3 Ověření v tomto auditu

| Kontrola | Výsledek |
|---|---|
| Backend `pytest backend/tests` (SQLite, bez sítě) | **2 failed**, 1248 passed, 10 skipped (Z2) |
| `pyflakes` | čisté |
| Frontend `npm test` / `lint` / `tsc` / `next build` | 389 pass / 0 chyb (3 starší varování) / OK / OK (22 s) |
| Hosted CI na `main` (`e9ce037`, 2026-10-21) | zelené – ještě před „výbuchem" testů 2026-10-23 |
| Měření paměti (x86_64, prázdná DB) | backend 140 MB RSS, `next-server` 133 MB RSS, špička `next build` 1,34 GB |

---

## 3. Zjištění

Závažnost: **blokující** (bez toho nemá smysl ladit další) · **vysoká** · **střední** · **nízká**.

| # | Závažnost | Zjištění | Důkaz | Reprodukce | Dopad |
|---|---|---|---|---|---|
| Z1 | **blokující** | Produkční běh jen na Windows PC; žádný Linux runtime, frontend bez `output: 'standalone'`, auth brána běží v Node (`proxy.ts`) | `scripts/windows/register-tasks.ps1:112-129`, `docs/operations.md:3-4`, `frontend/next.config.ts:3-25`, `frontend/proxy.ts:14`, `backend/AGENTS.md:370` (zmiňuje systemd, unit neexistuje) | vypnout PC → Hub z telefonu ve škole nedostupný | Priorita 1 z používání; bez ní se Hub mimo domov nepoužívá |
| Z2 | **vysoká** | Dva testy padají podle reálného data: `context_materials` počítá okno „14 dní" z `utc_now()`, testy mají pevné `NOW = 2026-10-09` | `backend/modules/school/integrations.py:56`, `backend/tests/test_study_materials.py:24` | `pytest backend/tests/test_study_material_reading.py::test_ai_context_lists_ids_but_never_text` → fail; s `utc_now` posunutým na 2026-10-10 projde (ověřeno) | každý nový PR (i Finance v1 MRK-64) bude mít červené CI; porušuje pravidlo „fake hodiny" (`AGENTS.md`) |
| Z3 | **vysoká** | Moodle ICS události nemají vazbu na kurz/předmět; `CATEGORIES` se neparsuje; Termíny Školy a „co hoří" je neukazují | `backend/modules/calendar/parser.py:102-167`, `backend/modules/calendar/models.py:56-80`, `backend/school_integrations.py:150-210` | importovaný „ZKOUŠKOVÝ TEST …" je jen v Kalendáři, ne u předmětu ve Škole | Priorita 2 z používání |
| Z4 | **vysoká** | `upsert_goal` s `id` přepíše nezadaná pole výchozími hodnotami; potvrzovací karta ukazuje jen argumenty | `backend/tools.py:806-841`, `backend/tool_registry.py:372-386` | AI: „posuň termín cíle X na 1. 12." → po potvrzení `description=""`, `status=active`, `progress=0` | tichá ztráta dat po potvrzené akci (porušení P9/„stale check") |
| Z5 | **vysoká** | Předměty nejdou upravit ani archivovat; `active` se používá jen v Rychlém přidání | `backend/main.py:1468,1472`, `backend/school_integrations.py:259`, `backend/models.py:338-346` | v UI ani API není akce „archivovat předmět" | staré předměty zaplevelují výběry, mapování kurzů a Rychlé přidání; vstup z používání |
| Z6 | **střední** | Hranice MRK-60: (a) snapshot finančního cíle se loguje jako `area=goals` → projde do `get_recent_activity`; (b) planner nefiltruje finanční cíle a jeho text se ukládá do historie chatu; (c) `upsert_goal` nekontroluje `is_finance_goal` a schéma povoluje `area=finance` | (a) `backend/modules/finance/service.py:290`, `backend/tools.py:257-270`, filtr `backend/read_queries.py:234-237`; (b) `backend/planner_service.py:132-206` (žádné `is_finance_goal`), `backend/main.py:631-635`; (c) `backend/tools.py:823-845`, `backend/tool_registry.py:377` | automatický cíl se zdrojem `finance_balance` → „Cíl 'Úspory' 40% → 45%" v AI read toolu aktivity | do LLM se dostane název a % finančního cíle (ne částky); `docs/finance.md:19` slibuje opak |
| Z7 | **střední** | Kalendář podporuje jen jeden ICS zdroj (`config_key='moodle'`); Google Kalendář přes soukromé ICS nejde přidat | `backend/modules/calendar/service.py:30-32,196-215,264-268`, `backend/modules/calendar/router.py:74-76`, `frontend/modules/calendar/CalendarPage.tsx:40,46` | není kam zadat druhou ICS adresu | Kalendář se nepoužívá (vstup z používání) |
| Z8 | **střední** | Řídicí centrum / Dnes / Týdenní přehled se překrývají; hlavní obrazovka nemá „co hoří", „co se změnilo", „další volný blok" ani kalendář; `recent_activity` je mrtvý payload | `frontend/lib/dashboardLayout.ts:63-74`, `frontend/components/dashboard/widgets.tsx:364-391`, `backend/main.py:2460-2527` (grep `recent_activity` ve `frontend/` = 0) | otevřít `/` vs `/today` | Dnes a Týdenní přehled se neotevírají; uživatel nevidí to podstatné |
| Z9 | **střední** | 19 plochých položek navigace, desktop i mobil stejné; flag modulu vypne celý modul, neexistuje skupina „Systém" ani „schovat z navigace" | `frontend/lib/navigation.ts:11-37`, `frontend/components/Sidebar.tsx:26-60,147`, `frontend/lib/modules.ts:190-197` | otevřít menu na 390 px | přeplněná navigace (vstup z používání) |
| Z10 | **střední** | Tag push oznámení je na připomínku (`standa-reminder-{id}`), ne na výskyt; bez `renotify` se nový výskyt nahradí potichu; bez `requireInteraction` a akčních tlačítek | `backend/delivery_service.py:269-271`, `frontend/public/sw.js:15-21` | denní připomínka, včerejší oznámení zůstalo v liště → dnešní přijde bez zvuku **(domněnka dle Notification API, ověřit lokálně na Androidu)** | připomínka se přehlédne (Priorita 3) |
| Z11 | **střední** | Routing toolů: podřetězec `"test"` (i `termin`, `ukol`) označí Školu; follow-up #1 stále otevřený; obchází i MRK-60 pravidlo „nenahrazuj finance zápis jiným" | `backend/school_integrations.py:406`, `docs/follow-ups.md:6-16`, `backend/tool_router.py:245` | „přidej výdaj 100 Kč za smoke test" → explicitní oblasti {finance, school} → nabídnuty školní write tooly | zbytečné tokeny, riziko špatného zápisu (pořád s potvrzením) |
| Z12 | **střední** | Read tooly se při provedení nekontrolují proti route ani dostupnosti modulu (výjimka: studijní materiály) | `backend/ai.py:362-363,430-440`, `backend/tool_registry.py:120-132` | model zavolá read tool vypnutého modulu, který nebyl v requestu → provede se | spoléhá na chování Groqu; jiný provider by mohl číst data vypnutého modulu |
| Z13 | **střední** | Limit pokusů o PIN je klíčovaný hlavičkou `X-Forwarded-For` bez ověření proxy | `backend/main.py:296-302`, `backend/auth_service.py:73-99` | střídat `X-Forwarded-For` → limit se neuplatní | brute-force PIN z tailnetu; po přesunu na Pi/notebook zůstává |
| Z14 | **střední** | Search: ~17 zdrojů × až 500 řádků do Pythonu na každý dotaz (debounce 180 ms); paměť se hledá jen v prvních 79 znacích; některé zdroje berou 500 řádků bez `order_by` | `backend/search_service.py:72-112`, `backend/core_integrations.py:49-55`, `frontend/hooks/useGlobalSearch.ts:18` | uložit paměť s klíčovým slovem za 80. znakem → Ctrl+K ho nenajde | chybějící výsledky, zátěž na Pi |
| Z15 | **střední** | WoT nemá počítadlo M-ek ani souhrn po tancích; Cíle nemají WoT automatický zdroj | `backend/wot_service.py:256-260`, `backend/goal_history_service.py:31-126` | cíl „50 M-ek" nejde napojit | ruční progres (vstup z používání) |
| Z16 | **střední** | Po chybě v N-tém kole chatu zůstanou pending akce z dřívějších kol v DB (potvrditelné 30 min), frontend je smaže z obrazovky | `backend/main.py:685-706`, `frontend/hooks/useAiChat.ts:138,166-167` | Groq výpadek ve 2. kole po návrhu v 1. kole | uživatel neví o existujícím návrhu |
| Z17 | **střední** | Hlavní chat volání nemá `max_tokens`; až 10 kol toolů na dotaz | `backend/ai.py:742-752` | – | nepředvídatelná spotřeba denního limitu Groqu |
| Z18 | **střední** | Upload screenshotu/replaye načte celé tělo (`await request.body()`) – limit kontroluje jen deklarovaný `Content-Length` | `backend/main.py:1229-1236,1342` | chunked upload bez `Content-Length` | paměťová špička; na 1 GB RAM riziko OOM |
| Z19 | **střední** | Dnes a timeline načítají všechny připomínky včetně všech hotových v historii | `backend/core_integrations.py:75` | – | roste navždy; zpomalí `/today` na Pi |
| Z20 | nízká | Briefing, weekly snapshot a `/planner` neřeší dostupnost modulů | `backend/main.py:2304-2311` (bez `access`), `backend/briefing_snapshot.py`, `backend/weekly_snapshot.py` (grep `access` = 0) | vypnout modul → planner ho dál navrhuje | nekonzistence s Dashboardem (`backend/main.py:2468` filtruje) |
| Z21 | nízká | Pozorovatelnost: access log uvicornu loguje `?q=` dotazy; pod Task Schedulerem se stdout nikam neukládá; AI latence/chyby jen do stdout, bez historie; žádná diagnostika v UI | `backend/production.py:153-154`, `docs/operations.md:244-252`, `backend/llm_usage.py:1-16`, `docs/monitoring.md:66-68` | – | po chybě není z čeho zjistit příčinu |
| Z22 | nízká | Nepoužívané endpointy: L10 (`GET /ai/confirm/{id}`, `POST /ai/execute`) a dále `/pending` (filtr více stavů nikdy nic nevrátí), `/mff/role-options`, `/push/status` | `backend/main.py:933,962,2675-2685,1736,2208` | grep cest ve `frontend/` = 0 | mrtvý kód, matoucí API |
| Z23 | nízká | Dokumentace neodpovídá kódu: `AGENTS.md:52` uvádí 3 ui-check skripty (je jich 7); tabulka migrací v `backend/AGENTS.md:80-90` končí `0008`; `docs/monitoring.md:12-13` tvrdí, že `/health` chybí | viz odkazy | – | agenti a Standa pracují s neaktuálním obrazem |
| Z24 | nízká | Paměť bez dedupe a bez expirace/druhu (trvalé vs. dočasné vs. rozhodnutí) | `backend/models.py:203-221`, `backend/tools.py:1218-1250` | uložit stejnou paměť 2× | šum v promptu (max 3 položky) |
| Z25 | nízká | Fitness/Rehab zápis po jednotlivých sériích, bez šablon a „zopakovat minulý trénink" | `frontend/modules/fitness/SessionForm.tsx:34-51`, `docs/fitness.md:38` | zapsat 6 rehab cviků | modul se nepoužívá |
| Z26 | nízká | UI cílů nenabízí 3 existující automatické zdroje (`work_total_hours`, `finance_total_balance`, `school_exams_passed`); `GoalRequest.source` bez allowlistu | `frontend/lib/goals.ts:22-33`, `backend/main.py:388-399` | – | nekonzistence |
| Z28 | střední | Řídicí centrum ve výchozím pořadí dává nahoru nepoužívané karty (Klíčová čísla = Odpracováno, Výdělek, Bilance, Výdaje, pořadí 50) před Cíle (60), Nadcházející (70) a Hry (100); vlastní rozložení se ukládá jen do `localStorage` jednoho zařízení | `frontend/lib/dashboardLayout.ts:64-74,89`, `frontend/hooks/useDashboardLayout.ts:17,33,64` | otevřít `/` na telefonu po úpravě rozložení na PC → výchozí pořadí | více než polovina obrazovky jsou nepoužívané oblasti (vstup z používání); úpravu je nutné dělat na každém zařízení zvlášť |
| Z27 | nízká | Chybí bezpečná cesta pro jednorázové souhrnné dotazy nad produkcí (statistiky ze vstupu) | žádný read-only endpoint/skript; `/scheduler/*`, `/backup/*` jsou provozní (`backend/main.py:2705-2741`) | – | statistiky používání nejdou získat bez změny ACL env souboru |

**Ověřené hranice (bez porušení):**

- **AI zápisy jen s potvrzením:** každý WRITE tool jde přes `prepare_write_action` (`backend/ai.py:391-428`), provedení
  jen v `execute_confirm_action` s atomickým claimem (`backend/ai.py:191-226`), stale check a undo
  (`backend/mutation_service.py:686-690,725`). Finance zápis z AI je odmítnut (`backend/ai.py:893`). Jediný zápis bez
  potvrzení je interní souhrn konverzace (`backend/history_service.py:115-117`).
- **Finance mimo AI** v promptu, kontextu, toolech, briefingu a weekly: ověřeno (`backend/ai.py:55`,
  `backend/module_registry.py:110-115`, `backend/read_queries.py:209`, `backend/briefing_snapshot.py:237`,
  `backend/weekly_snapshot.py:434`). LLM logy obsahují jen čísla (`backend/llm_usage.py:69-135`). Výjimky viz Z6.
- **Zdroje pravdy** (`docs/home-server.md` §3): nic v kódu nestaví druhé úložiště dokumentů, receptů ani zařízení.
  Návrhy v tomto auditu je také nestaví (Google Kalendář jen read-only ICS, Kalendář zůstává Hub + upstream importy).
- **Auth na všech routách:** globální `require_auth` (`backend/main.py:252-262,277-280`), routery modulů ho dědí
  (`backend/main.py:292-295`); veřejné jen `/`, `/health`, `/auth/*` (`backend/main.py:249`).

---

## 4. Navržený scope

**Must = 4 vrstvy** (horní hranice zadání). Vše v existujících modulech, žádný nový modul.

### Must

| Vrstva | Položka | Přínos | Náročnost | Závislosti | Riziko | Linear |
|---|---|---|---|---|---|---|
| **M1 Stabilní základ** | M1.1 Opravit testy závislé na hodinách (Z2) | CI zase zelené pro všechny PR | S | – | nízké | nový |
| | M1.2 Uzavřít díry MRK-60 (Z6) | hranice Finance dodržena | S | M1.1 | nízké | nový (navazuje MRK-60) |
| | M1.3 `upsert_goal` jako částečná úprava s diffem (Z4) | žádná ztráta dat po potvrzení | S | – | nízké | nový |
| | M1.4 Limit PINu nezávislý na `X-Forwarded-For` (Z13) | bezpečný login i po přesunu hostu | S | – | nízké | nový |
| **M2 Hub 24/7 bez PC** | M2.1 Linux runtime (systemd, `standalone` build, obnova ze zálohy) na starém notebooku nebo Pi 3B (Z1) | Hub dostupný ve škole | M–L | M1.1 | střední (HW, PG verze, PWA origin) | MRK-27 / MRK-46 (zúžit) + nový |
| **M3 Termíny ve Škole** | M3.1 Archivace/úprava předmětů (Z5) | čisté předměty pro mapování | S–M | – | nízké | nový |
| | M3.2 Moodle události → kurz/předmět, Termíny ve Škole a „co hoří" v Dnes (Z3) | „kdy je test" na jednom místě | M | M3.1, MRK-42 mapování kurzů | střední (formát reálného ICS – ověřit lokálně) | nový (navazuje MRK-31/42) |
| | M3.3 Více ICS zdrojů (Google Kalendář read-only) (Z7) | Kalendář začne dávat smysl | S | – | nízké | nový (navazuje MRK-31) |
| **M4 Denní smyčka** | M4.1 Jedna hlavní obrazovka (Z8) | jedno místo ráno i během dne | M | M3.2 pro „co hoří" testy | střední (UX) | nový |
| | M4.2 Zúžená navigace + skupina Systém + zaparkování modulů (Z9) | přehledné menu na mobilu | S–M | – | nízké | nový (navazuje MRK-18) |
| | M4.3 Všimnutelné připomínky (Z10) | pojistka, která funguje | S | – | nízké | nový (navazuje MRK-24) |
| | M4.4 Kontextové návrhy dotazů pro AI | „vím, na co se ptát" | S | M4.1 | nízké | nový |

### Should

| Položka | Přínos | Náročnost | Závislosti | Riziko | Linear |
|---|---|---|---|---|---|
| S1 WoT počítadlo M-ek + automatický zdroj cíle (Z15) | cíl „50 M-ek" sám roste | S–M | – | nízké | nový |
| S2 AI spolehlivost: regresní sada bez LLM, `max_tokens`, osiřelé pending akce, kontrola read toolů, oprava „test" (Z11, Z12, Z16, Z17) | méně překvapení v chatu | M | M1.1 | nízké | nový (uzavře follow-up #1) |
| S3 Search a Paměť: SQL předfiltr místo 500 řádků, hledání v celém textu paměti, druh + expirace paměti (Z14, Z24) | správné výsledky, menší zátěž na Pi | M | – | střední (migrace paměti) | nový |
| S4 Pozorovatelnost a diagnostika: logy do souboru, AI metriky v DB, read-only diagnostika v Nastavení (Z21, Z27) | dá se zjistit, co se stalo | M | M2.1 | nízké | nový (navazuje MRK-26) |
| S5 Odolnost na malém HW: streamovaný limit uploadu, omezený dotaz připomínek, přísnější limity ZIP importu (Z18, Z19) | bez OOM na 1 GB | S | M2.1 | nízké | nový |
| S6 Škola: zápočet a výsledek u předmětu (docházka jako otevřená otázka) | stav studia na jednom místě | S–M | M3.1 | nízké | nový |
| S7 Fitness rychlý zápis: sady cviků a „zopakovat poslední" (Z25) – jen pokud Standa chce Rehab používat (otázka 6) | Rehab se dá zapisovat za < 1 min | M | M4.2 (rozhodnutí o zaparkování) | nízké | nový |

### Later

- PostgreSQL fulltext (`tsvector` + GIN, `unaccent`, `pg_trgm`) – až po S3, pokud SQL předfiltr nestačí (příloha A, B3).
- Vícekrokové AI plány: dávka návrhů s „potvrdit vše" a závislostmi (příloha A, B9).
- Souhrny a testové otázky ze studijních materiálů s odkazem na stranu/snímek (nad MRK-44).
- Detekce konfliktů v kalendáři; opakované úkoly / závislosti v plánovači.
- MFF rychlejší zápis postav (jen při návratu ke hře).
- Smazání mrtvých endpointů (Z22), aktualizace dokumentace (Z23 – lze přibalit k libovolnému PR), UI cílů pro chybějící zdroje (Z26), Briefing/planner podle dostupnosti modulů (Z20).

---

## 5. Návrhy issues (Must a Should)

Formát podle [linear-issue-template.md](../linear-issue-template.md). **Issues nejsou založené v Linearu** – založí se po
schválení. Štítky a milník: *Standa Hub 2.0 — Mega Update*.

### M1.1 Fix wall-clock dependent study-material tests

## Kontext
Od 2026-10-23 padají `test_ai_context_lists_ids_but_never_text` a `test_search_context_changes_and_module_gate`:
`context_materials` počítá „nové za 14 dní" z `utc_now()` (`backend/modules/school/integrations.py:56`), testy mají pevné
`NOW = 2026-10-09` (`backend/tests/test_study_materials.py:24`). Každý nový PR má červené CI.

## Scope
- `context_materials` bere čas z `ContextRequest` (`req.local_now` / `req.today`), ne z `utc_now()`.
- Grep dalších `utc_now()` v `ContextSection.build` / `SearchSource` a stejná oprava, pokud existují.

## Mimo scope
- Jiné změny kontextu studijních materiálů.

## Akceptační kritéria
- [ ] Oba testy projdou bez ohledu na systémové datum (regresní test s hodinami posunutými o 60 dní).
- [ ] Hosted CI zelené.

## Jak ověřit
`pytest backend/tests/test_study_materials.py backend/tests/test_study_material_reading.py`; CI.

## Odkazy
Z2; MRK-42, MRK-44.

### M1.2 Close remaining Finance → AI leak paths (MRK-60 follow-up)

## Kontext
Z6: název a % finančního cíle se k LLM dostane přes aktivitu (`area=goals`), planner a `upsert_goal`.

## Scope
- Snapshot/aktivita automatického finančního cíle buď s `area=finance`, nebo filtr `is_finance_goal` v
  `get_recent_activity` (`backend/read_queries.py:234-237`) podle `entity_type=Goal` + zdroje.
- `planner_service` vynechá finanční cíle (`_deadline_actions_for_goals`, stagnace; `backend/planner_service.py:132-206`).
- `upsert_goal` odmítne `id` finančního cíle a `area=finance` (`backend/tools.py:823-845`, `backend/tool_registry.py:377`).
- Neúspěšné Quick Add finance potvrzení se neloguje do `system` s textem výjimky (`backend/ai.py:957-963`).

## Mimo scope
- Finance v1 MRK-64…68.

## Akceptační kritéria
- [ ] Test: automatický cíl `finance_balance` + snapshot → `get_recent_activity`, planner i briefing ho neobsahují.
- [ ] Test: AI `upsert_goal` na finanční cíl → odmítnuto s vysvětlením.
- [ ] `docs/finance.md` odpovídá chování.

## Jak ověřit
Nové testy v `test_finance_ai_exclusion*` / `test_planner.py`; žádné reálné LLM.

## Odkazy
Z6; MRK-60; `docs/finance.md:19`.

### M1.3 Make AI goal updates partial with a diff preview

## Kontext
Z4: `upsert_goal` s `id` nastaví všechna nezadaná pole na výchozí hodnoty (`backend/tools.py:806-841`).

## Scope
- Úprava existujícího cíle přes `modify_records` (entita `goal` už existuje, `backend/mutation_service.py`) nebo
  `upsert_goal` mění jen zadaná pole.
- Potvrzovací karta ukáže diff „staré → nové".

## Mimo scope
- Nový formulář cílů.

## Akceptační kritéria
- [ ] Test: úprava jen `target_date` zachová popis, stav, prioritu a progres.
- [ ] Stale check při změně cíle mezi návrhem a potvrzením.

## Jak ověřit
`test_ai_mutations.py` / nový test; ui-check karty potvrzení (desktop + 390 px).

## Odkazy
Z4.

### M1.4 Rate-limit PIN login independent of X-Forwarded-For

## Kontext
Z13: `_get_client_ip` věří první hodnotě `X-Forwarded-For` (`backend/main.py:296-302`).

## Scope
- Brát `X-Forwarded-For` jen od důvěryhodné proxy (env allowlist, výchozí: nedůvěřovat), jinak `request.client.host`.
- Omezit velikost in-memory slovníku pokusů.

## Mimo scope
- Změna PIN mechanismu.

## Akceptační kritéria
- [ ] Test: rotace `X-Forwarded-For` limit neobejde.
- [ ] Tailscale Serve na Windows i Linuxu dál funguje (dokumentovaná proxy).

## Jak ověřit
Test `test_auth*`; Standa lokálně login přes Tailscale (ověřit lokálně).

## Odkazy
Z13; MRK-24.

### M2.1 Always-on Linux runtime on existing hardware (old laptop or Raspberry Pi 3B)

## Kontext
Priorita 1 z používání: PC neběží 24/7, Hub není dostupný ve škole. Runtime je jen Windows (Z1). Měření a posouzení HW:
příloha D. MRK-46/MRK-27 plánují mini PC s Docker Compose; tato položka je levnější mezikrok bez nákupu HW.

## Scope
- `frontend/next.config.ts`: `output: 'standalone'`; build na PC, na server se kopíruje jen `standalone` + `static`.
- Linux služby: systemd unity pro backend (`python -m production`) a frontend (`node server.js`), restart a start po bootu;
  skripty v `scripts/linux/` jako protějšek `scripts/windows/`.
- PostgreSQL na serveru (verze ≥ produkční 18, `docs/backups.md:115`), DB na USB/SSD, ne SD karta.
- Přesun dat: obnova z existující zálohy (`pg_dump` plain + `psql`, `docs/backups.md:63-93`) a `MEDIA_DIR` přes restic
  (`docs/offsite-backups.md:202-204`); nikdy experiment na originálu (`docs/home-server.md` §8).
- Tailscale Serve na Linuxu, nový origin → `FRONTEND_ORIGINS`, `NEXT_PUBLIC_API_URL`, nová instalace PWA a push
  (`docs/https-pwa-push.md:96-99`).
- POSIX práva env souborů (protějšek Windows ACL, `backend/offsite_restic.py:9`).
- Health check a off-site zálohy běží na novém hostu; Windows zůstává záložní, ne paralelní produkce (jeden vlastník
  scheduleru, `backend/scheduler_service.py:24-27`).

## Mimo scope
- Docker Compose a další domácí služby (MRK-46…55).
- Nákup HW.

## Akceptační kritéria
- [ ] Hub běží 7 dní bez zapnutého PC, `/health` = healthy, dostupný z telefonu přes Tailscale ve škole.
- [ ] Obnova ze zálohy na novém hostu prošla (počty řádků klíčových tabulek sedí), originál beze změny.
- [ ] Restart hostu → služby samy naběhnou do 2 min.
- [ ] Na Pi 3B: RSS backend + frontend + PG pod 700 MB při běžném používání (ověřit lokálně).
- [ ] Runbook v `docs/operations.md` (Linux sekce), opravený `backend/AGENTS.md:370`.

## Jak ověřit
Standa lokálně (reálná DB, telefon mimo domácí síť). V cloudu jen build `standalone` a smoke test na x86 Linuxu.

## Odkazy
Z1; MRK-23, MRK-27, MRK-46; příloha D.

### M3.1 Archive and edit school subjects

## Kontext
Z5: předměty nejdou upravit ani vyřadit; preferovaná je archivace (zachová historii).

## Scope
- `PATCH /school/subject/{id}` (název, kód, semestr, kredity, `active`) + Activity; případně `archived_at` (vzor Návyky
  a Fitness, `backend/modules/habits/models.py:28`).
- Archivované předměty: skryté ve výběrech (`frontend/app/school/page.tsx:610`), v mapování kurzů a návrhu
  (`backend/modules/school/service.py:417-458`), v `get_school_subjects`; v Search a historii zůstávají se štítkem.
- UI: „Archivovat / Obnovit" u předmětu, filtr „Zobrazit archivované".

## Mimo scope
- Tvrdé mazání předmětů.

## Akceptační kritéria
- [ ] Archivace nezmění ani nesmaže úkoly, zkoušky, mapování kurzů ani studijní materiály.
- [ ] Archivovaný předmět se nenabízí v Rychlém přidání ani formulářích, ale je vidět v historii.
- [ ] Testy endpointu + ui-check desktop a 390 px.

## Jak ověřit
Nové testy `test_school_subjects.py`; ui-check. Po merge úklid dat (Standa).

## Odkazy
Z5; vstup z používání „School – vyřazení předmětů".

### M3.2 Link Moodle calendar events to courses/subjects and surface them as deadlines

## Kontext
Z3, Priorita 2: testy z Moodle ICS jsou jen v Kalendáři. Kurzy už mají ruční mapování na předmět (`StudyCourse.subject_id`,
MRK-42).

## Scope
- Parser čte `CATEGORIES` (a případně kurz v `DESCRIPTION`/`URL`); nový sloupec u `calendar_events` (aditivní migrace).
- Párování na `StudyCourse.short_name` → `subject_id` (deterministicky, bez podobnosti názvů); nespárované zůstávají
  nespárované.
- Škola → Termíny: Moodle události u předmětu (štítek „Moodle", odkaz do Kalendáře), bez duplikace ručních zkoušek.
- Dnes → „co hoří": Moodle test/uzávěrka do 7 dní.
- Párování „otevřeno/uzavřeno" kvízu do jednoho termínu jen pokud to reálný export umožní (ověřit lokálně).

## Mimo scope
- Zápis do Moodlu; automatické vytváření zkoušek bez potvrzení.

## Akceptační kritéria
- [ ] Syntetické ICS s `CATEGORIES` → událost u správného předmětu ve Škole i v Dnes.
- [ ] Bez `CATEGORIES` nebo bez mapování → nic se nespáruje a nic se neztratí.
- [ ] Ověřeno na reálném Moodle exportu (ověřit lokálně, anonymizované výsledky do issue).

## Jak ověřit
Testy parseru a integrací; ui-check `/school` a `/today` (desktop + 390 px); Standa s reálným `MOODLE_ICS_URL`.

## Odkazy
Z3; MRK-31, MRK-42, MRK-43; otevřená otázka 3.

### M3.3 Support several read-only ICS sources (Google Calendar)

## Kontext
Z7: jediný zdroj `config_key='moodle'`. Google Kalendář nabízí soukromou ICS adresu; to je read-only a v souladu se
zdroji pravdy (Kalendář = Hub + upstream importy, `docs/home-server.md` §3). Obousměrná synchronizace se nenavrhuje.

## Scope
- Allowlist zdrojů v kódu (např. `moodle` → `MOODLE_ICS_URL`, `google` → `GOOGLE_ICS_URL`), `sync_source(key)`,
  `configured` po zdrojích, výsledek syncu po zdrojích (`backend/modules/calendar/service.py:30-32,196-268`).
- UI: synchronizace všech nakonfigurovaných zdrojů, štítek zdroje u události.
- Bez migrace (`kind='ics'`, `config_key` ≤ 20 znaků).

## Mimo scope
- OAuth Google API, zápis do Google Kalendáře, plánovaný sync.

## Akceptační kritéria
- [ ] Dva syntetické ICS zdroje vedle sebe, reconcile jednoho neovlivní druhý.
- [ ] URL se nikdy neobjeví v API, logu ani chybě (kanárkové testy jako MRK-30).

## Jak ověřit
Testy `test_calendar*.py`; Standa lokálně s reálnou Google ICS adresou.

## Odkazy
Z7; MRK-31.

### M4.1 One main daily screen

## Kontext
Z8 + vstup z používání: Dnes a Týdenní přehled duplikují Řídicí centrum a neotevírají se.

## Scope
- Řídicí centrum (`/`) převezme jádro `/today`: co hoří (overdue + testy do 7 dní), dnešní timeline, další volný blok,
  „od včera se změnilo" (top 5 z `/changes`), připomínky dnes.
- Využít existující `/today` a `/changes` API; odstranit mrtvý `recent_activity` z `/dashboard`.
- `/today` a `/review` zůstanou dostupné jako odkazy z karet („Otevřít →"), ne položky hlavní navigace (M4.2).
- Nové výchozí pořadí karet: co hoří / Nadcházející testy, Cíle, WoT nahoře; Klíčová čísla dolů (Z28).
- Rozložení dashboardu uložit na server (např. jako uživatelské nastavení), aby platilo na telefonu i PC (Z28).

## Mimo scope
- Nové datové zdroje; AI generování obsahu obrazovky.

## Akceptační kritéria
- [ ] Na 390 px je první obrazovka bez scrollu: co hoří + další položka dne.
- [ ] Žádný blok se neopakuje dvakrát na téže obrazovce.
- [ ] Rozložení upravené na PC platí i na telefonu; existující `localStorage` rozložení se při prvním načtení převezme.
- [ ] Prázdné, chybové a načítací stavy podle `docs/design-system.md`.

## Jak ověřit
ui-check (desktop + 390 px) s mock API; Standa týden reálného používání.

## Odkazy
Z8, Z28; příloha A, B4 a B12.

### M4.2 Narrow navigation, System group and module parking

## Kontext
Z9: 19 položek. Vstup z používání určuje denně používané plochy.

## Scope
- Hlavní navigace: Řídicí centrum, Škola, Cíle, Připomínky, Návyky, WoT, AI asistent (+ Kalendář po M3.3).
- Skupina „Další": Dnes, Týdenní přehled, Plánovač, Finance (do vydání Finance v1), Fitness, MFF, Práce.
- Skupina „Systém" (pod Nastavením): Co se změnilo, Aktivita, Paměť, Nastavení.
- Zaparkování MFF / Práce / Fitness flagem (MRK-18) jen podle rozhodnutí Standy; data zůstanou.
- Ctrl+K dál najde všechny stránky.

## Mimo scope
- Mazání modulů nebo dat.

## Akceptační kritéria
- [ ] Na 390 px hlavní menu ≤ 8 položek; skupiny jsou rozbalitelné.
- [ ] Vypnutý modul zmizí ze všech skupin; zapnutý ve „Další" funguje beze změny.
- [ ] Zaparkovaný modul zmizí i z karet Řídicího centra (Klíčová čísla, Hry) – ověřeno ui-checkem.
- [ ] `frontend/lib/moduleFramework.test.mjs` a registry parity zůstanou zelené.

## Jak ověřit
`module-flags-check.mjs`, `ui-check.mjs` (desktop + 390 px).

## Odkazy
Z9; MRK-18.

### M4.3 Noticeable reminder notifications

## Kontext
Z10 + Priorita 3. Zvuk určuje Android kanál; stránka může ovlivnit `renotify`, `requireInteraction`, `vibrate`, akce.

## Scope
- Tag na výskyt (`standa-reminder-{id}-{occurrence}`) nebo `renotify: true` (`backend/delivery_service.py:271`,
  `frontend/public/sw.js:15-21`).
- `requireInteraction` + `vibrate` pro připomínky (ne pro všechny typy).
- Akce „Hotovo" / „Odložit 10 min" v oznámení (endpointy připomínek existují).
- Krátký návod v Nastavení „Jak zapnout zvuk oznámení na Androidu"; nastavení push přesunout z `/reminders` do Nastavení.

## Mimo scope
- Nativní aplikace, ntfy.

## Akceptační kritéria
- [ ] Opakovaná připomínka znovu zazvoní/zavibruje, i když předchozí výskyt visí v liště (ověřit lokálně, Android).
- [ ] Oznámení zůstane viset do odkliknutí.
- [ ] Akce „Hotovo" označí připomínku jako hotovou bez otevření aplikace.

## Jak ověřit
Testy `delivery_service`; Standa na telefonu.

## Odkazy
Z10; MRK-24.

### M4.4 Contextual AI prompt suggestions

## Kontext
„Nevím, na co se ptát." Scénáře z přílohy A, B12.

## Scope
- Statické, deterministické návrhy v `/ai` a jako rychlé akce na hlavní obrazovce, Škole a Cílech
  („Co mě tento týden čeká ve škole?", „Jak jsem na tom s cíli?", „Najdi v materiálech k X část o Y").
- Návrhy podle dostupných modulů (flagy); žádný návrh pro Finance (MRK-60).

## Mimo scope
- LLM generované návrhy.

## Akceptační kritéria
- [ ] Každý návrh vede na dotaz, který routing pošle do správné oblasti (test routeru bez LLM).
- [ ] Vypnutý modul = žádný návrh.

## Jak ověřit
`test_tool_router.py`, frontend test, ui-check.

## Odkazy
Příloha A, B12; M4.1.

### S1 WoT mastery counter and automatic goal source

## Kontext
Z15. Ruční M-ko existuje (`POST /wot/milestones`, `backend/main.py:1193`), chybí souhrn a napojení na cíl.

## Scope
- Souhrn: celkem ace M, počet tanků s M, seznam po tancích (`backend/wot_service.py`), na `/wot` nahoře.
- Automatický zdroj cíle `wot_ace_mastery_count` (`backend/goal_history_service.py`), refresh snapshotu po
  create/patch/delete M-ka, položka v `frontend/lib/goals.ts`.
- Zviditelnit „Přidat Mko" (horní akce stránky / Rychlé přidání).

## Mimo scope
- Osobní rekordy, gamifikace (`docs/wot-milestones.md:129-131`).

## Akceptační kritéria
- [ ] Cíl „50 M-ek" s automatickým zdrojem roste po přidání M-ka bez ručního zásahu.
- [ ] Počítání podle rozhodnutí (otázka 7) pokryté testem.

## Jak ověřit
`test_wot_milestones.py`, `test_goals_automatic_v2.py`; ui-check `/wot`.

## Odkazy
Z15.

### S2 AI chat reliability pack

## Kontext
Z11, Z12, Z16, Z17; příloha A, B1.

## Scope
- Routing: „test" jen jako samostatné slovo ve školním kontextu, regresní test (follow-up #1).
- Read tooly: kontrola route a dostupnosti modulu při provedení (`backend/ai.py:430-440`).
- `max_tokens` pro chat volání (`backend/ai.py:746-752`).
- Po chybě vrátit existující pending akce turnu, nebo je zrušit (`backend/main.py:685-706`).
- Regresní sada scénářů s `FakeGroq` (seznam v příloze A, B1).

## Mimo scope
- Změna providera, fallback model.

## Akceptační kritéria
- [ ] Všechny scénáře z B1 běží v CI bez sítě.
- [ ] Follow-up #1 uzavřený v `docs/follow-ups.md`.

## Jak ověřit
pytest; žádné reálné Groq.

## Odkazy
Z11, Z12, Z16, Z17.

### S3 Search and memory correctness

## Kontext
Z14, Z24; příloha A, B2 a B3.

## Scope
- Search: SQL předfiltr (`ILIKE` na titulek/klíčová pole) + `order_by` + limit; studijní text jen přes `defer`.
- Paměť: hledání v celém obsahu; dedupe přesné shody; sloupce `kind` (fact/temporary/decision), `expires_at`,
  `supersedes_id` (aditivní migrace, backfill `kind='fact'`); prefetch vynechá expirované.

## Mimo scope
- PostgreSQL fulltext (Later).

## Akceptační kritéria
- [ ] Paměť s klíčovým slovem za 80. znakem je k nalezení.
- [ ] Search nenačítá víc než N řádků na zdroj, kde N = limit výsledků × rezerva (test počtu dotazů/řádků).
- [ ] Expirovaná dočasná paměť se nedostane do promptu.

## Jak ověřit
`test_search.py`, `test_context_prefetch.py`; migrace upgrade → downgrade -1 → upgrade na PG.

## Odkazy
Z14, Z24.

### S4 Observability and read-only diagnostics

## Kontext
Z21, Z27; příloha A, B11.

## Scope
- Logy backendu a frontendu do rotovaného souboru (Windows i Linux); access log bez query stringu.
- AI metriky (latence, chyby, tokeny) do DB tabulky s retencí; souhrn v diagnostice.
- Read-only „Systém → Diagnostika" v Nastavení: `/health`, poslední zálohy, scheduler, AI chyby za 24 h, počty záznamů
  po oblastech (jen čísla – nahrazuje SQL statistiky ze vstupu).

## Mimo scope
- Externí monitoring (MRK-48).

## Akceptační kritéria
- [ ] Žádný obsah záznamů, dotazů ani financí v logu nebo diagnostice.
- [ ] Statistiky aktivity po týdnech dostupné bez přístupu k env souboru.

## Jak ověřit
Testy endpointu; Standa lokálně.

## Odkazy
Z21, Z27; MRK-26.

### S5 Small-hardware resilience

## Kontext
Z18, Z19; M2.1 na 1 GB RAM.

## Scope
- Streamovaný upload s tvrdým limitem i bez `Content-Length` (`backend/main.py:1229-1236,1342`).
- Dotaz připomínek v Dnes/timeline omezený na okno dne (`backend/core_integrations.py:75`).
- Konfigurovatelné nižší limity ZIP importu pro malý host (`backend/modules/school/zip_import.py:41`).

## Mimo scope
- Optimalizace mimo tyto cesty.

## Akceptační kritéria
- [ ] Chunked upload nad limit → 413 bez načtení celého těla (test).
- [ ] `/today` čte jen připomínky relevantní pro den (test počtu řádků).

## Jak ověřit
pytest; Standa na cílovém HW (ověřit lokálně).

## Odkazy
Z18, Z19; M2.1.

### S6 Subject credit status and result

## Kontext
Vstup z používání „stav zápočtu"; výsledek zkoušky už existuje (`backend/school_service.py:124-145`).

## Scope
- U předmětu: stav zápočtu (nesplněn / splněn / neuznán) + datum, souhrn výsledků zkoušek.
- Activity + doménová událost při změně stavu.

## Mimo scope
- Docházka (otevřená otázka 8), napojení na UIS.

## Akceptační kritéria
- [ ] Stav zápočtu vidět ve Škole a v AI kontextu Školy.
- [ ] Aditivní migrace, testy.

## Jak ověřit
pytest; ui-check `/school`.

## Odkazy
M3.1.

### S7 Fitness/Rehab quick logging

## Kontext
Z25; jen pokud Standa chce Rehab používat (otázka 6), jinak modul zaparkovat (M4.2).

## Scope
- Sady cviků (šablona rehab/tréninku) a „zopakovat poslední" s předvyplněnými hodnotami.
- Hromadná archivace starých cviků.

## Mimo scope
- Plány tréninků, AI coaching (`docs/fitness.md:38`).

## Akceptační kritéria
- [ ] Zápis 6 rehab cviků ze sady za < 1 min na mobilu (ui-check 390 px).

## Jak ověřit
`fitness-check.mjs`, pytest.

## Odkazy
Z25; MRK-33.

---

## 6. Pořadí a vlny

| Vlna | Obsah | Paralelně s | Kolize s Finance v1 (MRK-64…68) |
|---|---|---|---|
| **0 – hned** | M1.1 (první, odblokuje CI), M1.2, M1.3, M1.4 | Finance v1 pokračuje | M1.1 odblokuje červené CI i pro MRK-64. M1.2 sahá na `read_queries.py`, `planner_service.py` a `backend/modules/finance/service.py:290` – domluvit pořadí s MRK-65/66 (stejný modul), jinak bez kolize |
| **1 – dostupnost** | M2.1 (+ S5 před ostrým přesunem na 1 GB HW) | Vlna 2 (kód) | Přesun hostu = nový origin a reinstalace PWA; neprovádět uprostřed MRK-68 real-data acceptance (stejná produkční DB) |
| **2 – termíny** | M3.1 → M3.2; M3.3 paralelně | Vlna 1, Finance v1 | bez kolize (jiné moduly); M3.2 přidává migraci → sekvencovat čísla revizí s MRK-65/66 (poučení z 0021 Fitness/Moodle) |
| **3 – denní smyčka** | M4.1, M4.2, M4.3, M4.4 | S1, S2 | M4.2 mění navigaci: Finance do „Další" až do vydání MRK-68, pak rozhodnout; MRK-64 přidává `/finance/import` – stránka, ne položka navigace |
| **4 – Should** | S1, S2, S3, S4, S6, S7 | – | S3 Search: Finance v1 MRK-66 přidává Search zdroj pro nový ledger – S3 až po MRK-66, nebo S3 udělat tak, aby nový zdroj převzal stejný vzor |
| **Release** | tag + changelog „Hub 2.0" | – | Finance v1 může vyjít samostatně dřív i později |

Co jde paralelně: celá vlna 0 jsou malé nezávislé PR; M2.1 je převážně provozní práce (skripty, runbook) a nesahá na
aplikační kód kromě `next.config.ts`; M3.3 je nezávislé na M3.1/M3.2.

---

## 7. Otevřené otázky pro Standu

1. **Hardware pro 24/7:** máš starý notebook (kolik RAM, CPU, funkční baterie)? Pokud ano, doporučuji ho před Pi 3B
   (x86_64 bez rizika ARM wheelů, víc RAM, baterie jako UPS). Pi 3B je proveditelné jen s limity (příloha D).
2. **UIS ČZU:** nabízí UIS export zkouškových termínů (iCal/ICS nebo jiný soubor)? (ověřit lokálně). Pokud ano, jde
   přidat jako další ICS zdroj (M3.3); pokud ne, zůstává ruční zápis zkoušky (existuje, i přes Rychlé přidání).
3. **Moodle ICS:** obsahuje reálný export `CATEGORIES` se zkratkou kurzu? Pošli jen anonymizovanou informaci ano/ne
   a tvar (bez URL). Na tom stojí M3.2.
4. **Google Kalendář:** stačí read-only (soukromá ICS adresa)? Který/é kalendář/e?
5. **Hlavní obrazovka:** souhlas, že se `/today` „vlije" do Řídicího centra a Dnes + Týdenní přehled zmizí z hlavní
   navigace?
6. **Zaparkovat flagem teď:** MFF? Práce? Fitness/Rehab – zaparkovat, nebo udělat rychlý zápis (S7)?
7. **Počítání M-ek:** všechny ace záznamy, nebo jen unikátní tanky? (Více záznamů na tank je povolené.)
8. **Docházka:** stačí ruční „byl/nebyl" po týdnech, nebo po hodinách (to by vyžadovalo rozvrh MRK-41)? Je v 2.0?
9. **Finance v navigaci** během Finance v1: v hlavní, nebo v „Další" do vydání MRK-68?
10. **Připomínky:** `requireInteraction` jen pro připomínky, nebo i pro důležité notifikace (termíny)?

---

## Příloha A: Odpovědi na otázky B1–B12

### B1 AI chat v produkci

- **Routing** je deterministický: klíčová slova (`backend/context_service.py:99-128`, `_has` je prostý podřetězec,
  `:88-89`), intenty a regexy zápisu (`backend/tool_router.py:52-91`); route se počítá jednou na dotaz
  (`backend/ai.py:739`). Kill switch `AI_TOOL_ROUTING=false` (`backend/llm_config.py:104`). Slabá místa: Z11, Z12 a
  `widen_route`, které po chybě validace nabídne všechny write tooly (`backend/tool_router.py:276-277`).
- **Chyby Groqu:** 3 pokusy (`backend/llm_config.py:30`); 429 čeká podle `retry-after` max 20 s
  (`backend/llm_usage.py:50-66`), denní limit bez opakování (`backend/ai.py:526-531`); `/chat` vrací 429 / 503 / 500
  (`backend/main.py:685-719`). Fallback provider neexistuje. Frontend rozlišuje stavy (`frontend/lib/aiChat.ts:59-89`).
- **Pending akce a undo:** propose (TTL 30 min) → claim → stale check → provedení + audit → undo 24 h
  (`backend/ai.py:191-282,330-356`, `backend/mutation_service.py:686-725`); recovery při startu (`backend/main.py:199-218`).
  Mezery: Z4, Z16.
- **Limity tokenů:** historie 8 zpráv / 2500 tokenů, souhrn 300 (`backend/llm_config.py:25-28`), CURRENT STATE 500–600
  (`backend/context_service.py:224-234`), plná sada toolů ≤ 5150 (`backend/tests/test_llm_budget.py:60`), routované
  ≤ 3500 (`backend/tests/test_tool_router.py:259-264`); **chybí `max_tokens`** (Z17).
- **Regresní sada bez LLM (návrh pro S2), s `FakeGroq` (`backend/tests/fakes.py:24-48`):**
  1. 5xx / výpadek spojení → 2 opakování → 503 a čitelná zpráva;
  2. 429 s `retry-after` a denní limit;
  3. chyba ve 2. kole po návrhu v 1. kole → pending akce není osiřelá;
  4. vyčerpání `MAX_TOOL_ROUNDS`;
  5. více pending akcí v jednom turnu + potvrzení v libovolném pořadí;
  6. „test" ve finančním dotazu → žádné školní tooly;
  7. read tool mimo route / vypnutý modul → odmítnut;
  8. `upsert_goal` částečná úprava;
  9. finanční cíl v aktivitě / planneru → nikdy v promptu;
  10. expirace pending akce během potvrzení.

### B2 Paměť

- **Dnes:** `Memory(area, category, content, importance, active, …)` (`backend/models.py:203-221`), kategorie a oblasti
  jsou volné řetězce (enum jen v toolu, `backend/tool_registry.py:102-103`).
  - Výběr do promptu: všechny aktivní řádky, skóre = shoda 5znakových kmenů × 3 + oblast + důležitost, max 3 × 140 znaků
    (`backend/context_service.py:35-36,131-150`).
  - Bez dedupe, bez expirace.
  - Hledání v Ctrl+K vidí jen 79 znaků (Z14).
- **Návrh (S3), aditivní migrace:**
  - `kind` ∈ {`fact` trvalé, `temporary` dočasné, `decision` rozhodnutí};
  - `expires_at` (dočasné; prefetch ho filtruje, job deaktivuje expirované);
  - `supersedes_id` FK (nové rozhodnutí deaktivuje staré a drží řetěz historie);
  - `content_hash` (dedupe).
  - Rozhodnutí dostanou v promptu vlastní malý limit **(domněnka – ověřit v praxi)**.
  - Dopad: `rank_memories`, schéma `save_memory`, `MemoryRequest` / `MemoryUpdateRequest` (`backend/main.py:401-414`),
    UI `/memory`.

### B3 Search

- **Dnes:**
  - Skóre ve vrstvách 100/85/70/55/45/30 (`backend/search_service.py:38-58`), max 30 výsledků a 6 na typ (`:26-28`).
  - Každý zdroj načte až 500 řádků bez textového filtru a skóruje v Pythonu (`backend/search_service.py:72-84`).
  - Studijní text se do haystacku bere jen do 5000 znaků, ale z DB se načte celý
    (`backend/modules/school/integrations.py:17,29-45`).
  - V paletě chybí filtr podle modulu i rychlé akce (`frontend/components/search/CommandPalette.tsx:105`).
- **PostgreSQL fulltext** (`tsvector` + GIN, `unaccent`, `pg_trgm`):
  - Výhody: hledá v celém textu bez limitu 500, rychlé na velkých datech.
  - Náklady:
    - `CREATE EXTENSION` vyžaduje práva;
    - `unaccent` není IMMUTABLE (nutný wrapper pro generovaný sloupec);
    - stock PG nemá český slovník (`simple` + `unaccent`) **(domněnka)**;
    - ~10 tabulek s backfillem;
    - testy běží na SQLite (`.github/workflows/ci.yml:20`) → dvě cesty kódu, nová cesta krytá jen PG testem.
- **Doporučení:** nejdřív S3 (SQL předfiltr + `defer` textu + oprava paměti) – stejný výsledek pro současná data za
  zlomek ceny. Fulltext až jako Later, pokud data přerostou.

### B4 Můj den / Today / Dashboard

| Blok | Řídicí centrum | Dnes | Týdenní přehled | Plánovač |
|---|---|---|---|---|
| Termíny brzy | ✅ upcoming (škola) | ✅ max 3 | ✅ příští týden | ✅ |
| Po termínu | jen přes planner | ✅ pozornost | ✅ | ✅ |
| Připomínky dnes | ❌ (jen notifikace) | ✅ | ✅ | ❌ |
| Návyky | skrytý widget | ✅ | ❌ | ❌ |
| Kalendář / volný blok | ❌ | ✅ další volný blok | ❌ | ❌ |
| Cíle | ✅ | ❌ | ✅ | ✅ stagnace |
| Doporučení planneru | ✅ top 3 | ✅ priority | ❌ | ✅ |
| Co se změnilo | ❌ (`recent_activity` nevyužito) | ❌ | ✅ aktivita | ❌ |

**Mají samostatné stránky obsah navíc oproti kartám?** Ano:

- karta „Dnes" na Řídicím centru jsou jen 3 akce planneru (`frontend/components/dashboard/widgets.tsx:364-391`), stránka
  `/today` přidává timeline dne, pozornost a další volný blok (`backend/today_service.py:231-276`);
- karta „Týdenní přehled" je malé shrnutí, stránka `/review` má celý přehled a historii týdnů (`frontend/app/review/page.tsx:34,121`).

Proto je doporučení: stránky ponechat dostupné z odkazu na kartě, odebrat je z hlavní navigace (M4.2) a obsah, který
na Řídicím centru chybí (timeline, další volný blok, co hoří), převzít do hlavní obrazovky (M4.1).

**Nepoužívané karty na Řídicím centru:**

- „Upravit dashboard" je umí skrýt a přeřadit už dnes, bez vývoje (`frontend/app/page.tsx:43,150`, `visible`/`order`
  v `frontend/lib/dashboardLayout.ts:92-94`). Rozložení se ale ukládá jen do `localStorage` daného zařízení
  (`frontend/hooks/useDashboardLayout.ts:17,33,64`), takže telefon a PC je nutné nastavit zvlášť (Z28).
- Karty vypnutých modulů zmizí samy: `availableWidgets` (`frontend/lib/dashboardLayout.ts:84-85`). Kombinované karty se
  ořežou po modulech – Klíčová čísla bez Práce ukáží jen Finance a naopak (`frontend/components/dashboard/widgets.tsx:334-341`),
  Hry bez MFF jen WoT (`:516-525`). Zaparkování Práce, Financí a MFF flagem (M4.2) tedy uvolní horní polovinu obrazovky.
- Výchozí pořadí dává Klíčová čísla (50) před Cíle (60), Nadcházející (70) a Hry (100) (Z28) → M4.1 změní výchozí
  pořadí: Nadcházející testy, Cíle, WoT nahoru.

Zdroje: `frontend/lib/dashboardLayout.ts:63-74`, `backend/today_service.py:231-276`, `backend/weekly_snapshot.py:44-52`,
`backend/planner_service.py:415-416`. Chybí na hlavní obrazovce: co hoří, změny, další volný blok, kalendář → M4.1.

### B5 Calendar + School

- **Konflikty:** detekce neexistuje; překryvy se záměrně zobrazují odděleně (`frontend/modules/calendar/lib.ts:146`) →
  Later.
- **Týdenní pohled** existuje (`frontend/modules/calendar/WeekView.tsx`).
- **Deadliny** ve Škole jsou jen ručně zadané (Z3).
- **Studijní materiály:**
  - Sync, ZIP import i čtení existují.
  - Souhrny a testy s odkazem na zdroj zatím nejsou; stavebním kamenem je `location` (strana/snímek) v
    `get_study_material_text` (`backend/modules/school/reading.py:300-306`) → Later.
- **Ruční rozvrh MRK-41:** Backlog. Pro „kdy je test" není nutný; nutný by byl jen pro docházku po hodinách (otázka 8).
- **MRK-43 (reálný Moodle WS):** Backlog, neověřeno. Moodle ICS reálně funguje podle vstupu z používání; ZIP import
  (MRK-56) je náhradní cesta pro materiály.
- **UIS ČZU:** zdroj zkouškových termínů neověřen (otázka 2).

### B6 Planner

- Opakované úkoly neexistují.
  - Opakování umí jen připomínky (`none|daily|weekly`, `backend/reminder_service.py:38,87-120`).
  - Návyky nemají rozvrh (`backend/modules/habits/models.py:19-33`).
- Závislosti neexistují; obecná entita „úkol" také ne (jen školní úkoly a připomínky).
- Přehled nesplněného nejblíž pokrývá pozornost v Dnes (max 8) a planner (max 5) → M4.1 dá „co hoří" na hlavní
  obrazovku.
- Nový „Task" modul se nenavrhuje (žádné nové moduly).

### B7 WoT

- **Existuje:**
  - `WotMilestone` s `mastery ∈ {ace, first, second, third}` a více záznamy na tank (`backend/wot_service.py:25-26`,
    `backend/tests/test_wot_duplicate_records.py`);
  - CRUD (`backend/main.py:1184-1217`);
  - screenshoty a replaye.
- **Chybí:**
  - počítadlo a souhrn po tancích (`backend/wot_service.py:256-260` jen řadí);
  - zdroj cíle;
  - osobní rekordy (`docs/wot-milestones.md:129-131`).
- „Přidat Mko" je až ve 4. sekci stránky (`frontend/app/wot/page.tsx:495-503`), na mobilu po scrollu přes zdroje
  a grindy → S1 přesune akci nahoru.

### B8 Fitness / MFF / Work / Finance

- **Zaparkovat flagem:**
  - Mechanismus existuje: env `MODULE_<ID>_ENABLED`, `PUT /modules/{id}`, Nastavení (`docs/module-feature-flags.md:48-100`).
  - Data zůstanou; vypnutý modul zmizí z navigace, Search, Dnes i AI.
  - Doporučení: MFF a Práce zaparkovat; Fitness podle otázky 6.
- **Schovat, ale nechat zapnuté:** dnes nejde (Z9) → M4.2, skupina „Další".
- **Finance v1:**
  - Nezastavovat.
  - V navigaci zatím ve „Další" – stránka stále běží na legacy API (`frontend/app/finance/page.tsx:63-64`) a import UI
    (MRK-64) chybí.
  - Do hlavní navigace až po MRK-68, pokud se bude používat.
- **Fitness / Rehab použitelný:** sady cviků + „zopakovat poslední" + archivace (S7).

### B9 Vícekrokové AI úkoly

- **Funguje:** více pending akcí v jednom turnu i napříč koly (`backend/ai.py:741,819`), seznam karet ve frontendu
  (`frontend/components/ai/MessageList.tsx:102`); `modify_records` až 20 cílů jedné entity v jedné transakci
  (`backend/mutation_service.py:35,676`).
- **Chybí:**
  - objekt „plán / dávka" s „potvrdit vše";
  - závislosti mezi návrhy (např. zkouška potřebuje `subject_id` předmětu, který vznikne až po potvrzení);
  - různé změny pro různé cíle v jednom `modify_records`;
  - náhled u create toolů;
  - pravidla pro částečné selhání.
- „Naplánuj přípravu na zkoušku" dnes jde jako několik nezávislých připomínek k potvrzení → Later.

### B10 Notifikace, Změny a Activity

- **„Co se změnilo"** je užitečné, ne technický log: SQL filtr šumu, `system.*` pryč, vytvořené a hned smazané pryč
  (`backend/change_feed.py:96-108`, `backend/briefing_snapshot.py:53-75`).
  - Slabiny: opakované úpravy se neslučují a záložní titulek může být technický `event.type`
    (`backend/module_contracts.py:235`).
  - Doporučení: top 5 na hlavní obrazovce (M4.1), stránka do „Systém".
- **Aktivita** je záměrně technický log (`frontend/app/activity/page.tsx:65-71`) → „Systém".
- **Push end-to-end:**
  - Řetězec existuje celý: job každých 60 s → notifikace → fronta → Web Push (TTL 12 h, `Urgency: high`) → sw.js → klik
    (`backend/scheduler_service.py:117-124`, `backend/delivery_service.py:274-381`, `frontend/public/sw.js:25-41`).
  - Podle vstupu oznámení na telefonu chodí; slabina je Z10.
  - Pozdní push starší 12 h se tiše zahodí (`backend/delivery_service.py:49`).

### B11 Provoz a pozorovatelnost

- **`/health`** je veřejný; hlásí verzi, DB, migrace, scheduler, zálohy a off-site; 503 jen při unhealthy
  (`backend/health_service.py:36-93`, `backend/health_router.py:10-14`). Nehlásí disk, opakovaná selhání jobů ani AI.
- **Access log** je výchozí uvicorn a obsahuje `?q=` (Z21).
- **Logy** pod Task Schedulerem nikam neodchází **(domněnka)**.
- **Monitoring:** opt-in monitoring log (`backend/monitoring_logging.py:1-30`).
- **AI metriky** jen ve stdout.
- **Diagnostický pohled** chybí (`docs/monitoring.md:66-68` „Deferred") → S4.

### B12 Každodenní smyčka – scénáře

Předpoklad pro všechny scénáře mimo domov: **M2.1** (dnes blokuje vše).

1. **Ráno na telefonu (7:30, 1 min): „Co mě dnes čeká?"**
   - *Funguje dnes:* `/today` ukáže timeline (připomínky, termíny, návyky, kalendář) a další volný blok; Řídicí centrum
     top 3 akce.
   - *Brzdí:* Hub mimo domov nedostupný (Z1); Dnes se neotevírá a Řídicí centrum nemá „co hoří" (Z8); testy z Moodle
     nejsou u předmětů (Z3).
   - *Po 2.0:* jedna obrazovka „co hoří + dnešek + další volný blok" (M4.1).
2. **Ve škole o přestávce: „Kdy je test z X?"**
   - *Funguje dnes:* Škola → Termíny (ručně zadané zkoušky), Kalendář → Nadcházející (Moodle), Ctrl+K hledá zkoušky
     i události.
   - *Brzdí:* nedostupnost (Z1), dvě oddělená místa, žádná vazba Moodle → předmět (Z3).
   - *Po 2.0:* Škola → Termíny ukáže ruční i Moodle termíny u předmětu (M3.2).
3. **Po škole (5 min): zapsat nový úkol/test a podívat se do podkladů.**
   - *Funguje dnes:* Rychlé přidání „test z matiky v pátek" → potvrzení; AI „co je v prezentaci o rekurzi" → omezené
     pasáže s číslem snímku (MRK-44).
   - *Brzdí:* staré předměty v nabídce (Z5); nevíš, na co se AI ptát (M4.4).
4. **Večer (2 min): odškrtat den.**
   - *Funguje dnes:* návyky v Dnes, WoT „Přidat Mko", připomínky na zítra.
   - *Brzdí:* M-ko nezvedne cíl „50 M-ek" (Z15); návyky jsou na Řídicím centru skryté.
5. **Neděle večer (10 min): co mě čeká příští týden.**
   - *Funguje dnes:* Týdenní přehled (AI nad snapshotem), Kalendář → týdenní pohled.
   - *Brzdí:* bez Google Kalendáře jen školní a Moodle data (Z7); přehled duplikuje Řídicí centrum.
   - *Po 2.0:* Kalendář se všemi zdroji (M3.3) + přehled jako odkaz z hlavní obrazovky.
6. **Pojistka během dne: připomínka.**
   - *Funguje dnes:* push přijde.
   - *Brzdí:* tiché nahrazení opakované připomínky a rychlé zmizení (Z10).
   - *Po 2.0:* M4.3.

---

## Příloha B: Zařazení „Vstupu z používání"

| Bod | Kategorie | Řešení | Kde v plánu |
|---|---|---|---|
| Zvuk/vibrace oznámení | (vyřešeno, nebyla chyba) | – ; zbývá `requireInteraction` + `renotify` | M4.3 |
| Moodle ICS „nefunguje" | (vyřešeno, nebyla chyba) – datová mezera | svázání s předměty; UIS jako otevřená otázka | M3.2, otázka 2 |
| Goals × WoT „50 M-ek" | chybějící funkce | automatický zdroj cíle | S1 |
| WoT seznam a počítadlo M-ek | chybějící funkce | souhrn po tancích | S1 |
| School vyřazení předmětů | chybějící funkce | archivace | M3.1 |
| Moodle události ↔ Škola | chybějící funkce | párování přes `CATEGORIES` + mapování kurzů | M3.2 |
| School docházka | chybějící funkce | granularita nejasná | otázka 8 (bez příkladu použití zůstává otázkou) |
| School stav zápočtu | chybějící funkce | stav u předmětu | S6 |
| Kalendář ↔ Google | chybějící funkce | read-only ICS, druhý zdroj; obousměrná sync ne (zdroje pravdy) | M3.3, otázka 4 |
| Push připomínky se přehlédnou | nepohodlné ovládání | `requireInteraction`, `renotify`, akce, návod | M4.3 |
| WoT ruční M-ko nenalezeno | nepohodlné ovládání | akce nahoru / Rychlé přidání | S1 |
| „Nevím, jak to používat" | nepohodlné ovládání | denní scénáře + jedna obrazovka | M4.1, B12 |
| Duplicita Dnes / Řídicí centrum / Týdenní přehled | nepohodlné ovládání | stránky mají obsah navíc → z hlavní navigace pryč, dostupné z odkazu na kartě; chybějící obsah do hlavní obrazovky | M4.1, M4.2, B4 |
| Řídicí centrum ukazuje nepoužívané oblasti | nepohodlné ovládání | dnes jde skrýt přes „Upravit dashboard" (jen na zařízení); karty vypnutých modulů zmizí samy; nové výchozí pořadí + rozložení na serveru | Z28, M4.1, M4.2, B4 |
| Přeplněná navigace | nepohodlné ovládání | zúžení + skupiny + parkování | M4.2 |
| AI chat „nevím, na co se ptát" | nepohodlné ovládání | kontextové návrhy | M4.4 |
| Fitness/Rehab pracné | nepohodlné ovládání | sady cviků nebo zaparkovat | S7 / M4.2, otázka 6 |
| MFF pracné | nepohodlné ovládání | zaparkovat; rychlejší zápis Later | M4.2, Later |
| Priorita 1 dostupnost | (priorita) | Linux runtime na existujícím HW | M2.1, otázka 1 |
| Priorita 2 testy/zkoušky | (priorita) | M3.1–M3.3; UIS otázka | M3, otázka 2 |
| Priorita 3 připomínky všimnutelné | (priorita) | M4.3 | M4.3 |
| School úklid předmětů | úklid dat | Standa po M3.1 | po M3.1 |
| Statistiky – chybí bezpečná cesta | zjištění (nízké) | read-only diagnostika | S4 (Z27) |

---

## Příloha C: Průřezové kontroly

- **Bezpečnost:**
  - Auth všude (§3).
  - Login rate limit Z13.
  - Cookies HttpOnly + SameSite=Lax, `Secure` vynucený v produkci s https (`backend/production.py:55-66`).
  - CORS explicitní seznam originů (`backend/main.py:237-246`).
  - Uploady: názvy generuje server, sniff typu, servírování s `nosniff` (`backend/media_storage.py:29,67-110`); slabina
    Z18.
  - ZIP import dobře chráněný (`backend/modules/school/zip_import.py:42-111`).
  - Logy: tři `print(exc)` s možným osobním obsahem **(domněnka)** (`backend/main.py:216,1964`,
    `backend/reminder_service.py:476`); access log Z21.
  - Finance v AI Z6.
  - Cesty AI zápisu bez potvrzení: žádné.
- **Duplicity a mrtvý kód:**
  - Z22.
  - L7 stále platí – REST vs. `tools.py` zápisy pro práci, WoT, školu a cíle (`backend/main.py:1472,1510,1549,1592,1803`
    vs. `backend/tools.py:210-841`).
  - Refresh snapshotu cíle zkopírovaný 4× (`backend/main.py:1835`, `backend/tools.py:257`,
    `backend/modules/finance/service.py:290`, `backend/mutation_service.py:606`) – zdroj Z6(a).
- **Konzistence UI:**
  - Stránky používají `@/components/ui`, PageHeader a stavy.
  - Rizika na 390 px: pevné `grid-cols-3` (`frontend/app/today/page.tsx:173`), `w-20 whitespace-nowrap` (`:495`) a nowrap
    částky (`frontend/app/finance/page.tsx:334,355`) – ověřit v ui-check při M4.1.
- **Výkon:**
  - Z14, Z19.
  - Plné tabulky v Dnes/planner/notifikacích (`backend/school_integrations.py:98-232`,
    `backend/planner_service.py:46-341`, `backend/notifications_service.py:394-396,487`).
  - N+1 `compute_goal_progress_and_value` na cíl (`backend/goal_history_service.py:133-145`).
  - Největší stránky: `/school` 1084 ř., `/goals` 776 ř.; build `.next/static` 1,8 MB.
- **Dokumentace vs. kód:**
  - Z23.
  - `backend/AGENTS.md:370` zmiňuje systemd/NSSM, realita je Task Scheduler.
  - `docs/monitoring.md:66` System panel neexistuje.

---

## Příloha D: Raspberry Pi 3B vs. starý notebook (Priorita 1)

**Měřeno v tomto auditu** (x86_64, Linux, prázdná SQLite DB, scheduler zapnutý, jen připomínky vypnuté):

| Proces | RSS |
|---|---|
| Backend `uvicorn main:app` po `/health`, `/dashboard`, `/today`, `/search`, `/school/materials`, `/calendar` | 140 MB |
| Frontend `next-server` po načtení 5 stránek | 133 MB |
| `next build` (špička všech Node procesů) | 1,34 GB, 22 s na 4 jádrech |
| `node_modules` / `.next` po buildu | 476 MB / 74 MB |

**Odhady (domněnka, ověřit lokálně):** PostgreSQL s malým `shared_buffers` 50–120 MB; Raspberry Pi OS Lite 64bit
~100–150 MB; na ARM64 může Python/Node RSS vyjít jinak.

**Závěr:**

- **Pi 3B (1 GB) je proveditelné, ale na hraně:** ~450–550 MB v klidu **(domněnka)**.
- **Podmínky pro Pi:**
  - frontend se **musí** sestavit jinde (build potřebuje > 1 GB);
  - `output: 'standalone'`, aby se nekopírovalo 476 MB `node_modules`;
  - 64bit OS (aarch64 wheely pro `cryptography`, `psycopg2-binary`, `bcrypt` – **domněnka**, ověřit `pip install`);
  - DB a `MEDIA_DIR` na USB disku (SD karta se zápisy opotřebuje);
  - zram/swap;
  - nižší limity uploadu a ZIP importu (S5);
  - pozor na sdílenou USB 2.0 sběrnici s Ethernetem (I/O).
- **Starý notebook** (x86_64, ≥ 4 GB RAM) je výrazně bezpečnější: build přímo na místě, žádné riziko ARM wheelů,
  baterie funguje jako UPS (`docs/home-server.md` §9).
- **Obě varianty** potřebují totéž: Linux služby (systemd), PostgreSQL ≥ 18 klient i server pro obnovu plain dumpu
  (`docs/backups.md:115`; na Debianu/RPi OS repozitář PGDG – **domněnka**), Tailscale Serve, nový origin a reinstalaci
  PWA. Pokrývá M2.1.

---

## Příloha E: Metodika

- **Vstup z používání** je podle popisu MRK-69 ve stavu 2026-10-25 21:24 UTC, včetně bodů doplněných během auditu
  („Řídicí centrum ukazuje nepoužívané oblasti", upřesněná duplicita Dnes / Týdenní přehled).
- **Zdroj:** `origin/main` @ `e9ce037`. Povinné dokumenty podle MRK-69 přečteny; otevřené issues a milníky projektu
  Standa Hub v Linearu prošly.
- **Sběr důkazů:** čtyři paralelní čtecí průzkumy (AI + Finance hranice; Paměť / Search / Dnes / Planner / navigace;
  Škola / Kalendář / WoT / Fitness / Finance; Provoz / bezpečnost / push / UI / výkon / dokumentace). Klíčová tvrzení
  (Z1–Z6, Z10, Z13, Z14, Z18, Z19, Z20) jsem před zápisem ověřil přímo v kódu.
- **Spuštěno:** backend pytest a pyflakes (SQLite, `--disable-socket`), frontend test/lint/tsc/build, měření paměti
  (lokální uvicorn a `next start`, bez reálných dat). Reprodukce Z2 s posunutými hodinami.
- **Nespuštěno:** reálné LLM (Groq count 0), reálná DB, `.env`, telefon, reálný Moodle/UIS/Google. Ui-check skripty
  s mock API nebyly potřeba – stav stránek je doložen kódem.
