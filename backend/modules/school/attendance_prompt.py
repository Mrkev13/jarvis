"""MRK-149: po skončení cvičení / semináře / laborky z rozvrhu přijde push „Byl jsi?“ s akcemi Byl / Nebyl.

Hodinový krok Školy (`ModuleIntegrations.hourly`): najde hodiny, které skončily v posledních `WINDOW` (rozvrh přes
jádrový most `class_weeks_service` – Škola Kalendář neimportuje), a u aktivního předmětu bez splněného zápočtu, kde
docházka za ten týden ještě není zapsaná, založí jedno oznámení typu `attendance_prompt` (zvoneček + Web Push,
`ATTENDANCE_PUSH`). Klíč `attendance:<předmět>:<pondělí>` = nejvýš jedno oznámení na předmět a týden, i když je
hodin víc. Akce v oznámení volají běžný `PUT /school/subject/{id}/attendance`; zápis oznámení vyřeší
(`progress.set_attendance`). Zrušená hodina nic nepošle, přesunutá až po novém konci.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

import class_weeks_service
from models import Notification, Subject
from modules.school.models import SchoolAttendance
from modules.school.progress import credit_status, week_start
from time_utils import APP_TZ, utc_now

NOTIFICATION_TYPE = "attendance_prompt"
SOURCE_TYPE = "attendance"
WINDOW = timedelta(hours=3)        # hodinový krok + rezerva; starší hodiny se nedoptávají
LONGEST_LESSON = timedelta(hours=6)


def prompt_key(subject_id: int, week) -> str:
    return f"attendance:{subject_id}:{week.isoformat()}"


def prompt_attendance(db: Session, now: datetime | None = None) -> int:
    """→ počet nových oznámení. Nic necommituje. `now` = naive UTC."""
    now = now or utc_now()
    now_aware = now.replace(tzinfo=timezone.utc)
    lessons = class_weeks_service.attendance_lessons(db, now_aware - WINDOW - LONGEST_LESSON, now_aware)
    created = 0
    for sid, kind, begin, end in lessons:
        if not now_aware - WINDOW < end <= now_aware:
            continue
        local_begin, local_end = begin.astimezone(APP_TZ), end.astimezone(APP_TZ)
        week = week_start(local_begin.date())
        key = prompt_key(sid, week)
        if db.query(Notification.id).filter(Notification.dedupe_key == key).first():
            continue
        subject = db.get(Subject, sid)
        if subject is None or subject.active is False or credit_status(subject) == "passed":
            continue
        if db.query(SchoolAttendance.id).filter(SchoolAttendance.subject_id == sid,
                                                SchoolAttendance.week_start == week).first():
            continue
        db.add(Notification(
            area="school", title="Byl jsi na hodině?",
            message=f"{subject.name} – {kind.lower()} {local_begin:%H:%M}–{local_end:%H:%M}",
            severity="info", read=False, created_at=now, notification_type=NOTIFICATION_TYPE,
            source_type=SOURCE_TYPE, source_id=sid, dedupe_key=key, last_triggered_at=now, resolved=False,
            action_url=f"/school?subject={sid}"))
        db.flush()
        created += 1
    return created


def resolve_prompt(db: Session, subject_id: int, week) -> None:
    """Docházka za týden zapsaná (odkudkoli) → oznámení vyřešit, ať v zvonečku ani v push frontě nevisí."""
    for n in db.query(Notification).filter(Notification.dedupe_key == prompt_key(subject_id, week),
                                           Notification.resolved == False):  # noqa: E712
        n.resolved = True
