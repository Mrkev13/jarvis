# Standa Hub – Backend AGENTS Reference

## 1. Stack a celková architektura

- **Backend**: FastAPI + SQLAlchemy 2.x (declarative Base v `models.py`) + `database.py` (SessionLocal / engine).
- **DB**: Primárně Postgres; SQLite (přes `DATABASE_URL`) podporováno pro testy / offline fallback. Žádné runtime `ALTER TABLE` ani `create_all` – schéma spravuje výhradně **Alembic** (viz kapitola 3).
- **Závislosti**: `requirements.txt` je pinnutý na ověřené verze (vč. `tzdata` pro `zoneinfo` na Windows). Groq se volá přes balíček `openai` (OpenAI-kompatibilní API).
- **Čas**: timestampy v DB jsou naive UTC; kalendářní logika je v Europe/Prague přes `time_utils.py` (viz kapitola 11).
- **Frontend**: Next.js 16 App Router (TypeScript) + Tailwind. Port `3000` běží samostatně, komunikuje s BE přes `NEXT_PUBLIC_API_URL` (typicky `http://…:8000`).
- **Spouštění BE ( produkce )**:
  ```
  uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
  ```
  `--workers 1` je **VYŽADOVÁNO**, protože APScheduler BackgroundScheduler běží per-process (bez DB advisory locku by se hourly job spustil N×).

---

## 2. Activity Log (`activity_service.py`, `ActivityLog`)

**Účel**: Audit trail napříč všemi moduly (Work / Finance / Goals / Memory / School / MFF / WoT / AI / System). Vždy je zapsán společně se změnou business dat.

### 2.1 Transakční model (kritické)

**`log_activity()` NEDĚLÁ vlastní `commit()` ani `flush()` kromě dedupe checku.**  
Vzorové použití (vždy jeden společný commit):

```python
from activity_service import log_activity
tx = FinanceTransaction(amount=2437, kind="income")
db.add(tx)

log_activity(db, "finance", "create", "Finance income +2 437 Kč",
             entity_type="FinanceTransaction", entity_id=tx.id,
             delta=delta_dict(old_tx_state, tx, ["amount", "kind"]),
             user_context="manual")   # nebo "ai_confirm"

db.commit()   # JEDEN commit pro tx i audit
```

Pokud insert ActivityLog selže (např. UNIQUE constraint na `dedupe_key`), vyhodí SQLAlchemy výjimku **před** commitem → business změna se taky neprovede (atomicita).

### 2.2 Služba

`log_activity(db, area, action_type, summary, *, entity_type, entity_id, delta, user_context, dedupe_key) -> ActivityLog | None`

- `db.flush()` se provede pouze před `SELECT 1` kontrolou duplicity dle `dedupe_key`, aby se detekovaly i necommitované řádky v rámci stejné session.
- Pokud `dedupe_key` už existuje, vrátí `None` (idempotentní 2× volání).
- Default `dedupe_key` = `{area}:{action_type}:{entity_type}:{entity_id}:{md5(summary)[:8]}`.
- Indexy: `ix_activity_logs_created_at`, `ix_activity_dedupe_key` (UNIQUE).

### 2.3 9 Areas

| area      | Barva FE | Příklady                                                                      |
|-----------|----------|-------------------------------------------------------------------------------|
| `finance` | green/red/gray | income +2 437 Kč, expense −500 Kč, transaction_delete                       |
| `work`    | modrá    | Work session +7,5 h, edit session, sync→finance                              |
| `goals`   | fialová  | Cíl „150 000 Kč“ 9 % → 11 %, create_goal, delete_goal                        |
| `memory`  | šedá     | Memory updated (upsert), new_chat_msg                                         |
| `school`  | oranžová | Assignment done, new assignment, grade updated                                |
| `mff`     | tyrkysová | T4 built, build progress, dispatch updated                                   |
| `wot`     | tmavě zelená | Resource gathered, grind completed, battle result                           |
| `ai`      | světle modrá | Pending action confirmed/rejected, Planner review, tool_call                 |
| `system`  | tmavě šedá | Scheduler ran, backup created, expired pending cleanup, session invalidated  |

### 2.4 Endpointy

- `GET /activity` – filtry `area`, `action_type`, `limit`, `offset`, `from_date`, `to_date`, `q` (full-text LIKE). Vrací stránkovaný seznam.
- `GET /activity/{id}` – jeden záznam s parsovaným `delta` JSON.
- `GET /dashboard` – `recent_activity: list[5]` nejnovějších záznamů; **read-only, nevytváří GoalProgressHistory snapshoty**.

---

## 3. Alembic migrace (8 revizí)

Alembic je **jediný vlastník schématu**. `Base.metadata.create_all` se v produkčním startu nevolá
(používají ho jen unit testy na in-memory SQLite).

### 3.1 Pořadí revizí

| Soubor (v `backend/alembic/versions/`) | Tabulky / účel                                                      |
|----------------------------------------|---------------------------------------------------------------------|
| `0001_initial_baseline.py`             | 15 původních tabulek (BEZ activity, pending, backup, auth)         |
| `0002_activity_log.py`                 | `activity_logs` (10 sloupců, `ix_activity_dedupe_key` UNIQUE)      |
| `0003_pending_actions.py`              | `pending_actions` (6 sloupců, FSM index `ix_pending_status_created`) |
| `0004_goals_sources.py`                | Marker no-op (změny v goal source logic jsou čistě Python, DB nemění) |
| `0005_backup_log.py`                   | `backup_logs` (10 sloupců)                                          |
| `0006_auth_sessions.py`                | `auth_sessions` (8 sloupců)                                         |
| `0007_reconcile_schema_drift.py`       | Sjednocení názvů/existence indexů a NOT NULL s `models.py` (viz 3.4) |
| `0008_conversation_summary.py`         | `conversations.summary` (Text) + `summarized_until_message_id` (Integer), oba nullable (kap. 16) |

### 3.2 Startup (FastAPI lifespan)

Při **importu** `main.py` se na DB nesahá. Vše běží v `lifespan` při startu aplikace:

```
lifespan:
  RUN_ALEMBIC_UPGRADE_AT_STARTUP (default true)
      ? run_migrations()  → alembic upgrade head   (chyba = FATÁLNÍ, server nenastartuje)
      : jen log – schéma musí být na head ručně (alembic upgrade head)
  → _seed_default_subjects()         (jen pokud tabulka subjects je prázdná)
  → _recover_pending_actions()       (viz 4.3)
  → start_scheduler()                (jen pokud SCHEDULER_ENABLED=true)
  … aplikace běží …
  shutdown → stop_scheduler()
```

`run_migrations()` používá absolutní cesty (`script_location`, `version_locations`), funguje z libovolného cwd.
`alembic/env.py` volá `fileConfig(..., disable_existing_loggers=False)`, aby upgrade uvnitř uvicornu nevypnul jeho loggery.

**Pozor – žádný `alembic/__init__.py`.** Složka `backend/alembic/` nesmí být Python balíček: při startu
z `backend/` (`python -m uvicorn`) by zastínila knihovnu `alembic` (`ModuleNotFoundError: alembic.config`).
Hlídá to test `test_alembic_library_importable_from_backend_dir`.

### 3.3 CLI (ruční spouštění)

```
cd backend
alembic -c alembic.ini current
alembic -c alembic.ini upgrade head
alembic -c alembic.ini downgrade -1
```

(`alembic.ini` má `prepend_sys_path = .`, `env.py` bere `DATABASE_URL` z prostředí / `.env`.)

### 3.4 Schema drift (0007) a regresní testy

Produkční PostgreSQL byla původně vytvořena přes `create_all` (bez `alembic_version`) a před Roadmap 3.0
stampnuta na `0006_auth_sessions`. Její indexy / NOT NULL se lišily od migrací i od modelů. `0007`:

- se řídí aktuálním stavem DB (inspector) → idempotentní pro čistou DB (0001→0007) i stampnutou produkci,
- **nejdřív zkontroluje NULL** ve sloupcích, které mají být NOT NULL; při nálezu migraci přeruší s výpisem
  (žádné vymýšlení hodnot) – oprav data a spusť znovu,
- downgrade vrací tvar dle řetězce 0001→0006 (ne původní nekonzistentní stav create_all DB).

Regresní testy:
- `SchemaDriftTestCase.test_head_matches_models` – čistá SQLite na head == `models.py` (`compare_metadata == []`).
  **Každá nová migrace musí tento test udržet zelený.**
- `tests/test_migration_postgres.py` – opt-in proti skutečnému PostgreSQL; spouští se jen s
  `TEST_POSTGRES_URL` na jednorázovou DB s `test` v názvu (prázdná DB i obnovená kopie produkce z `pg_dump`).
  Novou migraci vždy nejdřív ověř na obnovené kopii, teprve pak na produkci.

---

## 4. Persistent Pending Actions + 6-stavový FSM

**Původní problém**: RAM `_pending_actions = {}` ztrácela data po restartu. Řešení: DB tabulka `pending_actions`.

### 4.1 Stavový automat

```
 pending ──confirm──▶ executing ──success──▶ executed
    │                    │
    ├─reject             └─────▶ failed
    └─expire (TTL)
```

### 4.2 Atomická confirmace (dvojklik ochrana)

