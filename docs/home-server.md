# Home server (mini PC): architektura a zdroje pravdy

Stav: **schválený architektonický směr**. Linear: milník **Home Server / Mini PC**, dokumentační issue MRK-45.

Tento dokument určuje hranice budoucího 24/7 domácího serveru a vlastnictví dat. Není to nákupní seznam ani příkaz spustit všechny služby najednou. Nasazování je postupné a každá služba musí mít jasný přínos, vlastní provozní ověření a zálohování.

Navazuje na [provozní postupy Hubu](operations.md), [monitoring](monitoring.md), [lokální zálohy](backups.md), [off-machine zálohy](offsite-backups.md) a [modulový rámec](module-framework.md).

## 1. Cíl a hranice platformy

Budoucí mini PC je Linuxová 24/7 platforma pro Standa Hub / Jarvis, PostgreSQL a vybrané domácí služby:

- Home Assistant, Mosquitto MQTT a později případně Frigate;
- Pi-hole, Caddy, Tailscale a Syncthing;
- Nextcloud, Immich, Jellyfin, Paperless-ngx, Vaultwarden, Mealie, Homebox a FreshRSS;
- Uptime Kuma, externí heartbeat přes healthchecks.io, ntfy, Diun a backup tooling;
- až po stabilizaci základu Wyoming Whisper + Piper pro MRK-36;
- volitelně herní server (game server), pokud na něj zbývá kapacita a není v konfliktu s kritickými službami.

Ne všechny služby startují v první den. Nová služba přichází až tehdy, když je předchozí vlna stabilní, monitorovaná a její nenahraditelná data mají ověřenou obnovu.

Současný produkční stav zůstává beze změny: MRK-23 provozuje Hub na Windows. Linuxový mini PC je budoucí cílové prostředí, nikoli zpětná změna současného runtime. Migrace Hubu nastane až podle samostatného, ověřeného plánu MRK-27.

## 2. Role Hubu, Jarvise a externích aplikací

Architektura rozlišuje tři vrstvy:

- **Externí aplikace** vlastní specializovaná trvalá data a jejich doménovou logiku.
- **Standa Hub** agreguje, propojuje a zasazuje data do Today, briefingu, vyhledávání, cílů, auditní stopy a dalších přehledů. Orchestrace patří sem.
- **Jarvis** je inteligentní rozhraní nad Hubem a explicitními akcemi. Není databází ani univerzálním přístupem k API.

Hub nemá znovu implementovat zralou externí aplikaci bez silného důvodu. Pokud služba danou doménu spolehlivě vlastní, Hub staví konektor a uživatelskou orchestrace, ne druhou editovatelnou databázi.

## 3. Zdroje pravdy

Pro každou datovou doménu existuje právě jeden autoritativní zdroj.

| Doména | Zdroj pravdy | Role Hubu / Jarvise | Důsledek |
| --- | --- | --- | --- |
| Finance | **Standa Hub** | Vlastní data, cíle, briefing, audit a potvrzované akce. | Actual Budget se nezavádí jako druhý zdroj. Další priorita je bankovní CSV/import vrstva. |
| Jídlo, recepty, jídelníčky a nákupy | **Mealie** | Hub čte, kontextualizuje a orchestruje přes API. | V Hubu nevznikne duplicitní databáze receptů. |
| Dokumenty, smlouvy, pojistky a jejich expirace | **Paperless-ngx** | Hub ukazuje expirace, připomínky, Today/briefing kontext a odpovídá na Jarvis dotazy. | Hub ukládá pouze vazby a vlastní orchestration data, ne druhý archiv dokumentů. |
| Fyzický inventář, sériová čísla a záruky | **Homebox** | Hub zobrazuje končící záruky a relevantní Life Admin kontext. | Inventář se neduplikuje do Hubu. |
| Zařízení, senzory, smart home a zahrada | **Home Assistant** | Jarvis provádí jen validované allowlistované akce přes Home Assistant. | Jarvis nikdy přímo neovládá relé ani zařízení. |
| Fotky | **Immich** | Hub může později povrchově odkazovat či vyhledávat přes konektor. | Immich se stane autoritativním až po ověřené záloze a obnově fotografií. |
| Obecný cloudový a dokumentový workspace | **Nextcloud** | Hub může odkazovat a zobrazovat omezená metadata. | Nextcloud vlastní pracovní soubory a sdílení. |
| Synchronizace složek | **Syncthing je transport**, ne sémantický zdroj pravdy. | Hub jej nepovažuje za druhou databázi. | Synchronizované složky nesmějí vytvářet konkurenční vlastnictví stejných dat. |
| Kalendář a školní plánování | **Standa Hub Calendar + nakonfigurované upstream importy** | Hub sjednocuje kalendář podle stávající architektury a pravidel importů. | Tento dokument nemění Calendar ani Moodle implementaci. |
| Hesla | **Vaultwarden** | Hub ani Jarvis k obsahu trezoru nemají přístup. | Před použitím jako primárního správce je nutná off-machine záloha a restore drill. |
| Média pro přehrávání | **Jellyfin knihovna / její úložiště** | Hub může později zobrazit stav služby, ne vlastnit katalog. | Nahraditelná média nemají stejnou zálohovací prioritu jako fotky a dokumenty. |

