# Paměť a její vyhledávání (MRK-84)

Paměť (`Memory`) je dlouhodobý kontext pro Jarvise: preference, plány, rozhodnutí, rutiny. Aktuální čísla a termíny
v ní nejsou zdrojem pravdy, ty patří do modulů (`ai.py`, pravidlo „module data wins"). Logika: `backend/memory_service.py`.

## Druh a platnost (migrace `0030_memory_lifecycle`)

| Sloupec | Význam |
| --- | --- |
| `kind` | `fact` (výchozí; existující řádky dostaly `fact`), `temporary`, `decision` – `statuses.MEMORY_KINDS` |
| `expires_at` | naive UTC; `temporary` ho vyžaduje. Po vypršení se vzpomínka nikde nepoužije |
| `supersedes_id` | vzpomínka, kterou tahle nahrazuje – připraveno pro MRK-111 (zatím bez chování) |

**Použitelná vzpomínka** = aktivní a nevypršená (`memory_service.usable`). Jen ty jdou do AI kontextu (prefetch
`context_service.build_current_context`), do planneru, do read toolu `get_memories` a do globálního vyhledávání.
Stránka Paměť (`GET /memories`) ukazuje i vypršené, s polem `expires_at`.

`POST /memory` přijímá `kind` a `expires_at` (s časovou zónou se převede na UTC); neplatný druh nebo dočasná vzpomínka
bez data = 422.

### Zadání druhu a platnosti (MRK-117)

- **Jarvis:** `save_memory` má volitelné `kind` a `expires_at` v pražském čase (`YYYY-MM-DD` = do konce dne, nebo
  `YYYY-MM-DDTHH:MM`). Resolver (`memory_ai_tool.prepare_save_memory`) ověří druh, budoucí platnost a že `temporary`
  platnost má – jinak žádná pending akce a model se má doptat. Executor po potvrzení převede čas na naive UTC
  (`time_utils.local_to_utc`). Náhled potvrzení ukáže „dočasná · platí do …“.
- **Stránka Paměť:** odznak druhu (Dočasná / Rozhodnutí) a platnosti („Platí do …“ / „Vypršela …“, vypršelá je
  ztlumená), filtr *Platnost* (vše / platné / vypršelé) a při přidání výběr druhu a pole *Platí do*. Úprava druh ani
  platnost nemění.

## Duplicity

Uložení textu, který už má použitelná (aktivní a nevypršená) vzpomínka (po sjednocení mezer a velikosti písmen, bez
ohledu na oblast), nový řádek nevytvoří: vrátí existující s `"deduplicated": true` a nic nezapíše (tedy ani do Aktivity).
Vypršená vzpomínka duplicitou není – stejný text s novou platností se uloží jako nová vzpomínka.

## Vyhledávání

- Paměť se hledá v celém textu (titulek výsledku zůstává zkrácený na 80 znaků).
- Každý zdroj globálního vyhledávání čte nanejvýš `ROW_LIMIT` řádků s deterministickým pořadím (`ORDER BY` … `id`).
- Studijní materiály: z DB jde jen úryvek extrahovaného textu (`substr(..., 1, SEARCH_TEXT_CHARS)`, sloupec je
  `defer`), kurzy jen pro nalezené materiály.
- Předfiltr v SQL (`ILIKE`) záměrně není: porovnání bez diakritiky dělá Python (`search_service.normalize`), PostgreSQL
  bez rozšíření `unaccent` by „zkouska" na „Zkouška" nenašel. Fulltext v PostgreSQL je Later.

Testy: `backend/tests/test_memory_lifecycle.py`.
