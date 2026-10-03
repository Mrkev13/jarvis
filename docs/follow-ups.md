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

## 2. AI read nástroje vrací časy v UTC místo Europe/Prague

- **Kde:** `backend/read_queries.py` (např. finance transakce `created_at`, aktivita `timestamp`) vrací
  naive UTC `isoformat()`. Stejně se chovalo i staré `tools.get_finance_transactions` na `main` před A5 –
  **není to regrese A5**.
- **Projev:** transakce vytvořená v 07:12 pražského času se v odpovědi AI ukázala jako 05:12
  (jednou dokonce s popiskem „UTC").
- **Dopad:** zavádějící čas pro uživatele; filtrování podle dne už pražské hranice používá správně.
- **Návrh:** v read výsledcích pro AI převádět timestampy přes `time_utils.to_local()` a posílat je
  s offsetem (např. `2026-10-03T07:12:51+02:00`); data typu `Date` beze změny. Přidat test na
  CET/CEST. Zvážit totéž pro REST endpointy, které časy zobrazuje frontend.