Změna této tabulky je architektonické rozhodnutí: samostatný issue, PR a review. Nesmí vzniknout jako vedlejší efekt implementace modulu.

## 4. Pravidla integrací

1. Každá datová doména má právě jeden zdroj pravdy.
2. Credentials externích služeb zůstávají pouze na backendu/serveru, mimo repo, frontend, logy a Linear.
3. Credentials, tokeny ani celé citlivé odpovědi nikdy nevstupují do LLM kontextu.
4. Konektory jsou přednostně read-only. Do Hubu předávají jen normalizované, minimální údaje potřebné pro konkrétní funkci.
5. Změna externího stavu jde výhradně přes explicitní validovanou akci/tool path. Neexistuje obecný nástroj „zavolej libovolné API“.
6. Citlivé, nevratné nebo bezpečnostní zápisy vyžadují vhodné potvrzení uživatele. Zámky, ventily, topení a podobné akce nesmějí být proaktivní ani pouze hlasové.
7. Každá akce respektuje allowlist, kontrolu aktuálnosti, audit a existující potvrzovací tok Hubu.
8. Výpadek konektoru znamená „zdroj nedostupný“; nesmí vést k hádání, tichému přepsání dat nebo falešnému úspěchu.
9. Nový Hub modul nejdřív ověří, zda danou doménu už nevlastní externí služba. Pokud ano, vzniká konektor/orchestrace.

## 5. Základ serveru a síť

| Vrstva | Směr |
| --- | --- |
| Host | Linux na mini PC. Konkrétní volba bare-metal vs. virtualizace patří do MRK-46. |
| Runtime | Docker Compose pro home-server služby; konfigurace verzovaná, secrets mimo repo. |
| Privátní přístup | Tailscale bez veřejného port-forwardingu. |
| Reverzní proxy / TLS | Caddy pro interní názvy a řízené směrování. |
| Lokální DNS | Pi-hole; výpadek DNS nesmí bez rozmyslu odříznout celou domácnost. |
| Události IoT | Mosquitto MQTT až s prvním skutečným MQTT use-case. |

Caddy, Tailscale a Pi-hole mají rozdílné role: Caddy směruje HTTP(S), Tailscale vytváří privátní síť a Pi-hole řeší DNS/filtering. Žádná z těchto vrstev neobchází autentizaci aplikací.

## 6. Observabilita

Jedna kontrola nemůže pokrýt všechny typy selhání:

- **Standa Hub `/health`** je autoritativní aplikační health contract Hubu: databáze, migrace, scheduler, backup freshness a verze podle [monitoring.md](monitoring.md).
- **Uptime Kuma** běží uvnitř domácí infrastruktury a hlídá jednotlivé služby a jejich endpointy.
- **healthchecks.io** přijímá odchozí heartbeat celého mini PC. Chybějící ping zachytí úplný výpadek hostu, internetu nebo napájení, který lokální Kuma sama nenahlásí.
- **ntfy** je transport infrastrukturních upozornění na telefon; není zdrojem health stavu.
- Host metriky doplní CPU, RAM, disk, teploty a SMART. Konkrétní nástroj se zvolí až v realizačním issue.

Alert má uvádět, která vrstva selhala. Úspěšný HTTP ping na proxy nesmí maskovat nezdravý `/health` payload.

## 7. Aktualizační politika

Kritické služby se neaktualizují unattended Watchtower-style upgradem. Diun pouze oznámí dostupnou verzi. Kritické jsou zejména PostgreSQL, Vaultwarden, Immich, Home Assistant, Nextcloud a Standa Hub.

Řízený update probíhá po jedné službě:

1. ověřit aktuální zálohy a jejich poslední výsledek;
2. vytvořit snapshot tam, kde dává smysl;
3. aktualizovat jednu službu;
4. ověřit aplikační health a závislosti;
5. zkontrolovat logy a případné migrace;
6. při problému rollbacknout podle dokumentovaného postupu.

