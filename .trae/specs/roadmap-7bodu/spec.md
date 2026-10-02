# Standa Hub Roadmap 7 bodů – Product Requirements Document (REV. 2)

## Overview
- **Summary**: Implementace 7 prioritních modulů pro přechod Standa Hub z "MVP lokálního použití" na "odolný 24/7 provoz s auditabilitou a bezpečností". **Změněné pořadí implementace dle zpětné vazby**: 1) Activity Log, 2) Alembic migrace (hned po ActLog – odtud už žádný runtime ALTER), 3) Persistent pending_actions, 4) Automatic Goals 2.0, 5) Background Scheduler, 6) Automatické pg_dump zálohy, 7) Auth/PIN systém.
- **Purpose**: (a) Každá write operace má audit trail ve STEJNÉ transakci s business změnou; (b) žádná ztráta confirmations po restartu; (c) 7 automatických goal sources centrálně na 1 místě; (d) notifikace + snapshoty každou hodinu bez otevřeného UI; (e) správné verzování DB od bodu 2 dál; (f) recoverabilita dat; (g) ochrana citlivých dat na obou vrstvách (Next + FastAPI).
- **Target Users**: Jediný uživatel (vlastník). Nasazení: single Uvicorn worker + Next.js dev server / standalone build, Tailscale síť.

## Goals
1. **Activity Log (1. v pořadí)**: Každá write operace napříč 9 moduly produkuje záznam ve **STEJNÉ DB transakci** s hlavní změnou. Activity Log je poslední tabulka vytvořená starým runtime ALTER patternem.
2. **Alembic (2. v pořadí – hned po ActLog!)**: Všechny následující změny schématu (tabulky 3–7) už **pouze přes Alembic revize**. Baseline = existující 17 tabulek (bez budoucích). Každá nová tabulka = samostatná revize (0002…0006).
3. **Persistent pending_actions (3.)**: Nový 6-stavový automat s atomickým `UPDATE…WHERE status='pending'` (předchází dvojkliku), záznam přežije restart, žádný mezistav "approved" před execution.
4. **Automatic Goals 2.0 (4.)**: 7 automatických sources implementováno **JEDNOU v goal_history_service**; tools.py, dashboard, scheduler, planner – VŠICHNÍ volají tu samou funkci – žádná duplikace.
5. **Background Scheduler (5.)**: Každou hodinu generuje notifikace + goal snapshoty. **Dashboard zůstává čistě read-only** (nevolá snapshot). Assumption: single Uvicorn worker.
6. **Automatické zálohy (6.)**: pg_dump ve 3:00 ráno + retention 30 dní. SQLite fallback.
7. **Auth/PIN systém (7.)**: 2-vrstvá ochrana: Next.js middleware (port 3000 – FE routy) + FastAPI middleware/deps (port 8000 – API). Secure cookie dle ENV, pro default HTTP development Secure=False.

## Non-Goals
- Víceuživatelský systém.
- Voice 2.0 / wake word / server-side Whisper.
- WoT goal sources (až v dalších fázích – explicitně user vynechal).
- UI redesign existujících stránek mimo `/activity`, `/login`, `/backup-management`.
- Migrace na jiný DB engine.
- Více backend workerů (Uvicorn --workers N). Uvedeno jako explicitní omezení, nebude řešeno locky.
- HTTPS / reverse proxy v rámci těchto 7 bodů. Secure cookie výchozí = False; až při nasazení za TLS uživatel nastaví ENV.

## Background & Context
- Současná architektura: FastAPI + SQLAlchemy 2.x declarative Base. Runtime `ALTER TABLE` helpery v `main.py:L140–L361` – **bude odstraněn JEŠTĚ PŘED implementací bodu 3 (pending_actions).**
- Existuje 17 tabulek (models.py září 2026). Žádná budoucí tabulka není v baseline.
- Pending actions aktuálně RAM dict.
- Automatic goals duplicitní (goal_history_service + tools.py). **Bude centralizováno do 1 source of truth.**
- Notifikace: pouze při requestu uživatele. Dashboard původní design – read-only (snapshoty jen write + scheduler).
- Žádný auth – FE (3000) a BE (8000) jsou 2 samostatné servery. Middleware je třeba na OBOU stranách.

