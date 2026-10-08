"""Globální vyhledávání (Roadmap 4D) – deterministické, bez LLM, bez indexu.

Data jsou malá (osobní aplikace), takže se pro každý dotaz projdou omezené výběry z tabulek a seřadí
v Pythonu: porovnání bez diakritiky a velikosti písmen, pořadí přesná shoda → začátek → celé slovo →
podřetězec → všechna slova dotazu. Výsledky mají jeden tvar (SearchResult) a vedou na stránku modulu
s parametrem záznamu (např. /school?exam=12). Žádné interní údaje (auth, push, pending akce, konverzace).
Stejná pravidla normalizace/řazení má frontend v lib/search.ts (navigace se hledá lokálně).
"""
from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from goal_history_service import compute_goal_progress_and_value
from models import Assignment, Exam, FinanceTransaction, Goal, Memory, MffCharacter, Reminder, Subject, WorkSession, WotGrind, WotReplay
from module_registry import ModuleAccess, current_access
from reminder_service import describe_recurrence, format_local
from statuses import REMINDER_ACTIVE_STATUSES, is_assignment_done
from time_utils import to_local
from text_utils import finance_category_label_cz, format_czk_cz, format_date_cz, format_hours_cz, format_num_cz

MIN_QUERY = 2
MAX_QUERY = 100
MAX_RESULTS = 30
PER_TYPE = 6
ROW_LIMIT = 500  # na tabulku – data jsou malá, ale dotaz musí zůstat omezený


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


_EXAM_TYPES = {"exam": "Zkouška", "test": "Test", "quiz": "Kvíz", "midterm": "Průběžný test", "oral": "Ústní zkouška", "other": "Jiné"}
_PRIORITY = {"high": "vysoká priorita", "medium": "", "low": ""}
_MFF_STATUS = {"built": "postaveno", "building": "rozpracováno", "in_progress": "rozpracováno", "planned": "plánováno", "inactive": "neaktivní"}
_GOAL_STATUS = {"active": "aktivní", "in_progress": "rozpracovaný", "completed": "splněný", "paused": "pozastavený", "cancelled": "zrušený"}
_AREA = {"school": "Škola", "work": "Práce", "finance": "Finance", "wot": "World of Tanks", "mff": "Marvel FF",
         "personal": "Osobní", "fitness": "Fitness", "hobby": "Hobby", "travel": "Cestování", "general": "Obecné",
         "goals": "Cíle", "reminders": "Připomínky"}
_MEMORY_CATEGORY = {"context": "Kontext", "preference": "Preference", "plan": "Plán", "decision": "Rozhodnutí",
                    "routine": "Rutina", "constraint": "Omezení", "goal": "Cíl", "fact": "Fakt"}
_GRIND_STATUS = {"active": "aktivní", "paused": "pozastaveno", "completed": "dokončeno"}


def _join(*parts) -> str:
    return " · ".join(p for p in parts if p)


