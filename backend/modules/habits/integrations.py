"""Příspěvky Návyků do globálních agregátorů (MRK-21) – vyhledávání, Dnes, GET /dashboard, AI kontext a REST.

Žádný agregátor o Návycích neví: vše jde přes `ModuleDef.integrations` (module_registry.py). Rychlé přidání
zatím ne (formulář Rychlého přidání na frontendu ještě není v manifestu modulu – viz docs/habits.md).
"""
from __future__ import annotations

from context_format import list_or_none, short
from module_contracts import (
    ChangeSource, activity_changes, event_changes,
    ContextRequest, ContextSection, DashboardSection, EntityRef, ModuleIntegrations, SearchSource, TodaySource,
)
from modules.habits import service
from modules.habits.models import Habit, HabitEntry
from modules.habits.router import router
from text_utils import format_num_cz, join_parts
from today_types import TodayItem

ROW_LIMIT = 500

# ---------- vyhledávání ----------


def search_habits(db, q):
    for h in db.query(Habit).order_by(Habit.name).limit(ROW_LIMIT).all():
        sub = join_parts("Návyk", f"cíl {service.target_label(h)}" if service.target_label(h) else "",
                         "" if h.active else "archivovaný")
        yield "habit", h.id, h.name, sub, "navyk habit rutina", "habits", f"/habits?habit={h.id}"


# ---------- Dnes ----------


def _today_entries(c) -> dict[int, HabitEntry]:
    return {e.habit_id: e for e in c.db.query(HabitEntry).filter(HabitEntry.date == c.today).all()}


def _measure(entry: HabitEntry, h: Habit) -> str:
    if entry.duration_minutes is not None:
        return f"{entry.duration_minutes} min"
    if entry.value is not None:
        return f"{format_num_cz(entry.value)} {h.unit or ''}".strip()
    return ""


def today_habits(c) -> list[TodayItem]:
    entries = _today_entries(c)
    items = []
    for h in service.active_habits(c.db):
        e = entries.get(h.id)
        state = service.day_state(h, c.today, e, c.today)
        if state is None:
            continue
        target = f"cíl {service.target_label(h)}" if service.target_label(h) else ""
        if e is None:
            subtitle, status, actions = join_parts("Návyk", target), "open", ["complete", "skip"]
        else:
            subtitle = join_parts("Návyk", service.STATE_LABELS[e.state], _measure(e, h))
            status, actions = "done", []
        items.append(TodayItem(
            id=f"habit:{h.id}", type="habit", title=h.name, subtitle=subtitle, area="habits",
            date=c.today.isoformat(), status=status, href=f"/habits?habit={h.id}", source_id=h.id, actions=actions,
        ))
    return items


# ---------- AI kontext ----------


def context_habits(req: ContextRequest) -> list[str]:
    data = service.list_habits(req.db, req.today, include_archived=False)
    today_items = [f"{short(h['name'], 30)} {service.STATE_LABELS[h['today']['state']]}" for h in data["active"]
                   if h["today"]["state"]]
    s = data["summary"]
    week = f"; posledních 7 dní splněno {s['week_done']}/{s['week_expected']}" if s["week_expected"] else ""
    return [f"Návyky dnes: {list_or_none(today_items, len(today_items))}{week}"]


def habit_names(db):
    return [h.name for h in service.active_habits(db)]


INTEGRATIONS = ModuleIntegrations(
    changes=(ChangeSource(
        "habits", areas=frozenset({"habits"}),
        from_event=event_changes({"entry": "/habits"}, {"habits.entry.done": "Návyk splněn",
                                                        "habits.entry.skipped": "Návyk přeskočen"}),
        from_activity=activity_changes({"habit": "/habits?habit={id}"}, "/habits"),
    ),),
    search=(SearchSource("habits", 75, search_habits),),
    today=(TodaySource("habits", 30, timeline=today_habits),),
    entity_refs=(EntityRef("habit", "/habits?habit={id}"),),
    dashboard=(DashboardSection("habits", lambda db, access: service.summary(db)),),
    context=(
        ContextSection("habits", ("navyk", "habit", "rutin", "rehab"), order=75, build=context_habits,
                       name_hints=habit_names),
    ),
    routers=(router,),
)
