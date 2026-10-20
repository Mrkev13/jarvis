# Zálohy databáze a médií

Jeden běh `backup_service.run_backup()` vytváří konzistentní sadu informací pro obnovu:

1. dump PostgreSQL (nebo komprimovanou kopii SQLite),
2. SHA-256 dumpu,
3. inkrementální archiv souborů z `MEDIA_DIR`,
4. manifest aktuálního stavu médií,
5. run metadata spojující dump s konkrétním manifestem.

Selžání kteréhokoli kroku znamená `failed` v `BackupLog`; běh se netváří jako kompletní záloha.

## Konfigurace

- `BACKUP_ENABLED=true`
- `BACKUP_DIR` nastavte na samostatný disk nebo síťové úložiště.
- `MEDIA_DIR` ukazuje na živé uživatelské soubory.
- `BACKUP_RETENTION_DAYS` určuje uchování DB dumpů, run metadat a manifestů (výchozí 30 dní).
- `PG_DUMP_PATH` lze nastavit na konkrétní `pg_dump`/`pg_dump.exe`.

`pg_dump` se hledá v tomto pořadí: explicitní `PG_DUMP_PATH`, běžný `PATH`, a na Windows standardní instalace `%ProgramFiles%/PostgreSQL/<verze>/bin` (nejvyšší verze první). Neplatný explicitní soubor je chyba s návodem, co opravit; přihlašovací údaje se nelogují.

## Struktura `BACKUP_DIR`

```text
BACKUP_DIR/
├─ standa_hub_<timestamp>.pgdump.gz
├─ runs/
│  └─ backup_<timestamp>.json
└─ media/
   ├─ manifests/
   │  └─ media_<timestamp>.json
   └─ archive/
      ├─ wot-replays/<server-name>.wotreplay
      └─ <parent>/.versions/<filename>/<sha256>--<filename>
```

První obsah dané relativní cesty se uloží přímo pod `media/archive/`. Stejný obsah se při dalším běhu podle SHA-256 přeskočí. Jiný obsah pod stejnou relativní cestou se uloží jako neměnná verze; existující data se nepřepisují. Manifest obsahuje `relative_path`, `size`, `sha256`, `archive_path`, `archived_at` a stav `copied`/`unchanged`.

Soubory odstraněné ze živého `MEDIA_DIR` se z archivu automaticky nemažou. DB dump, run metadata a manifesty se řídí DB retention; archivovaná média jsou záměrně ponechána, dokud je správce výslovně neprořeže. To chrání proti opožděně zjištěnému smazání za cenu růstu podle unikátního obsahu.

## Obnova

Základní pravidla:

- **Nikdy neobnovujte přes živou DB ani přes živé `MEDIA_DIR`.** Obnova jde vždy do nové databáze a nové složky; produkce se přepne až po ověření a původní stav zůstane vedle jako cesta zpět.
- Dokud je produkční DB čitelná, udělejte před jakýmkoli zásahem **novou zálohu aktuálního stavu** (i poškozený stav je důkaz a cesta zpět) a nechte ji být.
- Celý postup (kromě přepnutí) jde provést bez zastavení produkce; aplikace se zastavuje jen na samotné přepnutí.

### Postup (Windows produkce, MRK-23)

Elevovaná PowerShell session (zápis do `C:\StandaHub`, `BACKUP_DIR`, `MEDIA_DIR` a čtení `.env.production` mají jen Administrators + SYSTEM). Hesla nikdy nepište do příkazové řádky ani do historie; `PGPASSWORD` nastavte jen v této session a na konci ji smažte:

```powershell
$s = Read-Host 'Heslo DB' -AsSecureString
$env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
# ... kroky níže ...
Remove-Item Env:PGPASSWORD
```

1. **Zaznamenejte výchozí stav:** `git -C C:\StandaHub rev-parse HEAD`, `/health` (commit, migrace) a bezpečné počty řádků klíčových tabulek.
2. **Vyberte zálohu:** `runs/backup_<timestamp>.json` se `status: success`. Ověřte `Get-FileHash -Algorithm SHA256` dumpu proti `database.sha256` a manifestu proti `media.manifest_sha256`. Nesoulad = stop, zkuste starší běh.
3. **Vytvořte novou prázdnou DB** se jménem, které se nedá splést (`standa_hub_restore_<YYYYMMDD>`); `standa_hub` v tomto kroku nikdy nemažte ani nepřejmenovávejte.
4. **Obnovte dump.** Windows nemá `gunzip` a roura mezi dvěma nativními programy ve Windows PowerShell 5.1 překóduje bajty (rozbije UTF-8), proto přes dočasný soubor ve složce dostupné jen správcům (soubor obsahuje všechna data):

   ```powershell
   $py   = 'C:\StandaHub\.venv\Scripts\python.exe'
   $psql = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
   $dump = '<BACKUP_DIR>\standa_hub_<timestamp>.pgdump.gz'   # z run metadata, hash ověřen v kroku 2
   $sql  = '<složka jen pro správce>\restore.sql'
   $env:PGHOST = 'localhost'; $env:PGUSER = '<db user>'; $env:PGDATABASE = 'standa_hub_restore_<YYYYMMDD>'
   & $py -c "import gzip,shutil,sys; shutil.copyfileobj(gzip.open(sys.argv[1],'rb'), open(sys.argv[2],'wb'))" $dump $sql
   & $psql -X -v ON_ERROR_STOP=1 --single-transaction -f $sql
   Remove-Item $sql
   ```

   `ON_ERROR_STOP` + `--single-transaction` znamená: buď celý dump, nebo nic. Jakákoli chyba ve výstupu = obnova neplatná.