## Functional Requirements

### 1. Activity Log (FR-AL)
- **FR-AL-1 (Transakční model – JEDEN commit)**:
  - `activity_service.log_activity(db, ...)` **NEDĚLÁ vlastní commit**. Vrací `ActivityLog` objekt, přidá jej do session `db.add(activity)`.
  - Volající (main.py write routa, tools.py write fce) udělá společný commit: `db.add(business_obj) + db.add(activity) + db.commit()`.
  - Pokud insert activity selže (např. constraint), výjimka probublá ven a business změna se **rollbackne** – žádná data bez auditu.
- **FR-AL-2**: Model `ActivityLog` s tabulkou `activity_logs`:
  - `id PK`, `timestamp DateTime (utcnow)`, `area String(50)`, `action_type String(50)`, `entity_type String(50) null`, `entity_id Integer null`, `summary String(500)`, `delta_json Text null (JSON)`, `user_context String(100) null (ai_confirm/manual/scheduler/api)`, `dedupe_key String(180) null UNIQUE`.
  - Indexy: `(area, timestamp DESC)`, UNIQUE `dedupe_key`.
- **FR-AL-3**: Write hooks do 9 modulů (finance, work, goals, memory, school, mff, wot, ai/system, planner) – každý přidává activity do stejné session před commit.
- **FR-AL-4**: Endpointy `GET /activity?area=&limit=&offset=&from=&to=&q=` a `GET /activity/{id}`.
- **FR-AL-5**: FE stránka `/activity` časová osa + filtry. `/dashboard` přidá `recent_activity: []` (pouze read, žádný write do snapshot).

### 2. Alembic migrace (FR-ALM)
- **FR-ALM-1 (Pořadí revizí odpovídá skutečnému vývoji)**: Žádné budoucí tabulky v baseline. Přesně 6 revizí:
  1. `0001_baseline_existing_schema` – 17 tabulek (FinanceTransaction, Goal, Memory, WotResource, WotGrind, Subject, Assignment, Exam, WorkSession, MffCharacter, Conversation, Message, Notification, GoalProgressHistory, PlannerRecommendationHistory + **již vytvořený activity_logs z bodu 1** pokud to už v době baseline existuje? NE – Activity Log je v Alembic jako 0002. Baseline = tabulky co jsou v models.py před implementací tohoto roadmapu.)
  2. `0002_activity_log` – CREATE activity_logs + indexy.
  3. `0003_pending_actions` – CREATE pending_actions + indexy.
  4. `0004_goals_changes` – žádná změna sloupců (jen data), takže prázdná? NE – pokud nejsou potřeba změny sloupců, žádná 0004 revize nebude (přeskočíme).
  5. `0005_backup_log` – CREATE backup_logs tabulka.
  6. `0006_auth_sessions` – CREATE auth_sessions tabulka.
- **FR-ALM-2**: `alembic/env.py` používá `target_metadata = Base.metadata` (z database.py), importuje všechny modely. `alembic.ini` v backend/ adresáři, sqlalchemy.url = `%(DATABASE_URL)s` z env.
- **FR-ALM-3**: `main.py` po implementaci bodu 2 (Alembic):
  1. Smazat všechny `_migrate_*` runtime ALTER funkce a jejich volání.
  2. Pořadí: `Base.metadata.create_all(engine)` (fallback pro unit testy SQLite) → pokud `RUN_ALEMBIC_UPGRADE_AT_STARTUP=true` → `alembic upgrade head` přes Python API.
- **FR-ALM-4**: Dokumentace do AGENTS.md: create revize, upgrade/downgrade.

### 3. Persistent pending_actions (FR-PA)
- **FR-PA-1**: Model `PendingAction` tabulka `pending_actions` vytvořená **Alembic revizí 0003**:
  - `id PK`, `action_id String(64) UNIQUE INDEX`, `tool String(100)`, `arguments_json Text`, `status String(30)`, `created_at`, `expires_at (+30min)`, `executed_at null`, `result_json Text null`.
  - INDEX: `action_id UNIQUE`, `(status, expires_at)`.
