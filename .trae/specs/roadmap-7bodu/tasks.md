# Standa Hub Roadmap 7 bodů – Implementation Plan (REV. 2)

Nové pořadí dle zpětné vazby: **1. Activity Log → 2. Alembic → 3. Pending Actions → 4. Goals 2.0 → 5. Scheduler → 6. Backup → 7. Auth/PIN**

---

## Task 1.1: ActivityLog model + runtime ALTER (POSLEDNÍ runtime ALTER, co bude)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - Do `backend/models.py` přidat `ActivityLog(Base)`, tabulka `activity_logs`:
    - `id (Integer PK)`, `timestamp (DateTime default=datetime.utcnow, nullable=False)`
    - `area (String(50), nullable=False)`
    - `action_type (String(50), nullable=False)` – create/update/delete/sync/snapshot/approve/reject/scheduler/backup/expire/error
    - `entity_type (String(50), nullable=True)` – např. "FinanceTransaction", "WorkSession", "Goal"
    - `entity_id (Integer, nullable=True)` – FK reference (bez fyzického FK constraintu)
    - `summary (String(500), nullable=False)` – lidsky čitelný text např. "+7,5 h Work session – Projekt X"
    - `delta_json (Text, nullable=True)` – JSON old→new změn v dictu, serializováno
    - `user_context (String(100), nullable=True)` – "ai_confirm" / "manual" / "scheduler" / "api" / "system"
    - `dedupe_key (String(180), nullable=True, UNIQUE)` – pro idempotentní retry
  - Indexy:
    1. `Index("ix_activity_area_timestamp", ActivityLog.area, ActivityLog.timestamp.desc())`
    2. `Index("ix_activity_dedupe_key", ActivityLog.dedupe_key, unique=True)`
  - Runtime ALTER migration v `main.py` (POSLEDNÍ TENTO DRUH!) – dočasně dokud neuděláme bod 2 (Alembic).
    - Stejný pattern jako `_migrate_mff_characters_table`: pokus CREATE TABLE IF NOT EXISTS, postupně přidat sloupce co chybí.
- **Acceptance Criteria Addressed**: AC-AL-1, AC-AL-2, FR-AL-2
- **Test Requirements**:
  - `rule` TR-1.1.1: `Base.metadata.create_all` na temp SQLite → tabulka `activity_logs` existuje, 9 sloupců
  - `rule` TR-1.1.2: Insert modelu area="finance" action_type="create" summary="test" → uspěje
- **Notes**: dedupe_key složení standard: `f"{area}:{action_type}:{entity_type or ''}:{entity_id or ''}:{hashlib.md5(summary.encode()).hexdigest()[:8]}"`

## Task 1.2: activity_service.py – log_activity() BEZ COMMITU (společná transakce)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1.1
- **Description**:
  - Vytvořit `backend/activity_service.py`
  - `def log_activity(db: Session, area: str, action_type: str, summary: str, *, entity_type: str | None = None, entity_id: int | None = None, delta: dict | None = None, user_context: str | None = None, dedupe_key: str | None = None) -> ActivityLog | None:`
  - Behavior:
    1. Sestav default dedupe_key pokud není.
    2. Pokud už dedupe existuje v DB (SELECT 1 WHERE dedupe_key = X) → vrať None (duplicitní, nic nepřidávej).
    3. Jinak vytvoř nový `ActivityLog` objekt.
    4. **NEDĚLAT `db.commit()`. NEDĚLAT `db.flush()`. POUZE `db.add(activity)`.** Vrať activity objekt.
  - Pomocné: `def delta_dict(old_obj: Any, new_obj: Any, fields: list[str]) -> dict` serializuje old/new hodnoty daných fieldů do dictu.
- **Acceptance Criteria Addressed**: AC-AL-1 (transakční rollback), NFR-3 (idempotentnost)
- **Test Requirements**:
  - `rule` TR-1.2.1: Dvakrát `log_activity(db, ..., dedupe_key="abc123")` – v DB je pouze 1 záznam (druhý vrátí None).
  - `rule` TR-1.2.2: Volej log_activity → **následně** call `db.rollback()` (simuluj chybu hlavní transakce) – v DB není žádný activity záznam (nebyl commit).
  - `rubric` TR-1.2.3: Kvalita service – 1/5 inline vs 5/5 clean separace s helpery. Threshold >= 4. Evidence = zdroják.
- **Notes**: Commit je 100% zodpovědnost volajícího (main.py routes, tools.py write funkce).

