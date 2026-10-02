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

## 3. Alembic migrace (7 revizí)

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

### 7.2 Verifikace + retention

- `_verify_backup(path, checksum)`: `SHA256` souboru == uložené checksum v BackupLog.
- `_apply_retention(db, cutoff=now - BACKUP_RETENTION_DAYS=30d)`: smaže `backup_logs` řádek + unlinkne soubor pro řádky `started_at < cutoff`.

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
  `AI_MAX_CONTEXT_TOKENS` (2500, pro A3/A4). `GROQ_API_KEY` se čte jen při vytvoření klienta v `ai.py`.
- **Odhad tokenů** (`llm_budget.py`): deterministický, bez tokenizeru – ~4 ASCII znaky / token, ne-ASCII znak 2×.
  `estimate_fixed_overhead(system_prompt, tools)` = system prompt (vč. A1 data/času) + kompaktní JSON tool schémat.
- **Groq free tier = 8 000 TPM** a celá fixní režie se posílá v *každém* LLM volání (i v každém tool kole).
  Proto platí pevný limit **3 500 odhadovaných tokenů**, hlídaný testem
  `FixedOverheadBudgetTestCase` (všechny dny v týdnu, CET i CEST). Za běhu `ask_ai` jen loguje warning,
  pokud režie překročí `AI_MAX_FIXED_TOKENS` (request neblokuje).
- **Pravidla pro tool schémata** (vytvářej přes `ai._tool()`): obecná pravidla (potvrzení zápisu, paměť,
  nevymýšlení dat) patří do `SYSTEM_PROMPT`, ne do popisů toolů. Popis = krátce *co* tool dělá + jen
  nezbytné rozlišení. Jména, parametry a `required` musí sedět s Python funkcí (`ToolRegistryTestCase`);
  READ tooly začínají `get_`, WRITE `add_`/`update_`/`upsert_`/`save_` (prompt je podle jména rozlišuje).
  Interní `user_context` se LLM nikdy nevystavuje.
- **Kontrakt s frontendem**: planner JSON blok (` ```json ` + `summary`, `actions[priority, area, title, reason]`)
  parsuje `frontend/app/ai/page.tsx → tryParseWeeklyPlan`; hlídá `SystemPromptSafetyTestCase`.
- Přidání dalších toolů nad rozpočet → nejdřív routing toolů (Roadmap 3.0 A5), ne zvyšování limitu.
