"""Globální vyhledávání (Roadmap 4D) – deterministické, bez LLM, bez indexu.

Data jsou malá (osobní aplikace), takže se pro každý dotaz projdou omezené výběry z tabulek a seřadí
v Pythonu: porovnání bez diakritiky a velikosti písmen, pořadí přesná shoda → začátek → celé slovo →
podřetězec → všechna slova dotazu. Výsledky mají jeden tvar (SearchResult) a vedou na stránku modulu
s parametrem záznamu (např. /school?exam=12). Žádné interní údaje (auth, push, pending akce, konverzace).
Stejná pravidla normalizace/řazení má frontend v lib/search.ts (navigace se hledá lokálně).

MRK-20: záznamy dodávají moduly (`ModuleIntegrations.search` v `<modul>_integrations.py`, jádro v
core_integrations.py); tady zůstává jen politika – skóre, řazení, limit na typ, celkový limit a gating.
"""
from __future__ import annotations

import logging
import unicodedata
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from module_registry import ModuleAccess, current_access

log = logging.getLogger(__name__)

MIN_QUERY = 2
MAX_QUERY = 100
MAX_RESULTS = 30
PER_TYPE = 6
ROW_LIMIT = 500  # na tabulku – data jsou malá, ale dotaz musí zůstat omezený (zdroje v *_integrations.py)


def normalize(text) -> str:
    """„Zkouška Fyzika" → „zkouska fyzika": malá písmena, bez diakritiky, sloučené mezery."""
    decomposed = unicodedata.normalize("NFD", str(text or ""))
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " ".join(stripped.lower().split())


def score_text(query: str, title: str, extra: str = "") -> int:
    """Skóre shody (0 = žádná). `query` už normalizovaný; `extra` = podtitulek a klíčová slova."""
    if not query:
        return 0
    t = normalize(title)
    if t == query:
        return 100
    if t.startswith(query):
        return 85
    words = t.split()
    if any(w.startswith(query) for w in words):
        return 70
    if query in t:
        return 55
    tokens = query.split()
    haystack = f"{t} {normalize(extra)}"
    if len(tokens) > 1 and all(any(w.startswith(tok) for w in haystack.split()) for tok in tokens):
        return 45
    if query in haystack:
        return 30
    return 0


@dataclass
class SearchResult:
    id: str
    type: str
    title: str
    subtitle: str
    area: str
    href: str
    score: int


def _candidates(db: Session, q: str, access: ModuleAccess):
    """Kandidáti od zdrojů jádra a dostupných modulů (MRK-20: `ModuleIntegrations.search`), v pevném pořadí zdrojů.

    Zdroj, který selže, se přeskočí (log + rollback čtecí transakce) – ostatní moduly hledají dál.
    """
    sources = sorted((src for _owner, src in access.contributions("search")), key=lambda src: src.order)
    for src in sources:
        try:
            # list(): chyba dotazu se projeví tady, ne až uprostřed řazení
            yield from list(src.fetch(db, q))
        except Exception:  # noqa: BLE001 – jeden modul nesmí shodit vyhledávání
            log.exception("search: source %s failed", src.name)
            db.rollback()


def search(db: Session, raw_query: str, limit: int = MAX_RESULTS, *, access: ModuleAccess | None = None) -> dict:
    """Výsledky seřazené podle skóre (u shody pořadí podle typu a titulku), max. PER_TYPE na typ.

    Roadmap 6C: záznamy modulu, který nesmí do vyhledávání (vypnutý flag), se vynechají – řazení beze změny.
    """
    q = normalize(raw_query)[:MAX_QUERY]
    if len(q) < MIN_QUERY:
        return {"query": q, "results": [], "total": 0}
    access = access or current_access()
    found: list[SearchResult] = []
    for typ, rid, title, subtitle, extra, area, href in _candidates(db, q, access):
        if not access.allows_entity(typ, "search"):  # pojistka: zdroj by neměl vracet cizí typy
            continue
        s = score_text(q, title, f"{subtitle} {extra}")
        if s:
            found.append(SearchResult(f"{typ}:{rid}", typ, str(title), subtitle, area, href, s))
    found.sort(key=lambda r: (-r.score, normalize(r.title)))
    per_type: dict[str, int] = {}
    out: list[SearchResult] = []
    for r in found:
        if per_type.get(r.type, 0) >= PER_TYPE:
            continue
        per_type[r.type] = per_type.get(r.type, 0) + 1
        out.append(r)
        if len(out) >= max(1, min(limit, MAX_RESULTS)):
            break
    return {"query": q, "results": [asdict(r) for r in out], "total": len(found)}
