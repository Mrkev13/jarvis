# Home server (mini PC) – architektura a zdroje pravdy

Stav: **rozhodnuto** (2026-10-09). Linear milník **Home Server / Mini PC**, dokument MRK-45.
Navazuje na [monitoring.md](monitoring.md), [backups.md](backups.md), [offsite-backups.md](offsite-backups.md)
a [module-framework.md](module-framework.md).

Tabulka zdrojů pravdy (§3) a pravidla integrací (§4) platí i pro budoucí moduly Hubu
(Food, Life Admin, Home, Voice). Rozhodují, co Hub staví sám a co jen čte.

---

## 1. Účel

Mini PC je **24/7 produkční základna** pro Standa Hub / Jarvise a domácí služby, nezávislá na
hlavním PC. Hlavní PC zůstává vývojový stroj s vlastní dev DB.

- Dokud mini PC není, běží produkce na současném PC (MRK-23). Všechno se popisuje jako
  Docker Compose / skripty v gitu, takže přesun je obnova ze zálohy, ne nová instalace (MRK-27).
- Raspberry Pi 3B zůstává pro Smart Mirror (MRK-37), ne jako server.

### Hardware (orientačně)

| | Minimum | Doporučeno pro celý seznam |
|---|---|---|
| CPU | Intel N100/N150 | Intel s Quick Sync (N100+ nebo kancelářské „Tiny/Micro/Mini“ i5 8.–10. gen.) |
| RAM | 16 GB | **32 GB** (Immich + Jellyfin + Whisper + Nextcloud + Hub + HA současně) |
| Systém + DB | NVMe 500 GB | NVMe 1 TB |
| Média, fotky | – | samostatný HDD (interní nebo USB) |
| Napájení | – | malá UPS + NUT |

Pozor: řada N100 strojů má jeden slot RAM a oficiálně 16 GB. Použité kancelářské mini PC mívají
dva sloty a 32–64 GB. Koupit s 16 GB a RAM rozšířit později je v pořádku.

---

## 2. Služby a pořadí nasazení

Jedna služba = jeden Linear issue. Další vlna začíná, až předchozí běží a je zálohovaná.

| Vlna | Služba | Role |
|---|---|---|
| 0 Základ | Linux (Debian) + Docker Compose | každá služba v Compose souboru v gitu |
| 0 | Tailscale | jediný vzdálený přístup; **žádné otevřené porty do internetu** |
| 0 | Caddy | interní adresy (`hub.home`, `ha.home`…) + HTTPS; s Tailscale Serve pro telefon |
| 1 Provoz | Uptime Kuma + externí heartbeat + ntfy | dostupnost služeb, alerty na telefon (§5) |
| 1 | Restic/Borg + offsite kopie | zálohy + pravidelný test obnovy |
| 2 Hub | Standa Hub / Jarvis + PostgreSQL | přesun ze současného PC přes zálohu a obnovu (MRK-27) |
| 3 Domácnost | Home Assistant (+ Mosquitto MQTT, až budou senzory) | zařízení, senzory, později zahrada |
| 3 | UPS + NUT | bezpečné vypnutí při výpadku proudu, stav UPS v HA |
| 4 Data | Paperless-ngx (+ Stirling-PDF) | dokumenty, OCR, expirace |
| 4 | Vaultwarden | hesla (kritické – jen s ověřenou offsite zálohou) |
| 5 | Mealie | recepty, jídelníček, nákupní seznam |
| 5 | Immich | fotky z telefonu – **až po ověřeném restore drillu** |
| Později | Nextcloud, Syncthing, Homebox, FreshRSS, Jellyfin, Pi-hole (+ Unbound), Forgejo mirror, Homepage, Wyoming Whisper/Piper (s MRK-36), Frigate (s kamerami) | podle reálné potřeby |

Zamítnuto: **Actual Budget** (duplikuje Finance v Hubu, viz §3) a **Watchtower** (§5).

Pi-hole: DNS přidělovat přes Tailscale (jen vlastní zařízení) nebo s veřejným záložním DNS
v routeru, aby výpadek serveru nevyřadil internet celé domácnosti.

---

## 3. Zdroje pravdy

**Pro stejná data existuje vždy právě jeden zdroj pravdy.** Hub data jinde vlastněná nekopíruje
jako editovatelnou kopii. Čte je, zobrazuje, propojuje a Jarvis nad nimi odpovídá.

