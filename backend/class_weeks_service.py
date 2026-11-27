"""MRK-148: most Škola ← Kalendář pro docházku (stejný vzor jako `goal_history_service` → WoW).

Moduly v `modules/<id>/` se navzájem neimportují (MRK-21) a nesahají na registr modulů. Docházka Školy ale potřebuje
vědět, ve kterých týdnech má předmět v ručním rozvrhu Kalendáře cvičení / seminář / laborku. Tenhle jádrový modul
je jediné místo, které obě strany spojuje: zeptá se registru, jestli je Kalendář dostupný, a teprve pak zavolá
`modules.calendar.timetable.attendance_weeks`. Importy jsou líné (registr importuje integrace modulů → cyklus).
"""
from __future__ import annotations

from datetime import date


def timetable_weeks(db, lo: date, hi: date) -> dict[int, set[date]]:
    """{subject_id: pondělí týdnů s výukou z rozvrhu}; prázdné = rozvrh docházku neurčuje (vypnutý Kalendář)."""
    from module_registry import current_access
    if not current_access().is_available("calendar"):
        return {}
    from modules.calendar.timetable import attendance_weeks
    return attendance_weeks(db, lo, hi)
