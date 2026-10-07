"""AI úpravy, mazání a dokončení existujících záznamů přes pending akce (Roadmap 3.0 Phase B).

Dvě fáze, obě deterministické (bez LLM):

1. `resolve_mutation` (při návrhu, uvnitř AI requestu): z popisu cíle (`target`) najde v DB přesně ty
   záznamy, kterých se změna týká, zvaliduje změny a vrátí *plán* – ověřená ID, snímek starých hodnot,
   nové hodnoty a náhled pro UI. Nejednoznačný / nenalezený cíl → `MutationRefused` (žádná pending akce,
   model se má doptat). Model tedy nikdy nevybírá ID naslepo: ID od modelu se jen ověří proti DB.
2. `apply_mutation_plan` (po potvrzení v UI, přes stávající `execute_confirm_action`): provede plán
   v JEDNÉ transakci. Každý cíl se znovu načte podle uloženého ID a porovná se snímkem – smazaný nebo
   mezitím změněný záznam = chyba a nic se neprovede (žádné částečné dávky). Potvrzení nikdy znovu
   nevyhledává cíl podle textu.

Plán se ukládá do stávajícího `PendingAction.arguments` jako `{"plan": {...}}` – bez migrace.
"""
from __future__ import annotations

import json as _json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import text as _sql_text
from sqlalchemy import update as _sql_update
from sqlalchemy.orm import Session

from activity_service import log_activity
from context_service import fold_text
from database import SessionLocal
from models import Assignment, Exam, FinanceTransaction, Goal, Memory, PendingAction, WorkSession, WotGrind
from statuses import ASSIGNMENT_DONE_STATUSES
from time_utils import to_local, utc_now
from text_utils import clip, finance_category_cz, format_num_cz

ACTION_UPDATE, ACTION_DELETE, ACTION_COMPLETE = "update", "delete", "complete"
MAX_BATCH = 20
MAX_CANDIDATES = 5
MAX_SCAN = 2000  # kolik nejnovějších řádků se prohledává textovým filtrem

_PRIORITIES = ("high", "medium", "low")
_ASSIGNMENT_DONE = ASSIGNMENT_DONE_STATUSES  # kanonické stavy: statuses.py


class MutationRefused(Exception):
    """Cíl nelze bezpečně určit / změna je neplatná → žádná pending akce, model se má doptat."""

    def __init__(self, code: str, detail: str, candidates: list[dict] | None = None):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.candidates = candidates or []

    def as_tool_result(self) -> dict:
        out = {"status": "not_prepared", "error": self.code, "detail": self.detail}
        if self.candidates:
            out["candidates"] = self.candidates
        return out


class StaleTarget(Exception):
    """Při potvrzení cíl neexistuje nebo se od návrhu změnil → nic se neprovede."""


# ===== formátování pro náhled / audit =====

def _num(value) -> str:
    if value is None:
        return "–"
    return format_num_cz(value, 2).replace("\u00a0", " ")


def _d(value) -> str:
    if value is None or value == "":
        return "–"
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(value, datetime):
        value = to_local(value).date()
    return f"{value.day}. {value.month}. {value.year}"


def _short(text, limit: int = 60) -> str:
    return clip(text, limit)


