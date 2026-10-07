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

1. Zastavte aplikaci a vyberte `runs/backup_<timestamp>.json` se stavem `success`.
2. Ověřte SHA-256 DB dumpu proti `database.sha256` v run metadata.
3. Rozbalte plain SQL dump a obnovte ho standardním `psql` do prázdné PostgreSQL databáze (SQLite kopii rozbalte na cílový DB soubor).
4. Ověřte SHA-256 manifestu proti `media.manifest_sha256`.
5. Pro každý záznam manifestu ověřte `size` a `sha256` souboru na `archive_path`, pak jej zkopírujte do `MEDIA_DIR/<relative_path>`. Cílové soubory s jiným hashem nepřepisujte bez ručního rozhodnutí.
6. Spusťte `alembic -c alembic.ini upgrade head`, pokud je kód novější než obnovený dump.
7. Spusťte backend s jedním workerem a poté frontend; zkontrolujte replaye a screenshoty proti DB.

Run metadata i manifest používají relativní cesty vůči `BACKUP_DIR`, takže lze celý záložní strom přenést na jiný stroj.

## Kapacita

Každý unikátní obsah se archivuje jednou pro danou relativní cestu. Denní režie jsou jen komprimovaný DB dump a malé JSON soubory; nevzniká denní kopie všech replayů. Praktický odhad vypočíte jako `počet replayů × průměrná velikost replaye` plus screenshoty, změněné verze a 30 dní DB dumpů.
