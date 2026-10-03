"""Kanonické stavy záznamů – jediné místo pravdy (Roadmap 3.5).

Stavy jsou volné řetězce (UI, AI i starší data používají české i anglické hodnoty), proto se porovnávají
vždy po `norm()` (ořez + malá písmena). Nové moduly importují odsud; nedefinují vlastní seznamy.
"""
from __future__ import annotations

# Úkol je hotový (vše ostatní = otevřený).
ASSIGNMENT_DONE_STATUSES = frozenset({"done", "completed", "hotovo", "closed", "finished"})
# Zkouška je ještě před námi (passed/failed/… = uzavřená).
EXAM_OPEN_STATUSES = frozenset({"upcoming", "scheduled", ""})
# Zkouška je složená (automatické cíle „složené zkoušky").
EXAM_PASSED_STATUSES = frozenset({"passed", "hotovo", "done", "completed", "splneno", "prospel"})
# Cíl neběží: nepočítá se do plánu, upozornění, přehledů ani stagnace.
GOAL_INACTIVE_STATUSES = frozenset({"completed", "cancelled", "paused"})
# AI čtení „otevřených" cílů: pozastavené se ukazují (uživatel se na ně může ptát), skryté jsou jen uzavřené.
GOAL_OPEN_EXCLUDED = frozenset({"completed", "cancelled"})
# Připomínka čeká nebo zazněla a není vyřízená.
REMINDER_ACTIVE_STATUSES = ("scheduled", "fired")
# MFF postava je postavená (automatické cíle).
MFF_BUILT_STATUSES = frozenset({"built", "hotovo", "done", "completed"})


def norm(status) -> str:
    return (status or "").strip().lower()


def is_assignment_done(status) -> bool:
    return norm(status) in ASSIGNMENT_DONE_STATUSES


def is_exam_open(status) -> bool:
    return norm(status) in EXAM_OPEN_STATUSES


def is_goal_inactive(status) -> bool:
    return norm(status) in GOAL_INACTIVE_STATUSES