def _plain(value):
    """JSON-bezpečná hodnota pro snímek / plán (data jako ISO, čísla jako float)."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return str(value)


# ===== validace hodnot změn =====

def _v_str(required: bool = False, max_len: int = 1000):
    def parse(value):
        if value is None:
            if required:
                raise ValueError("nesmí být prázdné")
            return ""
        s = str(value).strip()
        if required and not s:
            raise ValueError("nesmí být prázdné")
        if len(s) > max_len:
            raise ValueError(f"max {max_len} znaků")
        return s
    return parse


def _v_num(min_value: float | None = None, *, strict_positive: bool = False, max_value: float | None = None):
    def parse(value):
        try:
            f = float(value)
        except (TypeError, ValueError):
            raise ValueError("musí být číslo") from None
        if strict_positive and f <= 0:
            raise ValueError("musí být kladné")
        if min_value is not None and f < min_value:
            raise ValueError(f"musí být ≥ {min_value:g}")
        if max_value is not None and f > max_value:
            raise ValueError(f"musí být ≤ {max_value:g}")
        return f
    return parse


def _v_int(min_value: int, max_value: int):
    def parse(value):
        try:
            f = float(value)
        except (TypeError, ValueError):
            raise ValueError("musí být celé číslo") from None
        if f != int(f):
            raise ValueError("musí být celé číslo")
        n = int(f)
        if not min_value <= n <= max_value:
            raise ValueError(f"musí být {min_value}–{max_value}")
        return n
    return parse


def _v_enum(*options: str):
    def parse(value):
        s = str(value or "").strip().lower()
        if s not in options:
            raise ValueError(f"povolené hodnoty: {', '.join(options)}")
        return s
    return parse


def _v_date(nullable: bool = True):
    def parse(value):
        if value in (None, ""):
            if nullable:
                return None
            raise ValueError("datum je povinné")
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            raise ValueError("datum musí být YYYY-MM-DD") from None
    return parse


@dataclass(frozen=True)
class FieldDef:
    attr: str  # sloupec modelu
    label: str  # česky pro náhled
    parse: Callable
    fmt: Callable = _short


@dataclass(frozen=True)
class EntityDef:
    name: str
    model: type
    area: str  # activity log oblast
    label: str  # „transakce", „úkol", …
    entity_type: str  # activity log entity_type
    fields: dict[str, FieldDef]  # klíč = název ve `changes` od modelu
    actions: frozenset[str]
    text_of: Callable[[Any], str]  # text pro hledání (bez diakritiky se porovnává až po fold)
    describe: Callable[[Any], str]
    date_of: Callable[[Any], date | None] | None = None
    type_of: Callable[[Any], str] | None = None
    order_key: Callable[[Any], tuple] = lambda o: (o.id,)
    base_filter: Callable[[Any], bool] = lambda o: True  # např. jen aktivní paměti
    batch_actions: frozenset[str] = frozenset()
    complete_changes: dict = field(default_factory=dict)
    is_completed: Callable[[Any], bool] = lambda o: False
    snapshot_attrs: tuple[str, ...] = ()


def _finance_desc(t: FinanceTransaction) -> str:
    sign = "+" if (t.transaction_type or "") == "income" else "−"
    desc = f" ({_short(t.description, 40)})" if t.description else ""
    return f"{sign}{_num(t.amount)} Kč {finance_category_cz(t.category)}{desc} · {_d(t.created_at)}"


def _work_desc(s: WorkSession) -> str:
    return f"{_d(s.date)} · {_num(s.hours)} h · {s.project or '–'} · {_num(s.hourly_rate)} Kč/h"


def _subject_name(obj) -> str:
    subject = getattr(obj, "subject", None)
    return subject.name if subject is not None else ""


def _assignment_desc(a: Assignment) -> str:
    subj = f" ({_subject_name(a)})" if _subject_name(a) else ""
    due = f" · termín {_d(a.due_date)}" if a.due_date else ""
    return f"{_short(a.title, 50)}{subj}{due} · {a.status or 'todo'}"


def _exam_desc(e: Exam) -> str:
    subj = f" ({_subject_name(e)})" if _subject_name(e) else ""
    return f"{_short(e.title, 50)}{subj} · {_d(e.exam_date)} · {e.status or '–'}"


def _goal_desc(g: Goal) -> str:
    return f"{_short(g.title, 50)} ({g.area}) · {g.status} · {int(g.progress or 0)} %"


def _grind_desc(g: WotGrind) -> str:
    return f"{g.tank} · {_num(g.xp_remaining)} XP · {g.status}"


def _memory_desc(m: Memory) -> str:
    return f"[{m.area}/{m.category}] {_short(m.content, 70)}"


def _fmt_money(v) -> str:
    return f"{_num(v)} Kč"


ENTITIES: dict[str, EntityDef] = {
    "finance_transaction": EntityDef(
        name="finance_transaction", model=FinanceTransaction, area="finance", label="transakce",
        entity_type="FinanceTransaction",
        fields={
            "amount": FieldDef("amount", "Částka", _v_num(strict_positive=True), _fmt_money),
            "category": FieldDef("category", "Kategorie", _v_str(required=True, max_len=100)),
            "description": FieldDef("description", "Popis", _v_str(max_len=255)),
            "transaction_type": FieldDef("transaction_type", "Typ", _v_enum("income", "expense")),
        },
        actions=frozenset({ACTION_UPDATE, ACTION_DELETE}),
        text_of=lambda t: f"{t.description or ''} {t.category or ''}",
        describe=_finance_desc,
        date_of=lambda t: to_local(t.created_at).date() if t.created_at else None,
        type_of=lambda t: t.transaction_type or "",
        order_key=lambda t: (t.created_at or datetime.min, t.id),
        snapshot_attrs=("amount", "category", "description", "transaction_type"),
    ),
    "work_session": EntityDef(
        name="work_session", model=WorkSession, area="work", label="pracovní záznam", entity_type="WorkSession",
        fields={
            "date": FieldDef("date", "Datum", _v_date(nullable=False), _d),
            "hours": FieldDef("hours", "Hodiny", _v_num(strict_positive=True, max_value=24), _num),
            "project": FieldDef("project", "Projekt", _v_str(max_len=150)),
            "hourly_rate": FieldDef("hourly_rate", "Sazba", _v_num(min_value=0), lambda v: f"{_num(v)} Kč/h"),
            "description": FieldDef("description", "Poznámka", _v_str(max_len=500)),
        },
        actions=frozenset({ACTION_UPDATE, ACTION_DELETE}),
        text_of=lambda s: f"{s.project or ''} {s.description or ''}",
        describe=_work_desc,
        date_of=lambda s: s.date,
        order_key=lambda s: (s.date or date.min, s.id),
        snapshot_attrs=("date", "hours", "project", "hourly_rate", "description", "finance_transaction_id"),
    ),
    "school_assignment": EntityDef(
        name="school_assignment", model=Assignment, area="school", label="úkol", entity_type="Assignment",
        fields={
            "title": FieldDef("title", "Název", _v_str(required=True, max_len=255)),
            "description": FieldDef("description", "Popis", _v_str(max_len=1000)),
            "due_date": FieldDef("due_date", "Termín", _v_date(), _d),
            "priority": FieldDef("priority", "Priorita", _v_enum(*_PRIORITIES)),
            "status": FieldDef("status", "Stav", _v_enum("todo", "in_progress", "done", "overdue")),
        },
        actions=frozenset({ACTION_UPDATE, ACTION_DELETE, ACTION_COMPLETE}),
        text_of=lambda a: f"{a.title or ''} {a.description or ''} {_subject_name(a)}",
        describe=_assignment_desc,
        date_of=lambda a: a.due_date,
        type_of=lambda a: a.status or "",
        batch_actions=frozenset({ACTION_COMPLETE}),
        complete_changes={"status": "done"},
        is_completed=lambda a: (a.status or "").strip().lower() in _ASSIGNMENT_DONE,
        snapshot_attrs=("title", "description", "due_date", "priority", "status", "subject_id"),
    ),
    "school_exam": EntityDef(
        name="school_exam", model=Exam, area="school", label="zkouška", entity_type="Exam",
        fields={
            "title": FieldDef("title", "Název", _v_str(required=True, max_len=255)),
            "exam_type": FieldDef("exam_type", "Typ", _v_enum("exam", "test", "quiz", "paper", "other")),
            "exam_date": FieldDef("exam_date", "Datum", _v_date(), _d),
            "status": FieldDef("status", "Stav", _v_enum("upcoming", "scheduled", "passed", "failed")),
            "notes": FieldDef("notes", "Poznámka", _v_str(max_len=1000)),
        },
        actions=frozenset({ACTION_UPDATE, ACTION_DELETE}),
        text_of=lambda e: f"{e.title or ''} {e.notes or ''} {_subject_name(e)}",
        describe=_exam_desc,
        date_of=lambda e: e.exam_date,
        type_of=lambda e: e.exam_type or "",
        snapshot_attrs=("title", "exam_type", "exam_date", "status", "notes", "subject_id"),
    ),
    "goal": EntityDef(
        name="goal", model=Goal, area="goals", label="cíl", entity_type="Goal",
        fields={
            "title": FieldDef("title", "Název", _v_str(required=True, max_len=255)),
            "description": FieldDef("description", "Popis", _v_str(max_len=2000)),
            "status": FieldDef("status", "Stav", _v_enum("active", "in_progress", "completed", "paused", "cancelled")),
            "priority": FieldDef("priority", "Priorita", _v_enum(*_PRIORITIES)),
            "progress": FieldDef("progress", "Progres", _v_int(0, 100), lambda v: f"{int(v or 0)} %"),
            "target_date": FieldDef("target_date", "Termín", _v_date(), _d),
        },
        actions=frozenset({ACTION_UPDATE, ACTION_DELETE, ACTION_COMPLETE}),
        text_of=lambda g: f"{g.title or ''} {g.description or ''}",
        describe=_goal_desc,
        date_of=lambda g: g.target_date,
        type_of=lambda g: g.area or "",
        complete_changes={"status": "completed"},
        is_completed=lambda g: (g.status or "").lower() == "completed",
        snapshot_attrs=("area", "title", "description", "status", "priority", "progress", "target_date",
                        "tracking_type"),
    ),
    "wot_grind": EntityDef(
        name="wot_grind", model=WotGrind, area="wot", label="WoT grind", entity_type="WotGrind",
        fields={
            "xp_remaining": FieldDef("xp_remaining", "Zbývá XP", _v_num(min_value=0), _num),
            "priority": FieldDef("priority", "Priorita", _v_enum(*_PRIORITIES)),
            "status": FieldDef("status", "Stav", _v_enum("active", "paused", "completed", "planned")),
        },
        actions=frozenset({ACTION_UPDATE, ACTION_DELETE}),
        text_of=lambda g: g.tank or "",
        describe=_grind_desc,
        type_of=lambda g: g.status or "",
        snapshot_attrs=("tank", "xp_remaining", "priority", "status"),
    ),
    "memory": EntityDef(
        name="memory", model=Memory, area="memory", label="paměť", entity_type="Memory",
        fields={
            "content": FieldDef("content", "Obsah", _v_str(required=True, max_len=2000), lambda v: _short(v, 80)),
            "importance": FieldDef("importance", "Důležitost", _v_int(1, 10), lambda v: f"{int(v or 0)}/10"),
            "category": FieldDef("category", "Kategorie", _v_enum(
                "preference", "decision", "context", "routine", "constraint", "plan")),
            "area": FieldDef("area", "Oblast", _v_str(required=True, max_len=50)),
        },
        actions=frozenset({ACTION_UPDATE, ACTION_DELETE}),
        text_of=lambda m: m.content or "",
        describe=_memory_desc,
        type_of=lambda m: m.area or "",
        order_key=lambda m: (m.updated_at or m.created_at or datetime.min, m.id),
        base_filter=lambda m: bool(m.active),
        snapshot_attrs=("area", "category", "content", "importance", "active"),
    ),
}

_ACTION_TITLES = {
    ACTION_UPDATE: "Upravit",
    ACTION_DELETE: "Smazat",
    ACTION_COMPLETE: "Označit jako hotové",
}


# ===== 1) návrh: vyhledání cíle a sestavení plánu =====

def _snapshot(entity: EntityDef, obj) -> dict:
    return {attr: _plain(getattr(obj, attr, None)) for attr in entity.snapshot_attrs}


def _parse_target_date(value, name: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise MutationRefused("invalid_target", f"target.{name} musí být datum YYYY-MM-DD") from None


def _matches(entity: EntityDef, obj, words: list[str], day, d_from, d_to, type_value: str) -> bool:
    if not entity.base_filter(obj):
        return False
    if words:
        hay = fold_text(entity.text_of(obj))
        if not all(w in hay for w in words):
            return False
    if day or d_from or d_to:
        d = entity.date_of(obj) if entity.date_of else None
        if d is None or (day and d != day) or (d_from and d < d_from) or (d_to and d > d_to):
            return False
    if type_value:
        if entity.type_of is None or fold_text(entity.type_of(obj)).strip() != type_value:
            return False
    return True


def _candidate(entity: EntityDef, obj) -> dict:
    return {"id": obj.id, "label": entity.describe(obj)}


def _find_targets(db: Session, entity: EntityDef, action: str, target: dict) -> list:
    if not isinstance(target, dict):
        raise MutationRefused("invalid_target", "target musí být objekt s popisem záznamu")
    words = [w for w in fold_text(str(target.get("text") or "")).split() if len(w) >= 2]
    day = _parse_target_date(target.get("date"), "date")
    d_from = _parse_target_date(target.get("date_from"), "date_from")
    d_to = _parse_target_date(target.get("date_to"), "date_to")
    if (day or d_from or d_to) and entity.date_of is None:
        raise MutationRefused("invalid_target", f"{entity.label}: nelze filtrovat podle data")
    type_value = fold_text(str(target.get("type") or "")).strip()
    latest = bool(target.get("latest"))
    all_matching = bool(target.get("all_matching"))
    raw_id = target.get("id")
    has_filter = bool(words or day or d_from or d_to or type_value)

    if raw_id not in (None, ""):
        try:
            target_id = int(raw_id)
        except (TypeError, ValueError):
            raise MutationRefused("invalid_target", "target.id musí být celé číslo z výsledku nástroje") from None
        obj = db.get(entity.model, target_id)
        if obj is None or not entity.base_filter(obj):
            raise MutationRefused("target_not_found", f"{entity.label} s id {target_id} neexistuje")
        if has_filter and not _matches(entity, obj, words, day, d_from, d_to, type_value):
            raise MutationRefused(
                "id_mismatch",
                f"{entity.label} s id {target_id} neodpovídá popisu cíle – ověř u uživatele, který záznam myslí",
                [_candidate(entity, obj)],
            )
        return [obj]

    if not has_filter:
        raise MutationRefused(
            "ambiguous_target",
            "Cíl není popsán (chybí text, datum nebo typ). Zeptej se uživatele, který záznam myslí.",
        )

    rows = db.query(entity.model).order_by(entity.model.id.desc()).limit(MAX_SCAN).all()
    found = [o for o in rows if _matches(entity, o, words, day, d_from, d_to, type_value)]
    if action == ACTION_COMPLETE:
        found = [o for o in found if not entity.is_completed(o)]
    found.sort(key=entity.order_key, reverse=True)

    if not found:
        raise MutationRefused("target_not_found", f"Žádný {entity.label} neodpovídá popisu. Zeptej se uživatele.")
    if len(found) == 1:
        return found
    if all_matching:
        if action not in entity.batch_actions:
            raise MutationRefused(
                "batch_not_supported",
                f"Hromadnou akci '{action}' pro {entity.label} nepodporuji. Vyber jeden záznam.",
                [_candidate(entity, o) for o in found[:MAX_CANDIDATES]],
            )
        if len(found) > MAX_BATCH:
            raise MutationRefused(
                "too_many_targets",
                f"Popisu odpovídá {len(found)} záznamů (max {MAX_BATCH} najednou). Zužte výběr.",
            )
        return found
    if latest:
        return found[:1]
    raise MutationRefused(
        "ambiguous_target",
        f"Popisu odpovídá {len(found)} záznamů. Zeptej se uživatele, který myslí (nebo zda všechny).",
        [_candidate(entity, o) for o in found[:MAX_CANDIDATES]],
    )


def _parse_changes(entity: EntityDef, action: str, changes) -> dict:
    if action != ACTION_UPDATE:
        return dict(entity.complete_changes) if action == ACTION_COMPLETE else {}
    if not isinstance(changes, dict) or not changes:
        raise MutationRefused("invalid_changes", "Úprava potřebuje changes s novými hodnotami.")
    unknown = [k for k in changes if k not in entity.fields]
    if unknown:
        raise MutationRefused(
            "invalid_changes",
            f"{entity.label}: neznámá pole {unknown}; povolená: {sorted(entity.fields)}",
        )
    parsed = {}
    for key, value in changes.items():
        try:
            parsed[key] = entity.fields[key].parse(value)
        except ValueError as exc:
            raise MutationRefused("invalid_changes", f"{entity.fields[key].label}: {exc}") from None
    return parsed


def _item_changes(entity: EntityDef, obj, changes: dict) -> list[dict]:
    out = []
    for key, new in changes.items():
        fd = entity.fields.get(key)
        attr = fd.attr if fd else key
        old = getattr(obj, attr, None)
        if _plain(old) == _plain(new) or (old in (None, "") and new in (None, "")):
            continue
        fmt = fd.fmt if fd else _short
        label = fd.label if fd else key
        out.append({"field": key, "label": label, "old": fmt(old), "new": fmt(new)})
    return out


def _warnings(entity: EntityDef, action: str, objs: list, changes: dict) -> list[str]:
    notes: list[str] = []
    if entity.name == "work_session":
        for s in objs:
            if s.finance_transaction_id is None:
                continue
            if action == ACTION_DELETE:
                notes.append("Navázaný příjem ve financích zůstane (stejně jako při mazání v aplikaci).")
            elif {"hours", "hourly_rate"} & set(changes):
                hours = changes.get("hours", s.hours)
                rate = changes.get("hourly_rate", s.hourly_rate)
                notes.append(f"Navázaný příjem ve financích se změní na {_num(round(hours * rate, 2))} Kč.")
    if entity.name == "goal" and "progress" in changes:
        if any((g.tracking_type or "manual").lower() != "manual" for g in objs):
            raise MutationRefused("invalid_changes", "Automatický cíl má progres počítaný z dat – nelze ho nastavit.")
    if entity.name == "goal" and action == ACTION_COMPLETE:
        if any((g.tracking_type or "manual").lower() == "manual" and int(g.progress or 0) < 100 for g in objs):
            notes.append("Progres ručního cíle se nastaví na 100 %.")
    if entity.name == "memory" and action == ACTION_DELETE:
        notes.append("Paměť se deaktivuje (jako v aplikaci), obsah zůstane uložen.")
    return notes


def resolve_mutation(db: Session, entity: str, action: str, target: dict, changes: dict | None = None) -> dict:
    """Návrh změny → deterministický plán pro pending akci. Jen čte DB."""
    ent = ENTITIES.get(str(entity or "").strip())
    if ent is None:
        raise MutationRefused("unsupported_entity", f"Podporované entity: {sorted(ENTITIES)}")
    action = str(action or "").strip().lower()
    if action not in ent.actions:
        raise MutationRefused(
            "unsupported_action", f"{ent.label}: podporované akce {sorted(ent.actions)}",
        )
    if action != ACTION_UPDATE and changes:
        # Mazání/dokončení nemá nové hodnoty – nejasný záměr se raději nevykoná.
        raise MutationRefused("invalid_changes", f"Akce '{action}' nepřijímá changes; pro úpravu použij update.")

    parsed = _parse_changes(ent, action, changes)
    if (
        action == ACTION_UPDATE
        and ACTION_COMPLETE in ent.actions
        and ent.name != "goal"  # dokončení cíle navíc nastaví progres 100 % → není to stejná změna
        and parsed == dict(ent.complete_changes)
    ):
        # „Označ jako hotové" posílá model často jako update {status: done} – je to přesně dokončení
        # (stejná DB změna), takže platí jeho pravidla: dávka, přeskočení už hotových, náhled „Dokončit".
        action = ACTION_COMPLETE
    objs = _find_targets(db, ent, action, target or {})

    items = []
    for obj in objs:
        diff = _item_changes(ent, obj, parsed) if action != ACTION_DELETE else []
        if action != ACTION_DELETE and not diff:
            continue
        items.append((obj, diff))
    if not items:
        raise MutationRefused("no_change", "Záznam už má požadované hodnoty – není co měnit.")
    warnings = _warnings(ent, action, [o for o, _ in items], parsed)

    count = len(items)
    noun = ent.label if count == 1 else f"{count}× {ent.label}"
    preview = {
        "kind": action,
        "entity": ent.name,
        "title": f"{_ACTION_TITLES[action]}: {noun}",
        "count": count,
        "items": [{"id": o.id, "label": ent.describe(o), "changes": diff} for o, diff in items],
        "warnings": warnings,
    }
    return {
        "version": 1,
        "entity": ent.name,
        "action": action,
        "targets": [{"id": o.id, "snapshot": _snapshot(ent, o)} for o, _ in items],
        "changes": {k: _plain(v) for k, v in parsed.items()},
        "preview": preview,
    }


# ===== 2) potvrzení: atomické provedení plánu =====

def _coerce(entity: EntityDef, key: str, value):
    """Hodnota z JSON plánu → typ sloupce (data zpět na date)."""
    fd = entity.fields[key]
    return fd.parse(value) if value is not None else None


def _refresh_auto_goals(db: Session, sources: set[str], user_context: str) -> None:
    from goal_history_service import compute_goal_progress_and_value, ensure_goal_progress_snapshot

    goals = (
        db.query(Goal)
        .filter((Goal.tracking_type == "automatic") | (Goal.tracking_type == "Automatic"))
        .filter(Goal.source.in_(sorted(sources)))
        .all()
    )
    changed = False
    for g in goals:
        before, _ = compute_goal_progress_and_value(db, g)
        if ensure_goal_progress_snapshot(db, g):
            after, _ = compute_goal_progress_and_value(db, g)
            if before != after:
                log_activity(db, "goals", "snapshot", f"Cíl '{g.title}' {before}% → {after}%",
                             entity_type="Goal", entity_id=g.id, user_context=user_context)
            changed = True
    if changed:
        db.commit()


def _row_dump(obj) -> dict:
    """Všechny sloupce řádku (JSON-bezpečně) – pro obnovu smazaného záznamu při undo (Phase C)."""
    return {col.key: _plain(getattr(obj, col.key)) for col in obj.__mapper__.column_attrs}


# Roadmap 4H: změna / vrácení z ručního povrchu (ne AI) – původ v textu Aktivity.
_MANUAL_ORIGIN = {"today": "Dnes"}


def _origin(user_context: str) -> str:
    return _MANUAL_ORIGIN.get(user_context, "AI")


def _apply_one(db: Session, ent: EntityDef, action: str, obj, changes: dict, user_context: str) -> dict:
    """Provede jednu položku plánu. Vrací vedlejší efekty potřebné pro undo (Phase C)."""
    effects: dict = {}
    label = ent.describe(obj)
    old_values = {k: _plain(getattr(obj, ent.fields[k].attr)) for k in changes if k in ent.fields}

    if action == ACTION_DELETE:
        delta = {attr: {"old": _plain(getattr(obj, attr, None)), "new": None} for attr in ent.snapshot_attrs}
        if ent.name != "memory":
            effects["row"] = _row_dump(obj)
        if ent.name == "finance_transaction":
            effects["unlinked_work_sessions"] = [
                sid for (sid,) in db.query(WorkSession.id).filter(WorkSession.finance_transaction_id == obj.id).all()
            ]
            db.execute(
                _sql_text("UPDATE work_sessions SET finance_transaction_id = NULL WHERE finance_transaction_id = :tid"),
                {"tid": obj.id},
            )
        if ent.name == "memory":
            obj.active = False  # soft delete jako DELETE /memory/{id}
            delta = {"active": {"old": True, "new": False}}
        log_activity(db, ent.area, "delete", _short(f"Smazáno ({_origin(user_context)}): {label}", 480),
                     entity_type=ent.entity_type, entity_id=obj.id, delta=delta, user_context=user_context)
        if ent.name == "wot_grind":
            from wot_service import detach_completions
            detach_completions(db, obj.id)  # historie splnění zůstává (Game Enrichment B)
        if ent.name != "memory":
            db.delete(obj)
        return effects

    for key, value in changes.items():
        setattr(obj, ent.fields[key].attr, _coerce(ent, key, value))
    if ent.name == "goal" and action == ACTION_COMPLETE and (obj.tracking_type or "manual").lower() == "manual":
        old_values.setdefault("progress", _plain(obj.progress))
        obj.progress = 100
        changes = {**changes, "progress": 100}
    if ent.name == "work_session" and {"hours", "hourly_rate"} & set(changes) and obj.finance_transaction_id:
        tx = db.get(FinanceTransaction, obj.finance_transaction_id)
        if tx is not None:
            new_amount = round(float(obj.hours) * float(obj.hourly_rate), 2)
            if float(tx.amount or 0) != new_amount:
                log_activity(db, "finance", "update",
                             _short(f"Příjem z práce upraven ({_origin(user_context)}): {_num(tx.amount)} → {_num(new_amount)} Kč", 480),
                             entity_type="FinanceTransaction", entity_id=tx.id,
                             delta={"amount": {"old": float(tx.amount or 0), "new": new_amount}},
                             user_context=user_context)
                effects["linked_income"] = {"id": tx.id, "before": float(tx.amount or 0), "after": new_amount}
                tx.amount = new_amount
    delta = {k: {"old": old_values.get(k), "new": _plain(v)} for k, v in changes.items()}
    verb = "Dokončeno" if action == ACTION_COMPLETE else "Upraveno"
    log_activity(db, ent.area, "complete" if action == ACTION_COMPLETE else "update",
                 _short(f"{verb} ({_origin(user_context)}): {label}", 480),
                 entity_type=ent.entity_type, entity_id=obj.id, delta=delta, user_context=user_context)
    return effects


def apply_mutation_plan(plan: dict, user_context: str = "manual") -> dict:
    """Provede potvrzený plán v jedné transakci; stale/smazaný cíl → StaleTarget a nic se nezmění."""
    if not isinstance(plan, dict) or plan.get("version") != 1:
        raise ValueError("Neplatný plán pending akce")
    ent = ENTITIES.get(plan.get("entity"))
    action = plan.get("action")
    if ent is None or action not in ent.actions:
        raise ValueError("Plán obsahuje nepodporovanou entitu nebo akci")
    targets = plan.get("targets") or []
    if not targets or len(targets) > MAX_BATCH:
        raise ValueError("Plán nemá platný počet cílů")
    changes = dict(plan.get("changes") or {})
    if any(k not in ent.fields for k in changes):
        raise ValueError("Plán obsahuje neznámé pole")

    db = SessionLocal()
    try:
        objs = []
        for t in targets:
            obj = db.get(ent.model, int(t["id"]))
            if obj is None:
                raise StaleTarget(f"{ent.label} (id {t['id']}) mezitím zmizel – nic jsem nezměnil.")
            if _snapshot(ent, obj) != t.get("snapshot"):
                raise StaleTarget(f"{ent.label} (id {t['id']}) se od návrhu změnil – nic jsem nezměnil.")
            objs.append(obj)
        undo_items = []
        for t, obj in zip(targets, objs):
            label = ent.describe(obj)  # před provedením – smazaný řádek už popsat nejde
            effects = _apply_one(db, ent, action, obj, changes, user_context)
            item = {"id": int(t["id"]), "label": label, "before": t.get("snapshot"), **effects}
            if action != ACTION_DELETE or ent.name == "memory":
                db.flush()
                item["after"] = _snapshot(ent, obj)
            undo_items.append(item)
        undo = build_undo_record(plan, ent, action, undo_items)
        db.commit()
        if ent.name in ("finance_transaction", "work_session"):
            try:
                _refresh_auto_goals(db, {"finance_balance", "work_month_hours"}, user_context)
            except Exception as exc:  # noqa: BLE001 - změna je už uložená; snímek cíle se dopočítá později
                db.rollback()
                print(f"[mutation] goal snapshot refresh selhal ({type(exc).__name__})")
        return {"entity": ent.name, "action": action, "count": len(objs), "ids": [t["id"] for t in targets],
                "undo": undo}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ===== Phase C: undo potvrzené změny =====
#
# Při provedení plánu se do původní pending akce uloží undo záznam (arguments["undo"]): snímek PŘED
# (z plánu) a PO změně, u smazání celý řádek a navázané vazby. Undo je zase pending akce (tool
# undo_change) se stejným potvrzením. Při provedení: podmíněný UPDATE původní akce executed → undone
# (nejvýš jednou) + obnovení všech položek v JEDNÉ transakci; aktuální stav musí přesně odpovídat
# snímku PO, jinak se nic nezmění. Model nikdy nerekonstruuje staré hodnoty.

UNDO_WINDOW_HOURS = 24
UNDO_STATUS = "undone"
UNDO_SUPPORTED = frozenset({
    ("finance_transaction", ACTION_UPDATE), ("finance_transaction", ACTION_DELETE),
    ("work_session", ACTION_UPDATE), ("work_session", ACTION_DELETE),
    ("school_assignment", ACTION_UPDATE), ("school_assignment", ACTION_DELETE),
    ("school_assignment", ACTION_COMPLETE),
    ("school_exam", ACTION_UPDATE), ("school_exam", ACTION_DELETE),
    ("goal", ACTION_UPDATE), ("goal", ACTION_COMPLETE),
    ("wot_grind", ACTION_UPDATE), ("wot_grind", ACTION_DELETE),
    ("memory", ACTION_UPDATE), ("memory", ACTION_DELETE),
})
UNDO_UNSUPPORTED_REASONS = {
    ("goal", ACTION_DELETE): "smazání cíle smaže i jeho historii progresu, tu nelze obnovit",
}
UNDO_AREAS = tuple(sorted({e.area for e in ENTITIES.values()}))


def build_undo_record(plan: dict, ent: EntityDef, action: str, items: list[dict]) -> dict:
    supported = (ent.name, action) in UNDO_SUPPORTED
    rec = {
        "version": 1,
        "executed_at": utc_now().isoformat(),
        "entity": ent.name,
        "action": action,
        "title": (plan.get("preview") or {}).get("title") or f"{_ACTION_TITLES[action]}: {ent.label}",
        "supported": supported,
    }
    if supported:
        rec["items"] = items
    else:
        rec["reason"] = UNDO_UNSUPPORTED_REASONS.get((ent.name, action), "tuto změnu nelze vrátit")
    return rec


def _coerce_column(model, attr: str, value):
    """Hodnota ze snímku (JSON) → typ sloupce modelu."""
    if value is None:
        return None
    col = model.__table__.columns[attr]
    try:
        py = col.type.python_type
    except NotImplementedError:
        return value
    if py is datetime:
        return datetime.fromisoformat(value) if isinstance(value, str) else value
    if py is date:
        return date.fromisoformat(value[:10]) if isinstance(value, str) else value
    if py is bool:
        return bool(value)
    if py is int:
        return int(value)
    if py is float:
        return float(value)
    return str(value) if py is str else value


def _undo_item(db: Session, ent: EntityDef, action: str, item: dict, *, apply: bool) -> list[dict]:
    """Ověří, že položku lze vrátit (aktuální stav = stav po změně), a při apply ji obnoví.

    Vrací seznam změn pro náhled/audit [{label, old (teď), new (po vrácení)}]. Nesoulad → StaleTarget.
    """
    model = ent.model
    obj = db.get(model, int(item["id"]))
    hard_delete = action == ACTION_DELETE and ent.name != "memory"
    if hard_delete:
        if obj is not None:
            raise StaleTarget(f"{ent.label} (id {item['id']}) už existuje – obnovení by ho přepsalo.")
        row = item.get("row") or {}
        if ent.name == "work_session" and row.get("finance_transaction_id") is not None:
            if db.get(FinanceTransaction, int(row["finance_transaction_id"])) is None:
                raise StaleTarget("Navázaný příjem pracovního záznamu mezitím zmizel.")
        if ent.name in ("school_assignment", "school_exam") and row.get("subject_id") is not None:
            from models import Subject
            if db.get(Subject, int(row["subject_id"])) is None:
                raise StaleTarget("Předmět záznamu mezitím zmizel.")
        if ent.name == "wot_grind" and db.query(WotGrind).filter(WotGrind.tank == row.get("tank")).first():
            raise StaleTarget(f"Grind '{row.get('tank')}' mezitím vznikl znovu.")
        sessions = []
        for sid in item.get("unlinked_work_sessions") or []:
            sess = db.get(WorkSession, int(sid))
            if sess is None or sess.finance_transaction_id is not None:
                raise StaleTarget("Pracovní záznam navázaný na transakci se mezitím změnil.")
            sessions.append(sess)
        if apply:
            restored = model(**{k: _coerce_column(model, k, v) for k, v in row.items()})
            db.add(restored)
            db.flush()
            for sess in sessions:
                sess.finance_transaction_id = restored.id
        return [{"label": "Záznam", "old": "smazán", "new": "obnoven"}]

    if obj is None:
        raise StaleTarget(f"{ent.label} (id {item['id']}) mezitím zmizel – nic jsem nevrátil.")
    if _snapshot(ent, obj) != item.get("after"):
        raise StaleTarget(f"{ent.label} (id {item['id']}) se od změny upravil – nic jsem nevrátil.")
    linked = item.get("linked_income")
    tx = None
    if linked:
        tx = db.get(FinanceTransaction, int(linked["id"]))
        if tx is None or float(tx.amount or 0) != float(linked["after"]):
            raise StaleTarget("Navázaný příjem z práce se mezitím změnil – nic jsem nevrátil.")
    before, after = item.get("before") or {}, item.get("after") or {}
    labels = {fd.attr: fd for fd in ent.fields.values()}
    diff = []
    for attr in ent.snapshot_attrs:
        if before.get(attr) == after.get(attr):
            continue
        fd = labels.get(attr)
        cur = getattr(obj, attr, None)
        old_val = _coerce_column(model, attr, before.get(attr))
        diff.append({"label": fd.label if fd else ("Aktivní" if attr == "active" else attr),
                     "old": (fd.fmt if fd else _short)(cur), "new": (fd.fmt if fd else _short)(old_val)})
        if apply:
            setattr(obj, attr, old_val)
    if linked:
        diff.append({"label": "Příjem z práce", "old": _fmt_money(linked["after"]), "new": _fmt_money(linked["before"])})
        if apply:
            tx.amount = float(linked["before"])
    return diff


def _undo_record_of(pa: PendingAction) -> dict | None:
    try:
        args = _json.loads(pa.arguments) if pa.arguments else {}
    except ValueError:
        return None
    rec = args.get("undo") if isinstance(args, dict) else None
    return rec if isinstance(rec, dict) and rec.get("version") == 1 else None


def _within_window(rec: dict, now: datetime) -> bool:
    try:
        executed = datetime.fromisoformat(rec["executed_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return now - executed <= timedelta(hours=UNDO_WINDOW_HOURS)


def _undo_candidates(db: Session, area: str | None) -> list[tuple[PendingAction, dict]]:
    now = utc_now()
    since = now - timedelta(hours=UNDO_WINDOW_HOURS + 1)
    rows = (
        db.query(PendingAction)
        .filter(PendingAction.tool == "modify_records", PendingAction.status == "executed",
                PendingAction.created_at >= since)
        .order_by(PendingAction.id.desc())
        .limit(50)
        .all()
    )
    out = []
    for pa in rows:
        rec = _undo_record_of(pa)
        if not rec or not rec.get("supported") or not _within_window(rec, now):
            continue
        ent = ENTITIES.get(rec.get("entity"))
        if ent is None or (area and ent.area != area):
            continue
        out.append((pa, rec))
    out.sort(key=lambda pr: (pr[1]["executed_at"], pr[0].id), reverse=True)
    return out


def _undo_candidate(pa: PendingAction, rec: dict) -> dict:
    return {"action_id": str(pa.id), "label": rec.get("title"), "executed_at": rec.get("executed_at")}


def resolve_undo(db: Session, action_id=None, area: str | None = None, latest: bool = False) -> dict:
    """Najde přesně jednu vratnou provedenou změnu a sestaví undo plán. Jen čte DB."""
    area = (str(area).strip().lower() or None) if area else None
    if area and area not in UNDO_AREAS:
        raise MutationRefused("invalid_target", f"Oblast musí být jedna z {list(UNDO_AREAS)}")
    if action_id not in (None, ""):
        try:
            pid = int(action_id)
        except (TypeError, ValueError):
            raise MutationRefused("invalid_target", "action_id musí být id provedené akce") from None
        pa = db.get(PendingAction, pid)
        if pa is None or pa.tool != "modify_records":
            raise MutationRefused("target_not_found", "Taková provedená AI změna neexistuje.")
        if pa.status == UNDO_STATUS:
            raise MutationRefused("already_undone", "Tahle změna už byla vrácena.")
        if pa.status != "executed":
            raise MutationRefused("not_executed", "Změna nebyla provedena, není co vracet.")
        rec = _undo_record_of(pa)
        if not rec:
            raise MutationRefused("unsupported", "U této změny nejsou uložená data pro vrácení.")
        if not rec.get("supported"):
            raise MutationRefused("unsupported", f"Tuto změnu nelze vrátit: {rec.get('reason')}.")
        if not _within_window(rec, utc_now()):
            raise MutationRefused("expired", f"Vrátit jde jen změny z posledních {UNDO_WINDOW_HOURS} h.")
    else:
        candidates = _undo_candidates(db, area)
        if not candidates:
            raise MutationRefused("target_not_found", "Nenašel jsem žádnou nedávnou AI změnu, kterou jde vrátit.")
        if len(candidates) > 1 and not latest:
            raise MutationRefused(
                "ambiguous_target",
                f"Vratných změn je {len(candidates)}. Zeptej se uživatele, kterou vrátit (nebo poslední).",
                [_undo_candidate(pa, rec) for pa, rec in candidates[:MAX_CANDIDATES]],
            )
        pa, rec = candidates[0]

    ent = ENTITIES[rec["entity"]]
    items = []
    try:
        for item in rec.get("items") or []:
            items.append({"id": item["id"], "label": item.get("label"),
                          "changes": _undo_item(db, ent, rec["action"], item, apply=False)})
    except StaleTarget as exc:
        raise MutationRefused("stale_target", str(exc)) from None
    if not items:
        raise MutationRefused("unsupported", "Změna nemá žádné položky k vrácení.")
    warnings = ["Smazané záznamy se obnoví včetně původního id."] if rec["action"] == ACTION_DELETE \
        and ent.name != "memory" else []
    return {
        "version": 1,
        "kind": "undo",
        "original_action_id": pa.id,
        "entity": ent.name,
        "action": rec["action"],
        "preview": {
            "kind": "undo",
            "entity": ent.name,
            "title": _short(f"Vrátit: {rec.get('title')}", 120),
            "count": len(items),
            "items": items,
            "warnings": warnings,
        },
    }


def apply_undo_plan(plan: dict, user_context: str = "manual") -> dict:
    """Provede potvrzené undo: nejvýš jednou, atomicky, jen pokud nic nezastaralo."""
    if not isinstance(plan, dict) or plan.get("version") != 1 or plan.get("kind") != "undo":
        raise ValueError("Neplatný undo plán")
    try:
        original_id = int(plan["original_action_id"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Undo plán nemá platné original_action_id") from None

    db = SessionLocal()
    try:
        pa = db.get(PendingAction, original_id)
        if pa is None or pa.tool != "modify_records":
            raise StaleTarget("Původní akce neexistuje.")
        rec = _undo_record_of(pa)
        if not rec or not rec.get("supported"):
            raise StaleTarget("Původní akci nelze vrátit.")
        if rec.get("entity") != plan.get("entity") or rec.get("action") != plan.get("action"):
            raise StaleTarget("Undo plán neodpovídá původní akci.")
        if not _within_window(rec, utc_now()):
            raise StaleTarget(f"Vrátit jde jen změny z posledních {UNDO_WINDOW_HOURS} h.")
        # Nejvýš jednou: přepnout executed → undone podmíněně, ve stejné transakci jako obnovení.
        flipped = db.execute(
            _sql_update(PendingAction)
            .where(PendingAction.id == original_id, PendingAction.status == "executed")
            .values(status=UNDO_STATUS)
        )
        if flipped.rowcount != 1:
            raise StaleTarget("Tahle změna už byla vrácena (nebo není provedená).")

        ent = ENTITIES[rec["entity"]]
        ids = []
        for item in rec.get("items") or []:
            diff = _undo_item(db, ent, rec["action"], item, apply=True)
            ids.append(int(item["id"]))
            log_activity(
                db, ent.area, "undo", _short(f"Vráceno ({_origin(user_context)}): {item.get('label') or ent.label}", 480),
                entity_type=ent.entity_type, entity_id=int(item["id"]),
                delta={"undo_of_action": original_id, "restored": diff}, user_context=user_context,
                dedupe_key=f"undo:{original_id}:{item['id']}",
            )
        if user_context not in _MANUAL_ORIGIN:  # vrácení ruční akce (Dnes) není akce AI → bez záznamu v oblasti AI
            log_activity(
                db, "ai", "undo", _short(f"Vrácena AI akce #{original_id}: {rec.get('title')}", 480),
                entity_type="PendingAction", entity_id=original_id,
                delta={"undo_of_action": original_id, "entity": ent.name, "action": rec["action"], "ids": ids},
                user_context=user_context, dedupe_key=f"undo:{original_id}",
            )
        args = _json.loads(pa.arguments) if pa.arguments else {}
        args["undo"] = {**rec, "undone_at": utc_now().isoformat()}
        pa.arguments = _json.dumps(args, ensure_ascii=False, default=str)
        db.commit()
        if ent.name in ("finance_transaction", "work_session"):
            try:
                _refresh_auto_goals(db, {"finance_balance", "work_month_hours"}, user_context)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                print(f"[undo] goal snapshot refresh selhal ({type(exc).__name__})")
        return {"undone_action_id": original_id, "entity": ent.name, "action": rec["action"],
                "count": len(ids), "ids": ids}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def propose_undo(db: Session, area: str | None = None, action_id: str | None = None, latest: bool = False) -> dict:
    """Resolver AI toolu undo_change."""
    return resolve_undo(db, action_id=action_id, area=area, latest=latest)


def execute_undo(plan: dict, user_context: str = "manual") -> dict:
    """Executor potvrzené undo pending akce."""
    return apply_undo_plan(plan, user_context=user_context)


# ===== vstupy pro tool registry (modify_records) =====

def propose_modify_records(db: Session, entity: str, action: str, target: dict, changes: dict | None = None) -> dict:
    """Resolver AI toolu modify_records: plán pro pending akci, nebo MutationRefused."""
    return resolve_mutation(db, entity, action, target, changes)


def execute_modify_records(plan: dict, user_context: str = "manual") -> dict:
    """Executor po potvrzení pending akce (volá ho execute_confirm_action s uloženým plánem)."""
    return apply_mutation_plan(plan, user_context=user_context)
