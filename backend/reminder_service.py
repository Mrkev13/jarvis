"""Připomínky (Roadmap 3.0 Phase D): pražský čas, opakování, životní cyklus a zpracování splatných.

Bez LLM: splatnost se vyhodnocuje deterministicky (`process_due_reminders`) a zazněná připomínka se
objeví jako běžná notifikace (`notifications`, type "reminder") – zvonek ji ukáže bez dalšího AI requestu.

Čas:
- Úložiště je naive UTC (stejně jako zbytek DB). Uživatel zadává i vidí čas v Europe/Prague.
- Opakované připomínky drží „nástěnný" pražský čas (`local_time`, `weekdays`): neděle 19:00 zůstane 19:00
  i přes změnu letního času.
- DST: neexistující čas (jarní posun, 02:00–03:00) se posune o mezeru vpřed (02:30 → 03:30 SELČ);
  dvojznačný čas (podzimní 02:00–03:00) bere první výskyt (letní čas, fold=0). Viz `local_to_utc`.

Stavy: scheduled → fired (jednorázová zazněla) → done; cancelled kdykoli. Opakovaná po zaznění zůstává
scheduled a posune `due_at` na další výskyt. Odložení: jednorázová = nový `due_at` (scheduled);
opakovaná = `snoozed_until` (jednorázový extra výskyt, série běží dál).

Zazvonění výskytu je nejvýš jednou: podmíněný UPDATE (WHERE due_at/snoozed_until = původní hodnota)
ve stejné transakci jako vložení notifikace s dedupe klíčem `reminder:<id>:<výskyt>`. Každá připomínka
má vlastní transakci – chyba jedné neovlivní ostatní.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import update as _sql_update
from sqlalchemy.orm import Session

from activity_service import log_activity
from context_service import fold_text
from models import Notification, Reminder
from time_utils import local_to_utc, to_local, utc_now

STATUS_SCHEDULED, STATUS_FIRED, STATUS_DONE, STATUS_CANCELLED = "scheduled", "fired", "done", "cancelled"
ACTIVE_STATUSES = (STATUS_SCHEDULED, STATUS_FIRED)
RECURRENCES = ("none", "daily", "weekly")
LATE_AFTER = timedelta(minutes=15)  # zpoždění po výpadku, které se v notifikaci výslovně uvede
MAX_TITLE = 255
_WEEKDAY_SHORT = ("po", "út", "st", "čt", "pá", "so", "ne")
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class ReminderError(ValueError):
    """Neplatný vstup připomínky (text pro uživatele / model)."""


# ===== čas =====

def parse_local_datetime(value: str) -> datetime:
    """'YYYY-MM-DDTHH:MM' (nebo s mezerou) v pražském čase → naive UTC."""
    raw = str(value or "").strip().replace(" ", "T")
    try:
        local = datetime.fromisoformat(raw[:16])
    except ValueError:
        raise ReminderError("Čas musí být ve tvaru YYYY-MM-DDTHH:MM (pražský čas).") from None
    return local_to_utc(local)  # i s explicitním offsetem → správné UTC


def parse_local_time(value: str) -> str:
    m = _TIME_RE.match(str(value or "").strip())
    if not m:
        raise ReminderError("Čas opakování musí být HH:MM.")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def parse_weekdays(value) -> str:
    """'0,6' / [0, 6] / 'ne' → normalizovaný řetězec pondělí=0 … neděle=6."""
    names = {"po": 0, "ut": 1, "st": 2, "ct": 3, "pa": 4, "so": 5, "ne": 6}
    items = value if isinstance(value, (list, tuple)) else str(value or "").replace(";", ",").split(",")
    days = set()
    for item in items:
        token = fold_text(str(item)).strip()
        token = token if token.isdigit() else token[:2]
        if token.isdigit() and 0 <= int(token) <= 6:
            days.add(int(token))
        elif token in names:
            days.add(names[token])
        elif token:
            raise ReminderError("Dny v týdnu: čísla 0–6 (po=0 … ne=6) nebo zkratky po, út, st, čt, pá, so, ne.")
    if not days:
        raise ReminderError("Týdenní připomínka potřebuje aspoň jeden den.")
    return ",".join(str(d) for d in sorted(days))


def next_occurrence(recurrence: str, weekdays: str | None, local_time: str, after_utc: datetime) -> datetime:
    """První výskyt přísně po `after_utc` (naive UTC), počítaný v pražském nástěnném čase."""
    hh, mm = (int(x) for x in local_time.split(":"))
    allowed = {int(d) for d in (weekdays or "").split(",") if d != ""} if recurrence == "weekly" else set(range(7))
    if not allowed:
        raise ReminderError("Týdenní připomínka potřebuje aspoň jeden den.")
    start = to_local(after_utc).date()
    for offset in range(0, 15):
        day = start + timedelta(days=offset)
        if day.weekday() not in allowed:
            continue
        candidate = local_to_utc(datetime.combine(day, time(hh, mm)))
        if candidate > after_utc:
            return candidate
    raise ReminderError("Nelze spočítat další výskyt.")  # pragma: no cover - 15 dní pokryje každý týden


def format_local(dt_utc: datetime | None) -> str:
    if dt_utc is None:
        return "–"
    local = to_local(dt_utc)
    return f"{_WEEKDAY_SHORT[local.weekday()]} {local.day}. {local.month}. {local.year} {local:%H:%M}"


def describe_recurrence(r: Reminder) -> str:
    if r.recurrence == "daily":
        return f"denně v {r.local_time}"
    if r.recurrence == "weekly":
        days = ", ".join(_WEEKDAY_SHORT[int(d)] for d in (r.weekdays or "").split(",") if d != "")
        return f"každý týden ({days}) v {r.local_time}"
    return "jednorázově"


# ===== serializace =====

def effective_due(r: Reminder) -> datetime:
    return r.snoozed_until if r.snoozed_until is not None and r.snoozed_until < r.due_at else r.due_at


def serialize(r: Reminder, now: datetime | None = None) -> dict:
    now = now or utc_now()
    due = effective_due(r)
    is_due = r.status == STATUS_FIRED or (r.status == STATUS_SCHEDULED and due <= now)
    return {
        "id": r.id,
        "title": r.title,
        "note": r.note or "",
        "status": r.status,
        "state": "due" if is_due else r.status,
        "due_at": r.due_at.isoformat() + "Z",
        "due_local": to_local(r.due_at).isoformat(),
        "due_label": format_local(r.due_at),
        "next_label": format_local(due),
        "snoozed_until": r.snoozed_until.isoformat() + "Z" if r.snoozed_until else None,
        "snoozed_label": format_local(r.snoozed_until) if r.snoozed_until else None,
        "recurrence": r.recurrence,
        "weekdays": r.weekdays,
        "local_time": r.local_time,
        "recurrence_label": describe_recurrence(r),
        "last_fired_at": r.last_fired_at.isoformat() + "Z" if r.last_fired_at else None,
        "last_fired_label": format_local(r.last_fired_at) if r.last_fired_at else None,
        "fire_count": int(r.fire_count or 0),
    }


def label(r: Reminder) -> str:
    when = describe_recurrence(r) if r.recurrence != "none" else format_local(r.due_at)
    return f"{r.title} · {when}"


# ===== vytvoření / úpravy =====

@dataclass(frozen=True)
class ReminderSpec:
    """Validovaná, deterministická data pro vytvoření (ukládá se i do pending plánu)."""
    title: str
    note: str
    due_at: datetime
    recurrence: str
    weekdays: str | None
    local_time: str | None

    def as_plan(self) -> dict:
        return {"title": self.title, "note": self.note, "due_at": self.due_at.isoformat(),
                "recurrence": self.recurrence, "weekdays": self.weekdays, "local_time": self.local_time}

    @classmethod
    def from_plan(cls, data: dict) -> "ReminderSpec":
        return cls(data["title"], data.get("note") or "", datetime.fromisoformat(data["due_at"]),
                   data["recurrence"], data.get("weekdays"), data.get("local_time"))


def _clean_title(title) -> str:
    t = " ".join(str(title or "").split())
    if not t:
        raise ReminderError("Připomínka potřebuje text.")
    if len(t) > MAX_TITLE:
        raise ReminderError(f"Text připomínky může mít nejvýš {MAX_TITLE} znaků.")
    return t


def build_spec(
    title: str,
    *,
    due_local: str | None = None,
    in_minutes: int | float | None = None,
    recurrence: str | None = "none",
    weekdays=None,
    time_local: str | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> ReminderSpec:
    """Z uživatelského / AI vstupu spočítá přesný první výskyt (UTC). Relativní čas se fixuje TEĎ."""
    now = now or utc_now()
    rec = str(recurrence or "none").strip().lower()
    if rec not in RECURRENCES:
        raise ReminderError("Opakování: none, daily nebo weekly.")
    title_clean = _clean_title(title)
    note_clean = str(note or "").strip()[:2000]
    if rec == "none":
        if (due_local in (None, "")) == (in_minutes in (None, "")):
            raise ReminderError("Zadej buď přesný čas (due_local), nebo za kolik minut (in_minutes).")
        if in_minutes not in (None, ""):
            try:
                minutes = float(in_minutes)
            except (TypeError, ValueError):
                raise ReminderError("in_minutes musí být číslo.") from None
            if minutes <= 0 or minutes > 60 * 24 * 366:
                raise ReminderError("in_minutes musí být kladné a nejvýš rok.")
            due = (now + timedelta(minutes=minutes)).replace(microsecond=0)
        else:
            due = parse_local_datetime(due_local)
            if due <= now:
                raise ReminderError(f"Čas {format_local(due)} už proběhl.")
        return ReminderSpec(title_clean, note_clean, due, "none", None, None)
    t = parse_local_time(time_local)
    days = parse_weekdays(weekdays) if rec == "weekly" else None
    first = next_occurrence(rec, days, t, now)
    return ReminderSpec(title_clean, note_clean, first, rec, days, t)


def create_from_spec(db: Session, spec: ReminderSpec, user_context: str = "manual") -> Reminder:
    now = utc_now()
    r = Reminder(title=spec.title, note=spec.note or None, due_at=spec.due_at, status=STATUS_SCHEDULED,
                 recurrence=spec.recurrence, weekdays=spec.weekdays, local_time=spec.local_time,
                 fire_count=0, created_at=now, updated_at=now)
    db.add(r)
    db.flush()
    log_activity(db, "reminders", "create", f"Připomínka: {label(r)}"[:480], entity_type="Reminder",
                 entity_id=r.id, user_context=user_context)
    return r


def _resolve_notifications(db: Session, reminder_id: int) -> int:
    rows = (
        db.query(Notification)
        .filter(Notification.source_type == "reminder", Notification.source_id == reminder_id,
                Notification.resolved == False)  # noqa: E712
        .all()
    )
    for n in rows:
        n.resolved = True
        n.read = True
    return len(rows)


def _require_active(r: Reminder) -> None:
    if r.status not in ACTIVE_STATUSES:
        raise ReminderError("Připomínka už je hotová nebo zrušená.")


def complete(db: Session, r: Reminder, user_context: str = "manual") -> Reminder:
    """Hotovo: jednorázová končí; u opakované se potvrdí aktuální výskyt a série běží dál."""
    _require_active(r)
    _resolve_notifications(db, r.id)
    r.snoozed_until = None
    if r.recurrence == "none":
        r.status = STATUS_DONE
    r.updated_at = utc_now()
    log_activity(db, "reminders", "complete", f"Připomínka hotová: {label(r)}"[:480], entity_type="Reminder",
                 entity_id=r.id, user_context=user_context, dedupe_key=f"reminder-done:{r.id}:{r.updated_at.isoformat()}")
    return r


def cancel(db: Session, r: Reminder, user_context: str = "manual") -> Reminder:
    _require_active(r)
    _resolve_notifications(db, r.id)
    r.status = STATUS_CANCELLED
    r.snoozed_until = None
    r.updated_at = utc_now()
    log_activity(db, "reminders", "cancel", f"Připomínka zrušena: {label(r)}"[:480], entity_type="Reminder",
                 entity_id=r.id, user_context=user_context)
    return r


def snooze_target(r: Reminder, *, minutes=None, until_local: str | None = None, now: datetime | None = None) -> datetime:
    """Kdy má odložená připomínka znovu zaznít (UTC); jen budoucí čas."""
    now = now or utc_now()
    if (minutes in (None, "")) == (until_local in (None, "")):
        raise ReminderError("Odložení: zadej buď minutes, nebo until_local.")
    if minutes not in (None, ""):
        try:
            m = float(minutes)
        except (TypeError, ValueError):
            raise ReminderError("minutes musí být číslo.") from None
        if m <= 0 or m > 60 * 24 * 60:
            raise ReminderError("Odložení musí být kladné a nejvýš 60 dní.")
        return (now + timedelta(minutes=m)).replace(microsecond=0)
    target = parse_local_datetime(until_local)
    if target <= now:
        raise ReminderError(f"Čas {format_local(target)} už proběhl.")
    return target


def snooze(db: Session, r: Reminder, until_utc: datetime, user_context: str = "manual") -> Reminder:
    _require_active(r)
    _resolve_notifications(db, r.id)
    if r.recurrence == "none":
        r.due_at = until_utc
        r.status = STATUS_SCHEDULED
    else:
        r.snoozed_until = until_utc
    r.updated_at = utc_now()
    log_activity(db, "reminders", "snooze", f"Připomínka odložena na {format_local(until_utc)}: {r.title}"[:480],
                 entity_type="Reminder", entity_id=r.id, user_context=user_context,
                 dedupe_key=f"reminder-snooze:{r.id}:{until_utc.isoformat()}")
    return r


def update(db: Session, r: Reminder, changes: dict, user_context: str = "manual") -> Reminder:
    """changes v absolutní podobě: title, note, due_at (UTC), recurrence, weekdays, local_time."""
    _require_active(r)
    old = label(r)
    if "title" in changes:
        r.title = _clean_title(changes["title"])
    if "note" in changes:
        r.note = str(changes["note"] or "").strip()[:2000] or None
    for key in ("recurrence", "weekdays", "local_time"):
        if key in changes:
            setattr(r, key, changes[key])
    if "due_at" in changes:
        r.due_at = changes["due_at"] if isinstance(changes["due_at"], datetime) else datetime.fromisoformat(changes["due_at"])
        if r.recurrence == "none" and r.status == STATUS_FIRED:
            r.status = STATUS_SCHEDULED
            _resolve_notifications(db, r.id)
    r.updated_at = utc_now()
    log_activity(db, "reminders", "update", f"Připomínka upravena: {old} → {label(r)}"[:480],
                 entity_type="Reminder", entity_id=r.id, user_context=user_context,
                 dedupe_key=f"reminder-update:{r.id}:{r.updated_at.isoformat()}")
    return r


# ===== zpracování splatných (scheduler / lazy při čtení notifikací) =====

def _notify(db: Session, r: Reminder, occurrence: datetime, key: str, now: datetime) -> bool:
    dedupe = f"reminder:{r.id}:{key}"
    if db.query(Notification.id).filter(Notification.dedupe_key == dedupe).first():
        return False
    late = now - occurrence
    message = f"Připomínka na {format_local(occurrence)}."
    if late > LATE_AFTER:
        message += f" Zpožděno – zobrazeno až {format_local(now)} (aplikace neběžela nebo nekontrolovala)."
    if r.note:
        message += f"\n{r.note}"
    db.add(Notification(
        area="reminders", title=f"⏰ {r.title}"[:255], message=message, severity="important", read=False,
        created_at=now, expires_at=None, notification_type="reminder", source_type="reminder",
        source_id=r.id, dedupe_key=dedupe[:150], last_triggered_at=now, resolved=False,
        action_url="/reminders",
    ))
    return True


def _fire_one(db: Session, reminder_id: int, now: datetime) -> int:
    """Zazvoní splatné výskyty jedné připomínky. Vrací počet nových notifikací (0 = už zpracováno)."""
    r = db.get(Reminder, reminder_id)
    if r is None or r.status != STATUS_SCHEDULED:
        return 0
    fired = 0
    if r.snoozed_until is not None and r.snoozed_until <= now:
        occurrence = r.snoozed_until
        claimed = db.execute(
            _sql_update(Reminder)
            .where(Reminder.id == r.id, Reminder.snoozed_until == occurrence, Reminder.status == STATUS_SCHEDULED)
            .values(snoozed_until=None, last_fired_at=now, fire_count=Reminder.fire_count + 1, updated_at=now)
        )
        if claimed.rowcount == 1 and _notify(db, r, occurrence, f"s{occurrence.isoformat()}", now):
            fired += 1
        db.refresh(r)
    if r.status == STATUS_SCHEDULED and r.due_at <= now:
        occurrence = r.due_at
        if r.recurrence == "none":
            values = {"status": STATUS_FIRED}
        else:
            # Po výpadku se zmeškané výskyty nezvoní jednotlivě: jedna notifikace (se zpožděním) a další
            # výskyt až v budoucnu.
            values = {"due_at": next_occurrence(r.recurrence, r.weekdays, r.local_time, max(now, occurrence))}
        claimed = db.execute(
            _sql_update(Reminder)
            .where(Reminder.id == r.id, Reminder.due_at == occurrence, Reminder.status == STATUS_SCHEDULED)
            .values(last_fired_at=now, fire_count=Reminder.fire_count + 1, updated_at=now, **values)
        )
        if claimed.rowcount == 1 and _notify(db, r, occurrence, occurrence.isoformat(), now):
            fired += 1
    return fired


def process_due_reminders(db: Session, now: datetime | None = None) -> dict:
    """Zazvoní všechny splatné připomínky. Idempotentní; každá připomínka ve vlastní transakci."""
    now = now or utc_now()
    ids = [
        rid for (rid,) in db.query(Reminder.id)
        .filter(Reminder.status == STATUS_SCHEDULED)
        .filter((Reminder.due_at <= now) | ((Reminder.snoozed_until.isnot(None)) & (Reminder.snoozed_until <= now)))
        .order_by(Reminder.due_at, Reminder.id)
        .all()
    ]
    stats = {"checked": len(ids), "fired": 0, "failed": 0}
    for rid in ids:
        try:
            stats["fired"] += _fire_one(db, rid, now)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - jedna vadná připomínka nesmí zastavit ostatní
            db.rollback()
            stats["failed"] += 1
            print(f"[reminders] reminder {rid} failed: {type(exc).__name__}: {exc}")
    return stats


def list_reminders(db: Session, status: str | None = "active", limit: int = 100, now: datetime | None = None) -> list[dict]:
    now = now or utc_now()
    q = db.query(Reminder)
    s = (status or "active").strip().lower()
    if s == "active":
        q = q.filter(Reminder.status.in_(ACTIVE_STATUSES))
    elif s != "all":
        q = q.filter(Reminder.status == s)
    rows = q.order_by(Reminder.due_at, Reminder.id).limit(max(1, min(int(limit or 100), 500))).all()
    items = [serialize(r, now) for r in rows]
    # Splatné nahoře, pak podle příštího výskytu.
    items.sort(key=lambda i: (i["state"] != "due", i["next_label"] == "–", i["due_at"]))
    return items


def today_bounds_local(now: datetime | None = None) -> tuple[datetime, datetime]:
    local_day = to_local(now or utc_now()).date()
    return local_to_utc(datetime.combine(local_day, time.min)), local_to_utc(datetime.combine(local_day + timedelta(days=1), time.min))


