# Standa Hub

Osobní operační systém pro školu, práci, finance, cíle, připomínky a herní historii.
Jarvis nad uloženými daty hledá, vysvětluje a připravuje změny k potvrzení.
Hub vlastní data a pravidla; AI akce mají potvrzení, audit a podporované změny undo.

## Architektura a stack

- **Frontend:** Next.js 16 App Router, React 19, TypeScript, Tailwind CSS.
- **Backend:** FastAPI, SQLAlchemy, Alembic, Python 3.12.
- **Databáze:** PostgreSQL; izolované testy využívají SQLite.
- **Jarvis:** Groq přes OpenAI SDK; testy používají fake klienty a transporty.
- **Provoz:** APScheduler, Web Push, zálohy DB i médií. Screenshoty a replaye
  leží v `MEDIA_DIR`, jejich metadata v DB. DB dump samotný média neobsahuje.

Frontend běží na portu 3000 a volá backend na portu 8000. Backend vlastní přihlášení,
business pravidla a migrace. Scheduler vyžaduje jediný backend worker.
Moduly deklaruje backendový registry; dostupnost řeší runtime konfigurace
v pořadí prostředí > DB > výchozí hodnota. Frontend čte stav z API, backend
vynucuje pravidla. Podrobnosti: [module feature flags](docs/module-feature-flags.md).

## Lokální backend

Potřebuješ Python 3.12, Node.js 24, npm a PostgreSQL 16. Příkazy spouštěj z kořene
repozitáře, pokud není uvedeno jinak. Vytvoř databázi a uživatele pro lokální Hub.

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell místo předchozího řádku:
# .\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements-dev.txt
cp backend/.env.template backend/.env
# PowerShell: Copy-Item backend/.env.template backend/.env
```

**Použij šablonu `backend/.env.template` a uprav `backend/.env` před spuštěním:**

- `DATABASE_URL`: tvoje lokální PostgreSQL spojení. Pro samostatný vývoj lze zvolit
  `sqlite+pysqlite:///./standa-hub.db`; PostgreSQL migrace ověřuje CI zvlášť.
- `FRONTEND_ORIGINS`: hosty frontendu, pro lokální vývoj localhost/127.0.0.1.
- `GROQ_API_KEY`: vlastní klíč pouze pro reálnou AI. SDK vyžaduje neprázdnou hodnotu
  už při konstrukci klienta; bez reálné AI použij `local-placeholder` a
  `GROQ_BASE_URL=http://127.0.0.1:9`. AI odpovědi pak nebudou dostupné.
- Pro vývoj bez background akcí nastav `SCHEDULER_ENABLED=false`,
  `REMINDERS_CHECK_ENABLED=false`, `DAILY_BRIEFING_ENABLED=false` a
  `WEEKLY_REVIEW_ENABLED=false`. Připomínky mají i lazy zpracování při čtení notifikací.
- `AUTH_PIN_HASH`: prázdná hodnota vypíná autentizaci; pro autentizovaný provoz
  nastav bcrypt hash podle [backend/AGENTS.md](backend/AGENTS.md).

Šablona obsahuje i volby pro push, zálohy a média. `.env` soubory ani skutečné
klíče nepatří do Gitu nebo CI konfigurace.