## Task 1.3: Write hooks do 9 modulů, vždy 1 společný commit
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1.2
- **Description**: Do každé write operace (v `main.py` POST/PUT/DELETE, v `tools.py` write fc, v `ai.py execute_confirm_action) přidat volání `log_activity(...)` PŘED commit, společně s business objektem, potom 1x `db.commit()`.
  - **Finance (POST/DELETE/transaction)**: area="finance", action_type=create/update/delete; summary např. "+2 437 Kč Freelance (příjem)" / "-890 Kč Oběd (výdej)"; delta old/new.
  - **Work (session create/update/delete + sync_to_finance)**: area="work"; summary např. "+7,5 h – Projekt Standalone"; pokud synced do finance, druhý záznam area="finance" action_type="sync".
  - **Goals (create/update/delete + PO ensure_goal_progress_snapshot pokud vrátil True progress změněn)**: area="goals"; progres summary "Cíl '150 tisíc' 9% → 11%".
  - **Memory (create/update/toggle active/delete)**: area="memory"; action_type=create/update/delete; summary "Pamatka 'Obchod na Smíchově' upravena / nastavena na inactive".
  - **School (subject, assignment, exam create/update/delete)**: area="school"; summary např. "Úkol 'Matematika 1' označen hotový".
  - **MFF (upsert character)**: area="mff"; summary "Postava 'Thor' Tier 3 → T4, build 75% → 100%"; delta tier/build_completeness.
  - **WoT (resource update, grind create/update/delete)**: area="wot"; summary "Změna kredity: 12 000 → 15 500".
  - **AI confirm / reject pending action**: area="ai"; action_type="approve" / "reject"; summary "Potvrzena akce add_work_session (2026-09-20 / 8h)" + user_context="ai_confirm".
  - **Planner / system (později bod 2+5)**: zatím ne, připraveno.
- **Acceptance Criteria Addressed**: AC-AL-2
- **Test Requirements**:
  - `rule` TR-1.3.1: 9 integrací provedeme; `SELECT COUNT(DISTINCT area) FROM activity_logs` = 9. (Vytvoříme záznamy v testovacím fixture.)
- **Notes**: Pokud write operace vrací HTTP chybu (400/404/500), db.rollback() a activity by se neměl uložit – díky stejnému commitu je to automatické.

## Task 1.4: Endpointy GET /activity + GET /dashboard recent_activity (read-only)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1.1, 1.2, 1.3
- **Description**:
  - `GET /activity`:
    - Query params: `area? (string)`, `action_type? (string)`, `limit? (int, default 50, max 500)`, `offset? (int, default 0)`, `from? (ISO DateTime)`, `to? (ISO DateTime)`, `q? (string – ILIKE %q% po poli summary)`
    - Seřazení `ORDER BY timestamp DESC, id DESC`
    - Vrací JSON `{items: [{id, timestamp, area, action_type, entity_type, entity_id, summary, user_context}], total: int, limit, offset}`
  - `GET /activity/{id}`: detail, delta_json parsovaný jako objekt
  - Do existujícího `GET /dashboard` (read-only! žádný write snapshot):
    - Přidej klíč `"recent_activity": [5 nejnovějších záznamů {timestamp, area, action_type, summary}]`
    - **DŮLEŽITÉ: `/dashboard` NIKDY NEVOLÁ ensure_goal_progress_snapshot.** Pouze read-only data.
  - Žádný DELETE /activity endpoint – audit je append-only.
- **Acceptance Criteria Addressed**: FR-AL-4, FR-AL-5, AC-AG-3 (dashboard 0 writes)
- **Test Requirements**:
  - `rule` TR-1.4.1: GET /dashboard recent_activity klíč je v odpovědi typu list, délka <=5.
  - `rule` TR-1.4.2: 55 activity fixtures; GET /activity?limit=20 offset=0 → 20, offset=20 → 20, offset=40 → 15, součet 55.
  - `rule` TR-1.4.3: 10x zavolej GET /dashboard, GoalProgressHistory stále prázdná (COUNT 0).
- **Notes**: q parametr používá `ILIKE %xyz%`. PostgreSQL optimalizace pro 10k řádků není třeba.

## Task 1.5: FE stránka /activity časová osa + filtry
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1.4
- **Description**: Vytvoř `frontend/app/activity/page.tsx` ("use client").
  - Layout: 2 sloupce (L: filtry, R: časová osa). Na mobilu filtry nahoře, pak osa.
  - Filtry: Area (multi-select z 9 oblastí), Action type (single), Q search input přes summary, Od/Do datum.
  - Časová osa: Skupiny podle dne (dnes / včera / datum s hvězdičkou). Grupa header = den.
  - Karty: Barvení dle area:
    - finance: zelená (income) / červená (expense) → podle summary prefix +/-
    - work: modrá
    - goals: fialová
    - memory: světle šedá
    - school: oranžová
    - mff: tyrkysová
    - wot: tmavě zelená
    - ai: světle modrá
    - system: tmavě šedá
  - Ikona pro každý action_type (create = ✚, update = ✎, delete = 🗑, approve = ✓, reject = ✗, snapshot = 📊, scheduler = ⏰, backup = 💾, expire = ⧗, sync = ⇌, error = ⚠).
  - Click na kartu → expandovatelný detail delta JSON (kódový blok).
  - Infinite scroll / Načíst další tlačítko na konci seznamu.
  - Do `frontend/components/Sidebar.tsx` přidej odkaz 📜 **Aktivita** na `/activity`.
- **Acceptance Criteria Addressed**: AC-AL-3, AC-RUB-1
- **Test Requirements**:
  - `rule` TR-1.5.1: npm run build → routa `/activity` je mezi generovanými routami (po dokončení celé roadmap = 15 rout: 13 původní + activity + login).
  - `rubric` TR-1.5.2: Kvalita UI AC-RUB-1; scale 0–5, threshold >= 4; evidence screenshot + zdroják.
- **Notes**: Žádný CSV export, žádné DELETE tlačítka v UI (audit append-only).

## Task 1.6: Unit testy Activity Log
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 1.1 až 1.5
- **Description**: Vytvoř `backend/tests/test_activity_log.py`.
  - `test_model_structure` (TR-1.1.1, TR-1.1.2).
  - `test_dedupe_key_idempotent` (TR-1.2.1).
  - `test_transaction_boundary_rollback` (TR-1.2.2) – použij temp DB, db.add activity, potom rollback, ověř že není v tabulce.
  - `test_9_write_hooks_9_areas` (TR-1.3.1).
  - `test_endpoint_filters` (TR-1.4.1, TR-1.4.2).
  - `test_dashboard_never_writes_snapshots` (TR-1.4.3) – fixture 0 snapshotů, 10x GET dashboard, stále 0.
- **Acceptance Criteria Addressed**: NFR-2 (test suite 70+ PASS)
- **Test Requirements**:
  - `rule` TR-1.6.1: `python -m unittest backend.tests.test_activity_log -v` 6/6 PASS.

---

## Task 2.1: Vytvoř backend/requirements.txt + instalace Alembic APScheduler bcrypt
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1 (Activity Log komplet hotový, poslední runtime ALTER tam je).
- **Description**:
  - Vytvoř `backend/requirements.txt` s pinovanými verzemi:
    ```
    fastapi>=0.110,<1
    uvicorn>=0.27,<1
    sqlalchemy>=2.0,<3
    python-dotenv>=1.0,<2
    alembic>=1.13,<2
    APScheduler>=3.10,<4
    bcrypt>=4.0,<5
    psycopg2-binary>=2.9,<3 ; platform_system != "Darwin" or sys_platform != "darwin"
    email-validator>=2.0,<3
    ```
  - Spusť lokálně `pip install -r requirements.txt`.
  - Ověř `alembic --version` funguje.
- **Acceptance Criteria Addressed**: FR-ALM-3, Constraints (dependencies)
- **Test Requirements**:
  - `rule` TR-2.1.1: `pip show alembic apscheduler bcrypt` → všechny 3 jsou nainstalované.

## Task 2.2: Inicializovat alembic strukturu (alembic.ini, env.py, versions/)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2.1
- **Description**:
  - V `backend/` adresáři inicializuj strukturu (nebo ručně vytvoř):
    - `backend/alembic.ini`:
      ```ini
      [alembic]
      script_location = alembic
      sqlalchemy.url = %(DATABASE_URL)s
      postgresql_hstore = off
      timezone = UTC
      [loggers] keys = root,sqlalchemy,alembic
      ```
    - `backend/alembic/env.py`:
      ```python
      from logging.config import fileConfig
      import os, sys
      sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
      from dotenv import load_dotenv
      load_dotenv()
      from sqlalchemy import engine_from_config, pool
      from alembic import context
      from database import Base, DATABASE_URL
      import models  # noqa: F401 – importuje VŠECHNY modely, aby metadata byla naplněná

      config = context.config
      if not config.get_main_option("sqlalchemy.url"):
          config.set_main_option("sqlalchemy.url", DATABASE_URL)
      if config.config_file_name is not None:
          fileConfig(config.config_file_name)
      target_metadata = Base.metadata
      def run_migrations_offline():
          context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
          with context.begin_transaction():
              context.run_migrations()
      def run_migrations_online():
          connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
          with connectable.connect() as connection:
              context.configure(connection=connection, target_metadata=target_metadata)
              with context.begin_transaction():
                  context.run_migrations()
      if context.is_offline_mode():
          run_migrations_offline()
      else:
          run_migrations_online()
      ```
    - `backend/alembic/versions/` (složka prázdná, zde vzniknou revize 0001…0006).
  - Do `.gitignore` v kořeni: `backend/alembic/versions/*.pyc`, `*.pyc` (pokud tam už nejsou).
- **Acceptance Criteria Addressed**: FR-ALM-2
- **Test Requirements**:
  - `rule` TR-2.2.1: `cd backend && alembic current` – běží bez error (řekne že žádná revize není aplikována).

## Task 2.3: Vytvořit 6 Alembic revizí (0001…0006) podle skutečného pořadí
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2.2
- **Description**: Ručně vytvoř 6 souborů v `backend/alembic/versions/` (autogenerate nepoužívejme, abychom měli kontrolu; později se použije autogenerate pro další změny).

  **0001_baseline_existing_schema.py** – 17 tabulek (models.py **BEZ activity_logs, pending_actions, backup_logs, auth_sessions**). Upgrade = CREATE TABLE pro: FinanceTransaction, Goal, Memory, WotResource, WotGrind, Subject, Assignment, Exam, WorkSession, MffCharacter (s 4 indexy), Conversation, Message, Notification (s 4 indexy), GoalProgressHistory (s 2 indexy), PlannerRecommendationHistory (s 3 indexy). Downgrade = DROP TABLE v opačném pořadí.

  **0002_activity_log.py** – CREATE activity_logs tabulka + 2 indexy (area/timestamp DESC, UNIQUE dedupe_key). Downgrade = DROP TABLE activity_logs, DROP INDEXy.

  **0003_pending_actions.py** – CREATE pending_actions (id, action_id UNIQUE, tool, arguments_json, status, created_at, expires_at, executed_at, result_json). Indexy: ix_pending_action_id UNIQUE, ix_pending_status_expires (status, expires_at). Status CHECK constraint: `CHECK (status IN ('pending','executing','executed','failed','rejected','expired'))`. Downgrade = DROP TABLE.

  **0004_goals_changes.py** – (Pokud nejsou potřeba žádné sloupečky changes, zůstane prázdná; vracíme upgrade/downgrade pass; dokumentujeme že 0004 je rezervovaná pro budoucí goal změny, zde aktuálně žádná změna sloupců.)

  **0005_backup_log.py** – CREATE backup_logs (id, started_at, finished_at, backup_path, size_bytes, ok, error_message, schedule_triggered, cleaned_up_at). Index: ix_backup_started (started_at DESC). Downgrade = DROP.

  **0006_auth_sessions.py** – CREATE auth_sessions (id, token_hash String(255) UNIQUE, created_at, expires_at, revoked_at, user_agent Text, ip_address String(50)). Index: ix_auth_token_hash UNIQUE, ix_auth_expires (expires_at DESC). Downgrade = DROP.

- **Acceptance Criteria Addressed**: AC-ALM-1, FR-ALM-1
- **Test Requirements**:
  - `rule` TR-2.3.1: `alembic upgrade head` na prázdnou PostgreSQL/SQLite → žádná chyba; tabulka `alembic_version.version_num = '0006_...'`
  - `rule` TR-2.3.2: `alembic downgrade base` → všechny tabulky pryč; poté `alembic upgrade head` → stejný výsledek jako po prvním upgrade.
  - `rule` TR-2.3.3: 6 souborů `0001_*.py` až `0006_*.py` je ve versions/ alphabeticky správně.

## Task 2.4: Odstranit runtime ALTER z main.py + přidat startup upgrade head
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2.3
- **Description**:
  1. Odstraň z main.py:
     - Celé funkce `_migrate_goals_table`, `_migrate_memories_table`, `_migrate_work_sessions_table`, `_migrate_mff_characters_table` (a všechny další _migrate_*).
     - Jejich volání (řádky kde se spouštějí hned po `Base.metadata.create_all`).
  2. Přidej novou funkci `_run_alembic_upgrade_head_if_enabled()`:
     ```python
     def _run_alembic_upgrade_head_if_enabled():
         enabled = os.getenv("RUN_ALEMBIC_UPGRADE_AT_STARTUP", "false").strip().lower() == "true"
         if not enabled:
             print("[ALEMBIC] skipped (RUN_ALEMBIC_UPGRADE_AT_STARTUP != true)")
             return
         try:
             from alembic import command
             from alembic.config import Config
             import pathlib
             ini_path = str(pathlib.Path(__file__).parent / "alembic.ini")
             cfg = Config(ini_path)
             # override sqlalchemy.url z DATABASE_URL (zajistí že použije stejné .env)
             from database import DATABASE_URL
             cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
             command.upgrade(cfg, "head")
             print("[ALEMBIC] upgrade head OK")
         except Exception as exc:
             # Chyba Alembic při startupu = CRITICAL; neměli bychom pokračovat ve špatném schématu
             raise RuntimeError(f"[ALEMBIC] upgrade head FAILED: {exc}") from exc
     ```
  3. Pořadí v main.py top-level:
     ```
     Base.metadata.create_all(bind=engine)        # fallback pro SQLite unit testy (vytvoří tabulky co nejsou v Alembic ještě = žádné, ale create_all idempotentní)
     _run_alembic_upgrade_head_if_enabled()       # ✅ novinka
     _pending_actions_startup_recovery()          # az po alembic (v bodu 3)
     _scheduler_start_if_enabled()                # az po alembic (bod 5)
     ```
  4. Do `backend/.env.template` přidej:
     ```
     # ALEMBIC
     RUN_ALEMBIC_UPGRADE_AT_STARTUP=true
     ```
  5. Do `backend/AGENTS.md` (vytvoř pokud neexistuje) přidej sekci Migrations:
     ```markdown
     ## Migrations (Alembic)
     - Vytvořit revizi (autogenerate z rozdílu models.py vs DB):
       `cd backend && alembic revision --autogenerate -m "popis zmeny"`
     - Aplikovat všechny doposud nevytvořené revize:
       `cd backend && alembic upgrade head`
     - Vrátit o 1 revizi zpět:
       `cd backend && alembic downgrade -1`
     - Kontrola aktuálně aplikované revize:
       `alembic current`
     - **Poznámka při deploy**: `RUN_ALEMBIC_UPGRADE_AT_STARTUP=true` spouští upgrade při každem startu backendu.
     ```
  6. Do `run-backend.cmd` (v kořeni) přidej před uvicorn: `set RUN_ALEMBIC_UPGRADE_AT_STARTUP=true`.
- **Acceptance Criteria Addressed**: AC-ALM-2, FR-ALM-3, FR-ALM-4
- **Test Requirements**:
  - `rule` TR-2.4.1: `rg -n "ALTER TABLE" backend/main.py` = 0 matchů (komentáře dovolené).
  - `rule` TR-2.4.2: Prázdná DB, RUN_ENABLED=true, spust uvicorn, ukonči → `alembic_version.version_num = poslední 0006_*`.
  - `rule` TR-2.4.3: `alembic history` vypíše 6 revizí v pořadí 0001…0006.

## Task 2.5: Test suite Alembic smoketest
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 2.4
- **Description**: Vytvoř `backend/tests/test_alembic_migration.py`
  - `test_upgrade_down_up_idempotent` (TR-2.3.2): temp SQLite file DB; upgrade head; downgrade base; upgrade head znovu; porovnej tabulky (počet, názvy) po 1. a 3. kroku – shodné.
  - `test_main_no_runtime_alter` (TR-2.4.1): `grep -n` assertion přes source text main.py.
- **Acceptance Criteria Addressed**: NFR-2
- **Test Requirements**:
  - `rule` TR-2.5.1: 2/2 unit testů PASS.

---

## Task 3.1: PendingAction model už přítomen 0003; ai.py refactor na DB (6-stavový automat)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2 (Alembic celý hotový, 0003_pending_actions je v DB). Also Task 1.3 (activity systém existuje).
- **Description**:
  - Smaž z `ai.py`:
    ```
    PENDING_ACTIONS_LOCK = threading.Lock()
    PENDING_ACTIONS: dict[str, dict] = {}
    PENDING_ACTION_TTL_SECONDS = 30 * 60
    ```
    a původní funkce `_store_pending_action` a `_pop_pending_action` (staré in-memory verze).
  - Nahraď novými DB implementacemi:
    ```python
    PENDING_ACTION_TTL_SECONDS = 30 * 60  # zachováno 30 min

    def _store_pending_action(tool: str, arguments: dict) -> str:
        action_id = "pa_" + secrets.token_urlsafe(9)
        from database import SessionLocal
        from models import PendingAction
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            expires = now + timedelta(seconds=PENDING_ACTION_TTL_SECONDS)
            pa = PendingAction(
                action_id=action_id,
                tool=tool,
                arguments_json=json.dumps(arguments, ensure_ascii=False),
                status="pending",
                created_at=now,
                expires_at=expires,
            )
            db.add(pa)
            db.commit()
            return action_id
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _get_pending_for_confirm(action_id: str) -> dict | None:
        """Atomicky přepne pending -> executing. Vrátí dict s tool, arguments, id nebo None."""
        from database import SessionLocal
        from models import PendingAction
        from sqlalchemy import update, select
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            stmt = (
                update(PendingAction)
                .where(PendingAction.action_id == action_id)
                .where(PendingAction.status == "pending")
                .where(PendingAction.expires_at > now)
                .values(status="executing", executed_at=now)
                .returning(PendingAction.id, PendingAction.tool, PendingAction.arguments_json, PendingAction.action_id)
            )
            # SQLite podpora RETURNING? SQLite 3.35+ ano; pokud ne, fallback:
            try:
                res = db.execute(stmt).fetchone()
            except Exception:
                # fallback pro starší SQLite: SELECT + UPDATE (risiko race, ale pro SQLite testy OK)
                cand = db.execute(select(PendingAction).where(PendingAction.action_id == action_id)).scalar_one_or_none()
                if cand and cand.status == "pending" and cand.expires_at and cand.expires_at > now:
                    cand.status = "executing"
                    cand.executed_at = now
                    res = (cand.id, cand.tool, cand.arguments_json, cand.action_id)
                else:
                    res = None
            db.commit()
            if not res:
                return None
            id_, tool, args_json, aid = res
            return {"id": id_, "action_id": aid, "tool": tool, "arguments": json.loads(args_json) if args_json else {}}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _mark_pending_status(action_row_id: int, status: str, result_json: str | None = None):
        from database import SessionLocal
        from models import PendingAction
        db = SessionLocal()
        try:
            pa = db.get(PendingAction, action_row_id)
            if pa:
                pa.status = status
                if result_json is not None:
                    pa.result_json = result_json
                db.commit()
        finally:
            db.close()
    ```
  - Refaktoruj `execute_confirm_action(action_id)` takto:
    1. `stored = _get_pending_for_confirm(action_id)` – pokud None = 409 action_not_available.
    2. Získej tool_name a arguments.
    3. Ověř že tool_name IN WRITE_TOOL_FUNCTIONS.
    4. `fn = WRITE_TOOL_FUNCTIONS[tool_name]`; `try: result = fn(**arguments); ok=True; status_after='executed'`; except Exception as exc: result=str(exc); ok=False; status_after='failed'.
    5. `_mark_pending_status(stored["id"], status_after, json.dumps({"ok": ok, "result": result}, ensure_ascii=False, default=str))`.
    6. Zároveň **Activity Log** (importovat activity_service.log_activity + nová db session? nebo připoj k tomu): area="ai" action_type="approve" pokud ok / "reject" v reject routě; summary: f"{status_after}: {tool_name} – {action_id}".
    7. Vrať stejný tvar JSON `{ok, error, detail, result}` jako původně (zachovat FE kompatibilitu).
  - Přidej `POST /chat/reject` endpoint v main.py (pokud ještě neexistuje):
    - Přijme `{action_id}`.
    - Update `PendingAction SET status='rejected' WHERE action_id=X AND status IN ('pending','executing')`.
    - ActivityLog area="ai" action_type="reject".
    - Vrátí 200 OK.
- **Acceptance Criteria Addressed**: FR-PA-1 až FR-PA-4, FR-PA-6, AC-PA-1, AC-PA-2, AC-PA-3
- **Test Requirements**:
  - `rule` TR-3.1.1: Vlož 2 pending rows → simuluj SIGKILL backendu (v testu = jen zavři spojení, znovu načti DB) → oba 2 stále pending.
  - `rule` TR-3.1.2: 2× současný `_get_pending_for_confirm(pa_X)` (dva thready / sekvenčně s transakcí) – 1× vrátí dict, 2× None a DB status='executing'.
  - `rule` TR-3.1.3: CHECK constraint v pending_actions zakáže 'foo' status (vyhodí IntegrityError při insertu).

## Task 3.2: Startup pending recovery + GET /pending endpoint
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 3.1
- **Description**:
  - V main.py po `_run_alembic_upgrade_head_if_enabled()` přidej:
    ```python
    def _pending_actions_startup_recovery():
        from database import SessionLocal
        from models import PendingAction
        from activity_service import log_activity
        from sqlalchemy import select, update
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            # Najdi všechny pending/executing co vypršely
            expired = db.execute(
                select(PendingAction)
                .where(PendingAction.status.in_(["pending", "executing"]))
                .where(PendingAction.expires_at < now)
            ).scalars().all()
            if expired:
                count = 0
                for pa in expired:
                    pa.status = "expired"
                    log_activity(db, "system", "expire",
                                 f"Pending action {pa.action_id} ({pa.tool}) vypršel TTL 30 min",
                                 dedupe_key=f"pa-expire:{pa.action_id}", user_context="system")
                    count += 1
                db.commit()
                print(f"[PENDING] recovery: expired {count} actions")
            else:
                print("[PENDING] recovery: nothing expired")
        except Exception as exc:
            db.rollback()
            print(f"[PENDING] recovery FAILED: {exc}")
        finally:
            db.close()

    # Volání na konci top-level imports/init sekce main.py
    _pending_actions_startup_recovery()
    ```
  - Endpoint `GET /pending`:
    - Vrací posledních 20 záznamů (WHERE created_at >= now - 10 min a status IN ('pending','executing','approved','executed') – jde o debugging endpoint).
    - Dostupné pouze lokálně / později pod AUTH (po bodu 7). Nyní bez auth.
- **Acceptance Criteria Addressed**: FR-PA-5, AC-PA-1 (po restartu jsou pending stále)
- **Test Requirements**:
  - `rule` TR-3.2.1: Vlož DB pending s expires_at = now - 3660. Spusť `_pending_actions_startup_recovery()`. DB status = 'expired'; activity_logs obsahuje 1 system/expire.

## Task 3.3: Unit testy Persistent pending
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 3.1, 3.2
- **Description**: Vytvoř `backend/tests/test_pending_persistent.py`.
  - `test_pending_survives_restart` (TR-3.1.1).
  - `test_confirm_atomic_dedup` (TR-3.1.2).
  - `test_status_machine_check_constraint` (TR-3.1.3).
  - `test_startup_expired_recovery` (TR-3.2.1).
  - `test_confirm_then_reject_409`: po úspěšném confirmu / pending už executing, druhý pokus confirm stejného action_id = 409.
- **Acceptance Criteria Addressed**: NFR-2
- **Test Requirements**:
  - `rule` TR-3.3.1: 5/5 unit testů PASS.

---

## Task 4.1: 5 nových automatic goal sources do 1 místa (goal_history_service)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2 (Alembic hotové). Bez závislosti na pending.
- **Description**:
  - Rozšiř `compute_automatic_goal_current_value(db: Session, source, today=None)` v `goal_history_service.py`:
    1. `finance_month_income`:
       ```python
       if source == "finance_month_income":
           d = today or date.today()
           total = 0.0
           # Postgres/SQLite unified rok-mesic string compare
           ym = f"{d.year:04d}-{d.month:02d}"
           for amt, ca_str in db.query(
               FinanceTransaction.amount,
               func.to_char(FinanceTransaction.created_at, 'YYYY-MM') if engine_is_postgres else func.strftime('%Y-%m', FinanceTransaction.created_at)
           ).filter(FinanceTransaction.transaction_type == "income").all():
               if ca_str == ym:
                   total += float(amt or 0)
           return float(total)
       ```
       (Jednodušší: Získej všechny v měsíci rovnou s BETWEEN, přes date range.)
       Lepší implementace:
       ```python
       d = today or date.today()
       month_start = date(d.year, d.month, 1)
       if d.month == 12:
           month_end = date(d.year + 1, 1, 1) - timedelta(days=1)
       else:
           month_end = date(d.year, d.month + 1, 1) - timedelta(days=1)
       # finance_month_income:
       return float(
           db.query(func.coalesce(func.sum(FinanceTransaction.amount), 0.0))
           .filter(FinanceTransaction.transaction_type == "income")
           .filter(cast(FinanceTransaction.created_at, Date) >= month_start)
           .filter(cast(FinanceTransaction.created_at, Date) <= month_end)
           .scalar() or 0.0
       )
       ```
    2. `finance_month_expenses` – totéž transaction_type=expense.
    3. `work_month_earnings`:
       ```python
       d = today or date.today()
       m_start = date(d.year, d.month, 1); m_end = last_day(d)
       total = (
           db.query(func.coalesce(func.sum(WorkSession.hours * WorkSession.hourly_rate), 0.0))
           .filter(WorkSession.hourly_rate > 0)
           .filter(WorkSession.date >= m_start).filter(WorkSession.date <= m_end).scalar()
       )
       return float(total or 0.0)
       ```
    4. `school_completed_assignments`:
       ```python
       completed_vals = {'done','completed','finished','dokonceno','hotovo','splneno'}
       cnt = db.query(func.count(Assignment.id)).filter(
           func.lower(func.coalesce(Assignment.status, '')).in_(completed_vals)
       ).scalar()
       return float(cnt or 0)
       ```
    5. `school_open_assignments`:
       ```python
       completed_vals = {'done','completed','finished','dokonceno','hotovo','splneno'}
       total = db.query(func.count(Assignment.id)).scalar() or 0
       done = db.query(func.count(Assignment.id)).filter(
           func.lower(func.coalesce(Assignment.status, '')) != ''  # nechceme NULL sem do INclude
       ).filter(func.lower(func.coalesce(Assignment.status, '')).in_(completed_vals)).scalar() or 0
       # NULL považujeme za open
       return float(total - done)
       ```
  - **Do `tools.py` NEPIŠ DUPLICITNÍ LOGIKU.** Místo toho:
    ```python
    def _compute_automatic_goal_current(source: str) -> float | None:
        # JEDINÁ SOUBOR PRAVDY = goal_history_service
        from goal_history_service import compute_automatic_goal_current_value
        db = SessionLocal()
        try:
            return compute_automatic_goal_current_value(db, source)
        finally:
            db.close()
    ```
  - Ověř že Dashboard, Planner, Scheduler volají service (ne starou lokální logiku tools.py – Dashboard by měl volat `compute_goal_progress_and_value`, což už volá service; správně).
  - Do `tools.py get_goals()` přidej `source_description` dict:
    ```python
    SOURCE_DESCRIPTIONS = {
        "finance_balance": "Aktuální bilance (příjmy mínus výdaje)",
        "work_month_hours": "Odpracované hodiny tento měsíc",
        "mff_t4_count": "Počet postav Tier 4 (MFF)",
        "mff_built_t4_count": "Dokončené T4 postavy (100 % build)",
        "mff_high_priority_built_count": "Hotové high-priority MFF postavy",
        "finance_month_income": "Příjmy v tomto měsíci",
        "finance_month_expenses": "Výdaje v tomto měsíci",
        "work_month_earnings": "Výdělky za tento měsíc (hodiny × sazba)",
        "school_completed_assignments": "Dokončené školní úkoly",
        "school_open_assignments": "Otevřené / nedokončené úkoly (včetně NULL status)",
    }
    ```
- **Acceptance Criteria Addressed**: FR-AG-1 (centralizace 1 místo), FR-AG-2 (5 nových), AC-AG-1, AC-AG-2
- **Test Requirements**:
  - `rule` TR-4.1.1: 5 nových + 5 původních = 10 sources, žádný nevrátí None při správných fixtures (income+expense+work+assignments existují).
  - `rule` TR-4.1.2: Grep v tools.py těla `_compute_automatic_goal_current` – neobsahuje slova `SUM(`, `query(` – pouze import + call goal_history_service.
  - `rule` TR-4.1.3: `school_open_assignments` počítá NULL status správně: fixture 3 assignments (1 done, 1 todo, 1 NULL status). Očekávaná hodnota = 2.0.

## Task 4.2: Goals FE select rozšíření
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 4.1
- **Description**:
  - V `frontend/app/goals/page.tsx`:
    - Pokud source select ještě neexistuje (jen textový input), nahraď `<select>`:
      ```tsx
      <label>Tracking source</label>
      <select value={source} onChange={e => setSource(e.target.value)} disabled={trackingType !== 'automatic'}>
        <option value="">Ruční (manuální zadávání progresu)</option>
        <option value="finance_balance">Bilance (Finance celkem)</option>
        <option value="work_month_hours">Hodiny tento měsíc (Práce)</option>
        <option value="mff_t4_count">T4 celkem (MFF)</option>
        <option value="mff_built_t4_count">T4 hotové (MFF)</option>
        <option value="mff_high_priority_built_count">Hotové high-priority (MFF)</option>
        <option value="finance_month_income">Měsíční příjmy (Finance)</option>
        <option value="finance_month_expenses">Měsíční výdaje (Finance)</option>
        <option value="work_month_earnings">Měsíční výdělky (Práce)</option>
        <option value="school_completed_assignments">Dokončené úkoly (Škola)</option>
        <option value="school_open_assignments">Nedokončené úkoly (Škola)</option>
      </select>
      ```
    - Pokud tracking_type = 'manual' → select je disabled a value=''.
    - V card cíle: pod progress barem zobraz malý text `{source_description || ''}`.
- **Acceptance Criteria Addressed**: FR-AG-3, FR-AG-4, AC-AG-2
- **Test Requirements**:
  - `rule` TR-4.2.1: Grep goals/page.tsx "finance_month_income" | 5 nových strings → 5 matchů.
  - `rule` TR-4.2.2: `npm run build` projde (14 rout doposud).

## Task 4.3: Unit testy Goals 2.0
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 4.1, 4.2
- **Description**: Vytvoř `backend/tests/test_goals_automatic_v2.py`.
  - `test_10_sources_values_correct` (TR-4.1.1) – fixtures, spust obě (tools.py delegát, service) porovnej, hodnoty == reference SQL.
  - `test_school_open_counts_null_status` (TR-4.1.3).
  - `test_tools_delegates_to_service` (TR-4.1.2) – načti source text function; assert neobsahuje 'SUM('.
- **Acceptance Criteria Addressed**: NFR-2
- **Test Requirements**:
  - `rule` TR-4.3.1: 3/3 unit testů PASS.

---

## Task 5.1: Scheduler APScheduler BackgroundScheduler init
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 4 (Goals 2.0). Závisí na Task 1 (activity existuje) a Task 3 (pending recovery spuštěno před scheduler init).
- **Description**:
  - V main.py přidej:
    ```python
    def _scheduler_start_if_enabled():
        import os
        if os.getenv("SCHEDULER_ENABLED", "false").strip().lower() != "true":
            print("[SCHEDULER] disabled")
            return None
        interval = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "3600"))
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            sched = BackgroundScheduler(timezone="UTC")

            def hourly_job_wrapper():
                from database import SessionLocal
                from activity_service import log_activity
                from notifications_service import generate_notifications
                from models import Goal
                from goal_history_service import ensure_goal_progress_snapshot
                from backup_service import run_backup, cleanup_retention  # z bodu 6 později – scheduler integrace
                import datetime as _dt

                # NOTE: backup se spouštěl dříve jen pokud hodina = BACKUP_SCHEDULE_HOUR (prozatím bez backup bodu 6, přidáme později v Task 6.2)

                db = SessionLocal()
                t0 = _dt.datetime.utcnow()
                n_notifs = 0
                n_snaps = 0
                duration_ms = 0
                try:
                    n_notifs = int(generate_notifications(db) or 0)

                    for goal in db.query(Goal).filter(Goal.status == "active").filter(Goal.tracking_type.ilike("automatic")).all():
                        if ensure_goal_progress_snapshot(db, goal, today=_dt.date.today()):
                            n_snaps += 1

                    db.commit()  # notifikace a snapshoty + activity společný commit? snapshot ano,
                                 # generate_notifications už asi dělá vlastní commit? ověř – pokud ano, neobaluj; jinak společný.

                    # + Task 6.2 sem potom: if hour == BACKUP_HOUR a dnes nebyl, spusť backup + cleanup

                    duration_ms = int((_dt.datetime.utcnow() - t0).total_seconds() * 1000)
                    log_activity(db, "system", "scheduler",
                                 f"Hourly scheduler OK: {n_notifs} notifikací, {n_snaps} goal snapshots, {duration_ms} ms",
                                 dedupe_key=f"sched-hourly:{t0.strftime('%Y%m%d-%H')}",  # 1 za hodinu
                                 user_context="scheduler")
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    duration_ms = int((_dt.datetime.utcnow() - t0).total_seconds() * 1000)
                    db2 = SessionLocal()
                    try:
                        log_activity(db2, "system", "error",
                                     f"Hourly scheduler FAILED {type(exc).__name__}: {str(exc)[:200]}",
                                     dedupe_key=f"sched-hourly-error:{t0.strftime('%Y%m%d-%H:%M')}",
                                     user_context="scheduler")
                        db2.commit()
                    finally:
                        db2.close()
                    # NIKDY nevyhazuj SystemExit
                finally:
                    db.close()

            sched.add_job(hourly_job_wrapper, 'interval', seconds=interval, max_instances=1, coalesce=True)
            # Coalesce = pokud se z nějakého důvodu 2 úlohy najednou (thread spaní), spustí jen 1 (spojí).
            sched.start()
            print(f"[SCHEDULER] started, every {interval}s (single worker)")
            return sched
        except Exception as exc:
            raise RuntimeError(f"[SCHEDULER] start FAILED: {exc}") from exc
    ```
  - Volání scheduler startup v main.py pořadí:
    1. Base.metadata.create_all
    2. _run_alembic_upgrade_head_if_enabled
    3. _pending_actions_startup_recovery
    4. _scheduler_start_if_enabled  ← NOVÉ
  - Do backend/.env.template přidej:
    ```
    # BACKGROUND SCHEDULER – single worker only (--workers 1)
    # Více workerů = každý spustí vlastní scheduler!
    SCHEDULER_ENABLED=false
    SCHEDULER_INTERVAL_SECONDS=3600
    ```
- **Acceptance Criteria Addressed**: FR-BS-1 až FR-BS-4, FR-BS-6, NFR-8 (single-worker)
- **Test Requirements**:
  - `rule` TR-5.1.1: SCHEDULER_ENABLED=true, interval=1 → za 30 ms je spuštěn job; za 5s je v ActivityLog 1 system/scheduler záznam (dedupe key).

## Task 5.2: POST /scheduler/run-now + ENV reference single-worker
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 5.1
- **Description**:
  - Endpoint `POST /scheduler/run-now`:
    - Synchronně spustí ten samý wrapper `hourly_job_wrapper()`.
    - Vrátí JSON `{"ok": true, "notifications_created": N, "snapshots": S, "duration_ms": ms, "trigger": "manual"}`.
  - Do backend/AGENTS.md doplň sekci Scheduler:
    ```markdown
    ## Background Scheduler
    - Jediný podporovaný deploy: `uvicorn main:app --workers 1`. Při více workerech se spustí N schedulerů a notifikace budou duplicitní.
    - Zapnutí: `SCHEDULER_ENABLED=true`.
    - Default interval: každou hodinu (3600 s), upravit přes `SCHEDULER_INTERVAL_SECONDS`.
    - Ruční spuštění (debug): `POST /scheduler/run-now`.
    ```
- **Acceptance Criteria Addressed**: FR-BS-5, AC-BS-1, AC-BS-2
- **Test Requirements**:
  - `rule` TR-5.2.1: 15 cílů fixtures + assignments za 2dny. Spusť `POST /scheduler/run-now`. DB GoalProgressHistory += 15 nových. Notifikace >= 1 nová. ActivityLog system/scheduler existuje.
  - `rule` TR-5.2.2: Grep "single worker" / "--workers 1" v .env.template, AGENTS.md, spec.md → min 2 reference.

## Task 5.3: Unit testy Scheduler
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 5.1, 5.2
- **Description**: Vytvoř `backend/tests/test_scheduler.py`
  - `test_scheduler_run_now_populates_snapshots_and_notifs` (TR-5.2.1)
  - `test_scheduler_error_is_swallowed` – mock generate_notifs raise RuntimeError → po run-now proces stále žije; ActivityLog system/error existuje.
  - `test_env_reference_single_worker` (TR-5.2.2) – grep přes source.
- **Acceptance Criteria Addressed**: NFR-2
- **Test Requirements**:
  - `rule` TR-5.3.1: 3/3 PASS.

---

## Task 6.1: BackupLog model (už v 0005) + backup_service.py
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 5 (Scheduler hotový, bez bodu 6 integrace). Závisí na Task 1 (activity).
- **Description**:
  - Ověř že v models.py je `BackupLog` (měl by být):
    ```python
    class BackupLog(Base):
        __tablename__ = "backup_logs"
        id = Column(Integer, primary_key=True)
        started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
        finished_at = Column(DateTime, nullable=True)
        backup_path = Column(String(500), nullable=False)
        size_bytes = Column(Integer, nullable=True)
        ok = Column(Boolean, nullable=False, default=False)
        error_message = Column(Text, nullable=True)
        schedule_triggered = Column(Boolean, nullable=False, default=False)
        cleaned_up_at = Column(DateTime, nullable=True)  # retention smazáno
    ```
    - Pokud není v models.py (0005 již vytvoří tabulku ale model by měl být pro ORM), P�IDEJ.
  - Vytvoř `backend/backup_service.py`:
    ```python
    import os, gzip, shutil, subprocess, pathlib, datetime as dt, hashlib
    from database import SessionLocal
    from models import BackupLog
    from activity_service import log_activity

    def _human_bytes(n: int) -> str:
        for u in ["B", "KB", "MB", "GB"]:
            if n < 1024:
                return f"{n:.1f} {u}"
            n /= 1024
        return f"{n:.1f} TB"

    def _db_type() -> tuple[str, str]:  # ("postgresql" / "sqlite", file_or_conn_str)
        from database import DATABASE_URL
        url = DATABASE_URL or ""
        if url.startswith("postgresql"):
            return "postgresql", url
        if url.startswith("sqlite"):
            # sqlite:///./path.db
            path = url.replace("sqlite:///", "").replace("sqlite://", "")
            return "sqlite", os.path.abspath(path)
        return "unknown", ""

    def run_backup(schedule_triggered: bool = False) -> BackupLog:
        db = SessionLocal()
        backup_dir = os.getenv("BACKUP_DIR", "./backups")
        retention = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
        pathlib.Path(backup_dir).mkdir(parents=True, exist_ok=True)

        now = dt.datetime.utcnow()
        stamp = now.strftime("%Y%m%d-%H%M%S")
        ok = False
        err = None
        final_path = None
        size = 0
        bl = BackupLog(started_at=now, backup_path="pending", size_bytes=None, ok=False, schedule_triggered=schedule_triggered)
        db.add(bl)
        db.commit()
        db.refresh(bl)
        try:
            dbt, info = _db_type()
            if dbt == "postgresql":
                filename = f"standa-hub-{stamp}.dump"
                final_path = os.path.abspath(os.path.join(backup_dir, filename))
                env = os.environ.copy()
                pg_pass = None
                # DATABASE_URL může být postgresql://user:pass@host:port/dbname – pg_dump použije
                cp = subprocess.run(
                    ["pg_dump", info, "--format=c", "--compress=9", f"--file={final_path}"],
                    capture_output=True, text=True, env=env, timeout=600
                )
                if cp.returncode != 0:
                    raise RuntimeError(f"pg_dump failed ({cp.returncode}): {cp.stderr[:500]}")
                # Verify
                cp2 = subprocess.run(["pg_restore", "--list", final_path], capture_output=True, timeout=120)
                if cp2.returncode != 0:
                    raise RuntimeError(f"pg_restore --list failed ({cp2.returncode})")
                ok = True
            elif dbt == "sqlite":
                filename = f"standa-hub-{stamp}.sqlite.gz"
                raw_path = os.path.join(backup_dir, f"standa-hub-{stamp}.sqlite")
                final_path = raw_path + ".gz"
                src_db_path = info
                # sqlite3 backup
                cp = subprocess.run(["sqlite3", src_db_path, f".backup {raw_path}"], capture_output=True, timeout=300)
                if cp.returncode != 0:
                    raise RuntimeError(f"sqlite3 .backup failed: {cp.stderr.decode('utf-8',errors='ignore')[:300]}")
                with open(raw_path, "rb") as f_in:
                    with gzip.open(final_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                os.remove(raw_path)
                # Verify gunzip test
                with gzip.open(final_path, "rb") as f:
                    f.read(16)  # header ok = valid gzip (pokud se nezpůsobí IOError)
                ok = True
            else:
                raise RuntimeError(f"Unknown DB type: {dbt} (DATABASE_URL)")

            size = os.path.getsize(final_path) if final_path and os.path.exists(final_path) else 0
        except Exception as exc:
            err = f"{type(exc).__name__}: {str(exc)[:600]}"
            ok = False
        finally:
            bl.finished_at = dt.datetime.utcnow()
            bl.backup_path = final_path or f"failed:{stamp}"
            bl.size_bytes = size
            bl.ok = ok
            bl.error_message = err
            db.commit()

            try:
                if ok:
                    log_activity(db, "system", "backup",
                                 f"Backup OK: {os.path.basename(final_path)} ({_human_bytes(size)})",
                                 dedupe_key=f"backup:{now.strftime('%Y%m%d-%H%M')}",
                                 user_context="system")
                else:
                    log_activity(db, "system", "backup",
                                 f"Backup SELHAL: {(err or '')[:180]}",
                                 dedupe_key=f"backup-err:{now.strftime('%Y%m%d-%H%M')}",
                                 user_context="system")
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()

        # Retention cleanup po každém úspěšném (či neúspěšném) backupu:
        try:
            cleanup_retention(retention_days=retention)
        except Exception:
            pass
        # Načti znovu nejnovější stav pro return
        db = SessionLocal()
        try:
            bl2 = db.get(BackupLog, bl.id)
            return bl2
        finally:
            db.close()

    def cleanup_retention(retention_days: int = 30):
        """Smaže soubory a označí v DB cleaned_up_at pro záznamy starší > retention_days."""
        backup_dir = os.getenv("BACKUP_DIR", "./backups")
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=retention_days)
        db = SessionLocal()
        try:
            candidates = (
                db.query(BackupLog)
                .filter(BackupLog.started_at < cutoff)
                .filter(BackupLog.cleaned_up_at.is_(None))
                .filter(BackupLog.ok == True)
                .all()
            )
            deleted_files = 0
            for b in candidates:
                if b.backup_path and os.path.exists(b.backup_path):
                    try:
                        os.remove(b.backup_path)
                        deleted_files += 1
                    except OSError:
                        pass
                b.cleaned_up_at = dt.datetime.utcnow()
            if candidates:
                log_activity(db, "system", "backup-cleanup",
                             f"Retention {retention_days}d: smazáno {deleted_files} souborů / {len(candidates)} záznamů",
                             dedupe_key=f"backup-retention:{cutoff.strftime('%Y%m%d')}-{retention_days}",
                             user_context="system")
            db.commit()
        finally:
            db.close()

    def backup_not_run_today(today: dt.date | None = None) -> bool:
        today = today or dt.date.today()
        db = SessionLocal()
        try:
            t0 = dt.datetime.combine(today, dt.time(0, 0, 0))
            t1 = t0 + dt.timedelta(days=1)
            any_ok = (
                db.query(BackupLog)
                .filter(BackupLog.started_at >= t0)
                .filter(BackupLog.started_at < t1)
                .filter(BackupLog.ok == True)
                .first()
            )
            return any_ok is None
        finally:
            db.close()
    ```
- **Acceptance Criteria Addressed**: FR-BK-1 až FR-BK-3, FR-BK-7, AC-BK-1, AC-BK-2
- **Test Requirements**:
  - `rule` TR-6.1.1: Temp BACKUP_DIR. run_backup() nad SQLite. (1) soubor existuje, (2) size > 100 bytes, (3) BackupLog.ok = True, (4) gzip readable.
  - `rule` TR-6.1.2: cleanup_retention(1): 2 fixtures (41d starý = smazán; 2d starý = zůstal) → os.path.exists odpovídá + cleaned_up_at u starého.

## Task 6.2: Scheduler backup job integrace + BE endpointy
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 6.1, Task 5 (Scheduler, kde vložíme volání backup)
- **Description**:
  - Do scheduler `hourly_job_wrapper()` (Task 5.1) přidej na konec bloku (před try/except konec):
    ```python
    # --- BACKUP (jen v hodinu BACKUP_SCHEDULE_HOUR a pokud dnes ještě nebyl)
    import os
    try:
        hour_now = _dt.datetime.utcnow().hour
        want_hour = int(os.getenv("BACKUP_SCHEDULE_HOUR", "3"))
        from backup_service import run_backup, backup_not_run_today
        if hour_now == want_hour and backup_not_run_today():
            run_backup(schedule_triggered=True)  # dělá vlastní DB spojení; v rámci wrapperu ok
    except Exception as exc_backup:
        # Nemělo by se stát – run_backup má vlastní try, ale double def.
        print(f"[SCHEDULER] backup sub-call failed: {exc_backup}")
    ```
  - Endpointy do main.py:
    1. `POST /backup/run-now`:
       - Volá `run_backup(schedule_triggered=False)`.
       - Vrací JSON BackupLog serializovaný: `{id, started_at, finished_at, backup_path, size_bytes, ok, error_message, schedule_triggered}`.
    2. `GET /backup/list`:
       - Posledních 30 BackupLog DESC started_at + doplní pole `file_exists` (os.path.exists) a `file_size` aktuální velikost.
       - Vrátí `{items: [...], backup_dir, retention_days}`.
  - Do backend/.env.template:
    ```
    # BACKUP (pg_dump pro Postgres, sqlite .backup + gzip pro SQLite)
    BACKUP_DIR=./backups
    BACKUP_RETENTION_DAYS=30
    # UTC hodina kdy scheduler spustí backup (pokud je scheduler zapnutý)
    BACKUP_SCHEDULE_HOUR=3
    ```
  - Do run-backend.cmd (nebo vytvoř `run-backup.cmd` v kořeni) – nechat uživatele, nyní stačí ENV.
- **Acceptance Criteria Addressed**: FR-BK-4, FR-BK-5, FR-BK-6, AC-BK-1
- **Test Requirements**:
  - `rule` TR-6.2.1: hourly job spuštěný v `hour == BACKUP_SCHEDULE_HOUR=3` (fake) a backup_today_ok = False (zadne dnes) → `run_backup` zavoláno (mock). Pokud hour != 3, nebo už dnes běžel → nevolá.

## Task 6.3: Unit testy Backup
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 6.1, 6.2
- **Description**: Vytvoř `backend/tests/test_backup.py`
  - `test_sqlite_backup_success` (TR-6.1.1)
  - `test_retention_cleanup` (TR-6.1.2)
  - `test_scheduler_hour_trigger_run_only_once_per_day` (TR-6.2.1)
- **Acceptance Criteria Addressed**: NFR-2
- **Test Requirements**:
  - `rule` TR-6.3.1: 3/3 PASS.

---

## Task 7.1: AuthSession model + auth_service.py (bcrypt + rate limit)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 6 (Backup hotový). Auth je poslední. Závisí na Task 1 (activity pro login fail/success).
- **Description**:
  - Pokud ještě v models.py není `AuthSession`, P�IDEJ (0006 už tabulku vytvořil):
    ```python
    class AuthSession(Base):
        __tablename__ = "auth_sessions"
        id = Column(Integer, primary_key=True)
        token_hash = Column(String(255), unique=True, nullable=False, index=True)
        created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
        expires_at = Column(DateTime, nullable=False)
        revoked_at = Column(DateTime, nullable=True)
        user_agent = Column(Text, nullable=True)
        ip_address = Column(String(50), nullable=True)
    ```
  - Vytvoř `backend/auth_service.py`:
    ```python
    import os, secrets, hashlib, threading, datetime as dt, re
    import bcrypt
    from database import SessionLocal
    from models import AuthSession

    # In-memory pokusy per IP (není persistenční; pro 1 user Tailscale dostačující)
    # Pokud někdy více procesů: přesuň do DB tabulky login_attempts.
    _ATTEMPTS_LOCK = threading.Lock()
    _ATTEMPTS: dict[str, tuple[int, float]] = {}  # key = ip_or_ua_hash -> (count, first_fail_ts_unix)
    MAX_ATTEMPTS = 5
    LOCK_SECONDS = 10 * 60

    def _now_unix() -> float:
        return dt.datetime.utcnow().timestamp()

    def auth_is_enabled() -> bool:
        """Pokud AUTH_PIN_HASH není vůbec v env, auth je VYPNUTÝ úplně."""
        v = os.getenv("AUTH_PIN_HASH") or ""
        return len(v.strip()) > 0

    def hash_pin(pin: str) -> str:
        if not re.fullmatch(r"[0-9]{4,6}", pin):
            raise ValueError("PIN musí být 4–6 číslic")
        # bcrypt max 72 bytes; PIN krátký → OK
        return bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")

    def _get_pin_hash() -> str | None:
        return os.getenv("AUTH_PIN_HASH") or None

    def _attempts_key(ip: str | None) -> str:
        ip = (ip or "unknown").strip() or "unknown"
        return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]

    def _rate_limited_check(ip: str | None) -> tuple[bool, str | None]:
        """Vrátí (povoleno_pokračovat, error_msg). Pokud zamčeno, False + zpráva."""
        with _ATTEMPTS_LOCK:
            k = _attempts_key(ip)
            count, first_fail = _ATTEMPTS.get(k, (0, 0.0))
            now = _now_unix()
            if count >= MAX_ATTEMPTS:
                if now - first_fail < LOCK_SECONDS:
                    remaining = int(LOCK_SECONDS - (now - first_fail))
                    return False, f"Příliš mnoho pokusů. Zkuste to prosím za {remaining // 60} min a {remaining % 60} s."
                # Lock vypršel, reset
                _ATTEMPTS[k] = (0, 0.0)
            return True, None

    def _attempt_failed_record(ip: str | None) -> bool:
        """Zvýší počitadlo; vrátí True pokud právě dosáhl MAX a nastavil se lock."""
        with _ATTEMPTS_LOCK:
            k = _attempts_key(ip)
            count, first_fail = _ATTEMPTS.get(k, (0, 0.0))
            if first_fail <= 0.0:
                first_fail = _now_unix()
            count += 1
            _ATTEMPTS[k] = (count, first_fail)
            return count >= MAX_ATTEMPTS

    def verify_pin(pin: str) -> bool:
        """Ověří PIN proti env AUTH_PIN_HASH."""
        h = _get_pin_hash()
        if not h:
            return False
        if not re.fullmatch(r"[0-9]{4,6}", pin):
            return False
        try:
            return bcrypt.checkpw(pin.encode("utf-8"), h.encode("utf-8"))
        except ValueError:
            # invalid hash ve formatu
            return False

    def _sha256_hex(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def generate_session_token() -> str:
        return "sess_" + secrets.token_urlsafe(32)  # plain text co jde do cookie; DB ukládá jen SHA256

    def create_session(db, plain_token: str, *, user_agent: str | None = None, ip_address: str | None = None, ttl_hours: int | None = None) -> AuthSession:
        if ttl_hours is None:
            ttl_hours = int(os.getenv("AUTH_SESSION_TTL_HOURS", "720"))
        now = dt.datetime.utcnow()
        s = AuthSession(
            token_hash=_sha256_hex(plain_token),
            created_at=now,
            expires_at=now + dt.timedelta(hours=ttl_hours),
            revoked_at=None,
            user_agent=(user_agent or "")[:4000] or None,
            ip_address=(ip_address or "")[:50] or None,
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return s

    def lookup_session(db, plain_token: str | None) -> AuthSession | None:
        if not plain_token or not plain_token.startswith("sess_"):
            return None
        th = _sha256_hex(plain_token)
        now = dt.datetime.utcnow()
        s = db.query(AuthSession).filter(AuthSession.token_hash == th).filter(AuthSession.revoked_at.is_(None)).filter(AuthSession.expires_at > now).first()
        return s

    def revoke_session(db, plain_token: str | None):
        if not plain_token:
            return
        th = _sha256_hex(plain_token)
        s = db.query(AuthSession).filter(AuthSession.token_hash == th).first()
        if s and s.revoked_at is None:
            s.revoked_at = dt.datetime.utcnow()
            db.commit()
    ```
  - Do backend/.env.template přidej:
    ```
    # AUTH / PIN
    # Pokud AUTH_PIN_HASH není vůbec nastaven = auth je vypnutý (výchozí pro lokální vývoj).
    # Vygeneruj hash: cd backend && python -c "from auth_service import hash_pin; import os; os.environ.setdefault('AUTH_PIN_HASH',''); print(hash_pin(input('Zadej PIN 4-6 cislic: ')))"
    AUTH_PIN_HASH=
    AUTH_SESSION_TTL_HOURS=720
    # AUTH_COOKIE_SECURE = true pouze nasazení za HTTPS (Tailscale Serve / TLS proxy)
    # Výchozí false = funguje i přes plain HTTP Tailscale IP:
    AUTH_COOKIE_SECURE=false
    ```
  - Do frontend/.env.local.template (nebo vytvoř pokud neexistuje) a .env.template:
    ```
    # Zapne Next.js middleware ochranu FE rout. (Stále API kontroluje!)
    NEXT_PUBLIC_AUTH_ENABLED=true
    # Backend URL pro middleware ověření platnosti session
    NEXT_PUBLIC_API_URL=http://100.102.110.1:8000
    ```
- **Acceptance Criteria Addressed**: FR-AU (VRSTVA B dependency), AC-AU-1 (API layer), AC-AU-3, AC-RUB-3
- **Test Requirements**:
  - `rule` TR-7.1.1: hash("1234") → verify OK; verify("4321") False; jiný salt stejný PIN = verify OK.
  - `rule` TR-7.1.2: 5× špatný pokus, 6. (i správný) = zamčen, vrátí False. Po 10.1 min = zase OK.
  - `rule` TR-7.1.3: `lookup_session(db, plain_token)` nenajde session po `revoke_session(db, token)`.

## Task 7.2: FastAPI Deps + API endpoints (login, logout, validate)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 7.1
- **Description**:
  - V main.py přidej dependency:
    ```python
    from fastapi import Depends, Request, HTTPException, status, Response
    from fastapi.responses import JSONResponse
    from auth_service import auth_is_enabled, lookup_session, verify_pin, create_session, revoke_session, _rate_limited_check, _attempt_failed_record

    def require_auth(request: Request, db: Session = Depends(get_db)):
        if not auth_is_enabled():
            return None  # auth vypnut, pass
        token = request.cookies.get("standa_session") or None
        s = lookup_session(db, token)
        if not s:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error": "auth_required"})
        return s  # můžete později rozšířit o user object, teď jen indikátor
    ```
  - Přidej Depends(require_auth) do všech chráněných endpointů. Nejlépe:
    - Vytvoř router /api pro novější; nebo přidej Depends k:
      - Všech POST/PUT/DELETE work/finance/goals/memory/school/mff/wot/chat endpoints (confirm/reject).
      - GET /dashboard /activity /backup/list /scheduler/run-now /pending /goals /planner endpoints.
    - **Nechať neochraňené**: `/login`, `/auth/session/validate` (GET), OPTIONS (CORS preflight). `/favicon.ico`.
    - **Poznámka**: `/auth/session/validate` musí být dostupný i BEZ auth (pouze ověří zda cookie platí; pokud ne 401 – stejná logika jako u require_auth).
  - Endpointy:
    1. `POST /login (anon)`, req body `{pin: string, next?: string}`:
       ```python
       class LoginRequest(BaseModel):
           pin: str
           next: str | None = "/"
       @app.post("/login")
       def login_endpoint(req: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
           from activity_service import log_activity
           ip = request.client.host if request.client else None
           ua = request.headers.get("user-agent")

           # 1. Rate limit check PŘED bcrypt (nechte útočníky platit lockem, ne CPU)
           ok, msg = _rate_limited_check(ip)
           if not ok:
               raise HTTPException(status_code=429, detail={"error": "too_many_attempts", "detail": msg, "retry_after": LOCK_SECONDS})

           # 2. Valid formátu PIN
           if not re.fullmatch(r"[0-9]{4,6}", req.pin or ""):
               # Nepočítej jako pokus (to je client error)
               raise HTTPException(status_code=400, detail={"error": "invalid_pin_format", "detail": "PIN musí být 4–6 číslic"})

           # 3. Verify
           if verify_pin(req.pin):
               # success – vyčisti počitadlo pro tento IP
               # (Reset: implementovat v _ATTEMPTS dict)
               with _ATTEMPTS_LOCK:
                   _ATTEMPTS.pop(_attempts_key(ip), None)

               plain = generate_session_token()
               s = create_session(db, plain, user_agent=ua, ip_address=ip)
               log_activity(db, "system", "login-success",
                            f"Přihlášení z {ip or '?'}",
                            dedupe_key=f"login-ok:{s.id}:{s.created_at.isoformat()}",
                            user_context="system")
               secure_c = os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() == "true"
               ttl_hours = int(os.getenv("AUTH_SESSION_TTL_HOURS", "720"))
               response.set_cookie(
                   "standa_session", plain,
                   max_age=ttl_hours * 3600,
                   path="/",
                   httponly=True,
                   samesite="lax",
                   secure=secure_c,
               )
               nxt = (req.next or "/")
               if not nxt.startswith("/") or nxt.startswith("//"):
                   nxt = "/"
               return {"ok": True, "redirect_to": nxt, "session_id": s.id}
           else:
               locked = _attempt_failed_record(ip)
               log_activity(db, "system", "login-fail",
                            f"Neúspěšné přihlášení z {ip or '?'}{' (LOCK 10min)' if locked else ''}",
                            dedupe_key=f"login-fail:{_attempts_key(ip)}:{int(_now_unix()//1)}",
                            user_context="system")
               if locked:
                   raise HTTPException(status_code=429, detail={"error": "too_many_attempts", "detail": "5× špatný PIN. Čekejte 10 minut."})
               raise HTTPException(status_code=401, detail={"error": "invalid_credentials", "detail": "Špatný PIN."})
       ```
    2. `POST /logout` (Depends(require_auth) – povinně přihlášen):
       ```python
       @app.post("/logout")
       def logout_endpoint(request: Request, response: Response, db: Session = Depends(get_db), _auth=Depends(require_auth)):
           token = request.cookies.get("standa_session")
           if token:
               revoke_session(db, token)
           response.delete_cookie("standa_session", path="/")
           return {"ok": True}
       ```
    3. `GET /auth/session/validate` (ANON – volá Next.js middleware):
       ```python
       @app.get("/auth/session/validate")
       def auth_session_validate(request: Request, db: Session = Depends(get_db)):
           if not auth_is_enabled():
               return {"ok": True, "auth": "disabled"}
           token = request.cookies.get("standa_session")
           s = lookup_session(db, token)
           if not s:
               raise HTTPException(status_code=401, detail={"error": "auth_required"})
           return {"ok": True, "auth": "valid", "expires_at": s.expires_at.isoformat()}
       ```
- **Acceptance Criteria Addressed**: FR-AU (VRSTVA B komplet), AC-AU-1, AC-AU-2, AC-AU-3
- **Test Requirements**:
  - `rule` TR-7.2.1: AUTH_PIN_HASH = None → 20 requestů na /goals, /finance, /work = 20× 200 OK (auth vypnut).
  - `rule` TR-7.2.2: AUTH = bcrypt("1234"), žádná cookie:
    - Browser-like (Accept text/html) request? Netřeba – API (application/json) = 401.
    - GET /goals = 401 JSON.
    - POST /login 1234 → 200, set-cookie 'standa_session' s HttpOnly.
    - S touto cookie GET /goals = 200 OK.
  - `rule` TR-7.2.3: 5× špatný PIN → 6. = 429 locked.

## Task 7.3: FE – Next.js Middleware (VRSTVA A) + stránka /login
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 7.2 (BE existuje)
- **Description**:
  - Vytvoř `frontend/middleware.ts` (v `frontend/` rootu, vedle app/) – Node runtime:
    ```ts
    import { NextRequest, NextResponse } from "next/server";

    const PROTECTED_PREFIXES = [
      "/ai", "/finance", "/work", "/memory", "/goals", "/planner",
      "/school", "/mff", "/wot", "/activity", "/backup", "/scheduler",
    ];

    function isProtected(pathname: string): boolean {
      if (pathname === "/login") return false;
      if (pathname.startsWith("/_next") || pathname.startsWith("/public/") || pathname === "/favicon.ico") return false;
      return PROTECTED_PREFIXES.some(p => pathname === p || pathname.startsWith(p + "/"));
    }

    export const config = {
      matcher: [
        "/ai/:path*", "/finance/:path*", "/work/:path*", "/memory/:path*", "/goals/:path*",
        "/planner/:path*", "/school/:path*", "/mff/:path*", "/wot/:path*",
        "/activity/:path*", "/backup/:path*", "/scheduler/:path*",
      ],
    };

    export async function middleware(request: NextRequest) {
      const authEnabled = (process.env.NEXT_PUBLIC_AUTH_ENABLED || "true") === "true";
      if (!authEnabled) return NextResponse.next();

      const { pathname, origin, searchParams } = new URL(request.url);
      const sessionCookie = request.cookies.get("standa_session")?.value;

      const loginUrl = new URL("/login", request.url);
      loginUrl.searchParams.set("next", pathname + (request.nextUrl.search || ""));

      if (!sessionCookie) {
        return NextResponse.redirect(loginUrl);
      }

      // Synchronní ověření přes backend API (GET /auth/session/validate)
      const backend = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      try {
        const validateUrl = `${backend.replace(/\/$/, "")}/auth/session/validate`;
        const res = await fetch(validateUrl, {
          method: "GET",
          headers: {
            Accept: "application/json",
            Cookie: `standa_session=${sessionCookie}`,
          },
          cache: "no-store",
        });
        if (res.ok) {
          return NextResponse.next();
        }
        // 401 → smaz cookie a redirect
        const r = NextResponse.redirect(loginUrl);
        r.cookies.delete("standa_session");
        return r;
      } catch (err) {
        // BE nedostupný – není-li auth_enabled=true (uživatel možná nemá backend zapnutý), umožnit přístup
        // Lepší: pokud FE má NEXT_PUBLIC_AUTH_ENABLED=true ale BE neodpovídá, redirect na login s chybovou hláškou.
        loginUrl.searchParams.set("error", "backend_unreachable");
        return NextResponse.redirect(loginUrl);
      }
    }
    ```
  - Vytvoř `frontend/app/login/page.tsx` ("use client"):
    - Layout: středová karta, gradient pozadí (tmavá).
    - Nadpis "🔒 Standa Hub". Podnadpis: "Zadej PIN pro přístup".
    - Input: `<input type="password" inputMode="numeric" pattern="[0-9]*" maxLength={6} autoComplete="one-time-code" />`.
    - 6 teček pod inputem (indikátor délky PINu) – vizuální feedback.
    - Tlačítko "Přihlásit se" (disabled během loading, když PIN < 4).
    - Query param `error=backend_unreachable` → červený banner "Nelze ověřit přístup – server neodpovídá, zkontroluj že běží backend na NEXT_PUBLIC_API_URL."
    - Po 401 invalid PIN → červený banner "Špatný PIN".
    - Po 429 → oranžový "Příliš mnoho pokusů, čekejte 10 minut."
    - Při `keydown` inputu při 6 znacích automaticky submit.
    - Po úspěšném 200 OK login → redirect na `next` nebo `/`.
    - Pokud sem přijde uživatel co už je přihlášený: při prvním renderu (isClient) fetch na `/auth/session/validate` (z apiUrl) → pokud 200 → redirect na `/`.
- **Acceptance Criteria Addressed**: FR-AU (VRSTVA A komplet), AC-AU-1, AC-RUB-3
- **Test Requirements**:
  - `rule` TR-7.3.1: npm run build → routa `/login` mezi generovanými; middleware.ts načten bez error (build projde). Celkem 15 rout: 13 původní + activity + login.

## Task 7.4: Unit testy Auth
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 7.1, 7.2, 7.3
- **Description**: Vytvoř `backend/tests/test_auth.py`
  - `test_hash_verify_pin` (TR-7.1.1) – bcrypt správně, salt random.
  - `test_rate_limit_5_fail_then_lock` (TR-7.1.2) – 5 špatných pokusů, 6 = zamčeno; 10 min+ znovu.
  - `test_lookup_revoked_session_invalid` (TR-7.1.3).
  - `test_auth_disabled_all_pass` (TR-7.2.1) – AUTH_PIN_HASH = None; requesty 20× 200 OK.
  - `test_login_flow_401_then_200` (TR-7.2.2) – POST /login 200 + cookie; následný protected request 200.
  - `test_login_rate_locked_429` (TR-7.2.3) – 5 špatných, 6 = 429.
- **Acceptance Criteria Addressed**: NFR-2
- **Test Requirements**:
  - `rule` TR-7.4.1: 6/6 unit testů PASS.

---

## Task 8.1: FINÁLE – Celá test suite + FE lint/build + ENV audit + docs
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Všechny 7 modulů (Tasks 1.1 – 7.4) – komplet implementace.
- **Description**:
  1. Spusť test suite: `python -m unittest discover -s backend/tests -p "test_*.py" -v` → očekávaný cca 70 testů PASS (původních 45 + 6 nových souborů ~ 25 → cca 70).
  2. Oprav chyby které vyskytnou.
  3. `cd frontend && npm run lint` – 0 errors (warningy mohou zůstat).
  4. `cd frontend && npm run build` – očekáváno 15 rout PASS.
  5. ENV audit backend/.env.template:
     - Ověř že jsou přítomné (Grep): RUN_ALEMBIC_UPGRADE_AT_STARTUP, SCHEDULER_ENABLED, SCHEDULER_INTERVAL_SECONDS, BACKUP_DIR, BACKUP_RETENTION_DAYS, BACKUP_SCHEDULE_HOUR, AUTH_PIN_HASH, AUTH_SESSION_TTL_HOURS, AUTH_COOKIE_SECURE, DATABASE_URL, FRONTEND_ORIGINS
     - Min 10 klíčů = OK.
  6. ENV audit frontend/.env.template:
     - NEXT_PUBLIC_API_URL, NEXT_PUBLIC_AUTH_ENABLED – přítomné.
  7. Backend AGENTS.md final – obsahuje: Migrations, Scheduler (single-worker note), Auth (vygenerování PIN hash, Secure cookie true až po TLS), Backup (pg_dump na PATH, SQLite fallback).
  8. Kontrola že žádný commit do repozitáře neobsahuje skutečné hodnoty (AUTH_PIN_HASH, DATABASE_URL s heslem atd.) – Grep "bcrypt\\$" v rámci kódu mimo .env a .env.local by neměl nic najít mimo test fixtures (které používají mock env).
- **Acceptance Criteria Addressed**: NFR-1 až NFR-8, AC-RUB-2
- **Test Requirements**:
  - `rule` TR-8.1.1: 70+ testů PASS, 0 FAIL.
  - `rule` TR-8.1.2: npm lint 0 errors, npm build 15 rout.
  - `rule` TR-8.1.3: backend/.env.template obsahuje >= 10 nových keys z bodu 5 ENV audit.
  - `rubric` TR-8.1.4: AC-RUB-2 env-only konfigurovatelnost; scale 0–5, threshold >= 4 (5 pokud .env.template má všechny s komentáři).
