"""Příspěvky modulu Škola do globálních agregátorů (MRK-20).

Bloky přesunuté beze změny chování ze search_service, today_service, main (GET /dashboard „upcoming"),
context_service a quick_add_service. Agregátory je volají jen pro dostupný modul (`module_registry`).
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

import quick_add_text as qt
from context_format import MAX_ITEMS, WINDOW_DAYS, list_or_none, short
from models import Assignment, Exam, Goal, Subject
from modules.school import integrations as materials
from module_contracts import (
    ChangeSource, activity_changes, event_changes,
    ContextRequest, ContextSection, DashboardSection, EntityRef, ModuleIntegrations, QuickAddKind, QuickAddRule,
    SearchSource, TimelineItem, TimelineSource, TodaySource,
)
from statuses import (
    ASSIGNMENT_DONE_STATUSES, EXAM_OPEN_STATUSES, GOAL_INACTIVE_STATUSES, is_assignment_done, is_exam_open, norm,
)
from text_utils import format_date_cz, join_parts
from time_utils import now_local, today_local
from today_types import UPCOMING_DAYS, TodayItem

log = logging.getLogger(__name__)
ROW_LIMIT = 500

# ---------- vyhledávání ----------

_EXAM_TYPES = {"exam": "Zkouška", "test": "Test", "quiz": "Kvíz", "midterm": "Průběžný test", "oral": "Ústní zkouška", "other": "Jiné"}


def search_school(db, q):
    subjects = {s.id: s for s in db.query(Subject).limit(ROW_LIMIT).all()}
    subj = lambda sid: subjects[sid].name if sid in subjects else ""  # noqa: E731

    for s in subjects.values():
        yield ("subject", s.id, s.name, join_parts("Předmět", s.code, s.semester, "archivovaný" if s.active is False else ""),
               f"{s.code} {s.semester}", "school", f"/school?subject={s.id}")
    for a in db.query(Assignment).order_by(Assignment.due_date.desc()).limit(ROW_LIMIT).all():
        done = is_assignment_done(a.status)
        sub = join_parts("Úkol", subj(a.subject_id), f"termín {format_date_cz(a.due_date)}" if a.due_date else "", "hotovo" if done else "")
        yield "assignment", a.id, a.title, sub, f"{subj(a.subject_id)} {a.description or ''} úkol", "school", f"/school?assignment={a.id}"
    for e in db.query(Exam).order_by(Exam.exam_date.desc()).limit(ROW_LIMIT).all():
        kind = _EXAM_TYPES.get((e.exam_type or "").lower(), "Zkouška")
        sub = join_parts(kind, subj(e.subject_id), format_date_cz(e.exam_date) if e.exam_date else "")
        yield "exam", e.id, e.title, sub, f"{subj(e.subject_id)} {kind} zkouska {e.notes or ''}", "school", f"/school?exam={e.id}"


# ---------- Dnes ----------


def _subjects(c) -> dict[int, str]:
    """Názvy předmětů pro podtitulky (jednou na požadavek). Chyba = bez názvů, položky se ukážou dál."""
    if "school_subjects" not in c.cache:
        try:
            c.cache["school_subjects"] = {s.id: s.name for s in c.db.query(Subject).all()}
        except Exception:  # noqa: BLE001 – bez názvů předmětů se dá pokračovat
            log.exception("today: subjects")
            c.cache["school_subjects"] = {}
    return c.cache["school_subjects"]


def _school_subtitle(kind: str, subject: str | None, extra: str | None = None) -> str:
    return " · ".join(x for x in (kind, subject, extra) if x)


def _exam_kind(exam_type: str | None) -> str:
    return {"test": "Test", "quiz": "Kvíz", "colloquium": "Kolokvium", "midterm": "Průběžný test", "oral": "Ústní zkouška"}.get(
        norm(exam_type), "Zkouška")


def today_school_timeline(c) -> list[TodayItem]:
    subjects = _subjects(c)
    items: list[TodayItem] = []
    for e in c.db.query(Exam).filter(Exam.exam_date == c.today).all():
        items.append(TodayItem(
            id=f"exam:{e.id}", type="exam", title=e.title,
            subtitle=_school_subtitle(_exam_kind(e.exam_type), subjects.get(e.subject_id)),
            area="school", date=c.today.isoformat(), status="open" if is_exam_open(e.status) else "done",
            href=f"/school?exam={e.id}", source_id=e.id,
        ))
    for a in c.db.query(Assignment).filter(Assignment.due_date == c.today).all():
        items.append(TodayItem(
            id=f"assignment:{a.id}", type="assignment", title=a.title,
            subtitle=_school_subtitle("Úkol · termín dnes", subjects.get(a.subject_id)),
            area="school", date=c.today.isoformat(), status="done" if is_assignment_done(a.status) else "open",
            href=f"/school?assignment={a.id}", source_id=a.id, actions=[] if is_assignment_done(a.status) else ["complete"],
        ))
    return items


def today_school_overdue(c) -> list[TodayItem]:
    subjects = _subjects(c)
    items: list[TodayItem] = []
    for a in c.db.query(Assignment).filter(Assignment.due_date.is_not(None), Assignment.due_date < c.today).all():
        if is_assignment_done(a.status):
            continue
        items.append(TodayItem(
            id=f"assignment:{a.id}", type="assignment", title=a.title,
            subtitle=_school_subtitle("Úkol po termínu", subjects.get(a.subject_id), f"termín {format_date_cz(a.due_date)}"),
            area="school", date=a.due_date.isoformat(), status="overdue", severity="important",
            href=f"/school?assignment={a.id}", source_id=a.id, actions=["complete"],
        ))
    for e in c.db.query(Exam).filter(Exam.exam_date.is_not(None), Exam.exam_date < c.today).all():
        if not is_exam_open(e.status):
            continue
        items.append(TodayItem(
            id=f"exam:{e.id}", type="exam", title=e.title,
            subtitle=_school_subtitle(f"{_exam_kind(e.exam_type)} proběhla – zapiš výsledek", subjects.get(e.subject_id),
                                      format_date_cz(e.exam_date)),
            area="school", date=e.exam_date.isoformat(), status="overdue", severity="warning",
            href=f"/school?exam={e.id}", source_id=e.id, actions=["record_result"],
        ))
    return items


def today_school_upcoming(c) -> list[TodayItem]:
    subjects = _subjects(c)
    first, last = c.today + timedelta(days=1), c.today + timedelta(days=UPCOMING_DAYS)
    items: list[TodayItem] = []
    for e in c.db.query(Exam).filter(Exam.exam_date >= first, Exam.exam_date <= last).all():
        if is_exam_open(e.status):
            items.append(TodayItem(
                id=f"exam:{e.id}", type="exam", title=e.title,
                subtitle=_school_subtitle(_exam_kind(e.exam_type), subjects.get(e.subject_id)), area="school",
                date=e.exam_date.isoformat(), status="upcoming", href=f"/school?exam={e.id}", source_id=e.id,
            ))
    for a in c.db.query(Assignment).filter(Assignment.due_date >= first, Assignment.due_date <= last).all():
        if not is_assignment_done(a.status):
            items.append(TodayItem(
                id=f"assignment:{a.id}", type="assignment", title=a.title,
                subtitle=_school_subtitle("Úkol", subjects.get(a.subject_id)), area="school",
                date=a.due_date.isoformat(), status="upcoming", href=f"/school?assignment={a.id}", source_id=a.id,
            ))
    return items


def today_school_closed(c) -> set[str]:
    refs = {f"assignment:{a.id}" for a in c.db.query(Assignment.id, Assignment.status).all() if is_assignment_done(a.status)}
    refs |= {f"exam:{e.id}" for e in c.db.query(Exam.id, Exam.status).all() if not is_exam_open(e.status)}
    return refs


# ---------- GET /dashboard: „upcoming" ----------


def get_upcoming(db, limit: int = 5, today: date | None = None):

    today_use: date = today or today_local()
    entries: list[dict] = []
    assignments = db.query(Assignment).filter(Assignment.due_date.is_not(None)).all()
    for it in assignments:
        if (it.status or "").strip().lower() in ASSIGNMENT_DONE_STATUSES:
            continue
        days = (it.due_date - today_use).days
        entries.append({
            "type": "assignment",
            "id": it.id,
            "title": it.title,
            "area": "school",
            "date": it.due_date.isoformat(),
            "days_left": days,
            "overdue": days < 0,
        })
    exams = db.query(Exam).filter(Exam.exam_date.is_not(None)).all()
    for it in exams:
        if (it.status or "").strip().lower() not in EXAM_OPEN_STATUSES:
            continue
        days = (it.exam_date - today_use).days
        entries.append({
            "type": "exam",
            "id": it.id,
            "title": it.title,
            "area": "school",
            "date": it.exam_date.isoformat(),
            "days_left": days,
            "overdue": days < 0,
        })
    goals = db.query(Goal).filter(Goal.target_date.is_not(None)).all()
    for g in goals:
        st = (g.status or "").lower()
        if st in GOAL_INACTIVE_STATUSES:
            continue
        days = (g.target_date - today_use).days
        entries.append({
            "type": "goal_target",
            "id": g.id,
            "title": g.title,
            "area": g.area or "general",
            "date": g.target_date.isoformat(),
            "days_left": days,
            "overdue": days < 0,
        })

    def sort_key(e):
        overdue_rank = 0 if e["overdue"] else 1
        if e["overdue"]:
            return (overdue_rank, int(e["days_left"] or 0), e["type"], e["title"])
        return (overdue_rank, int(e["days_left"] or 0), e["type"], e["title"])

    entries.sort(key=sort_key)
    return entries[:max(0, int(limit))]


# Typy položek „upcoming" → typ záznamu modulu (ref), pokud se liší (termíny cílů patří modulu Cíle).
_DASHBOARD_ENTITY = {"goal_target": "goal"}


def dashboard_upcoming(db, access):
    return [
        u for u in get_upcoming(db, limit=5)
        if access.allows_entity(_DASHBOARD_ENTITY.get(u.get("type"), u.get("type")), "dashboard")
    ]


# ---------- AI kontext ----------


def context_school(req: ContextRequest) -> list[str]:
    db, today = req.db, req.today
    window_end = today + timedelta(days=WINDOW_DAYS)
    open_assignments = [
        a for a in db.query(Assignment).filter(Assignment.due_date.is_not(None)).all()
        if (a.status or "").strip().lower() not in ASSIGNMENT_DONE_STATUSES
    ]
    overdue = sorted((a for a in open_assignments if a.due_date < today), key=lambda a: a.due_date)
    upcoming = sorted((a for a in open_assignments if today <= a.due_date <= window_end), key=lambda a: a.due_date)
    exams = sorted(
        (e for e in db.query(Exam).filter(Exam.exam_date.is_not(None)).all()
         if today <= e.exam_date <= window_end and (e.status or "").strip().lower() in EXAM_OPEN_STATUSES),
        key=lambda e: e.exam_date,
    )

    def fmt(title: str, subject, d: date) -> str:
        subj = f", {short(subject.name, 25)}" if subject is not None else ""
        return f"{short(title, 50)}{subj}, {d.isoformat()}"

    return [
        f"Škola po termínu: {list_or_none([fmt(a.title, a.subject, a.due_date) for a in overdue[:MAX_ITEMS]], len(overdue))}",
        f"Úkoly do {window_end.isoformat()}: {list_or_none([fmt(a.title, a.subject, a.due_date) for a in upcoming[:MAX_ITEMS]], len(upcoming))}",
        f"Zkoušky do {window_end.isoformat()}: {list_or_none([fmt(e.title, e.subject, e.exam_date) for e in exams[:MAX_ITEMS]], len(exams))}",
    ]


# ---------- Rychlé přidání: zkouška, úkol ----------

KW_EXAM = re.compile(r"\b(test|testu|zkouska|zkousku|zkousky|kviz|zapocet|pisemka|pisemku)\b")
KW_ASSIGNMENT = re.compile(r"\b(ukol|ukolu|deadline|assignment|referat|seminarka|seminarku|odevzdat|odevzdani)\b")
KW_PRIORITY_HIGH = re.compile(r"(\b(dulezit\w*|urgent\w*|priorita\s+vysoka)\b|!!)")


def load_subjects(db) -> list[dict]:
    if db is None:
        return []
    return [{"id": s.id, "name": s.name, "code": s.code or ""} for s in
            db.query(Subject).filter(Subject.active.isnot(False)).order_by(Subject.name).limit(200).all()]


def match_subjects(f: str, subjects: list[dict]) -> tuple[list[dict], list[dict]]:
    """Předmět podle názvu / kódu v textu (bez diakritiky, i skloňovaně: „z práva" → Právo).

    Vrací (kandidáti, podobné): přesná shoda názvu nebo kódu má přednost před shodou kmene prvního slova;
    „podobné" jsou další předměty se stejným kmenem – náhled je ukáže, aby výběr nebyl potichu.
    """
    words = re.findall(r"[a-z0-9]+", f)
    exact, stem_hits = [], []
    for s in subjects:
        name = qt.fold(" ".join(str(s["name"]).split()))
        code = qt.fold(str(s.get("code") or ""))
        if (len(name) >= 3 and re.search(rf"\b{re.escape(name)}\b", f)) or (code and code in words):
            exact.append(s)
        first = name.split(" ")[0] if name else ""
        if len(first) >= 4:
            stem = first[: max(4, len(first) - 2)]
            if any(w.startswith(stem) for w in words):
                stem_hits.append(s)
    hits = exact or stem_hits
    similar = [s for s in stem_hits if s not in hits]
    return hits, similar


def parse_school(t, d, now_utc: datetime, ctx: dict):
    kind, subjects = d.kind, ctx.get("subjects") or []
    today = now_local(now_utc).date()
    day = qt.find_date(t, today, d)
    qt.find_time(t, qt.Draft())  # čas u zkoušky zatím neukládáme – jen ho vynechat z názvu
    high = KW_PRIORITY_HIGH.search(t.f)
    if high:
        t.take(high)
    hits, similar = match_subjects(t.f, subjects)
    title = t.rest()
    date_key = "exam_date" if kind == "exam" else "due_date"
    d.fields = {"title": title, "subject_id": hits[0]["id"] if len(hits) == 1 else None, date_key: day.isoformat() if day else ""}
    if kind == "exam":
        em = KW_EXAM.search(t.f)
        word = em.group(1) if em else "zkouska"
        d.fields["exam_type"] = "test" if word.startswith(("test", "pisem", "zapoc")) else "quiz" if word == "kviz" else "exam"
    else:
        d.fields["priority"] = "high" if high else "medium"
    if not title:
        d.need("title", "Jak se to jmenuje?")
    if len(hits) != 1:
        d.need("subject_id", "Vyber předmět." if hits else "Ke kterému předmětu to patří?")
        if len(hits) > 1:
            d.warnings.append("Text odpovídá více předmětům – vyber správný.")
    elif similar:
        d.warnings.append("Podobný předmět: " + ", ".join(s["name"] for s in similar[:3]) + " – zkontroluj výběr.")
    if not day and not any(e["field"] == "date" for e in d.errors):
        d.need(date_key, "Kdy je termín?")
    elif day and day < today:
        d.warnings.append("Termín je v minulosti.")


def _school_tool_call(kind: str):
    def to_tool_call(f: dict, d, today, now_utc, db) -> tuple[str, dict]:
        title = qt.required(f, d, "title", "Doplň název.")
        key = "exam_date" if kind == "exam" else "due_date"
        when = qt.required(f, d, key, "Doplň termín.")
        if when:
            try:
                if abs((date.fromisoformat(when) - today).days) > 366:
                    d.error(key, "Termín je víc než rok od dneška.")
            except ValueError:
                d.error(key, "Neplatné datum.")
        try:
            sid = int(f.get("subject_id"))
        except (TypeError, ValueError):
            sid = None
        if sid is None or db.query(Subject.id).filter(Subject.id == sid).first() is None:
            d.error("subject_id", "Vyber existující předmět.")
        if title and len(title) > 255:
            d.error("title", "Název je moc dlouhý.")
        if kind == "exam":
            et = f.get("exam_type") if f.get("exam_type") in ("exam", "test", "quiz", "midterm", "oral", "other") else "exam"
            return "add_school_exam", {"title": title or "", "subject_id": sid, "exam_type": et, "exam_date": when}
        pr = f.get("priority") if f.get("priority") in ("low", "medium", "high") else "medium"
        return "add_school_assignment", {"title": title or "", "subject_id": sid, "due_date": when, "priority": pr}
    return to_tool_call


def _school_display(kind: str):
    def display(f: dict, ctx: dict, today) -> dict:
        subjects = {s["id"]: s["name"] for s in ctx.get("subjects") or []}
        key = "exam_date" if kind == "exam" else "due_date"
        label = {"test": "Test", "quiz": "Kvíz"}.get(f.get("exam_type"), "Zkouška") if kind == "exam" else "Úkol"
        when = format_date_cz(date.fromisoformat(f[key])) if f.get(key) else "termín? (doplň)"
        subj = subjects.get(f.get("subject_id")) or "předmět? (doplň)"
        return {"title": f.get("title") or label, "subtitle": " · ".join((label, subj, when)), "area": "school"}
    return display


def quick_add_context(db) -> dict:
    return {"subjects": load_subjects(db)}


def quick_add_output(ctx: dict) -> dict:
    return {"subjects": [{"id": s["id"], "name": s["name"]} for s in ctx.get("subjects") or []]}


# ---------- denní osa (MRK-13) ----------

def timeline_school(req) -> list[TimelineItem]:
    """Zkoušky a termíny úkolů daného dne: jen datum, žádný vymyšlený čas → denní sekce osy."""
    subjects = _subjects(req)
    items = []
    for e in req.db.query(Exam).filter(Exam.exam_date == req.day).all():
        items.append(TimelineItem(
            id=f"exam:{e.id}", kind="exam", title=e.title, date=req.day.isoformat(),
            status="open" if is_exam_open(e.status) else "done",
            subtitle=_school_subtitle(_exam_kind(e.exam_type), subjects.get(e.subject_id)), href=f"/school?exam={e.id}"))
    for a in req.db.query(Assignment).filter(Assignment.due_date == req.day).all():
        items.append(TimelineItem(
            id=f"assignment:{a.id}", kind="assignment", title=a.title, date=req.day.isoformat(),
            status="done" if is_assignment_done(a.status) else "open",
            subtitle=_school_subtitle("Úkol · termín", subjects.get(a.subject_id)), href=f"/school?assignment={a.id}"))
    return items


INTEGRATIONS = ModuleIntegrations(
    timeline=(TimelineSource("school", 20, timeline_school),),
    # MRK-28: dokončení/znovuotevření = doménové události, ostatní změny školy z Aktivity
    changes=(ChangeSource(
        "school", areas=frozenset({"school"}),
        from_event=event_changes({"assignment": "/school?assignment={id}", "exam": "/school?exam={id}",
                                  "subject": "/school?subject={id}", **materials.CHANGE_HREFS},
                                 {"school.assignment.completed": "Úkol splněn", "school.assignment.reopened": "Úkol znovu otevřen",
                                  "school.exam.closed": "Zkouška uzavřena", "school.exam.reopened": "Zkouška znovu otevřena",
                                  "school.subject.updated": "Předmět upraven", "school.subject.archived": "Předmět archivován",
                                  "school.subject.restored": "Předmět obnoven", **materials.CHANGE_TITLES}),
        from_activity=activity_changes({"assignment": "/school?assignment={id}", "exam": "/school?exam={id}",
                                        **materials.CHANGE_HREFS}, "/school"),
    ),),
    search=(SearchSource("school", 10, search_school), *materials.SEARCH),
    today=(
        TodaySource("school", 20, timeline=today_school_timeline, overdue=today_school_overdue,
                    upcoming=today_school_upcoming, closed_refs=today_school_closed),
    ),
    entity_refs=(
        EntityRef("assignment", "/school?assignment={id}", planner_actions=("complete",), notification_source=True),
        EntityRef("exam", "/school?exam={id}", notification_source=True),
        *materials.ENTITY_REFS,
    ),
    dashboard=(DashboardSection("upcoming", dashboard_upcoming, empty=[]),),
    context=(
        ContextSection("school", ("skol", "ukol", "zkous", "pisemk", "zapoct", "predmet", "semestr", "deadline", "termin", "test"),
                       order=10, build=context_school, covered_tools=("get_school_assignments", "get_school_exams")),
        *materials.CONTEXT,
    ),
    quick_add_rules=(
        QuickAddRule(20, "exam", lambda t: "high" if KW_EXAM.search(t.f) else None),
        QuickAddRule(30, "assignment", lambda t: "high" if KW_ASSIGNMENT.search(t.f) else None),
    ),
    quick_add_kinds=(
        QuickAddKind("exam", parse_school, _school_tool_call("exam"), _school_display("exam"),
                     context=quick_add_context, output=quick_add_output),
        QuickAddKind("assignment", parse_school, _school_tool_call("assignment"), _school_display("assignment"),
                     context=quick_add_context, output=quick_add_output),
    ),
    routers=materials.ROUTERS,  # MRK-42 /school/materials
)