```bash
cd backend
python -m alembic upgrade head
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

API dokumentace: http://127.0.0.1:8000/docs. Startup standardně také provede
`alembic upgrade head`; schéma spravuje Alembic, ne runtime `create_all`.
Ruční kontrola migrací z `backend/`:

```bash
python -m alembic current
python -m alembic upgrade head
```

Rollback `python -m alembic downgrade -1` používej jen vědomě se zálohou;
CI ověřuje upgrade/downgrade/upgrade na jednorázové PostgreSQL DB.

## Lokální frontend

V druhém terminálu:

```bash
cd frontend
cp .env.template .env.local
# PowerShell: Copy-Item .env.template .env.local
npm ci
npm run dev
```

**Uprav `frontend/.env.local`:** pro lokální vývoj nastav
`NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` místo Tailscale placeholderu ze šablony.
V prohlížeči otevři http://127.0.0.1:3000. Frontend a backend používej na stejném
hostu kvůli session cookies. Změna `NEXT_PUBLIC_API_URL` pro produkční frontend
vyžaduje nový build.

```bash
npm run build
npm start
```

Backend pro produkci spusť z `backend/` bez reloadu:

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

Produkční konfigurace musí výslovně mířit na produkční PostgreSQL, mít
nastavenou autentizaci a zálohy; vývojové `.env` nepřebírej automaticky.
Výše uvedené příkazy samy neřeší autostart/restart služby.

Geist a Geist Mono jsou lokálně přibalené pod OFL v `frontend/app/fonts/`;
produkční build nepotřebuje stahovat Google Fonts.

## Testy a kontrola kódu

Z kořene repo s aktivním Python prostředím, bez produkčních `.env`/secrets:

```bash
export DATABASE_URL='sqlite+pysqlite:///:memory:'
export GROQ_API_KEY=ci-placeholder-not-a-secret
export GROQ_BASE_URL=http://127.0.0.1:9
export SCHEDULER_ENABLED=false REMINDERS_CHECK_ENABLED=false
export DAILY_BRIEFING_ENABLED=false WEEKLY_REVIEW_ENABLED=false
export EXTERNAL_DELIVERY_ENABLED=false
python -m pyflakes backend/*.py backend/scripts/*.py
python -m pytest backend/tests --disable-socket --allow-unix-socket -x -q
```

Ve Windows PowerShell nastav stejné hodnoty pomocí `$env:DATABASE_URL = '…'`
a obdobně ostatní proměnné. Shell globy pro pyflakes lze nahradit:
`python -m pyflakes (Get-ChildItem backend/*.py, backend/scripts/*.py).FullName`.

`requirements-dev.txt` zahrnuje produkční `requirements.txt` i pytest, pyflakes a
pytest-socket. TCP sockets jsou v testech zakázané; Unix sockets jsou povolené
kvůli lokálním async testovacím smyčkám. Žádné reálné LLM volání není potřeba.
PostgreSQL test je opt-in přes `TEST_POSTGRES_URL` na jednorázovou DB s `test`
v názvu; bez ní je přeskočen a běží v samostatném CI jobu.

```bash
cd frontend
npm ci
npm run lint
npx tsc --noEmit
npm test
npm run build
```

## CI na GitHub Actions

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) běží při push i pull requestu:

1. **Backend:** instalace závislostí, pyflakes app souborů a scripts, pytest s SQLite
   a zakázanými TCP sockets. Existující Windows-only speech testy jsou na Linuxu
   přeskočené; jejich statické fallback kontroly běží.
2. **Migrace:** PostgreSQL 16 service container, `alembic upgrade head`,
   `alembic downgrade -1`, `alembic upgrade head` a kontrola schema driftu.
3. **Frontend:** npm ci, lint, TypeScript, testy a plný production build.

Setup actions cachují pip podle obou requirements souborů a npm download cache
podle `frontend/package-lock.json`. `node_modules` ani DB nejsou cachované.
Chyby kroků ukončí job; pytest končí při první chybě. Nový běh stejné větve
zruší zastaralý běh. CI nepoužívá repository secrets; DB heslo i SDK placeholder
jsou pouze testovací hodnoty. Pro povinné PR checks nastav tyto tři joby také
v GitHub branch protection/rulesetu; samotný workflow merge pravidla nevynucuje.
Doporučené přesné názvy required checks pro `main`:

- `Backend tests and pyflakes`
- `PostgreSQL migration round-trip`
- `Frontend lint, types, tests and build`

Nastavení branch protection zde není provedeno ani ověřeno. Výsledky lokálního
ověření a jeho omezení jsou v [CI verification](docs/mrk-22-ci-verification.md).

## Dokumentace

- [`docs/`](docs/) — architektonické principy, roadmapy a modulová dokumentace.
- [`backend/AGENTS.md`](backend/AGENTS.md) — podrobná reference backendu,
  autentizace, migrací, scheduleru, záloh a bezpečných AI akcí.
- [`frontend/AGENTS.md`](frontend/AGENTS.md) — pravidla pro aktuální Next.js.
- [`docs/wot-milestones.md`](docs/wot-milestones.md),
  [`docs/wot-replays.md`](docs/wot-replays.md) — WoT historie a média.
