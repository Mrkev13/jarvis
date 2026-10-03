"""AI tooly připomínek (Phase D) nad stávající pending-action architekturou.

- `get_reminders` – čtení (bez potvrzení).
- `add_reminder` – vytvoření: resolver hned spočítá přesný čas (relativní „za 2 hodiny" se fixuje při
  návrhu) a uloží ho do plánu; potvrzení vytvoří přesně to, co ukázal náhled.
- `manage_reminder` – úprava / odložení / hotovo / zrušení existující připomínky. Cíl se hledá stejně
  jako v Phase B (`mutation_service._find_targets`): nejednoznačný / nenalezený → `not_prepared`,
  žádná pending akce. Plán drží id + snímek; potvrzení při změně připomínky mezitím selže a nic nezmění.

Undo (Phase C) se na připomínky nevztahuje – zrušení / odložení / hotovo jde jednoduše znovu upravit.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

import reminder_service as rs
from database import SessionLocal
from models import Reminder
from mutation_service import EntityDef, MutationRefused, StaleTarget, _find_targets, _snapshot
from time_utils import to_local

MANAGE_ACTIONS = ("update", "snooze", "complete", "cancel")
_TITLES = {"update": "Upravit připomínku", "snooze": "Odložit připomínku", "complete": "Připomínka hotová",
           "cancel": "Zrušit připomínku"}

REMINDER_ENTITY = EntityDef(
    name="reminder", model=Reminder, area="reminders", label="připomínka", entity_type="Reminder",
    fields={}, actions=frozenset(MANAGE_ACTIONS),
    text_of=lambda r: f"{r.title or ''} {r.note or ''}",
    describe=rs.label,
    date_of=lambda r: to_local(rs.effective_due(r)).date(),
    type_of=lambda r: r.recurrence or "",
    order_key=lambda r: (rs.effective_due(r), r.id),
    base_filter=lambda r: r.status in rs.ACTIVE_STATUSES,
    snapshot_attrs=("title", "note", "due_at", "status", "recurrence", "weekdays", "local_time", "snoozed_until"),
)


def _refuse(exc: rs.ReminderError) -> MutationRefused:
    return MutationRefused("invalid_changes", str(exc))


# ===== čtení =====

def query_reminders(db: Session, status: str | None = "active", limit: int | None = 20) -> dict:
    """AI read tool: připomínky s pražskými časy (splatné první). Jen čte – zazvonění řeší scheduler."""
    try:
        n = max(1, min(int(limit or 20), 100))
    except (TypeError, ValueError):
        n = 20
    items = rs.list_reminders(db, status=status or "active", limit=500)
    keep = ("id", "title", "note", "status", "state", "next_label", "recurrence_label", "snoozed_label",
            "last_fired_label")
    trimmed = [{k: i[k] for k in keep if i.get(k) not in (None, "")} for i in items[:n]]
    return {"items": trimmed, "total": len(items), "returned": len(trimmed), "truncated": len(items) > n,
            "timezone": "Europe/Prague"}


# ===== vytvoření =====

def propose_add_reminder(
    db: Session,
    title: str,
    due_local: str | None = None,
    in_minutes: float | None = None,
    recurrence: str | None = None,
    weekdays=None,
    time_local: str | None = None,
    note: str | None = None,
) -> dict:
    try:
        spec = rs.build_spec(title, due_local=due_local, in_minutes=in_minutes, recurrence=recurrence or "none",
                             weekdays=weekdays, time_local=time_local, note=note)
    except rs.ReminderError as exc:
        raise _refuse(exc) from None
    probe = Reminder(title=spec.title, due_at=spec.due_at, recurrence=spec.recurrence, weekdays=spec.weekdays,
                     local_time=spec.local_time)
    changes = [{"label": "Kdy", "old": "", "new": rs.format_local(spec.due_at)}]
    if spec.recurrence != "none":
        changes.append({"label": "Opakování", "old": "", "new": rs.describe_recurrence(probe)})
    if spec.note:
        changes.append({"label": "Poznámka", "old": "", "new": spec.note[:120]})
    return {
        "version": 1,
        "kind": "reminder_create",
        "spec": spec.as_plan(),
        "preview": {"kind": "create", "entity": "reminder", "title": "Nová připomínka", "count": 1,
                    "items": [{"label": spec.title, "changes": changes}], "warnings": []},
    }


def execute_add_reminder(plan: dict, user_context: str = "manual") -> dict:
    if not isinstance(plan, dict) or plan.get("version") != 1 or plan.get("kind") != "reminder_create":
        raise ValueError("Neplatný plán připomínky")
    spec = rs.ReminderSpec.from_plan(plan["spec"])
    db = SessionLocal()
    try:
        r = rs.create_from_spec(db, spec, user_context=user_context)
        db.commit()
        return {"id": r.id, "title": r.title, "due_label": rs.format_local(r.due_at)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ===== úprava / odložení / hotovo / zrušení =====

def propose_manage_reminder(
    db: Session,
    action: str,
    target: dict,
    title: str | None = None,
    due_local: str | None = None,
    shift_minutes: float | None = None,
    snooze_minutes: float | None = None,
    snooze_until_local: str | None = None,
    recurrence: str | None = None,
    weekdays=None,
    time_local: str | None = None,
) -> dict:
    act = str(action or "").strip().lower()
    if act not in MANAGE_ACTIONS:
        raise MutationRefused("unsupported_action", f"Akce připomínky: {list(MANAGE_ACTIONS)}")
    edit_args = (title, due_local, shift_minutes, recurrence, weekdays, time_local)
    snooze_args = (snooze_minutes, snooze_until_local)
    if act != "update" and any(v not in (None, "", []) for v in edit_args):
        raise MutationRefused("invalid_changes", "Úpravy textu/času patří do action=update.")
    if act != "snooze" and any(v not in (None, "") for v in snooze_args):
        raise MutationRefused("invalid_changes", "Odložení patří do action=snooze.")
    # Víc shod s all_matching → batch_not_supported, bez upřesnění → ambiguous_target (Phase B pravidla).
    [r] = _find_targets(db, REMINDER_ENTITY, act, target or {})

    plan_changes: dict = {}
    diff: list[dict] = []
    try:
        if act == "update":
            changes = rs.build_update_changes(r, title=title, due_local=due_local, shift_minutes=shift_minutes,
                                              recurrence=recurrence, weekdays=weekdays, time_local=time_local)
            if "title" in changes and changes["title"] != r.title:
                diff.append({"label": "Text", "old": r.title, "new": changes["title"]})
            if "due_at" in changes:
                diff.append({"label": "Kdy", "old": rs.format_local(rs.effective_due(r)),
                             "new": rs.format_local(changes["due_at"])})
            if "recurrence" in changes:
                probe = Reminder(recurrence=changes["recurrence"], weekdays=changes.get("weekdays"),
                                 local_time=changes.get("local_time"))
                diff.append({"label": "Opakování", "old": rs.describe_recurrence(r),
                             "new": rs.describe_recurrence(probe)})
            plan_changes = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in changes.items()}
        elif act == "snooze":
            if r.status not in rs.ACTIVE_STATUSES:
                raise rs.ReminderError("Připomínka už je hotová nebo zrušená.")
            until = rs.snooze_target(r, minutes=snooze_minutes, until_local=snooze_until_local)
            diff.append({"label": "Kdy", "old": rs.format_local(rs.effective_due(r)), "new": rs.format_local(until)})
            plan_changes = {"until": until.isoformat()}
    except rs.ReminderError as exc:
        raise _refuse(exc) from None
    if act == "update" and not diff:
        raise MutationRefused("no_change", "Připomínka už má tyto hodnoty.")
    warnings = []
    if act in ("complete", "cancel") and r.recurrence != "none":
        warnings.append("Opakovaná připomínka: hotovo potvrdí jen aktuální výskyt, série běží dál."
                        if act == "complete" else "Zruší se celá opakovaná série.")
    return {
        "version": 1,
        "kind": "reminder_manage",
        "action": act,
        "reminder_id": r.id,
        "snapshot": _snapshot(REMINDER_ENTITY, r),
        "changes": plan_changes,
        "preview": {"kind": act, "entity": "reminder", "title": _TITLES[act], "count": 1,
                    "items": [{"id": r.id, "label": rs.label(r), "changes": diff}], "warnings": warnings},
    }


def execute_manage_reminder(plan: dict, user_context: str = "manual") -> dict:
    if not isinstance(plan, dict) or plan.get("version") != 1 or plan.get("kind") != "reminder_manage":
        raise ValueError("Neplatný plán připomínky")
    act = plan.get("action")
    if act not in MANAGE_ACTIONS:
        raise ValueError("Neplatná akce připomínky")
    db = SessionLocal()
    try:
        r = db.get(Reminder, int(plan["reminder_id"]))
        if r is None:
            raise StaleTarget("Připomínka mezitím zmizela – nic jsem nezměnil.")
        if _snapshot(REMINDER_ENTITY, r) != plan.get("snapshot"):
            raise StaleTarget("Připomínka se od návrhu změnila (nebo zazněla) – nic jsem nezměnil.")
        changes = dict(plan.get("changes") or {})
        if act == "update":
            if "due_at" in changes:
                changes["due_at"] = datetime.fromisoformat(changes["due_at"])
            rs.update(db, r, changes, user_context=user_context)
        elif act == "snooze":
            rs.snooze(db, r, datetime.fromisoformat(changes["until"]), user_context=user_context)
        elif act == "complete":
            rs.complete(db, r, user_context=user_context)
        else:
            rs.cancel(db, r, user_context=user_context)
        db.commit()
        return {"id": r.id, "action": act, "status": r.status, "due_label": rs.format_local(rs.effective_due(r))}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