Více kritických služeb se neaktualizuje v jednom neoddělitelném kroku.

**Výjimka: kód Standa Hubu po merge (MRK-98, opt-in).** Nasazení vlastního kódu z `main` není upstream upgrade
neznámé verze. Do `main` jde jen commit po review a zeleném CI. `scripts/windows/auto-update.ps1` ho nasazuje stejným
řízeným postupem jako ruční `update.ps1`: ověří čerstvou zálohu, migruje až po úspěšném buildu, čeká na health a při
chybě před migrací vrátí předchozí verzi. Commit, který jednou selhal, se automaticky znovu nezkouší. Zapíná se
registrací úlohy a dá se pozastavit (`-Mode Pause`). Netýká se to PostgreSQL ani ostatních služeb, ty dál podle
pravidel výše. Postup: [operations.md](operations.md#automatic-deploy-after-merge-mrk-98-opt-in).

## 8. Zálohy a obnova

- Systém a databáze jsou na NVMe; velké fotky a média ideálně na samostatném úložišti.
- Každá nenahraditelná doména má kopii mimo mini PC. Provider není tímto dokumentem zvolen.
- Backup tooling používá prověřené šifrované nástroje typu Restic nebo Borg; nevzniká vlastní kryptografie.
- Zálohy se nehodnotí pouze podle „job succeeded“. Pravidelné restore drilly ověřují čitelnost, integritu a postup obnovy.
- Fotky jsou nenahraditelné. Immich nesmí být autoritativní, dokud jejich off-machine záloha a obnova neprošla.
- Vaultwarden nesmí být primární správce hesel, dokud jeho off-machine záloha a scratch obnova neprošla.
- Hub používá existující DB + `MEDIA_DIR` backup kontrakt a MRK-25 offsite rozhraní; migrace na mini PC musí provést obnovu z kopie, nikdy experiment na jediném originálu.
- Nahraditelná média Jellyfinu mohou mít nižší backup tier, ale konfigurace a metadata služby musí být obnovitelné.

Retention, šifrování a cílový provider patří do konkrétního backup issue. Zde je závazný výsledek: off-machine kopie + pravidelně ověřená obnova.

## 9. Napájení: UPS a NUT

UPS s NUT je doporučená součást infrastruktury. Chrání proti poškození PostgreSQL a filesystemu, umožní graceful shutdown, poskytne stav napájení Home Assistantu a spustí upozornění při výpadku či nízké baterii.

Acceptance test musí ověřit pořadí bezpečného ukončení a čistý start po návratu napájení. Dočasný server na starém notebooku získává část stejné ochrany z vlastní baterie, ale stále potřebuje řízené vypnutí a monitoring jejího stavu.

## 10. Home Assistant a IoT

Home Assistant je autoritativní abstrakce zařízení, senzorů a automatizací. Mosquitto MQTT je budoucí transport pro senzory či DIY IoT, nikoli povinná vrstva od prvního dne.

Možné budoucí scénáře:

- zahradní závlaha a stav ventilů;
- vlhkost půdy, teploty, hladina nádrže nebo průtok;
- Wake-on-LAN herního PC;
- další domácí senzory a bezpečné automatizace.

Jarvis čte stav a žádá akce přes explicitní povolené Home Assistant služby podle MRK-38. Nikdy neposílá příkazy přímo relé, MQTT topicu nebo zařízení.

## 11. Hlas

Wyoming Whisper a Piper jsou budoucí infrastruktura pro MRK-36 Voice Jarvis. Nenasazují se před stabilizací core serveru, Hubu, monitoringu a záloh. Audio pipeline se nestaví v Hubu; Hub zůstává intent/orchestration vrstvou a zachovává pravidla potvrzení akcí.

## 12. Média a fotky

- **Jellyfin** je media server; na Intel hardwaru je preferována hardwarová akcelerace Quick Sync.
- **Immich** spravuje fotky a telefonní backup až po splnění backup gate z §8.

Immich, Jellyfin, Whisper, Nextcloud a Hub současně zvyšují nároky na RAM i I/O. Proto je 32 GB RAM pro celý plán preferováno, i když první fáze může začít se 16 GB.

## 13. Hardware guidance

Silným kandidátem je použitý kancelářský Tiny/Micro/Mini počítač, například řady Lenovo ThinkCentre Tiny, Dell OptiPlex Micro nebo HP EliteDesk Mini. Dokument nedoporučuje konkrétní inzerát ani model.

Žádoucí vlastnosti:

- Intel 8.–10. generace nebo novější a Quick Sync;
- dva RAM sloty;
- možnost začít na 16 GB a rozšířit na 32–64 GB;
- NVMe pro OS a databáze;
- samostatný HDD/SSD pro objemné fotky a média;
- rozumná idle spotřeba, chlazení a možnost připojit UPS.

Intel N100 má výbornou efektivitu, ale zařízení často používají jediný RAM slot a mají omezenou oficiální kapacitu. 32 GB může na některých kusech fungovat mimo oficiální specifikaci. Pro celý plán má kancelářský mini PC s větší paměťovou rezervou bezpečnější upgrade path.

## 14. Fáze nasazení

### Phase 1 — Foundation

Linux, Docker Compose, Tailscale, Caddy, Pi-hole, backup tooling, Uptime Kuma, healthchecks.io heartbeat, ntfy a Diun. Výsledek: obnovitelný a monitorovaný základ bez produkčních osobních dat.

### Phase 2 — Standa Hub

Standa Hub / Jarvis a PostgreSQL. Přesun z Windows až po ověřeném migračním plánu, restore drillu a kontrole `/health`, verzí i záloh. Windows runtime zůstává současným deploymentem do dokončení této fáze.

### Phase 3 — Smart home

Home Assistant, MQTT až podle potřeby, Wake-on-LAN a později zahrada. Jarvis bridge zůstává samostatnou integrační prací MRK-38.

### Phase 4 — Personal data

Paperless-ngx a Vaultwarden. Reálná data se vloží až po splnění jejich backup gate.

### Phase 5 — Food, photos and cloud

Mealie, Immich a Nextcloud/Syncthing s nepřekrývajícími se rolemi. Immich až po ověřené obnově fotografií.

### Phase 6 — Optional

Jellyfin, FreshRSS, Homebox (pokud nebyl potřebný dříve), Frigate a herní servery. Nasazení závisí na reálné potřebě a kapacitě. Voice infrastruktura začíná výhradně s MRK-36, nikoli automaticky v této fázi.

## 15. Dopad na roadmapu Hubu

- **Finance:** zůstávají nativní v Hubu. Pokračuje bankovní import milestone; Actual Budget se nepřidává.
- **Food:** plný nativní Food CRUD/receptový store je nutné přehodnotit. Mealie vlastní recepty, plány i nákupy; Hub Food se mění na konektor a orchestration UX (MRK-54).
- **Life Admin:** Paperless-ngx vlastní dokumenty a Homebox inventář/záruky. Hub vlastní pouze vlastní domény (například subscriptions) a agreguje expirace, připomínky a Jarvis kontext.
- **Home Assistant:** architektura odpovídá MRK-38: server-side token, read-only kontext a allowlistované potvrzované akce.
- **Voice:** infrastruktura odpovídá MRK-36 a nezačne před stabilním core serverem.
- **Calendar:** zůstává podle stávající architektury Hub Calendar + upstream imports; tento dokument Calendar ani Moodle nemění.

Existující roadmap issues se automaticky nemažou ani neruší. Architektonická změna se do nich zapisuje komentářem/vazbou a jejich scope se upraví až při samostatném triage nebo implementaci.

## 16. Linear rozpad a pořadí

Milník **Home Server / Mini PC** používá samostatné issues místo jednoho megatasku:

1. MRK-46 — base OS + Docker Compose;
2. MRK-47 — Tailscale + Caddy + lokální DNS;
3. MRK-48 — Kuma + external heartbeat + ntfy;
4. MRK-49 — backup stack + restore drill;
5. MRK-27 — migrace Standa Hubu na mini PC;
6. MRK-50 — Home Assistant foundation;
7. MRK-51 — UPS/NUT;
8. MRK-52 — Paperless-ngx;
9. MRK-53 — Vaultwarden;
10. MRK-54 — Mealie + read-only Hub connector;
11. MRK-55 — Immich po backup readiness.

Závislosti jsou záměrně sekvenční: osobní data nenastupují před backup/restore vrstvou a Hub se nemigruje před stabilním základem, sítí a monitoringem. Volitelné služby získají vlastní issue až ve chvíli, kdy se skutečně plánují.

## 17. Otevřená rozhodnutí

- Konkrétní host architektura (například bare-metal Linux vs. virtualizace pro Home Assistant) v MRK-46.
- Konkrétní mini PC, rozpočet a finální disková topologie.
- Konkrétní off-machine provider; MRK-25 zůstává provider-independent základ.
- Které volitelné služby mají reálný přínos a kdy si zaslouží samostatný issue.

Tyto body neblokují zdroj-pravdy ani integrační pravidla tohoto dokumentu.