- **FR-PA-2 (6-stavový automat)**: pouze tyto hodnoty `status`:
  - `pending` – initial, čeká na uživatele
  - `executing` – uživatel klikl POTVRDIT, atomicky update proběhl, tool právě běží
  - `executed` – úspěšně dokončeno, result uložen
  - `failed` – tool execution vyhodil výjimku
  - `rejected` – uživatel klikl ZAMÍTNNOUT
  - `expired` – vypršel TTL 30 min (bez confirm/reject)
- **FR-PA-3**: Confirm ATOMIC (zabraňuje dvojkliku 2× stejná write operace):
  ```python
  # POST /chat/confirm {action_id} handler
  stmt = (
    update(PendingAction)
    .where(PendingAction.action_id == action_id)
    .where(PendingAction.status == "pending")
    .where(PendingAction.expires_at > datetime.utcnow())
    .values(status="executing", executed_at=datetime.utcnow())
    .returning(PendingAction.id)
  )
  updated_count = db.execute(stmt).rowcount  # nebo scalar returning id
  db.commit()
  if updated_count != 1:
      return 409 {"error": "action_not_available", "detail": "Již zpracována / nevypršela / neexistuje"}
  ```
- **FR-PA-4**: Execution tool po confirmed/executing: `WRITE_TOOL_FUNCTIONS[tool](**args)` → výsledek → status='executed' + result_json; exception → status='failed'.
- **FR-PA-5**: Startup recovery po spuštění backendu:
  - UPDATE `pending_actions SET status='expired' WHERE status IN ('pending','executing') AND expires_at < now()` (executing také expirujeme, protože to jsou záznamy z předchozího spuštění co nikdy nedoběhly).
  - Pro každý expirovaný: ActivityLog `system/expire`.
- **FR-PA-6**: `_store_pending_action` nově vrací action_id a do DB vloží status='pending'. Žádná in-memory dict.

### 4. Automatic Goals 2.0 (FR-AG)
- **FR-AG-1 (Centralizace – 1 místo pravdy)**:
  - **JEDINÁ implementace**: `compute_automatic_goal_current_value(db: Session, source: str, today: date | None)` v `goal_history_service.py`.
  - `tools.py._compute_automatic_goal_current(...)` **jen deleguje** na service (import + zavolá). Žádná duplicitní logika.
  - Dashboard, Planner, Scheduler – VOLAJÍ SERVICE (ne tools.py lokální implementaci).
- **FR-AG-2**: 5 NOVÝCH sources (kromě 5 původních):
  1. `finance_month_income` – SUM(income.amount) za **ROK I MĚSÍC today**. PostgreSQL: `EXTRACT(YEAR FROM created_at) = :y AND EXTRACT(MONTH FROM created_at)=:m`; SQLite: `strftime('%Y-%m', created_at)=:ym`.
  2. `finance_month_expenses` – totéž pro expense.
  3. `work_month_earnings` – SUM(hours * hourly_rate WHERE hourly_rate > 0) za měsíc day.date v rok+měsíc.
  4. `school_completed_assignments` – COUNT rows where LOWER(COALESCE(status, '')) IN ('done','completed','finished','dokonceno','hotovo','splneno') – NULL status započítán jako **ne-dokončený**.
  5. `school_open_assignments` – COUNT rows where status IS NULL OR lower(COALESCE(status, '')) NOT IN (…) – **NULL považován za open**.
  - Přetrvávají: `finance_balance`, `work_month_hours`, `mff_t4_count`, `mff_built_t4_count`, `mff_high_priority_built_count` – celkem tedy 10 sources.
- **FR-AG-3**: Do get_goals přidá `source_description` user readable.
- **FR-AG-4**: Goals UI select zobrazuje všech 10.
- **FR-AG-5**: `/dashboard` **NENÍ ŽÁDNÝ write** do GoalProgressHistory. Pouze čte progres z `compute_goal_progress_and_value` (read-only, bez side efektu). Snapshoty = pouze write operace + scheduler hourly.

### 5. Background Scheduler (FR-BS)
- **FR-BS-1**: APScheduler BackgroundScheduler `>=3.10,<4`. Jediný cron `interval=3600s`.
- **FR-BS-2**: Obsah hourly jobu (transakce, commit na konci):
  1. `notifications_service.generate_notifications(db)` → count N (upravit funkci aby vracela int).
  2. Pro každý aktivní cíl (status=active) s tracking_type=automatic: `ensure_goal_progress_snapshot(db, goal)` (zde **ANO** snapshot zapisuje do DB – scheduler to má jako svou práci).
  3. `log_activity(area="system", action_type="scheduler", summary=...)` – společný commit.