5. **Ověřte DB:** `alembic_version` (viz krok 8), počty řádků proti záznamu z kroku 1 / času zálohy, všechny constrainty `convalidated`, indexy a FK. Očekávané rozdíly, které nejsou chybou:
   - `pg_get_constraintdef` CHECK constraintů vypadá po obnově jinak (`ARRAY[('a'::varchar)::text, …]` místo `(ARRAY['a'::varchar, …])::text[]`); povolené hodnoty i chování jsou stejné.
   - Řádek `backup_logs` běhu, který dump vytvořil, je v obnovené DB `running` (dump vzniká uprostřed běhu).
6. **Obnovte média do nové složky** (např. `…\media_restore_<YYYYMMDD>`): pro každý záznam manifestu ověřte `size` a `sha256` souboru na `archive_path` a zkopírujte ho na `<nová složka>/<relative_path>`. Pak ověřte reference DB proti souborům:
   - `study_materials.stored_name` → `study-materials/<sha256>.<ext>`, SHA-256 souboru = `checksum`, velikost = `stored_size`;
   - `wot_replays.stored_filename` → `wot-replays/`, SHA-256 = `sha256`;
   - `wot_milestone_screenshots.stored_name` → `wot-screenshots/`.
   Žádná chybějící ani neodpovídající položka; DB obsahuje jen jména souborů, nikdy cesty.
7. **Přepnutí (jediný krok s výpadkem):** nezastavujte během běžící zálohy. `Stop-ScheduledTask StandaHub-Frontend`, `Stop-ScheduledTask StandaHub-Backend`, ověřte, že na portu 8000 nikdo neposlouchá a neběží žádný backend proces. Pak přejmenujte, nic nemažte:
   - DB: `ALTER DATABASE standa_hub RENAME TO standa_hub_pre_restore_<YYYYMMDD>;` a `ALTER DATABASE standa_hub_restore_<YYYYMMDD> RENAME TO standa_hub;` (bez aktivních spojení). `.env.production` a jeho ACL tak zůstanou beze změny.
   - Média: živou složku přejmenujte na `media_pre_restore_<YYYYMMDD>` a obnovenou na původní jméno `MEDIA_DIR`. Ověřte, že SYSTEM má do nové složky zápis (backend běží jako SYSTEM).
8. **Schéma vs. kód:** stejná revize = nic nedělat. Kód novější než dump = explicitní `alembic upgrade head` s produkčním env (`RUN_ALEMBIC_UPGRADE_AT_STARTUP` zůstává `false`). Dump novější než kód (neznámá revize) = checkout commitu, který tu revizi zná; nikdy downgrade dat.
9. **Start a ověření:** `Start-ScheduledTask StandaHub-Backend`, pak `StandaHub-Frontend`; `scripts/windows/check-health.ps1 -RequireHealthy`; `/health` = healthy, správný commit, migrace `current`; jeden listener na 8000; v UI projít Home, Kalendář, Školu/materiály, Hledání.
10. **Úklid až po dnech ověřeného provozu** a nové úspěšné záloze obnoveného stavu: teprve pak smažte `standa_hub_pre_restore_*` a `media_pre_restore_*`.

**Přerušení / návrat:** do kroku 7 produkce nic nepoznala – stačí smazat obnovovací DB a složku. Selže-li ověření po přepnutí: zastavte obě úlohy, přejmenujte zpět (`standa_hub` → `standa_hub_failed_restore_<YYYYMMDD>`, `standa_hub_pre_restore_<YYYYMMDD>` → `standa_hub`; totéž pro složku médií), spusťte úlohy a ověřte `/health`. Nikdy nespouštějte druhý backend/scheduler proti obnovené DB.

Run metadata i manifest používají relativní cesty vůči `BACKUP_DIR`, takže lze celý záložní strom přenést na jiný stroj.

### Co záloha pokrývá a co ne

Pokrývá: celou aplikační PostgreSQL DB (všechny tabulky včetně `alembic_version`, tedy i verzi schématu) a všechny soubory pod `MEDIA_DIR` (studijní materiály, replaye, screenshoty).

