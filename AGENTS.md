# Standa Hub – pravidla pro agenty

Platí pro každého agenta v tomhle repu (Local/Cloud Claude, Codex). Krátký přehled; podrobnosti
jsou v odkazech. `CLAUDE.md` jen importuje tento soubor – pravidla piš sem.

**Standa Hub** = osobní operační systém (škola, práce, finance, cíle, připomínky, hry…).
Hub drží data a deterministickou logiku; **Jarvis** (AI přes Groq) nad nimi hledá, vysvětluje
a navrhuje změny, které uživatel potvrzuje. Jediný uživatel, česky psané UI.

- Stack: FastAPI + SQLAlchemy + Alembic + PostgreSQL (`backend/`), Next.js 16 + React 19 +
  Tailwind 4 (`frontend/`). Spuštění a env: [README.md](README.md).
- Backend reference (auth, migrace, scheduler, AI akce, zálohy): [backend/AGENTS.md](backend/AGENTS.md).
- Next.js 16 se liší od tréninkových dat: [frontend/AGENTS.md](frontend/AGENTS.md).
- Principy P1–P18: [docs/architecture-principles.md](docs/architecture-principles.md) ·
  nový modul: [docs/module-framework.md](docs/module-framework.md) +
  [docs/module-integration-checklist.md](docs/module-integration-checklist.md) (pilot: Návyky) ·
  události: [docs/domain-events.md](docs/domain-events.md) ·
  UI: [docs/design-system.md](docs/design-system.md) ·
  externí služby a zdroje pravdy: [docs/home-server.md](docs/home-server.md).
- Roadmapa a úkoly: Linear, projekt **Standa Hub** (tým MRK). GitHub = zdroj pravdy pro kód.

## Setup (idempotentní)

```bash
scripts/setup-dev.sh            # .venv + backend/requirements-dev.txt, npm ci ve frontend/
scripts/setup-dev.sh --check    # jen zjistí stav; exit 2 = něco je zastaralé
```

Instaluje jen když chybí závislosti nebo se změnil lockfile (jinak ~0,1 s). Cloudová prostředí
(Claude, Codex) mají mít `bash scripts/setup-dev.sh` nastavený jako setup skript. Má fungovat i
v Git Bash na Windows (lokální ověření zatím chybí). `--system-python` instaluje do aktuálního
interpretu místo `.venv`. `.env` soubory nevytváří a nemění – nikdy je necommituj.

## Ověření (stejné jako CI – `.github/workflows/ci.yml`)

Backend, z kořene repa. `PY` = Python prostředí: Linux/macOS venv `.venv/bin/python`,
Windows venv `.venv/Scripts/python`, při `--system-python` jen `python`.

```bash
PY=.venv/bin/python
export DATABASE_URL='sqlite+pysqlite:///:memory:' GROQ_API_KEY=ci-placeholder-not-a-secret \
  GROQ_BASE_URL=http://127.0.0.1:9 SCHEDULER_ENABLED=false REMINDERS_CHECK_ENABLED=false \
  DAILY_BRIEFING_ENABLED=false WEEKLY_REVIEW_ENABLED=false EXTERNAL_DELIVERY_ENABLED=false
"$PY" -m pyflakes backend/*.py backend/scripts/*.py backend/modules/*.py backend/modules/*/*.py
"$PY" -m pytest backend/tests --disable-socket --allow-unix-socket -x -q
```

Frontend, ve `frontend/`: `npm run lint && npx tsc --noEmit && npm test && npm run build`

- Migrace: CI dělá na PostgreSQL `upgrade head → downgrade -1 → upgrade head` + kontrolu driftu.
  Lokálně opt-in přes `TEST_POSTGRES_URL` (jednorázová DB s `test` v názvu).
- UI: `frontend/scripts/ui-check-run.sh [ui|flags|flags-off|changes] [--no-build]` – build, mock API z fixtures
  (žádný Groq), `next start`, kontroly (`ui-check.mjs`, `module-flags-check.mjs`, `changes-check.mjs`) a úklid
  serverů → screenshoty do `frontend/scripts/.ui-check/`. CI to spouští (job `ui`) a screenshoty nahraje jako
  artefakt `ui-check-screenshots`.
- Než napíšeš „hotovo“, spusť kontroly, kterých se změna týká. Neprošlo = napiš to i s výstupem.

## Nepřekročitelná pravidla kódu

- **Schéma jen přes Alembic**, migrace aditivní (upgrade/downgrade). Žádné `create_all` ani ALTER v runtime.
- **Audit:** každý zápis volá `log_activity` ve **stejné transakci** jako změna (jeden commit).
  Doménový fakt (dokončení, změna stavu…) jde přes `append_domain_event(…, activity=ActivityProjection(…))`
  ve stejné transakci – Aktivita je pak jeho projekce; událost musí být deklarovaná (docs/domain-events.md).
- **AI nikdy nezapisuje přímo:** resolver → pending action → potvrzení → stale check → provedení → audit (→ undo).
- **Deterministicky před AI:** co jde spočítat bez LLM, počítá kód; LLM dostává jen výsledek.
- **Čas:** v DB naive UTC (`time_utils.utc_now()`), „dnes“ a rozvrhy v Europe/Prague.
  Nikdy `datetime.now()` / `date.today()` bez zóny.
- **Finance do AI nejde** (MRK-60): žádná data, agregáty ani tooly Finance pro LLM; filtry jen přes
  `finance_ai_policy.py`. Práce do Finance nezapisuje. Detaily: [docs/finance.md](docs/finance.md).