- **FR-BS-3**: CELÝ job try/except. Exception → ActivityLog `system/error`. **Žádný SystemExit** – backend jede dál.
- **FR-BS-4**: ENV: `SCHEDULER_ENABLED=false` (default OFF – user explicitně zapne); `SCHEDULER_INTERVAL_SECONDS=3600`.
- **FR-BS-5**: `POST /scheduler/run-now` – spustí stejný job synchronně, vrátí JSON statistiky.
- **FR-BS-6**: **Constraint (Single-Worker)**: Scheduler funguje pouze při `uvicorn --workers 1`. Při více workerech by se job spustil 2× / 4× za hodinu (N workers). Omezení napsáno do ENV template commentaru, AGENTS.md a NFR. Nebude implementováno advisory locking v rámci tohoto roadmap bodu.

### 6. Automatické zálohy (FR-BK)
- **FR-BK-1**: `BackupLog` tabulka, Alembic `0005_backup_log`:
  - `id, started_at, finished_at, backup_path, size_bytes, ok Boolean, error_message, schedule_triggered Boolean, cleaned_up_at DateTime null`.
- **FR-BK-2**: `backup_service.run_backup(db, schedule_triggered=False)`:
  - `BACKUP_DIR` env default `./backups`. Vytvořit adresář.
  - filename `standa-hub-YYYYMMDD-HHMMSS.dump` (Postgres custom format --compress=9), nebo `.sqlite.gz`.
  - Postgres: `pg_dump $DATABASE_URL --format=c --compress=9 --file=$file` subprocess.
  - SQLite fallback: `sqlite3 dbpath ".backup $file"` + gzip.
  - Postgres verify: `pg_restore --list $file` exit 0.
  - Zapíše BackupLog, přidá do stejné transakce session, commit.
  - ActivityLog `system/backup`.
- **FR-BK-3**: Retention: `cleanup_retention(db, retention_days=30)` → `os.remove` soubory starší > days; BackupLog doplní cleaned_up_at.
- **FR-BK-4**: Scheduler integrace: uvnitř hourly jobu po notifikacích:
  `if datetime.utcnow().hour == int(BACKUP_SCHEDULE_HOUR=3) AND if_backup_not_run_today_then_run() + cleanup`.
- **FR-BK-5**: Endpointy `POST /backup/run-now` a `GET /backup/list`.
- **FR-BK-6**: ENV: `BACKUP_DIR`, `BACKUP_RETENTION_DAYS=30`, `BACKUP_SCHEDULE_HOUR=3`.

### 7. Auth/PIN systém (FR-AU) – 2-vrstvá ochrana
- **VRSTVA A – Next.js Middleware (frontend/middleware.ts, port 3000, FE routy)**
  - Match: config matcher = `/ai/:path*`, `/finance/:path*`, `/work/:path*`, `/memory/:path*`, `/goals/:path*`, `/planner/:path*`, `/school/:path*`, `/mff/:path*`, `/wot/:path*`, `/activity/:path*`, `/backup/:path*`.
  - Skip: `/login`, `/favicon.ico`, `/_next/static/*`, `/public/*`.
  - Krok 1: Pokud `AUTH_ENABLED` z FE config (env `NEXT_PUBLIC_AUTH_ENABLED`, default true, ale ověř přes API call) NEBO pokud cookie `standa_session` chybí → 307 redirect `/login?next=...`.
  - Krok 2 (ověření platnosti): Synchronní fetch na BE `GET /auth/session/validate` (na NEXT_PUBLIC_API_URL). Pokud 200 OK → pokračuj render Next stránky. Pokud 401 → smaž cookie, redirect na `/login`.
  - Next.js Middleware běží na edge/Node runtime – potřebujeme nakonfigurovat Node runtime.