`ai.py → _confirm_pending_action_atomically(action_id)`:

```python
stmt = update(PendingAction) \
         .where(and_(PendingAction.id == pk, PendingAction.status == "pending")) \
         .values(status="executing", executed_at=now())
res = db.execute(stmt); db.commit()
if res.rowcount != 1:
    raise HTTPException(status_code=409, detail="Race: už potvrzeno / vypršelo")
```

Kvůli `rowcount==1` lze záznam potvrdit **přesně jednou**, i když uživatel dvakrát klikne na Confirm.

### 4.3 Startup recovery

Při startu backendu (v lifespan, hned po Alembic upgrade) – `main._recover_pending_actions()`:

1. `status="pending" AND expires_at < now()` → `status="expired"`
2. `status="executing" AND created_at < now()-15 min` → `status="failed"`

Pozn.: tabulka `pending_actions` zatím **nemá** sloupce `executed_at` / `error_message`, proto recovery
používá `created_at` (a ukázka v 4.2 s `executed_at` je cílový stav). Doplnění sloupců a přechod na
`executed_at` je naplánován v Roadmap 3.0 fázi B1.

### 4.4 JSON shape zpětná kompatibilita

`/chat` response stále vrací:

```json
{ "answer": "...",
  "pending_actions": [{ "id": 42, "tool": "add_work_session",
                        "arguments": {...}, "expires_at": "2026-09-26T10:58:00" }] }
```

---

## 5. Automatic Goals 2.0 – 1 místo pravdy

**Duplicitní kód před REV.2**: stejný `source -> current_value` byl implementován v `goal_history_service.py` i `tools.py`.  
**Nyní**: jediná funkce `compute_automatic_goal_current_value(db, source, goal=None) -> (float, ok)` v `goal_history_service.py`. Všechny ostatní cesty (AI tools, Dashboard, Planner, hourly scheduler) **pouze delegují**.

### 5.1 13 goal sources

| Kategorie  | Source                           | Poznámka                                                                                  |
|------------|----------------------------------|-------------------------------------------------------------------------------------------|
| Finance    | `finance_month_income`           | `created_at BETWEEN first_day(year,month) AND last_day(year,month)` – **explicitně ROK i MĚSÍC**. |
| Finance    | `finance_month_expenses`         | obdobně, `kind='expense'`.                                                                |
| Work       | `work_month_earnings`            | `date BETWEEN first_day AND last_day`, `SUM(earnings)`.                                   |
| Work       | `work_total_hours`, `work_month_hours` | původní 4 sources zachovány.                                                         |
| School     | `school_completed_assignments`   | `status` v lowercased množině `{hotovo, done, completed, finished}`.                      |
| School     | `school_open_assignments`        | **`total - completed`** (tedy NULL status se automaticky počítá jako open, místo `NOT IN` které by NULL řádky vyřadilo). |
| MFF        | `mff_t4_count`                   | celkový počet T4 entit (WHERE entity_class='T4').                                         |
| MFF        | `mff_built_t4_count`             | build_completeness==1.0 (auto-computed 8 komponent).                                      |
| MFF        | `mff_high_priority_built_count`  | priorita='high' AND built.                                                                |
| Cíl obecně | `goal_target_fixed`, `goal_manual_progress` | původní zachované.                                                                 |

### 5.2 Snapshot politiky

- **write operace** (Work session create/finish, Finance upsert, School assignment toggle, …) → `ensure_goal_progress_snapshot()` PŘESNĚ když `before_pct != after_pct`.
- **hourly scheduler** → snapshot pro VŠECHNY aktivní automatic cíle (i beze změny, pro audit).
- **GET /dashboard** → **read-only, žádný snapshot nevytváří**.

---

## 6. Background Scheduler (APScheduler, single-worker)

### 6.1 Konfigurace

- `APScheduler 3.x BackgroundScheduler`, `IntervalTrigger(seconds=SCHEDULER_INTERVAL_SECONDS)`.
- Default: `SCHEDULER_ENABLED=false`, `SCHEDULER_INTERVAL_SECONDS=3600` (1× hodině).
- Job options: `coalesce=True`, `max_instances=1` (nikdy nena堆叠ovat hodinové joby za sebou).

### 6.2 Hourly job (`_run_hourly_job()`)

1. **Goal snapshots**: `ensure_goal_progress_snapshot_for_all_active_automatic_goals()` + audit System ActivityLog.
2. **Notifications**: `create_all_upcoming_deadline_notifications(db)` (14/7/3 dní před deadlinem, dedupe dle `(entity,date,type)`).
3. **Backup**: `should_run_backup_daily(hour)` + `run_backup(db)` → pouze když `hour>=BACKUP_HOUR_OF_DAY=3` a dnes ještě žádný success záznam.

### 6.3 Endpointy

- `GET /scheduler/status` – běží/nenaběhlý, poslední běh, příští běh.
- `POST /scheduler/run-now` – manuální okamžitý spust (pro testing / diagnostiku).

### 6.4 Single-worker constraint

```
⚠️  Scheduler podporuje POUZE 1 backend worker (--workers 1).
    Pokud pustíš více workers, hourly job poběží X× na každém procesu.
    Pro více workers je potřeba později přidat DB advisory lock nebo Redis RLock.
```

---

## 7. Automatické zálohy (`backup_service.py`, BackupLog)

### 7.1 Strategie dle DB driveru

- **Postgres** (`DATABASE_URL` obsahuje `postgresql`):
  ```
  pg_dump --no-owner --no-privileges -U user dbname | gzip > BACKUP_DIR/standa-hub-{ts}.sql.gz
  ```
- **SQLite** (`sqlite+pysqlite://…`): kopie `fileobj` přes `shutil.copyfileobj` → gzip → `BACKUP_DIR/standa-hub-{ts}.db.gz`.
- `pg_dump`: `PG_DUMP_PATH` → `PATH` → na Windows standardní `%ProgramFiles%/PostgreSQL/<verze>/bin`.
- Po DB dumpu stejný běh inkrementálně archivuje `MEDIA_DIR`; stejný SHA-256 přeskočí, změněnou
  relativní cestu uloží jako neměnnou verzi a existující obsah nepřepíše.

### 7.2 Verifikace + retention

- `_verify_backup(path, size, checksum)`: velikost i `SHA256` souboru souhlasí.
- `media/manifests/*.json`: relativní cesta, velikost, SHA-256, cesta v archivu, čas archivace a copied/unchanged.
- `runs/*.json`: timestamp, DB dump + checksum a konkrétní media manifest + checksum. Chyba médií znamená
  `BackupLog.status="failed"`.
- `_apply_retention`: po `BACKUP_RETENTION_DAYS` smaže DB dump, run metadata, manifest a `backup_logs` řádek.
  Neměnný archiv médií nemaže automaticky, takže smazaný živý soubor zůstane obnovitelný.

### 7.3 BackupLog status FSM

```
 running ──ok──▶ success   │   BACKUP_HOUR_OF_DAY default = 3 (03:00 Europe/Prague)
    └──err──▶ failed       │   1× / den (hourly scheduler 24×, ale jen 1× proběhne)
```

`should_run_backup_daily(hour_of_day, now_utc=None)`: hodina i „dnes už proběhla" se vyhodnocují
v pražském čase (den = pražská půlnoc → půlnoc převedená do UTC), nezávisle na DST.

### 7.4 Endpointy

- `POST /backup/run-now` – manuálně spusť zálohu.
- `GET /backup/list?limit=20` – seznam BackupLog, poslední N záznamů.

### 7.5 Off-machine kopie (`offsite_backup.py`)

- Zpracují jen dokončený schema-v1 run se `status="success"`; DB dump, manifest i všechna média musí projít kontrolou velikosti a SHA-256.
- Zdroj zůstává read-only. Self-contained TAR vzniká ve scratch adresáři a zachovává relativní layout stávajícího backupu.
- `LocalFilesystemOffsiteTarget`: zapisuje a fsyncuje do unikátní `.staging-*` složky, completion marker zapíše poslední a teprve pak rename na immutable run ID; crash před rename neblokuje retry. Staré staging složky lze bezpečně prořezat přes dry-run `cleanup_abandoned_staging`. Žádný overwrite existujícího run ID; provider child symlinky/junctions se odmítají.
- `AgeEncryptor`: externí `age`; povinné šifrování vyžaduje encryption i decryption capability a před publikací musí projít decrypt + úplná checksum verifikace. Klíč/secret ani cesta identity se neukládají do metadata/statusu.
- Retention je provider-independent politika: nejnovější run v 14 daily, 8 ISO-weekly a 12 monthly bucketech (Europe/Prague), sjednocení bez duplicit; nejnovější validní run zůstává vždy. `cleanup_retention` je pouze dry-run. Reálně maže jen uzavřená operace `apply_verified_retention`: stáhne a ověří kandidáty, naplánuje, znovu ověří všechny `keep` runy a až potom maže. Invalid/incomplete/corrupt run se automaticky nemaže.
- Restore verification vždy pracuje nad staženou kopií v temp: decrypt, bezpečná TAR extrakce, DB/manifest/media checksumy. Absolutní/`..` cesty, symlink, hardlink a speciální TAR členy jsou zakázané.
- Výsledky mají jen allowlisted kategorie pro local backup, encryption, transfer, verification a cleanup. Žádné zapojení do scheduleru, notifikací nebo `/health`; integrační kontrakt je v `docs/offsite-backups.md`.