| Oblast | Zdroj pravdy | Role Hubu / Jarvise |
|---|---|---|
| Finance (transakce, kategorie, cíle) | **Hub** | Vlastní modul; data přes import layer (bankovní CSV, milník 7.5) |
| Škola, práce, cíle, připomínky, návyky, kalendář, WoT | **Hub** | Vlastní moduly |
| Recepty, jídelníček, nákupní seznam | **Mealie** | Food v Hubu = konektor: dnešní jídlo v Today, „co uvařit / co koupit“ |
| Dokumenty, smlouvy, pojistky | **Paperless-ngx** | Expirace do Today/briefingu, odkazy na dokument, hledání |
| Inventář, sériová čísla, záruky | **Homebox** | Life Admin v Hubu ukazuje končící záruky |
| Zařízení, senzory, automatizace | **Home Assistant** | Stav do Hubu; akce jen přes allowlist (MRK-38) |
| Fotky | **Immich** | Žádná kopie v Hubu |
| Sdílené soubory a dokumenty k práci | **Nextcloud** | pracovní prostor (web, mobil, sdílení) |
| Synchronizace konkrétních složek mezi zařízeními | **Syncthing** | jen přenos, ne archiv; složky se s Nextcloudem nepřekrývají |
| Hesla | **Vaultwarden** | Jarvis k nim **nemá přístup** |
| Studijní materiály | **Moodle** (ČZU) | Hub synchronizuje a čte (MRK-42/44) |

Pravidla:
- Nový modul Hubu začíná otázkou: *„Existuje pro tato data už zdroj pravdy?“* Pokud ano, modul je
  konektor, ne nová databáze.
- Nextcloud a Syncthing smí být vedle sebe jen s oddělenou rolí a bez stejných složek.
- Změna řádku této tabulky je architektonické rozhodnutí: PR + review, ne vedlejší efekt jiné práce.

---

## 4. Pravidla integrací Jarvise

1. **Credentials jen v backendu** (env / soubor mimo repo). Nikdy v repu, logu, Linearu, frontendu
   ani v promptu – **LLM je nikdy nedostane**.
2. **Čtení přes konektory**: deterministický kód volá API služby, normalizuje a omezí data
   a teprve výsledek jde do kontextu Jarvise (P7). Výpadek služby = zdroj „nedostupný“, ne chyba Hubu.
3. **Zápisy jen přes explicitní, validované nástroje** se stejným tokem jako dnes: návrh → potvrzení
   uživatelem → kontrola aktuálnosti → provedení → audit. Žádný obecný „zavolej API“ nástroj.
4. **Allowlist akcí** pro Home Assistant a podobné služby. Nevratné nebo bezpečnostní akce
   (zámky, ventily, topení) jsou vždy jen s výslovným potvrzením, nikdy proaktivně a nikdy jen hlasem.
5. **Import layer** (milník 7.5) je jediný vstup externích dat do vlastních modulů Hubu:
   zdroj → syrový import → parse → normalizace → deduplikace → náhled → potvrzení → doménová služba → audit.
6. Každý konektor je modul s vlastním flagem (MRK-18), takže jde vypnout bez dopadu na zbytek.

---

## 5. Provozní pravidla

- **Hlídání**: Uptime Kuma kontroluje jednotlivé služby (Hub `/health`, PostgreSQL, HA, Paperless…).
  Protože běží na stejném stroji, doplňuje ji **externí heartbeat** (např. healthchecks.io): mini PC
  pravidelně hlásí „žiju“, při výpadku přijde upozornění zvenku. Alerty jdou přes **ntfy** na telefon.
- **Metriky serveru**: CPU, RAM, disky, teploty, SMART (např. Beszel/Netdata) – varování podle
  prahů z [monitoring.md](monitoring.md).
- **Aktualizace**: žádné automatické aktualizace kontejnerů (Watchtower zamítnut). **Diun** jen hlásí
  nové verze; aktualizace ručně: záloha / snapshot → aktualizace → kontrola `/health` a Kuma.
- **Zálohy**: zálohuje se jen nenahraditelné – DB Hubu, `MEDIA_DIR`, konfigurace HA, Paperless,
  Vaultwarden, fotky, dokumenty. Filmy pro Jellyfin se nezálohují. Vždy jedna kopie mimo mini PC
  ([offsite-backups.md](offsite-backups.md)), hlídané stáří záloh a pravidelný test obnovy.
- **Úložiště**: systém a databáze na NVMe; média a fotky na samostatném disku.
- **Napájení**: UPS + NUT – při výpadku se služby a DB korektně vypnou.
- **Síť**: žádné přesměrování portů na routeru; vše přes Tailscale.

---

## 6. Otevřené body

- Konkrétní hardware a rozpočet (podle §1).
- Proxmox (HA OS jako VM + Debian VM s Compose) vs. holý Debian s HA v kontejneru – rozhodne
  issue „Home server base OS“.
- Konkrétní offsite cíl pro zálohy mini PC (navazuje na provider rozhraní z MRK-25).