- **Kanonické moduly:** stavy `statuses.py`, env `env_config.py`, AI tooly `tool_registry.py`,
  frontend API `lib/api.ts`. Nic z toho nekopíruj lokálně.
- **Obří soubory** (`backend/main.py`, `backend/ai.py`): nepřidávej do nich podstatnou novou logiku.
  Nová funkcionalita patří do vlastního modulu, pokud je to součástí issue. Malé opravy existujícího
  kódu dělej na místě. Nesouvisející kód jen proto, že jsi soubor otevřel, nerefaktoruj ani
  nepřesouvej – takové vyčlenění je samostatný issue (např. MRK-20).
- **Testy:** nikdy reálné LLM ani síť (pytest-socket). Fake hodiny a `tests/fakes.py`. Bugfix = regresní test.
- **Bezpečnost:** žádné secrets, klíče, `.env`, dumpy DB ani uživatelská média v repu, logu ani v Linearu.

## Workflow: Linear issue → branch → PR → CI → review → merge

1. **Jeden issue = jedna branch = jeden PR.** Branch podle Linearu (`stanislavpetr06/mrk-NN-…`).
   Když prostředí vynucuje jiný název, dej `MRK-NN` do titulku PR. Titulek: `MRK-NN: <co>`,
   v popisu `Fixes MRK-NN`. Mimo scope issue nic neměň; nálezy navrhni jako nový issue.
2. **Před delší prací i před otevřením PR** sync: `git fetch origin && git merge origin/main`.
   Na sdílené nebo cizí branch nikdy rebase ani force-push.
3. **Role (MRK-97):** Claude = developer (kód, branch, commity, PR, opravy po review), Codex = reviewer,
   merge dělá GitHub auto-merge. **Agent, který branch vlastní, ji nemerguje** ani nezapíná auto-merge. Merge
   proběhne sám, až projde celé CI a check **Review gate** (verdikt `MERGE` pro aktuální commit). Do `main` se
   nikdy necommituje přímo.
   - **Kritické změny merguje jen Standa:** migrace (`backend/alembic/`), přihlašování a bezpečnost
     (`backend/auth*.py`, `frontend/proxy.ts`), zálohy a obnova, CI / review / deploy (`.github/`, `scripts/`,
     Docker/Compose). Gate po `MERGE` přidá label `manual-merge` a auto-merge nezapne.
4. **Review dělá jiný agent**, než který kód psal (Claude ↔ Codex). Codex ho spouští automaticky
   na Ubuntu serveru (`scripts/linux/codex-review.sh`, systemd timer). Review končí jedním samostatným řádkem
   `Codex-Verdict: MERGE` (nic neblokuje) nebo `Codex-Verdict: BLOCK`. Ten řádek píše **jen reviewer,
   nikdy autor kódu**, a platí jen pro commit, na kterém review vzniklo. Po pushi musí přijít nové review.
   - Nálezy autor opraví na téže branch. Po `BLOCK` to dělá automaticky Claude v jednorázovém Docker kontejneru
     na Ubuntu (`scripts/linux/claude-fix.sh`): dostane jen kopii souborů a smí je jen číst a upravovat (žádný kód
     z PR se nespouští); commit sestaví a zkontroluje důvěryhodný skript, pushne bez force; testy běží v CI a Codex
     zkontroluje nový commit.
   - **Limit:** nejvýš 3 automatická kola oprav na PR. Další `BLOCK`, oprava, která nevznikla, nebo oprava
     měnící `.github/` či `scripts/` = label `needs-human` a automatika se zastaví; rozhodne Standa (po odebrání
     labelu pokračuje).
   - Review gate běží jen z `main` (`pull_request_target`, dispatch, a každých 10 min přepočet všech PR), nikdy z kopie v PR.
5. PR vyplní šablonu (`.github/pull_request_template.md`). Povinně:
   - **UI změna** → screenshot desktop (1366 nebo 1920 px) + mobil (390 px) – stačí odkaz na artefakt
     `ui-check-screenshots` z CI a názvy souborů, které změnu ukazují;
   - **migrace** → výslovně uvést revizi, co dělá a že prošel upgrade/downgrade;
   - **Groq count** → přesný počet reálných Groq požadavků při práci a ověření (obvykle 0);
   - co bylo ověřeno lokálně na reálné DB/Windows a co jen v cloudu.
6. Po merge přejde issue na Done (Linear ↔ GitHub), jinak ho přepni ručně.

## Handoff (povinný při každém ukončení práce)

Preferovaně vlož níže uvedený handoff jako komentář do Linear issue. Pokud Linear není
dostupný, vrať přesně stejný handoff ve finální odpovědi a vlož ho do Linearu při nejbližší
dostupné příležitosti.

```
Stav: hotovo / rozpracováno / blokováno
Branch + HEAD: <branch> @ <sha>   PR: <odkaz nebo „zatím ne“>
Co se změnilo: <2–5 bodů>
Ověření: <příkazy + výsledek; co neběželo a proč>
Groq count: <N>
Migrace: <žádná / revize + upgrade/downgrade výsledek>
Zbývá / další krok: <…>   Ověřit lokálně: <reálná DB, Windows, mobil…>
```

## Co nedělat

- Neměnit `.env`, reálnou DB, `MEDIA_DIR` ani zálohy. Reálná data se ověřují jen lokálně.
- Nevolat reálné Groq bez výslovného zadání; pokud ano, uvést počet v handoffu.
- Nemazat a nepřepisovat cizí branch. Neslučovat víc issues do jednoho PR.
- Nezačínat refaktor ani „vylepšení“ mimo zadání; navrhnout ho jako issue v Linearu.