---

## 8. Auth/PIN systém – 2-vrstvá ochrana

**Architektonická důležitá poznámka z REV.2 review**: FastAPI middleware **nemůže chránit Next.js FE routy**, protože port 3000 obsluhuje Next.js, ne FastAPI. Proto 2 vrstvy.

### 8.1 Vrstva 1 – FE (Next.js middleware.ts)

- `matcher` např. na `/((?!login|_next|api/public|favicon.ico).*)`.
- PUBLIC_PATHS: `/login`, `/`, `/activity`, `/_next/*` (lze přidat / odebrat dle potřeb privacy).
- Fetch na `BE /auth/session/validate` s `credentials: include`.
  - `auth_disabled=true` → rovnou `NextResponse.next()`.
  - `valid=false` nebo fetch selhalo → **307 redirect** `/login?next=${pathname+search}`.
  - Fetch selhalo z důvodu BE downtime → lenient `next()` (BE si pořád ověří Depends).
- Catch chyb: `catch { next() }`.

### 8.2 Vrstva 2 – BE (globální FastAPI dependency)

- `require_auth` je **globální** dependency (`FastAPI(dependencies=[Depends(require_auth)])`) → platí pro všechny routy,
  i pro budoucí `APIRouter`y přidané přes `include_router`.
- Allowlist bez session: `AUTH_PUBLIC_PATHS = {"/", "/auth/login", "/auth/logout", "/auth/session/validate"}`.
- 401 JSON pokud session cookie chybí / neplatná / vypršelá / revokovaná.
- AUTH_PIN_HASH prázdný → **graceful degradation, auth je vypnutý**.
- FE posílá cookie přes `lib/api.ts → apiFetch()` (`credentials: "include"`, na 401 redirect na `/login?next=…`).
  FE otevírej na stejném hostu jako `NEXT_PUBLIC_API_URL`, jinak je cookie cross-site a neodejde.
- State-changing endpointy jsou POST/PATCH/DELETE (např. `POST /ai/reject/{id}`; GET → 405).

### 8.3 Pin hash + token storage

- **bcrypt 12 rounds**, vstup oříznut na max `72B` (`pin.encode()[:72]`).
- Rate limit per-IP paměťový:
  ```
  5 neúspěšných pokusů  → 300 s lock
  10 neúspěšných pokusů → 600 s lock
  ```
- Token generace: `secrets.token_urlsafe(32)` → plaintext token (v cookie).  
  V DB uložen **SHA256 hash**: `hashlib.sha256(token_plaintext.encode()).hexdigest()`.  
  (Kompromitace DB neodhalí aktivní session cookies.)
- Cookie: `HttpOnly`, `SameSite=Lax`, `Secure=AUTH_COOKIE_SECURE` (default **false** – produkci přes Tailscale HTTPS nastavit na true).
- `validate_session()` refreshne `last_seen_at` každých 5 min (redukce writeů).
- Expirace: `AUTH_SESSION_TTL_MINUTES` default = 1440 (24 h).
  Alternativně `AUTH_SESSION_TTL_HOURS` (má přednost, např. `12` nebo `0.5`). Jméno cookie: `AUTH_COOKIE_NAME`
  (default `standa_hub_session`, frontend middleware musí používat stejné).

### 8.4 Endpointy

- `POST /auth/login { pin }` → `{ ok, auth_disabled, until }` (HttpOnly cookie).
- `POST /auth/logout` → smaže AuthSession z DB + vymaže cookie.
- `GET /auth/session/validate` → `{ valid, auth_disabled, until, user_context_hint }`.

### 8.5 Nastavení PINu (první inicializace)

```python
from auth_service import _hash_pin
print(_hash_pin("123456"))
# výsledek ulož do backend/.env: AUTH_PIN_HASH=$2b$12$…
```

---

## 9. Spouštěcí checklist (24/7 provoz)

| Krok | Co nastavit / ověřit                                                                                  |
|------|-------------------------------------------------------------------------------------------------------|
| 1.   | `DATABASE_URL` → Postgres produkční instance (SQLite jen pro dev/test).                              |
| 2.   | `RUN_ALEMBIC_UPGRADE_AT_STARTUP=true`. Alternativa: ručně `alembic upgrade head` před prvním spuštěním. |
| 3.   | `SCHEDULER_ENABLED=true` + spouštět **`--workers 1`**.                                                 |
| 4.   | `BACKUP_ENABLED=true`. Nastavit `BACKUP_DIR=/srv/backups` na samostatný disk / síťový úložiště.       |
| 5.   | `AUTH_PIN_HASH=bcrypt_hash` + `AUTH_COOKIE_SECURE=true` **až když běžíš přes HTTPS / Tailscale Serve**. |
| 6.   | Firewall / Tailscale ACL: omezit přístup na :8000 a :3000 jen důvěryhodné sítě.                       |
| 7.   | `GROQ_API_KEY` / `OPENAI_API_KEY` doplněny (pokud chceš používat AI / Planner v produkci).            |
| 8.   | Automatický restart processu: `systemd --user` nebo NSSM (Windows) pro `uvicorn … --workers 1`.        |

---

## 10. Související artefakty

- Spec + tasks (schválené REV.2): `.trae/specs/roadmap-7bodu/spec.md`, `.trae/specs/roadmap-7bodu/tasks.md`.
- Testy: `python -m unittest discover -s backend/tests -p "test_*.py"` (z kořene repa). Klíčové soubory:
  `test_alembic_migration.py` (migrace, drift guard, lifespan startup), `test_migration_postgres.py` (opt-in PG),
  `test_auth.py` + `test_auth_enforcement.py`, `test_pending_persistent.py`, `test_ai_read_tool_args.py`,
  `test_ai_system_prompt_date.py`, `test_time_utils.py`, `test_finance_local_month.py`, `test_backup.py`.
- Testy importují modul s `os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")` **před** importem
  backendu – nikdy nesahají na produkční DB z `.env`.

---

## 11. Čas a časová pásma (`time_utils.py`)

- **Úložiště**: všechny `DateTime` sloupce jsou **naive UTC** (`datetime.utcnow`). Žádná migrace dat.
- **Kalendář aplikace**: Europe/Prague (`APP_TZ = ZoneInfo("Europe/Prague")`, data z balíčku `tzdata`).
- Helpery: `now_local()`, `today_local()`, `to_local()`, `local_to_utc()`,
  `local_day_bounds_utc(d)`, `local_week_bounds_utc(d)` (po–ne), `local_month_bounds_utc(d)`.
  Hranice vrací naive UTC jako **polouzavřený interval `[start, end)`** → v dotazech `col >= start AND col < end`.
  DST je ošetřené (den má 23/24/25 h).
- **AI**: `ai.build_system_prompt()` přidává do system promptu při **každém** requestu
  `CURRENT APPLICATION DATE: YYYY-MM-DD (den v týdnu)` + aktuální pražský čas – model neodhaduje „dnes/zítra".
- **Finance**: `finance_month_income/expenses` (goal sources) i dashboard měsíční součty počítají pražský
  kalendářní měsíc (transakce 1. 10. v 00:30 Praha = 30. 9. 22:30 UTC patří do října).
- **Zálohy**: `BACKUP_HOUR_OF_DAY` = pražská hodina.
- Pozn.: `WorkSession.date`, `Assignment.due_date` apod. jsou čisté `Date` (lokální kalendářní data) – bez konverze.

---

## 12. LLM konfigurace a rozpočet tokenů (`llm_config.py`, `llm_budget.py`)

- **Konfigurace** (`LLM_SETTINGS`, z env / `.env`; prázdné = default): `GROQ_MODEL` (`openai/gpt-oss-120b`),
  `GROQ_SUMMARY_MODEL` (= `GROQ_MODEL`), `GROQ_BASE_URL`, `AI_MAX_FIXED_TOKENS` (3500),
  `AI_CONTEXT_TARGET_TOKENS` (500) / `AI_MAX_CONTEXT_TOKENS` (600) pro CURRENT STATE prefetch (kap. 15).
  Klíč `GROQ_API_KEY` (fallback `OPENAI_API_KEY`) se čte jen při vytvoření klienta v `ai.py`.
- **Odhad tokenů** (`llm_budget.py`): deterministický, bez tokenizeru – ~4 ASCII znaky / token, ne-ASCII znak 2×.
  `estimate_fixed_overhead(system_prompt, tools)` = system prompt (vč. A1 data/času) + kompaktní JSON tool schémat.
- **Groq free tier = 8 000 TPM** a celá fixní režie se posílá v *každém* LLM volání (i v každém tool kole).
  Proto platí pevný limit **3 500 odhadovaných tokenů** pro *routovanou* sadu toolů (A5, kap. 17), hlídaný
  `test_tool_router.py`; plná sada všech toolů (`AI_TOOL_ROUTING=false` / nouzový fallback) má strop 4 500 (Phase B: ~4 340)
  (`FixedOverheadBudgetTestCase`, všechny dny v týdnu, CET i CEST). Za běhu `ask_ai` jen loguje warning,
  pokud režie poslané sady překročí `AI_MAX_FIXED_TOKENS` (request neblokuje).