- **VRSTVA B – FastAPI (port 8000, API endpoints)**
  - `AuthSession` model (Alembic revize 0006): `id, token_hash String(255) UNIQUE, created_at, expires_at, revoked_at null, user_agent null, ip_address null`.
  - Dependency `require_auth(request: Request, db: Session = Depends(get_db))`:
    - Pokud `AUTH_PIN_HASH` env **není definován vůbec** → pass (graceful degradation pro lokální vývoj, žádný auth).
    - Jinak: přečti cookie `standa_session` z request. Zavolej `auth_service.lookup_session(db, plain_token)`. Neexistuje / expired / revoked → 401 JSON `{"error":"auth_required"}`.
    - Vloženo do Depends u všech chráněných API: `/chat/*`, `/goals/*`, `/finance/*`, `/work/*`, `/memory/*`, `/planner/*`, `/school/*`, `/mff/*`, `/wot/*`, `/activity/*`, `/backup/*`, `/scheduler/*`, `/pending/*`, `/auth/logout`.
  - `POST /login` JSON {pin:string}:
    - Regex PIN `^[0-9]{4,6}$` → 400 jinak.
    - Rate limit per IP 5 pokusů, 10 min lock.
    - bcrypt.verify → úspěch: `auth_service.create_session(plain_token, user_agent, ip, ttl_hours=720)`.
    - Set-Cookie: `standa_session={plain}; Path=/; HttpOnly; SameSite=Lax; Secure=${AUTH_COOKIE_SECURE=false default}; Max-Age=${ttl*3600}`.
    - 200 `{ok: true, redirect_to: next||"/"}`.
    - Neúspěch: 401 + ActivityLog `system/login_fail`.
  - `POST /logout`: Depends(require_auth) + revoke session + Clear cookie.
  - `GET /auth/session/validate` (volá Next middleware): Depends(require_auth) → 200 `{ok: true}` nebo 401.
- **ENV konfigurace AUTH**:
  - `AUTH_PIN_HASH` (bcrypt hash 4–6 číslic; není-li vůbec nastaven → auth vypnutý úplně)
  - `AUTH_SESSION_TTL_HOURS=720` default 30 dnů
  - `AUTH_COOKIE_SECURE=false` default (HTTP / Tailscale plain); při HTTPS/Tailscale Serve nastavit true
  - `NEXT_PUBLIC_AUTH_ENABLED=true` (default na true; vypne-li user, FE middleware přeskočí – ale API stále kontroluje, takže je to jen UX convenience pro dev)

## Non-Functional Requirements
- **NFR-1 Performance**: `/dashboard` (read-only) max +20% latency vs původní 120ms.
- **NFR-2 Testy**: Min. 1 test soubor na modul (Activity, Pending, Goals2, Scheduler, Alembic, Backup, Auth) → **min 52→70 testů PASS** celkem.
- **NFR-3 Idempotentnost**: Activity dedupe_key + pending atomic UPDATE = dvojklik/dvojí odeslání requestu = žádné duplicitní writes.
- **NFR-4 Backward compatibility**: Žádná BREAKING změna existujících endpoints shapes. Nové fields nullable.
- **NFR-5 Lint + build**: `npm run lint 0 errors`, `npm run build = 15 rout (13 původních + /activity + /login)` ✅.
- **NFR-6 Config env-only**: Všechno可调的 (SCHEDULER, BACKUP, AUTH, ALEMBIC STARTUP RUN) v env + `.env.template` s comments. **Zero hardcoded secrets / PINy**.
- **NFR-7 Activity bezpečnost**: Žádný řádek nelze smazat z activity_logs UI/API – je to append-only audit. Žádný DELETE endpoint.
- **NFR-8 (Single-Worker constraint)**: Celá aplikace (především scheduler, ale i APScheduler session management) musí běžet na `uvicorn --workers 1`. Více workerů není v tuto chvíli podporováno a je uvedeno jako známé omezení.

## Constraints
- **Technické**: SQLAlchemy 2.x + Alembic; APScheduler 3.x; bcrypt; Next.js 16 Middleware (Node runtime). Žádné nové FE knihovny (zustává Tailwind + React 19, žádná shadcn).
- **Business**: Pořadí 1→2→3→4→5→6→7 – **Alembic hned po ActLog**, žádné runtime ALTER po 2.
- **Dependencies**: `alembic>=1.13`, `APScheduler>=3.10,<4`, `bcrypt>=4.0` přidány do backend/requirements.txt (vytvořit).

