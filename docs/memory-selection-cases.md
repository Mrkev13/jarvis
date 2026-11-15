# Kontrolní sada pro výběr vzpomínek (MRK-110)

Jarvis vybírá vzpomínky do promptu deterministicky (`backend/context_service.py`: `classify_areas`,
`is_planner_like`, `rank_memories`, max. 3 vzpomínky). Sada v `backend/tests/data/memory_selection_cases.json`
ukazuje, jestli změna výběru pomohla obecně, ne jen na jednom opraveném příkladu. Test:
`backend/tests/test_memory_selection.py` (bez LLM, bez DB, bez sítě; Groq count 0).

## Části

- **`tune`** – případy, na kterých se výběr ladí (min. 20).
- **`holdout`** – stranou, **při ladění se neupravují** (min. 10). Když změna projde `tune`, ale zhorší `holdout`,
  přeučila se na známé případy.
- **`known_gap`** – správné očekávání, které dnešní výběr nesplňuje; `note` říká proč. Počítá se do metrik, test
  kvůli němu nepadá. Když ho změna opraví, test to nahlásí: odeber `known_gap` a posuň baseline.

## Metriky (pro obě části zvlášť)

- `passed` – počet případů, které projdou celé;
- `recall` – podíl vzpomínek z `must`, které se vybraly;
- `violation_rate` – podíl vzpomínek z `must_not`, které se vybraly (nemají).

`baseline` v datech = dnešní stav. Test padá, když `passed` nebo `recall` klesne, nebo `violation_rate` stoupne.
Zlepšení se zapíše posunem `baseline` v tomtéž PR.

## Přidání případu

1. Chybná odpověď z praxe → co se mělo / nemělo vybrat. Data vždy vymyšlená, nic z reálné DB, **žádné finance**
   (MRK-60).
2. Chybí-li vzpomínka, přidej ji do `memories` (unikátní `id`).
3. Nový případ jde **nejdřív do `holdout`**; do `tune` se přesouvá jen při vědomém ladění.
4. Když dnes neprojde, označ ho `known_gap` s důvodem a nech baseline beze změny.

## Známé mezery (stav 2026-11-15)

- `planovani-rano` – v plánovacím režimu se obecná preference („ráno jsem nejproduktivnější") nevejde do top 3.
- `atlas-plan-zruseny` – zrušený plán vypadá jako platná vzpomínka; řeší MRK-111 (stav platnosti).
- `h-ceta` – časové slovo („pátek") zapne plánovací režim a ten přidá nesouvisející vzpomínky s vysokou
  důležitostí; kandidát na úpravu `is_planner_like`.