- **Pravidla pro tool schémata** (přidávej do `tool_registry.TOOL_SPECS`, kap. 17): obecná pravidla (potvrzení zápisu, paměť,
  nevymýšlení dat) patří do `SYSTEM_PROMPT`, ne do popisů toolů. Popis = krátce *co* tool dělá + jen
  nezbytné rozlišení. Jména, parametry a `required` musí sedět s Python funkcí (`ToolRegistryTestCase`);
  READ tooly začínají `get_`, WRITE `add_`/`update_`/`upsert_`/`save_` (prompt je podle jména rozlišuje).
  Interní `user_context` se LLM nikdy nevystavuje.
- **Kontrakt s frontendem**: planner JSON blok (` ```json ` + `summary`, `actions[priority, area, title, reason]`)
  parsuje `frontend/app/ai/page.tsx → tryParseWeeklyPlan`; hlídá `SystemPromptSafetyTestCase`.
- Nový tool = záznam v `tool_registry.py` s oblastmi (`areas`); routing (A5) ho pošle jen u dotazů z jeho oblasti.
- **Reálné měření (gpt-oss-120b)**: skutečné `prompt_tokens` ≈ 0,77 × odhad (odhad je záměrně konzervativní);
  fixní režie ≈ 2 700 skutečných tokenů na volání. Groq limit potvrzen hlavičkou `x-ratelimit-limit-tokens: 8000`.

---

## 13. Retry a observabilita LLM (`llm_usage.py`)

- SDK retry je vypnuté (`GROQ_SDK_MAX_RETRIES=0`); retry dělá jen `ai._llm_create_with_retry`
  (`AI_LLM_MAX_ATTEMPTS`, default 3). Po 429 čeká dle `retry-after` / „try again in …" (max
  `AI_LLM_RETRY_MAX_WAIT_SECONDS`). Dřív SDK tiše retryovalo 2× uvnitř každého aplikačního pokusu.
- Logger `standa_hub.llm` (vlastní handler, `AI_USAGE_LOG=false` vypne) loguje **jen čísla**:
  - každé volání: `prompt_tokens`, `completion_tokens`, `total_tokens`, `latency_ms`, `tool_calls`,
    `rl_remaining_tokens` (hlavička `x-ratelimit-remaining-tokens`), 429 / API chyby,
  - každý retry: důvod, pokus, čekání,
  - souhrn requestu (`ask_ai`): počet volání, `tool_rounds`, součty tokenů, latence, počet 429,
    `planner_nudged`, `planner_actions_removed`, A5: `tools_exposed`, `tool_schema_tokens`, `tool_route`
    (`areas`, `areas+write`, `write_unknown_area`, `generic`, `greeting`, `disabled`, `fallback`), `route_widened`.
- **Nikdy** se neloguje obsah promptu, zprávy uživatele, argumenty toolů, odpovědi ani klíče
  (hlídá `test_llm_observability.py`).
- 429 log obsahuje **druh limitu** z Groq zprávy (`limit=TPM|TPD|RPM|RPD`). Denní limity (`TPD`, `RPD`)
  se **neretryují** – čekání v sekundách nepomůže; uživatel dostane hlášku o denním limitu. Free tier
  gpt-oss-120b má kromě 8k TPM i denní limit tokenů – opakované ladicí běhy ho umí vyčerpat
  (`rl_remaining_tokens=8000`, a přesto 429 = typicky TPD).

---

## 14. Planner: routing a grounding (`main.detect_planner_intent`, `planner_guard.py`)

- **Rychlá cesta** (`detect_planner_intent` → rule-based `generate_plan`, bez LLM):
  dotazy na datum/čas (`DATE_TIME_QUESTION_SIGNALS`) jdou vždy na model; týdenní intent se kontroluje
  **před** denním („co mám dělat tento týden", „týdenní plán" ⊃ „denní plán"). Regrese: `test_planner_intent.py`.
- **LLM planner** (odpověď s ```json planner blokem) prochází v `ask_ai` pojistkami:
  0. zavolá-li model `get_goals` bez `get_memories`, server přidá `get_memories` do **téhož kola**
     (`_with_planner_memories`) – bez dalšího LLM volání. Model paměť v reálu často vynechá a připomínka
     by stála celé další kolo (~3k tokenů) → v ověřovacím běhu to přetáhlo 8k TPM;
  1. přijde-li planner odpověď úplně bez `get_goals`, model dostane **jednou** systémovou připomínku a pokračuje;
  2. `ground_planner_answer` odstraní akce, jejichž čísla s jednotkou / velká čísla, data, projekty
     (po slově „projekt…") nebo vlastní jména nejsou v evidence (tool výsledky tohoto requestu, zprávy
     uživatele, aktuální datum) ani z ní nejdou dopočítat (a±b, a·b, a/b·100 – jen pro hodnoty ≥ 100;
     přímá shoda ±0,51 nebo ±1 % kvůli zaokrouhlení). Čísla z tool výsledků se berou z JSON **hodnot**
     kromě metadat (`id`, `*_id`, `importance`); ISO data/timestampy a časy se jako čísla nepočítají
     (data se ověřují zvlášť) – jinak by např. rok 2026 „ověřil" vymyšlených 2 000 Kč (reálný případ).
     Obecné rady bez konkrétních hodnot guard neodstraňuje (to řeší jen prompt).
     Nezbude-li žádná akce, JSON blok se nahradí poznámkou (karta se nevykreslí). Testy: `test_planner_grounding.py`.
- Heuristika je záměrně přísná (raději méně akcí). Výstup pro UI zůstává kontraktem `tryParseWeeklyPlan`.

---

## 15. Server-side context prefetch (A3, `context_service.py`)

**Proč**: model (gpt-oss-120b na Groq) volá **1 tool na kolo** a `parallel_tool_calls=True` to nemění
(ověřeno reálně: API parametr přijme, ale vrací 1 tool call). Dotazy typu „co mám zítra" tak stály
3–6 kol × ~3k tokenů → 429 na 8k TPM. A3 proto data **předem načte serverem** a model odpovídá z nich.

- `ask_ai` před prvním LLM voláním zavolá `build_current_context(db, poslední_zpráva)` a vloží výsledek
  jako **druhou system zprávu** (hned za system prompt, před historii). Chyba prefetch = warning a request
  pokračuje bez kontextu (model si data načte tooly).
- **Výběr oblastí** `classify_areas`: deterministická klíčová slova bez diakritiky + jména projektů/tanků z DB.
  Čas/plán (zítra, dnes, týden, plán, priority, myslet…) → škola + cíle + upozornění; finance → finance + cíle;
  práce/projekt → práce + finance + cíle; WoT/tank → WoT; „jak jsem na tom/přehled" → škola, upozornění,
  cíle, práce, finance. Neznámý dotaz → jen datum. Žádné LLM volání.
- **Obsah** (max 3 položky na sekci, krátké řádky, prázdné = „žádné"): datum/čas, zítra, týden (po–ne);
  škola po termínu + úkoly a zkoušky na 7 dní (pražské datum); důležitá nepřečtená upozornění; aktivní cíle
  s progresem; práce tento měsíc + poslední záznam; finance tento měsíc + celková bilance; WoT zdroje + grindy.
  Připomínky (reminders) zatím neexistují (fáze D).
- **Paměť** `rank_memories`: jen aktivní; skóre = 3×překryv slov (5znakové kmeny) + 3 za shodu oblasti
  + importance; recency tiebreak; max 3 řádky po 140 znacích. Pro plánovací/přehledové dotazy i bez překryvu.
- **Rozpočet**: cíl 500, tvrdé max 600 odhadovaných tokenů (oddělené od fixní režie). Nad cíl se ubírá paměť,
  nad max sekce od nejméně relevantní (explicitně zmíněné oblasti zůstávají nejdéle). Test: `ContextBudgetTestCase`.
- **Autorita**: `CURRENT STATE` = živá data (prompt: odpovídej z něj, nenačítej znovu; tooly jen pro chybějící
  data). `RELEVANT MEMORY` = jen kontext. Pro planner grounding je CURRENT STATE evidence pro čísla/data/jména,
  paměť **jen pro jména/plány** (`build_evidence(..., name_only_texts)`), nikdy pro čísla.
- `covered_tools` kontextu se počítají jako „načtené" pro planner pravidla (žádné auto-`get_memories`
  ani připomínka, pokud cíle/paměť nese kontext).
- Log souhrnu requestu má `context_tokens` a `context_sections` (počet), nikdy obsah kontextu.

---

## 16. Historie konverzace a shrnutí (A4, `history_service.py`)

- **Jen LLM cesta** `/chat`: `_history_for_ai` se volá až po planner fast-path (rule-based plán historii
  nepotřebuje → žádné zbytečné shrnutí). Pořadí zpráv pro model:
  `system prompt → CURRENT STATE (A3) → CONVERSATION SUMMARY → [starší neshrnuté pod prahem] → posledních N`.