def _candidates(db: Session, q: str):
    """(typ, záznam → (titulek, podtitulek, extra, oblast, href)) pro všechny hledané moduly."""
    subjects = {s.id: s for s in db.query(Subject).limit(ROW_LIMIT).all()}
    subj = lambda sid: subjects[sid].name if sid in subjects else ""  # noqa: E731

    for s in subjects.values():
        yield "subject", s.id, s.name, _join("Předmět", s.code, s.semester), f"{s.code} {s.semester}", "school", f"/school?subject={s.id}"
    for a in db.query(Assignment).order_by(Assignment.due_date.desc()).limit(ROW_LIMIT).all():
        done = is_assignment_done(a.status)
        sub = _join("Úkol", subj(a.subject_id), f"termín {format_date_cz(a.due_date)}" if a.due_date else "", "hotovo" if done else "")
        yield "assignment", a.id, a.title, sub, f"{subj(a.subject_id)} {a.description or ''} úkol", "school", f"/school?assignment={a.id}"
    for e in db.query(Exam).order_by(Exam.exam_date.desc()).limit(ROW_LIMIT).all():
        kind = _EXAM_TYPES.get((e.exam_type or "").lower(), "Zkouška")
        sub = _join(kind, subj(e.subject_id), format_date_cz(e.exam_date) if e.exam_date else "")
        yield "exam", e.id, e.title, sub, f"{subj(e.subject_id)} {kind} zkouska {e.notes or ''}", "school", f"/school?exam={e.id}"
    for r in (db.query(Reminder).filter(Reminder.status.in_(REMINDER_ACTIVE_STATUSES)).order_by(Reminder.due_at).limit(ROW_LIMIT).all()):
        when = describe_recurrence(r) if r.recurrence != "none" else format_local(r.due_at)
        yield "reminder", r.id, r.title, _join("Připomínka", when), f"{r.note or ''} pripominka", "reminders", f"/reminders?reminder={r.id}"
    for w in db.query(WorkSession).order_by(WorkSession.date.desc(), WorkSession.id.desc()).limit(ROW_LIMIT).all():
        title = w.project or w.description or "Pracovní záznam"
        sub = _join("Práce", format_date_cz(w.date), format_hours_cz(w.hours, 1), w.description if w.project else "")
        yield "work_session", w.id, title, sub, f"{w.description or ''} prace", "work", f"/work?session={w.id}"
    for t in db.query(FinanceTransaction).order_by(FinanceTransaction.created_at.desc(), FinanceTransaction.id.desc()).limit(ROW_LIMIT).all():
        kind = "Příjem" if t.transaction_type == "income" else "Výdaj"
        category = finance_category_label_cz(t.category)
        title = t.description or category or kind
        sub = _join(kind, format_czk_cz(t.amount), category if t.description else "", format_date_cz(t.created_at) if t.created_at else "")
        yield "transaction", t.id, title, sub, f"{category} {t.category or ''} {kind}", "finance", f"/finance?transaction={t.id}"
    for g in db.query(Goal).limit(ROW_LIMIT).all():
        # stejné procento jako stránka Cíle – automatické cíle mají `progress` ve sloupci 0, hodnota se počítá
        pct, _ = compute_goal_progress_and_value(db, g)
        sub = _join("Cíl", _GOAL_STATUS.get((g.status or "").lower(), ""), f"{pct} %", f"do {format_date_cz(g.target_date)}" if g.target_date else "")
        yield "goal", g.id, g.title, sub, f"{g.description or ''} cil", "goals", f"/goals?goal={g.id}"
    for m in db.query(Memory).filter(Memory.active == True).limit(ROW_LIMIT).all():  # noqa: E712
        content = " ".join((m.content or "").split())
        title = content if len(content) <= 80 else content[:79].rstrip() + "…"
        cat = _MEMORY_CATEGORY.get((m.category or "").lower(), m.category or "")
        area = _AREA.get((m.area or "").lower(), m.area or "")
        yield "memory", m.id, title, _join("Paměť", cat, area), f"{cat} {area} pamet", "memory", f"/memory?memory={m.id}"
    for g in db.query(WotGrind).limit(ROW_LIMIT).all():
        sub = _join("Grind", f"zbývá {format_num_cz(g.xp_remaining, 0)} XP", _GRIND_STATUS.get((g.status or "").lower(), ""), _PRIORITY.get((g.priority or "").lower(), ""))
        yield "wot_grind", g.id, g.tank, sub, "wot tank grind", "wot", f"/wot?grind={g.id}"
    for r in db.query(WotReplay).order_by(WotReplay.uploaded_at.desc()).limit(ROW_LIMIT).all():
        # Game Enrichment C: replay – tank (nebo technický název vozidla / souboru), mapa, štítky, poznámka
        title = r.tank_name or (r.tank_tag.split(":", 1)[-1] if r.tank_tag else None) or r.original_filename or f"Replay #{r.id}"
        tags = " ".join(r.tags or [])
        sub = _join("Replay", r.map_name, format_date_cz(to_local(r.played_at)) if r.played_at else "", "★" if r.favorite else "")
        # technický tag zůstává dohledatelný i když má replay lidský název („A67_T57_58")
        tag = r.tank_tag.split(":", 1)[-1] if r.tank_tag else ""
        yield "wot_replay", r.id, title, sub, f"{tags} {r.notes or ''} {r.original_filename or ''} {tag} wot replay zaznam", "wot", f"/wot/replays?replay={r.id}"
    for c in db.query(MffCharacter).limit(ROW_LIMIT).all():
        sub = _join(f"{c.tier} · Lv. {c.level}" if c.level else c.tier, _MFF_STATUS.get((c.status or "").lower(), ""), c.uniform)
        yield "mff_character", c.id, c.name, sub, f"{c.uniform} {c.team} {c.role} mff postava", "mff", f"/mff?character={c.id}"


def search(db: Session, raw_query: str, limit: int = MAX_RESULTS, *, access: ModuleAccess | None = None) -> dict:
    """Výsledky seřazené podle skóre (u shody pořadí podle typu a titulku), max. PER_TYPE na typ.

    Roadmap 6C: záznamy modulu, který nesmí do vyhledávání (vypnutý flag), se vynechají – řazení beze změny.
    """
    q = normalize(raw_query)[:MAX_QUERY]
    if len(q) < MIN_QUERY:
        return {"query": q, "results": [], "total": 0}
    access = access or current_access()
    found: list[SearchResult] = []
    for typ, rid, title, subtitle, extra, area, href in _candidates(db, q):
        if not access.allows_entity(typ, "search"):
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