## Assumptions
- Uvicorn 1 worker (`uvicorn main:app --workers 1`). Pro více workerů by bylo třeba advisory lock / samostatný scheduler proces – není scope.
- pg_dump je na PATH (při 24/7 deploy na server; pro lokální vývoj SQLite fallback).
- Tailscale IP bez HTTPS = AUTH_COOKIE_SECURE=false; Secure zapne uživatel až při TLS terminaci (Tailscale Serve / Nginx proxy).
- Auth 4–6 číslic PIN + 5 pokusů lock 10 min dostačující pro 1-uživatelový scénář v síti Tailscale (ne internet public).
- ActivityLog záznamy > 10 000 řádků = neřešit stránkování výkon, pro takto rozsáhlý use case není třeba.

## Acceptance Criteria

### AC-AL-1: Transakční integrity – insert activity selhal, rollback business
- **Type**: `rule`
- **Given**: Mock `db.commit` vyhodí Exception po `db.add(activity)` (activity má špatný dedupe key / db constraint).
- **When**: Volání `POST /finance {transaction}`.
- **Then**: (1) Žádný nový řádek v `finance_transactions`; (2) Žádný nový řádek v `activity_logs`.
- **Pass Condition**: SELECT COUNT obou tabulek se neshoduje o 0 po neúspěšném requestu.
- **Evidence**: Unit test `test_activity_transaction_rollback.py`.

### AC-AL-2: 9 write operací = 9 activity records (1× každá area)
- **Type**: `rule`
- **Given**: Prázdná DB.
- **When**: Provedu 9 writes (finance create + delete, work update, goal snapshot, memory toggle, assignment create, mff upsert, wot resource update, ai approve pending).
- **Then**: 9 unikátních `area` GROUP BY area count = 1 v každé; žádný summary prázdný.
- **Pass Condition**: SQL group by count odpovídá.
- **Evidence**: test_activity_write_hooks.py.

### AC-ALM-1: 6 Alembic revizí odpovídá pořadí 0001…0006
- **Type**: `rule`
- **Given**: Prázdná DB.
- **When**: `alembic upgrade head`.
- **Then**: (1) 6 souborů versions postupně alphabetically (0001…0006); (2) tabulky vznikají v správném pořadí – (po 0001 jen původní 17), (po 0002 activity), (po 0003 pending), (po 0005 backup), (po 0006 auth).
- **Pass Condition**: `alembic history` výpis se shoduje s výčtem 6.
- **Evidence**: CLI stdout.

### AC-ALM-2: Žádný runtime ALTER v main.py po Alembic
- **Type**: `rule`
- **Given**: Implementace bodu 2 dokončena.
- **When**: `rg "ALTER TABLE" backend/main.py`.
- **Then**: 0 matchů. (Pouze v komentáři je dovoleno.)
- **Pass Condition**: grep count = 0.
- **Evidence**: Grep result.

### AC-PA-1: Pending přežije restart backendu
- **Type**: `rule`
- **Given**: AI request vytvoří 2 pending (add_work_session + create_income), oba status='pending' v DB.
- **When**: SIGKILL backend proces → restart backend (uvidí tu samou DB).
- **Then**: Po restartu oba 2 řádky stále pending; confirm PRVNÍ action_id = ÚSPĚCH 200; druhý stále pending.
- **Pass Condition**: COUNT(status='pending') po restartu = 2 → po 1 confirmu = 1.
- **Evidence**: Integration test output.

### AC-PA-2: Dvojklik na confirm = pouze 1× execution
- **Type**: `rule`
- **Given**: Jeden pending.
- **When**: Dva paralelní HTTP POST `/chat/confirm {action_id}` requesty (skoro současně, atomic update race).
- **Then**: Jeden vrací 200 OK; druhý vrací 409 status; write tool se spustí právě JEDNOU (zkontrolovat počet side efektů, např. 1 finance transaction vytvořena).
- **Pass Condition**: 1× 200, 1× 409, db count = 1 nový write objekt.
- **Evidence**: Unit test race simulation.