- **Okno**: posledních `AI_HISTORY_WINDOW_MESSAGES` (8) zpráv doslovně.
- **Shrnutí** (uložená konverzace): když starší, dosud neshrnuté zprávy (`id > summarized_until_message_id`)
  přesáhnou `AI_SUMMARY_TRIGGER_TOKENS` (1000), jedno volání `ai.summarize_conversation`
  (`GROQ_SUMMARY_MODEL`, bez toolů, `max_tokens=AI_MAX_SUMMARY_TOKENS`) shrne dávku max 3× práh
  a zapracuje předchozí shrnutí. Uloží se `summary` + `summarized_until_message_id` = poslední zahrnutá
  zpráva → **inkrementální posun, stejné zprávy se znovu neshrnují**. Pod prahem se starší zprávy posílají
  doslovně a shrnutí se nevolá.
- Velké dohánění (stará dlouhá konverzace): 1 shrnutí na turn; zbytek nad práh se ten turn vynechá
  a dožene se v dalších turnech.
- **Selhání shrnutí** (výjimka, prázdný text, denní limit…): request pokračuje, starší neshrnuté zprávy se
  pro tento turn vynechají (truncation), uložené shrnutí/ID se nemění.
- **Rozpočet**: `AI_MAX_HISTORY_TOKENS` (2500) = tvrdé max celé historie vč. shrnutí (nad něj se odebírají
  nejstarší zprávy, poslední nikdy). Validace: `AI_MAX_SUMMARY_TOKENS + AI_SUMMARY_TRIGGER_TOKENS ≤
  AI_MAX_HISTORY_TOKENS`. Celý request (odhad): fixní ≤ 3 500 + CURRENT STATE ≤ 600 + historie ≤ 2 500.
- Historie bez `conversation_id` (od klienta): jen okno + tvrdé max, nic se neukládá.
- Shrnutí **není evidence** pro planner grounding a je označené jako „context only".
- Log: řádek `history ...` (počty zpráv, tokeny, summary_used/called/failed, dropped) – nikdy obsah.

---

## 17. Registr a routing AI toolů (A5, `tool_registry.py`, `tool_router.py`, `read_queries.py`)

- **`tool_registry.py` = jediný zdroj pravdy** o AI toolech: `ToolSpec(name, kind read/write, areas, schema,
  func, covered_by_context, requires, takes_db, explicit_only)`. `ai.TOOLS` / `READ_TOOLS` / `WRITE_TOOLS` /
  `*_TOOL_FUNCTIONS` se z něj odvozují. Registr se při importu validuje (duplicity, `requires` jen na read tooly).
- **`read_queries.py`**: AI verze seznamových toolů s filtry a stropem (default 20, max 100), výsledek
  `{items, total, returned, truncated, filters}`: `get_finance_transactions` (typ, kategorie, období),
  `get_work_sessions` (projekt, období), `get_school_assignments` / `get_school_exams` (default jen otevřené),
  `get_goals` (oblast, stav; progres přes `tools.get_goals`), nový `get_recent_activity` (activity log, dny).
  Běží na db session AI requestu (`takes_db`). **REST endpointy dál volají `tools.py` – tvary odpovědí beze změny.**