Nepokrývá (obnovit nebo uložit jinak):

- zdrojový kód a `.venv` (git checkout + pinned závislosti), build frontendu (znovu `start-frontend.ps1 -Build`);
- `backend\.env.production` – heslo DB, `AUTH_PIN_HASH`, VAPID klíče, ICS URL; uložte ho odděleně a offline. Bez původního VAPID privátního klíče přestanou fungovat existující push odběry;
- definice úloh Task Scheduleru (znovu `scripts/windows/register-tasks.ps1`), ACL, AVG/OS nastavení, Tailscale;
- PostgreSQL server, role a oprávnění (dump je `--no-owner --no-privileges`);
- externí služby (Moodle, ICS kalendáře) – jejich data se po obnově znovu stáhnou.

Na tomto stroji leží `BACKUP_DIR` na stejném disku jako produkce a `MEDIA_DIR`; selhání disku zničí obojí. Proto existuje off-machine kopie na B2 (MRK-57, níže), jakmile je nakonfigurovaná. Heslo restic repozitáře a B2 klíč je nutné mít uložené **mimo tento počítač**, jinak kopie po ztrátě PC nejde dešifrovat.

### Restore drill

| Datum | Záloha | Výsledek |
|---|---|---|
| 2026-10-11 | čerstvý běh přes `run_backup()` (0,5 s), PostgreSQL 18 | Obnova do scratch DB `standa_hub_restore_drill` (`psql`, single transaction): 0 chyb, 0,7 s; 43/43 tabulek a všechny řádky shodné s produkcí (kromě očekávaného `backup_logs`), indexy/sekvence/FK identické, CHECK constrainty se stejnými hodnotami a vynucované. Média do scratch složky: 59/59 souborů ověřeno podle manifestu, 0 chybějících referencí, 0 nesouladů SHA-256. Aplikace (jednorázový proces bez scheduleru a bez portu) četla scratch DB/média: `/health` migrace `current`, Kalendář, Návyky, Škola, materiály včetně stažení souborů, Hledání (název i text) a Co se změnilo; žádný zápis. Scratch DB a složka poté smazány. Drill byl lokální, ne z off-machine kopie. |
| 2026-10-20 | **off-machine kopie z Backblaze B2** (restic snapshot `complete` lokálního běhu id 20, produkce `adf0d4c`, migrace 0024) | `python -m offsite_restic restore` do prázdné scratch složky: 9 s, 62 souborů ověřeno podle SHA-256 (kontrakt MRK-25). Dump do scratch DB `standa_hub_b2_restore_drill` (`psql`, single transaction): exit 0, 0 chyb, migrace `0024`. 44 tabulek: 40 bit po bitu shodných s produkcí, 4 se změnily až po záloze (`backup_logs`, `offsite_backup_runs`, `notifications`, `auth_sessions`). Počty sedí (subjects 4, exams 2, calendar_events 8, habits 1, study_courses 1, study_materials 54, domain_events 62, activity_logs 174). Média 59/59 podle manifestu, studijní bloby 45 (0 chybí, 0 nesouhlasí), WoT replaye OK, 16 FK bez sirotků, všechny constrainty platné. Aplikace (jednorázový proces bez scheduleru a bez portu): kalendář 8/8 výskytů, Návyky, Škola, Co se změnilo, 54 materiálů, stažení souborů 6/6 podle SHA, Hledání 5/5 (název) a 3/3 (text); žádný zápis. Scratch DB, soubory i restic cache poté smazány; B2 repozitář a oba snapshoty zachovány. |

## Off-machine kopie

**Produkce (MRK-57): restic → Backblaze B2.** Po každé úspěšné lokální záloze hodinový job scheduleru nahraje znovu ověřený běh (run JSON, dump, manifest a média podle SHA-256) do šifrovaného, deduplikovaného restic repozitáře na B2. Retence je 14 denních, 8 týdenních a 12 měsíčních záloh. Kontrola metadat běží zhruba denně, kontrola vzorku dat a prune jednou týdně. Stav je v `/health.offsite`; selhání pošle upozornění. **Lokální záloha na síti nikdy nezávisí.** Nastavení B2, tajných hodnot, provoz a obnova z B2: [offsite-backups.md](offsite-backups.md). Původní MRK-25 knihovna (TAR + age + filesystem target) slouží jako kontrola integrity běhu před nahráním a po obnově.

## Kapacita

Každý unikátní obsah se archivuje jednou pro danou relativní cestu. Denní režie jsou jen komprimovaný DB dump a malé JSON soubory; nevzniká denní kopie všech replayů. Praktický odhad vypočíte jako `počet replayů × průměrná velikost replaye` plus screenshoty, změněné verze a 30 dní DB dumpů.