### AC-PA-3: Status machine only 6 values
- **Type**: `rule`
- **Given**: Vytvoř, confirm, execute, error, reject, expire – každý scénář.
- **When**: Každý přechod.
- **Then**: `status IN ('pending','executing','executed','failed','rejected','expired')` vždy; žádný řetězec jiný.
- **Pass Condition**: CHECK constraint v tabulce nebo enum + testy.
- **Evidence**: DB constraint.

### AC-AG-1: 10 goal sources (5 nových + 5 starých) all != None
- **Type**: `rule`
- **Given**: Fixtures DB: 15 transactions, 6 sessions, 12 assignments, 8 MFF chars.
- **When**: Zavolám `compute_automatic_goal_current_value` pro každou z 10 sources.
- **Then**: Žádná nevrátí None. Finance income == odpovídá ručnímu SQL dotazu (rok i měsíc). School_open zahrnuje NULL status.
- **Pass Condition**: 10/10 ne-None a hodnoty == reference SQL.
- **Evidence**: test_goals_automatic_v2.py.

### AC-AG-2: tools.py deleguje na service (žádná duplicita)
- **Type**: `rule`
- **Given**: Zdroják tools.py po refaktoru.
- **When**: Grep `def _compute_automatic_goal_current` a zkontroluji tělo.
- **Then**: Tělo = pouze 2–3 řádky import + call service. Žádné `SUM(...)` přímo v tools.py.
- **Pass Condition**: Grep v tools.py "SUM(" 0 výskytů v této funkci.
- **Evidence**: Code link.

### AC-AG-3: Dashboard = 0 writes do DB
- **Type**: `rule`
- **Given**: Prázdná GoalProgressHistory tabulka (0 řádků).
- **When**: Udělám 10× GET `/dashboard` requestů.
- **Then**: Stále COUNT(GoalProgressHistory) = 0. Žádný zápis.
- **Pass Condition**: DB dotaz count = 0 po requestech.
- **Evidence**: Unit test spustí dashboard 10×.

### AC-BS-1: Hourly job vytvoří notifikace + snapshoty (ANIŽ BY UŽIVATEL OTEVŘEL UI)
- **Type**: `rule`
- **Given**: SCHEDULER_ENABLED=true; 15 cílů tracking=automatic; assignments s deadliny za 2 dny.
- **When**: Počkám 1 hodinu (nebo POST /scheduler/run-now).
- **Then**: (1) Min 1 nová notifikace created_at = now; (2) Min 15 nových řádků GoalProgressHistory (každý cíl 1 snapshot); (3) ActivityLog system/scheduler s counts.
- **Pass Condition**: Všechny 3 podmínky.
- **Evidence**: DB výpis.

### AC-BS-2: Single-worker assumption explicit, multi-worker behavior documented
- **Type**: `rule`
- **Given**: .env.template + AGENTS.md.
- **When**: Grep "workers 1" + "single worker" v backend souborech.
- **Then**: Min. 2 reference (comment v ENV + AGENTS.md + NFR).
- **Pass Condition**: Grep najde minimálně 2 zmínky.
- **Evidence**: Odkazy na řádky.

### AC-BK-1: pg_dump validní soubor (nebo SQLite .backup) funguje
- **Type**: `rule`
- **Given**: DB s testy.
- **When**: `POST /backup/run-now`.
- **Then**: (1) soubor existuje, (2) size_bytes > 1KB, (3) BackupLog.ok = true, (4) verify (pg_restore --list / gunzip sqlite) exit=0.
- **Pass Condition**: 4/4 true.
- **Evidence**: test_backup.py.

### AC-BK-2: Retention 30 dní cleanup
- **Type**: `rule`
- **Given**: 2 fake soubory (41 dní / 5 dnů starý) + odpovídající BackupLog řádky.
- **When**: cleanup_retention(30).
- **Then**: Starý 41d soubor je pryč (os.path.exists = false); 5d soubor existuje; oba BackupLog řádky mají cleaned_up_at nastaven u toho starého.
- **Pass Condition**: 3 podmínky.
- **Evidence**: Unit test.

### AC-AU-1: 2-vrstvá auth: FE middleware redirect + API 401 fungují
- **Type**: `rule`
- **Given**: AUTH_PIN_HASH nastaven; žádná session cookie.
- **When**:
  1. Browser GET http://frontend:3000/finance (Next middleware).
  2. HTTP GET http://backend:8000/goals Accept:application/json (FastAPI deps).