- **`tool_router.route_tools`** (deterministicky, bez LLM, jednou před prvním voláním; sada platí pro všechna kola):
  - text = aktuální zpráva uživatele; krátký follow-up (≤ 6 slov nebo „a …", „ano", „proč"…) + nejvýš **jedna**
    předchozí zpráva uživatele. Shrnutí konverzace (A4, system zpráva) ani odpovědi asistenta se nepoužívají.
  - oblasti: sdílené `context_service.classify_areas` (+ MFF) + intenty `memory`, `activity`; implikované oblasti
    stejně jako CURRENT STATE prefetch.
  - READ: tooly oblastí; souhrn (`covered_by_context`) se vynechá, když CURRENT STATE oblast pokryl a uživatel se
    na ni výslovně neptá; `explicit_only` (předměty, historie cíle) jen při výslovné oblasti; plánovací dotaz
    přidá `get_goals` + `get_memories`, pokud je nepokrývá kontext; `requires` se doplní vždy.
  - WRITE: **jen při write záměru** (rozkazovací sloveso, „utratil jsem…", částka v Kč / číslo v oblasti mimo
    otázku a žádost o výpis). Oblast známá → write tooly oblasti („pamatuj si" → jen `save_memory`); neznámá →
    všechny write tooly.
  - pozdrav → žádné tooly; dotaz bez oblasti → všechny READ tooly (`generic`).
- **Pojistky v `ask_ai`**: write tool mimo routovanou sadu `_run_tool_calls` odmítne (`write_not_available`,
  žádná pending akce); Groq 400 „tool validation" → jednou rozšířit na všechny READ (+ WRITE jen s write záměrem)
  a kolo zopakovat, při dalším odmítnutí poslední volání bez toolů. Planner připomínka jen pro dostupné tooly.
  Pending akce, potvrzení i auth jsou beze změny.
- **Kill switch**: `AI_TOOL_ROUTING=false` → každý request posílá přesně `ai.TOOLS` (všech 28) jako před A5.
- **Měření** (odhad schémat, bez kontextu → s CURRENT STATE): všechny tooly 28 / ~2 730; škola 7 → 4 tooly
  (~600 → ~400), finance 4 → 3 (~300 → ~255), WoT 2 (~100), pozdrav 0, obecný dotaz 18 READ (~1 310),
  zápis výdaje 5 → 4 (~430 → ~380), zápis s neznámou oblastí 12 (~1 560). Skript `backend/scripts/measure_tool_routing.py`.

---

## 18. AI úpravy, mazání a dokončení (Phase B, `mutation_service.py`, tool `modify_records`)

- **Žádná AI mutace se neprovede hned.** Úprava / smazání / dokončení existujícího záznamu je vždy pending akce
  ve stávající architektuře (`pending_actions`, `/actions/confirm`, `/ai/reject/{id}`, expirace, FSM
  pending → executing → executed/failed, ochrana proti dvojímu potvrzení, session auth) – žádný druhý systém.
- **Tool `modify_records(entity, action, target, changes)`** – `entity`: finance_transaction, work_session,
  school_assignment, school_exam, goal, wot_grind, memory; `action`: update / delete / complete.
  V registru má `resolver` (běží při návrhu) a `write_intent="mutate"`; router ho vystaví jen při mutačním
  slovese (změň, uprav, oprav, smaž, odstraň, zruš, označ, „je hotový"…) a create tooly pak skryje, pokud
  zároveň nezazní create sloveso („přidej", „zapiš"…). Otázky ho nedostanou nikdy.
- **Návrh (`resolve_mutation`)**: cíl se dohledá v DB podle `target` (id, text bez diakritiky přes název /
  popis / kategorii / předmět, datum, období, typ, `latest`, `all_matching`). ID od modelu se jen ověří
  (musí existovat a sedět s ostatními filtry). Nepopsaný / nejednoznačný / nenalezený cíl, neplatné nebo
  prázdné změny → `MutationRefused` → model dostane `not_prepared` (+ kandidáty) a **žádná pending akce
  nevznikne**; model se má doptat.
- **Plán v pending akci** (`arguments = {"plan": {...}}`, bez migrace): `version`, `entity`, `action`,
  `targets[{id, snapshot}]`, `changes`, `preview{kind, title, count, items[{id, label, changes[{label, old,
  new}]}], warnings}`. `/chat` vrací `preview` i u položky `pending_actions`.
- **Potvrzení (`apply_mutation_plan`)**: stávající `execute_confirm_action` zavolá executor s uloženým plánem.
  Každý cíl se načte podle ID a porovná se snímkem – smazaný nebo mezitím změněný = `StaleTarget`, akce
  `failed`, **nic se nezmění**. Vše v jedné transakci (dávka je atomická), audit log za každou položku
  (`user_context=ai_confirm`) + souhrnný `approve` záznam. Cíl se při potvrzení nikdy znovu nevyhledává.
- **Podpora**: finance (úprava, smazání – odpojí pracovní session jako REST), práce (úprava – navázaný příjem
  se přepočítá; smazání – příjem zůstane jako v REST), úkoly (úprava, smazání, dokončení, **dávkové dokončení
  max 20**), zkoušky (úprava, smazání), cíle (úprava, smazání, dokončení – ruční progres 100 %; automatický
  progres nastavit nelze), WoT grindy (úprava, smazání), paměť (úprava, smazání = deaktivace jako REST).
- **Nepodporováno**: MFF postavy, WoT zdroje (už mají `update_wot_resource`), předměty, notifikace, planner,
  dávky jiné než dokončení úkolů, „dokončení" zkoušky (výsledek passed/failed → úprava stavu).
- **Planner fast-path** (`main.detect_planner_intent`) při write záměru vrací None – „označ všechny dnešní
  úkoly jako hotové" jde na model, ne do denního planneru.
- **Frontend**: `lib/pendingActions.ts` → `normalizePreview` + `describePreview` vykreslí kartu obecně
  (akce, záznam, staré → nové, upozornění, u dávky seznam a počet); create karty zůstávají beze změny.
- Testy: `test_mutation_service.py`, `test_ai_mutations.py`, router v `test_tool_router.py`,
  frontend `lib/pendingActions.test.mjs`.

---

## 19. Undo potvrzené AI změny (Phase C, `mutation_service.py`, tool `undo_change`)

- **Data pro undo se ukládají při provedení**: `apply_mutation_plan` vrátí undo záznam a `execute_confirm_action`
  ho uloží do původní pending akce (`arguments["undo"]`) ve stejném commitu jako stav `executed`:
  `{version, executed_at, entity, action, title, supported, items[{id, label, before, after, row?,
  unlinked_work_sessions?, linked_income?}]}`. `before` = snímek z plánu (Phase B), `after` = snímek po změně,
  `row` = celý řádek u tvrdého smazání. UI dostane jen `result.undo_available`.
- **Undo je pending akce** (`undo_change`, plán `{version, kind: "undo", original_action_id, entity, action,
  preview}`) se stejným potvrzením / zamítnutím / expirací. Vzniká z chatu („vrať poslední změnu", „undo",
  „vrať poslední změnu ve financích") nebo tlačítkem **Vrátit** (`POST /actions/undo {action_id}` → nová
  pending karta). Model nikdy nerekonstruuje staré hodnoty.
- **Výběr (`resolve_undo`)**: jen provedené `modify_records` akce s undo záznamem z posledních
  `UNDO_WINDOW_HOURS` (24 h), volitelně podle oblasti. Víc kandidátů bez „poslední" → `ambiguous_target` +
  kandidáti, žádná pending akce. Už vrácené (`already_undone`), nepodporované, prošlé a zastaralé
  (`stale_target`: aktuální stav ≠ snímek po změně) se odmítnou už při návrhu.
- **Provedení (`apply_undo_plan`)**: podmíněný `UPDATE pending_actions SET status='undone' WHERE id=… AND
  status='executed'` ve stejné transakci jako obnovení → nejvýš jednou; každá položka znovu ověřena
  (stav = snímek po změně, u smazání id volné + vazby existují); jakákoli chyba = rollback, nic se nezmění.
  Smazané řádky se obnoví i s původním id a vazbami (pracovní session ↔ příjem).
- **Audit**: za každou položku `action_type="undo"` s `delta.undo_of_action=<id původní akce>` + souhrnný
  záznam `area="ai", action_type="undo", entity_type="PendingAction", entity_id=<id původní akce>`;
  původní akce dostane `undo.undone_at`.
- **Podporováno**: úprava (vše z Phase B), dokončení (úkol, cíl vč. ručního progresu), dávkové dokončení úkolů
  (atomicky), smazání transakce / pracovního záznamu / úkolu / zkoušky / WoT grindu, deaktivace paměti.
- **Nepodporováno**: smazání cíle (kaskádově maže historii progresu), create akce (`add_*`, `upsert_*`,
  `save_memory`, `update_wot_resource` – neukládají stav před změnou), undo undo, akce provedené před Phase C
  (nemají undo záznam), změny starší než 24 h.
- **Bez migrace**: `undone` je nová hodnota existujícího sloupce `pending_actions.status`.
- Testy: `test_undo.py`, router v `test_tool_router.py`, frontend `lib/pendingActions.test.mjs`.

---

## 20. Připomínky (Phase D, `reminder_service.py`, `reminder_actions.py`, migrace 0009)

- **Tabulka `reminders`** (migrace `0009_reminders`, jen nová tabulka): `title`, `note`, `due_at` (naive UTC =
  příští výskyt), `status`, `recurrence` (none/daily/weekly), `weekdays` („0,6", po=0), `local_time` („HH:MM"
  Praha), `snoozed_until`, `last_fired_at`, `fire_count`, časy; index `(status, due_at)`.
- **Čas**: ukládá se UTC, zadává a zobrazuje Europe/Prague (`due_local` „YYYY-MM-DDTHH:MM"). Opakování drží
  pražský nástěnný čas přes DST. Neexistující čas (jarní posun 02:00–03:00) se posune o mezeru vpřed
  (02:30 → 03:30), dvojznačný (podzimní) bere první výskyt (letní čas). Relativní „za 2 hodiny" se přepočte na
  absolutní čas při vytvoření / návrhu.
- **Stavy**: `scheduled` → `fired` (jednorázová zazněla) → `done`; `cancelled` kdykoli. Opakovaná zůstává
  `scheduled` a po zaznění posune `due_at`. Hotovo u opakované potvrdí jen aktuální výskyt. Odložení: jednorázová
  = nový `due_at`; opakovaná = `snoozed_until` (extra výskyt, série běží dál).
- **Zazvonění bez LLM** (`process_due_reminders`): podmíněný `UPDATE … WHERE due_at/snoozed_until = výskyt`
  + notifikace (`notification_type="reminder"`, `area="reminders"`, `severity="important"`,
  dedupe `reminder:<id>:<výskyt>`) v jedné transakci na připomínku → nejvýš jednou, chyba jedné neblokuje
  ostatní a připomínka se při dalším běhu zkusí znovu. Po výpadku: jednorázová zazní jednou s textem
  „Zpožděno…", opakovaná jednou a pak až další budoucí výskyt.
- **Kdo zpracovává**: job `standa_hub_reminders` ve stávajícím APScheduleru (`REMINDERS_CHECK_ENABLED=true`,
  `REMINDERS_CHECK_SECONDS=60`, běží i bez hodinového jobu) **a** lazy při `GET /notifications` a
  `/notifications/summary` (zvonek se ptá každých 30 s). Obojí je idempotentní.
- **REST** (session auth): `GET /reminders?status=active|all|done|cancelled`, `POST /reminders`,
  `PATCH /reminders/{id}`, `POST /reminders/{id}/snooze {minutes|until_local}`, `/done`, `/cancel`.
- **AI**: `get_reminders` (read; CURRENT STATE má řádek „Připomínky" se zazněnými a do 48 h, časové dotazy
  ho zahrnují), `add_reminder` (create) a `manage_reminder` (update/snooze/complete/cancel) – obojí pending
  akce s plánem (přesný čas / id + snímek) a náhledem; cíl přes Phase B resolver (nejednoznačný → doptat).
  Router: „připomeň" = create, „odlož/posuň/zruš" = mutate; u zmínky připomínky jen tooly připomínek.
  „co mám připomenout dnes" obchází planner fast-path. Undo (Phase C) se na připomínky nevztahuje.
- **Frontend**: `/reminders` (Teď / Nadcházející / Hotové a zrušené, Hotovo, +15 min / +1 h / Zítra 8:00,
  úprava, zrušení s potvrzením), zazněné i ve zvonku. `lib/reminders.ts` + testy.
- Testy: `test_reminders.py`, `test_reminders_api.py`, `test_ai_reminders.py`, migrace v
  `test_alembic_migration.py`, frontend `lib/reminders.test.mjs`.

---

## 21. Externí doručení připomínek – Web Push (Phase E, `webpush.py`, `delivery_service.py`, migrace 0010)

- **Proč Web Push**: standard prohlížečů, žádný účet u třetí strany ani SDK. Zprávu doručí push služba
  prohlížeče (Google FCM, Mozilla, Apple, Microsoft) podle odběru zařízení. Implementace jen nad
  `cryptography`: RFC 8291 šifrování (aes128gcm, ověřeno testovacím vektorem z RFC) + RFC 8292 VAPID (ES256).
- **Oddělení**: Phase D dál zazvoní připomínku a vytvoří interní notifikaci (zvonek). Externí doručení je
  samostatný krok – jeho chyba nic z toho neovlivní.
- **Tabulky** (migrace `0010_push_delivery`, jen nové): `push_subscriptions` (endpoint + klíče zařízení,
  unikátní `endpoint_hash`, `disabled_at` po 404/410) a `deliveries` (notifikace × kanál × cíl, unikátní
  `dedupe_key`, `status` pending/sending/sent/failed/skipped, `attempts`, `next_attempt_at`, `last_attempt_at`,
  `last_error` = jen kategorie, `provider_message_id`).
- **Životní cyklus** (job `standa_hub_reminders` po zazvonění, `run_delivery_cycle`):
  1. `enqueue_deliveries`: nevyřešené reminder notifikace z posledních 12 h → chybějící doručení pro každé
     aktivní zařízení (přihlášené před zazněním). Idempotentní.
  2. `process_deliveries`: claim pending → sending (podmíněný UPDATE), odeslání, pak `sent`, nebo další pokus
     (1/5/15/60 min, respektuje `Retry-After` max 1 h, max 5 pokusů → `failed exhausted:*`), nebo trvale
     `failed` (4xx; 404/410 navíc vypne zařízení). Vyřízená (Hotovo) / starší než 12 h → `skipped`.
     Přerušené `sending` se po 10 min vrátí do pending; hlavička `Topic` zajistí, že push služba případný
     duplikát nahradí.
- **Kanály**: rozhraní `DeliveryProvider` (`channel`, `is_configured`, `targets`, `send`); Web Push je první.
  Další kanál (ntfy, e-mail…) = nový provider + registrace v `configured_providers`.
- **API** (session auth): `GET /push/config` (jen veřejný klíč), `POST /push/subscriptions`,
  `POST /push/unsubscribe`, `POST /push/test` (jen na toto zařízení, mimo frontu), `GET /push/status`
  (zařízení bez endpointů a klíčů + poslední doručení). Odběr se validuje: jen https a známé push služby
  (`WEB_PUSH_EXTRA_HOSTS` pro další) → backend nejde zneužít k požadavkům do vnitřní sítě.
- **Konfigurace**: `EXTERNAL_DELIVERY_ENABLED` (default true), `WEB_PUSH_VAPID_PRIVATE_KEY`,
  `WEB_PUSH_VAPID_PUBLIC_KEY`, `WEB_PUSH_CONTACT`; klíče vygeneruje `scripts/generate_vapid_keys.py`.
  Bez klíčů se nic externě neposílá. Vyžaduje běžící reminder job (`REMINDERS_CHECK_ENABLED=true`).
- **Frontend**: `public/sw.js` (jen push + klik), `app/manifest.ts` + ikony, panel `PushSettings` na
  `/reminders` (oprávnění jen po kliknutí, test, vypnutí, vysvětlení nepodporovaného prostředí).
- **HTTPS (nutné pro mobil, MRK-24)**: prohlížeč povolí Web Push a instalaci PWA jen na https nebo localhost.
  Produkce: Tailscale Serve jen v tailnetu (nikdy Funnel) – `https://<pc>.<tailnet>.ts.net` → :3000 a
  `:8443` → :8000 přes `scripts/windows/tailscale-serve.ps1`; `NEXT_PUBLIC_API_URL=https://<pc>.<tailnet>.ts.net:8443`,
  `FRONTEND_ORIGINS` + https origin, `AUTH_COOKIE_SECURE=true` (`production.py` hlídá shodu). Postup, rollback,
  změna certu/hostname, VAPID a troubleshooting: [docs/https-pwa-push.md](../docs/https-pwa-push.md).
  Vývoj přes Tailscale: navíc `NEXT_DEV_EXTRA_ORIGINS=<pc>.<tailnet>.ts.net`.
  iPhone/iPad: Safari → Sdílet → Přidat na plochu, upozornění zapnout z ikony na ploše (iOS 16.4+).
- Testy: `test_webpush.py`, `test_delivery.py`, `test_push_api.py`, migrace v `test_alembic_migration.py`,
  frontend `lib/push.test.mjs`.


## 22. Denní přehled (Phase F, `briefing_snapshot.py`, `briefing_service.py`, migrace 0011)

- **Princip**: nejdřív deterministický **snímek** reálných dat (`build_snapshot`), teprve pak jedno volání LLM
  **bez toolů a bez historie konverzace**. LLM jen shrnuje a řadí; nic nemění v databázi.
- **Volání LLM** (jen pro přehled, běžný chat beze změny; `request_params()` → `extra_params` v
  `ai._llm_create_with_retry`): Chat Completions, **strict JSON Schema Structured Outputs**
  (`response_format=json_schema`, `strict: true`, schéma `RESPONSE_SCHEMA`: summary, priorities[ref,title,why],
  watch/upcoming[ref,text], note – vše povinné, `additionalProperties: false`, bez min/max a unionů; prázdná
  poznámka = `""`), `reasoning_effort="low"` (záměrně: model jen shrnuje hotový snímek, medium zbytečně pálí
  výstupní budget) a `max_completion_tokens=1200`. Schéma brání strukturálně vadnému JSON; obsah dál
  kontroluje defenzivní parsování + `ground`.
- **Proč 1200**: gpt-oss je reasoning model – reasoning tokeny se počítají do completion limitu. Původních
  700 se při živém testu vyčerpalo dřív, než vznikl celý JSON. Samotná odpověď má typicky ~250–450 tokenů, při plných seznamech (5 priorit
  + 2×5 položek s limity slov) do ~700; s nízkým reasoning zbývá rezerva. 1200 je **strop**, ne očekávaná spotřeba.
- **Rozpočet** (`estimate_request_tokens` = zprávy + schéma + strop výstupu): běžný snímek ~126 tokenů,
  požadavek ≈1750; nejhorší (vše plné) snímek ~633, požadavek ≈2257 – pořád hluboko pod 8k TPM. Skutečná
  spotřeba je typicky o stovky tokenů nižší (strop se nevyčerpá). Spotřeba se ukládá (prompt/completion/total,
  i u nepovedené odpovědi); `reasoning_tokens` se jen loguje, když ho provider vrátí.
- **Snímek**: sekce today / overdue / soon / attention / goals / finance / changes. Každá položka má `ref`
  (`assignment:12`, `exam:3`, `reminder:5`, `goal:2`, `notification:9`, `finance:2026-10`, `activity:…`),
  štítek, termín (pražský), odkaz `url` a příznak NOVÉ (oproti minulému přehledu). Stropy položek na sekci
  + strop 1200 tokenů (ořez od nejméně důležitých sekcí). Klidný den (nic v today/overdue/soon/attention)
  → přehled bez LLM (`model="deterministic"`).
- **Uzemnění** (`ground`): odkazy jen na existující položky snímku (bez duplicit, jen akční druhy), text
  s neověřitelnými čísly/daty/jmény (`planner_guard`) se nahradí štítkem ze snímku, nepodložené „proč"
  a poznámka se zahodí, souhrn spadne na deterministický. Nezbude-li nic → `grounding_rejected`.
  Počet oprav → `grounding_removed`.
- **Sekce změn bez technického šumu** (`meaningful_activity`): vynechá oblasti ai/system/auth/backup/
  scheduler, akce snapshot/sync/sync_to_finance/error/cleanup/migrace/backup/seed, `user_context`
  test*/cleanup/system/…, souhrny s `[TEST]`/`[VERIFY]`/„test cleanup" a záznamy vytvořené i smazané
  v rámci okna (úklid po ověřování – čistý dopad nulový). Úpravy, dokončení i smazání existujících dat zůstávají.
- **Tabulka** `daily_briefings` (migrace `0011_daily_briefings`): unikátní `briefing_date` (pražský den),
  `status` generating/ready/failed, `trigger` scheduler/catchup/manual, `attempts`, `next_retry_at`,
  `error_category`, `content` (JSON), `source_hash`, `source_refs`, tokeny/latence/model, `regenerated_count`.
  Claim je podmíněný UPDATE → žádné duplicitní generování; `generating` starší 10 min se převezme.
- **Scheduler**: vlastní job `standa_hub_briefing` (každých `DAILY_BRIEFING_CHECK_SECONDS`, první běh hned
  po startu = dohnání po restartu). Generuje jen pro **dnešní** pražský den a až po `DAILY_BRIEFING_TIME`
  (DST bezpečné – porovnává se pražský čas). Pozdě o >30 min → `trigger=catchup`. Chyby: denní limit Groq
  → další pokus za 3 h, rate limit/provider 15 min, neplatná odpověď/uzemnění 30 min; max 4 pokusy/den.
  Chyba přehledu nikdy neovlivní připomínky (oddělený job, try/except).
  Další kategorie: `finish_reason=length` nebo 400 „max tokens" → `output_limit` (6 h – stejný poddimenzovaný
  požadavek se hned neopakuje), 400 `json_validate_failed`/schéma → `schema_error` (1 h), refusal /
  `content_filter` → `refused` (6 h), jiná 4xx → `request_rejected` (6 h), prázdná / ne-JSON / nečekaná
  odpověď → `invalid_response`.
- **Doručení**: úspěšný (ne ruční) přehled vytvoří jednu notifikaci `daily_briefing` na den (dedupe
  `briefing:<datum>`, starší se uzavřou, platnost do konce dne). Web Push ji pošle stávající frontou z Phase E
  (`deliverable_types`), žádné druhé doručování; `DAILY_BRIEFING_PUSH=false` = jen zvonek. Odesílá ji
  reminder job → potřebuje `REMINDERS_CHECK_ENABLED=true`.
- **API** (session auth): `GET /briefing/today` (stav + obsah, bez AI přehledu deterministický náhled
  `fallback`), `POST /briefing/today/generate` `{regenerate}` (jen dnešek; 409 při běžícím generování;
  nepovedené přegenerování ponechá předchozí verzi s `error_category=regenerate_failed:*`).
- **Logy** (`standa_hub.briefing`): jen čísla a kategorie (datum, trigger, položky, tokeny, latence,
  opravy), nikdy prompt ani obsah snímku.
- **Frontend**: `components/DailyBriefingCard.tsx` nahoře na dashboardu, logika v `lib/briefing.ts`
  (+ `briefing.test.mjs`).
- **Konfigurace**: `DAILY_BRIEFING_ENABLED` (true), `DAILY_BRIEFING_TIME` (07:00), `DAILY_BRIEFING_PUSH`
  (true), `DAILY_BRIEFING_CHECK_SECONDS` (300, min 60).
- Testy: `test_briefing.py` (falešné hodiny i LLM; reálná cesta přes OpenAI SDK proti lokálnímu fake HTTP
  – `httpx.MockTransport`, žádný reálný Groq), migrace v `test_alembic_migration.py`.

## 23. Týdenní přehled (Phase G, `weekly_snapshot.py`, `weekly_review_service.py`, migrace 0012)

- **Princip** (jako Phase F): nejdřív deterministický **snímek**, pak jedno LLM volání přes sdílené
  `structured_llm.py` (strict JSON Schema, `reasoning_effort="low"`, `max_completion_tokens=1600`, bez toolů
  a bez historie). LLM jen vybírá, řadí a formuluje; nic nepočítá a nic nemění.
- **Týden**: pondělí 00:00 → neděle 24:00 Europe/Prague, `week_start` = pondělí (unikátní). Hranice přes
  `time_utils` (DST: týden má 167/168/169 h). Plánovaně `WEEKLY_REVIEW_DAY` + `WEEKLY_REVIEW_TIME` (default
  neděle 19:00) → přehled shrnuje týden **do okamžiku generování** (`period_end`, v UI „data do …").
  **Srovnání je like-for-like**: minulý týden ve stejném rozsahu (pondělí 00:00 → neděle 19:00, posun o 7
  pražských dní). Data bez času (práce, termíny) se berou po celých dnech do posledního zahrnutého dne.
- **Aktuální týden** (`due_week`): tento týden po plánovaném čase, jinak minulý týden. Scheduler i ruční
  generování pracují jen s ním → další týden nikdy dřív; když přehled minulého týdne chybí (server neběžel),
  dožene se po startu za **celý** týden (`trigger=catchup`). Starší týdny jsou jen ke čtení.
- **Snímek** (`build_weekly_snapshot`): metriky `metric:*` (tento | minulý týden | změna | lepší/horší jen
  u veličin s polaritou; drobné změny < 200 Kč / 1 h = beze změny; procenta jen nad základem 500 Kč):
  dokončené / nové úkoly, úkoly po termínu začátek → konec týdne, hodiny a výdělek z práce (+ „neobvykle"
  proti souvislé 3týdenní historii), příjmy / výdaje / bilance (příjem z práce v financích jen jednou –
  „z toho práce"), výrazné změny kategorií výdajů (≥ 500 Kč a ≥ 30 %), cíle s posunem, zazněné připomínky
  (hotovo / odloženo), termíny příštího týdne vs. tento týden (+ nejvytíženější den). Položky s odkazy:
  škola (dokončené, po termínu, zkoušky týdne s výsledkem), cíle (posun z `goal_progress_history`, splněné,
  stagnace ≥ 14 dní, po cílovém datu), nevyřízené připomínky, aktivita (sdílený filtr šumu z Phase F),
  příští týden (otevřené úkoly, otevřené zkoušky, jednorázové připomínky, cílová data).
  WoT/MFF nejsou zahrnuté – nemají historii postupu (v aktivitě se jen počítají).
- **Odkud jsou „dokončené" úkoly**: úkoly nemají časová razítka; dokončení = záznam v `activity_logs`
  (`complete` nebo `status` → done) v daném týdnu **a** úkol je dnes pořád hotový (vrácená dokončení se
  nepočítají). Stav úkolů po termínu na začátku týdne je rekonstruovaný (dnes otevřené + během týdne
  dokončené, bez úkolů založených až během týdne).
- **Odhady** (`forecast:*`) připravuje snímek, LLM je jen vybírá a smí přeformulovat. Jistota je pravidlo:
  `high` = známé termíny (≥ 3 termíny příští týden, nebo žádné po vytíženém týdnu), `moderate`/`low` =
  tempo výdajů v měsíci (≥ 7 dní dat, moderate od 14 dní), cíl s blízkým termínem a nedostatečným tempem
  (moderate při ≥ 21 dnech historie), trend hodin práce 3 týdny po sobě (low), růst backlogu (low).
  Nikdy: zdraví, nálada, motivace, výsledky zkoušek, kariéra, nepodložený příjem. Málo dat → žádný odhad.
- **Málo dat**: `signals` = uživatelská aktivita (bez šumu) + zazněné připomínky + zkoušky týdne + závazky
  příštího týdne + cíle s posunem; méně než 4 → deterministický přehled bez LLM („Klidný týden – málo dat").
- **Grounding** (`ground`): odkazy jen do snímku; tón musí sedět (úspěch = lepší metrika / dokončeno /
  posun, starost = horší / po termínu / stagnace; jeden ref nesmí být obojí); srovnání jen `metric:*`
  s minulou hodnotou; příští týden jen z jeho sekce; odhady jen kandidáti (jistota a podklad vždy ze
  snímku). Text: čísla s jednotkou nebo ≥ 100 musí ve snímku být **přímo** (žádné dopočty), data jen ze
  snímku, jména s tolerancí skloňování; fakta a souhrn bez kauzality („kvůli", „protože"…); zakázaná témata
  vždy; odhad s „určitě/jistě" → deterministický text kandidáta. Interní odkazy se z textu odstraní.
  Víc než polovina položek s neplatným odkazem, nebo nic použitelného → `grounding_rejected`.
- **Tabulka** `weekly_reviews` (migrace `0012_weekly_reviews`, ověřeno i na PostgreSQL 16): `week_start`
  (unikátní), `period_end`, `status`, `trigger`, `attempts`, `next_retry_at`, `error_category`, `content`
  (JSON), `snapshot_hash`, `snapshot_tokens`, tokeny/latence/model, `grounding_fixes`, `regenerated_count`.
  Prompt ani snímek se neukládají.
- **Scheduler**: job `standa_hub_weekly_review` (`WEEKLY_REVIEW_CHECK_SECONDS`, default 900 s, první běh
  po startu). Claim přes podmíněný UPDATE, `generating` starší 10 min se převezme, max 4 pokusy, odstupy jako
  Phase F (denní limit 3 h, output_limit 6 h…). Chyba nikdy neovlivní připomínky ani Denní přehled.
- **Notifikace**: jedna `weekly_review` na týden (dedupe `weekly_review:<pondělí>`, odkaz `/review`), jen
  u plánovaného/dohnaného přehledu. Web Push stávající frontou (`deliverable_types`, `WEEKLY_REVIEW_PUSH`).
- **API** (session auth): `GET /weekly-review` (aktuální týden + deterministický náhled `fallback`),
  `GET /weekly-review/history`, `GET /weekly-review/week/{pondělí}` (jen čtení), `POST /weekly-review/generate`
  `{regenerate}` (jen aktuální týden; 409 při běžícím generování).
- **Frontend**: `/review` (aktuální týden, historie, odhady vizuálně oddělené jako „Odhad / Forecast"
  s jistotou a podkladem), karta `WeeklyReviewCard` na dashboardu, logika v `lib/weeklyReview.ts`.
- **Rozpočet**: systémový prompt ~430 tokenů, schéma ~350; snímek: klidný ~100 (bez LLM), běžný ~550,
  rušný ~810, nejhorší ořezaný ~1650 (strop 2200) → požadavek vč. stropu výstupu ≈ 2,9k / 3,2k / 4,0k.
- Testy: `test_weekly_review.py` (falešné hodiny/LLM, reálná cesta SDK proti lokálnímu fake HTTP),
  migrace v `test_alembic_migration.py`, frontend `lib/weeklyReview.test.mjs`.

## 24. Architektonická pravidla (Roadmap 3.5)

- Trvalé principy: `docs/architecture-principles.md`; audit a dluh: `docs/architecture-audit.md`;
  nové moduly: `docs/module-integration-checklist.md`; frontend směr: `docs/roadmap4-ui-foundation.md`.
- **Kanonické moduly** (nic z nich neduplikovat lokálně):
  - `statuses.py` – stavy záznamů (úkol hotový, zkouška otevřená/složená, cíl neaktivní, připomínka aktivní)
    + `norm()` a predikáty. `read_queries` je jen re-exportuje.
  - `env_config.py` – `env_bool/env_int/env_str` (ořez; prázdné = default; 1/true/yes/on). Žádné vlastní
    parsování `os.environ`. Patří sem i `WEEKLY_REVIEW_ENABLED` / `DAILY_BRIEFING_ENABLED` (scheduler i služby
    používají stejná pravidla).
  - `module_registry.py` (Roadmap 6C + MRK-18 A2) – zapnutí modulů jediným resolverem `resolve_states`:
    prostředí `MODULE_<ID>_ENABLED` (platná hodnota = vynuceno, zamčeno) > uložená volba `module_settings`
    (Nastavení, `PUT /modules/{id}`, 409 při vynucení) > výchozí manifest; nesmysl v env = ignorován.
    `current_access().allows(modul, schopnost)`; brány v search/Dnes/Quick Add/AI kontextu/dashboardu a 404 pro
    REST vypnutého modulu (až po auth). Frontend stav čte za běhu z GET /modules. Zrcadlo `frontend/lib/modules.ts`.
    Podrobnosti: `docs/module-feature-flags.md`.
  - **Rámec modulů (MRK-20)** – `ModuleDef.integrations` (`module_contracts.ModuleIntegrations`) z
    `<modul>_integrations.py` (jádro: `core_integrations.py`). Vyhledávání, Dnes, GET /dashboard, AI kontext,
    Rychlé přidání a hodinový job iterují `current_access().contributions(...)`; do agregátorů se modulový kód
    **nepíše** (hlídá `tests/test_module_framework.py`). Poskytovatelé neimportují agregátory ani registr.
    Návod: `docs/module-integration-checklist.md`, architektura a zbývající ruční místa: `docs/module-framework.md`.
  - `time_utils.py` – UTC úložiště, Europe/Prague pro „dnes" a plány; nikdy `date.today()`.
  - `text_utils.py` – `clip()`, české názvy dnů, `fold_text()` (bez diakritiky) a `join_parts()`.
  - `planner_guard.strict_text_problems` – přísný grounding pro přehledy.
  - `ai.LLMRateLimitError` / `DailyLimitError` – chyby LLM se rozlišují typem, ne textem.
- **Testy:** sdílené test doubles v `tests/fakes.py` (`FakeGroq`, `completion`, `groq_error`, `FakeProvider`);
  testy neimportují z jiných testovacích modulů. Nikdy reálný Groq.
