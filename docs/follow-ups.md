# Follow-upy (neblokující)

Zjištěno při živém ověření Roadmap 3.0 A5 (2026-10-03, reálný Groq + PostgreSQL). Nic z toho neblokuje
merge A5 ani release v0.2.0; zápis i čtení zůstávají bezpečné.

## 1. „test" dává falešnou shodu s oblastí škola (`classify_areas`)

- **Kde:** `backend/context_service.py` → `_AREA_WORDS[AREA_SCHOOL]` obsahuje podřetězec `"test"`.
  `classify_areas` je sdílené pro CURRENT STATE prefetch (A3) i routing toolů (A5, `tool_router.py`).
- **Projev:** „přidej výdaj 1 Kč za A5 smoke test" → oblasti finance **+ škola** → routing vystavil
  10 toolů (~1 055 schema tokenů) místo ~5 (navíc `add_school_subject`, `add_school_assignment`,
  `add_school_exam` a školní read tooly); CURRENT STATE navíc obsahoval školní sekci.
- **Dopad:** jen tokeny navíc. Model zvolil správný tool; každý zápis stejně vyžaduje potvrzení v UI.
- **Návrh:** v pravidlech pro write záměr upřednostnit oblast podle objektu slovesa / částky v Kč
  („výdaj", „příjem" → jen finance) nebo školní „test" počítat jen jako samostatné slovo v otázce
  na školu. Přidat regresní test do `test_tool_router.py` a ověřit, že A3 testy kontextu zůstanou zelené.

## 2. ✅ VYŘEŠENO (Roadmap 3.5) – AI read nástroje vrací časy v UTC místo Europe/Prague

- **Kde:** `backend/read_queries.py` (např. finance transakce `created_at`, aktivita `timestamp`) vrací
  naive UTC `isoformat()`. Stejně se chovalo i staré `tools.get_finance_transactions` na `main` před A5 –
  **není to regrese A5**.
- **Projev:** transakce vytvořená v 07:12 pražského času se v odpovědi AI ukázala jako 05:12
  (jednou dokonce s popiskem „UTC").
- **Dopad:** zavádějící čas pro uživatele; filtrování podle dne už pražské hranice používá správně.
- **Návrh:** v read výsledcích pro AI převádět timestampy přes `time_utils.to_local()` a posílat je
  s offsetem (např. `2026-10-03T07:12:51+02:00`); data typu `Date` beze změny. Přidat test na
  CET/CEST. Zvážit totéž pro REST endpointy, které časy zobrazuje frontend.
- **Stav:** `read_queries` vrací pražský čas s offsetem (test CET/CEST v `test_read_queries.py`).
  REST endpointy pro frontend zůstávají beze změny (frontend si čas převádí sám) – případně Roadmap 4.

---

# Technický dluh z auditu Roadmap 3.5

Podrobnosti a klasifikace: `docs/architecture-audit.md` (L1–L12, R1–R10). Krátký seznam k naplánování:

## Backend (LATER)
- **L1** `main.py` (2,9k řádků, 83 rout): nové / upravované moduly přesouvat do `APIRouter`; první kandidáti
  dashboard agregace (~360 řádků) a `/chat` handler.
- **L2/L3** `ai.py`: oddělit `llm_client.py` (klient + `_llm_create_with_retry`) a `pending_actions.py`
  (stavový automat, startovní recovery z `main.py`, bez `HTTPException`). Pozor: ~10 testů patchuje
  `ai._llm_create_with_retry` / `ai.client`.
- **L4** Daily Briefing a Weekly Review mají téměř stejný claim/generate/notify/run_scheduled – vytáhnout až
  u třetího plánovaného AI výstupu.
- **L5** společný helper „vytvoř notifikaci jednou" (4 místa).
- **L6** doručování pushů běží v jobu připomínek (závislost na `REMINDERS_CHECK_ENABLED`), MAX_AGE 12 h pro
  všechny typy.
- **L7** zápisy v `tools.py` duplikují REST handlery (finance, práce, cíle…) → doménové služby (Roadmap 5).
- **L8** kopírované in-memory DB setupy v 33 testech → helper pro nové testy.
- **L9** `datetime.utcnow()` (deprecated v Pythonu 3.12) → `time_utils.utc_now()` jedním mechanickým krokem.
- **L10** nepoužívané endpointy `GET /ai/confirm/{id}` a `POST /ai/execute` – smazat po ověření, že je nic
  nevolá (frontend ne).
- **L12** sjednotit default `DATABASE_URL` (database.py nemá žádný, backup/alembic mají sqlite).
- **L13** zbývající privátní importy mezi moduly: `main.py` ← `ai._get_pending_action` / `_check_pending_expired`,
  `reminder_actions.py` ← `mutation_service._find_targets` / `_snapshot` → veřejná jména (spolu s L2).
- **L14** natvrdo zapsané stavy v `main.py`: cíle `("completed", "cancelled", "paused")` (2×, duplikát
  `GOAL_INACTIVE_STATUSES`) a WoT grind `("completed", "done", "cancelled")` → `statuses.py`.

## Frontend (Roadmap 4)
Viz `docs/roadmap4-ui-foundation.md` – sdílený data-fetching hook, primitivy, ConfirmDialog s busy stavem,
AppShell (jeden NotificationsBell), jazyk, `middleware.ts` → `proxy.ts`.