- **Then**:
  1. 307 Location = `/login?next=%2Ffinance`.
  2. 401 JSON `{"error":"auth_required"}`.
- **Pass Condition**: 307 + 401 správně.
- **Evidence**: Integration test output.

### AC-AU-2: AUTH_PIN_HASH není vůbec v env = auth vypnut úplně
- **Type**: `rule`
- **Given**: os.environ.pop("AUTH_PIN_HASH").
- **When**: 10× request na BE API (finance, goals, work…); 10× FE routes.
- **Then**: Vše 200 OK, žádné redirecty, žádné 401.
- **Pass Condition**: 20 requestů status 200.
- **Evidence**: Unit test s mock env.

### AC-AU-3: Správný PIN + 5× špatný (lock 10 min)
- **Type**: `rule`
- **Given**: hash("1234").
- **When**: (1) 1× POST /login 1234 = OK + cookie; (2) nový klient (bez cookie) 5× /login pin=0000 → 5. pokus 401 s "too many attempts" message; (3) 6. pokus pin=1234 → 429 Retry-After.
- **Then**: (1) cookie existuje + následný protected request OK. (2) 5. pokus 401. (3) 429 status.
- **Pass Condition**: 3 kroky status kódy OK.
- **Evidence**: test_auth.py.

### AC-RUB-1: Activity Log UI kvalita (časová osa + filtry)
- **Type**: `rubric`
- **Dimension**: Usability hledání konkrétní změny v historii
- **Scale**: 0-5
- **Anchors**: 0 žádná stránka; 2 plain tabulka bez filtrů; 3 tabulka + 1 filtr + stránkování; 4 časová osa dnů + 3 filtry (area, action_type, q search) + infinite scroll; 5 + barevná odlišení per area + expand detail delta JSON.
- **Pass Threshold**: >= 4
- **Evidence**: app/activity/page.tsx + screenshot.

### AC-RUB-2: Konfigurovatelnost env-only
- **Type**: `rubric`
- **Dimension**: Procento可调 parametrů, co jsou v .env (ne hardcoded)
- **Scale**: 0-5
- **Anchors**: 0 vše hardcoded; 2 3 parametry; 3 cca 50 %; 4 všechny klíčové (SCHEDULER_ENABLED, INTERVAL, RUN_ALEMBIC, BACKUP_* 3 param, AUTH_* 4 param) v env; 5 to samé + .env.template pro KAŽDOU proměnnou s popisem a defaultem.
- **Pass Threshold**: >= 4
- **Evidence**: .env.template vs code (grep usage = env proměnná match).

### AC-RUB-3: Auth bezpečnost (PIN + session)
- **Type**: `rubric`
- **Dimension**: (bcrypt + lock + HttpOnly + hash v DB) proti (plaintext + no lock + cookie visible).
- **Scale**: 0-5
- **Anchors**: 0 plain PIN v GET param. 1 plaintext PIN v DB, POST bez lock, not-httpOnly cookie. 2 bcrypt + 5/10 lock + cookie not httpOnly. 3 bcrypt + 5/10 + HttpOnly + SameSite=Lax. 4 bcrypt + 5/10 + token (HASH v DB neplain) + HttpOnly + Secure dle ENV + auto logout 720h + per-ip lock. 5 = 4 + CSRF token (XSRF-TOKEN) pro POST requesty + login rate limit 10/min per IP.
- **Pass Threshold**: >= 4
- **Evidence**: auth_service.py + middleware + Set-Cookie header.

## Open Questions
- [ ] CSRF (AC-RUB-3 body 5): Implementovat XSRF-TOKEN pro všechny state-changing POST requests, nebo stačí default 4 + SameSite=Lax pro Tailscale single-user scénář? **Default: bez CSRF v rámci tohoto bodu; zařadit jako TODO následně.**
- [ ] `/activity stránka export CSV`: Přidat tlačítko? Default: **NE, pouze AC-RUB-1 level 4 (kromě CSV)**.
- [ ] PIN 4–6 pouze číslice, nebo libovolný password string? **Default: pouze číslice `^[0-9]{4,6}$`.**
