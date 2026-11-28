"""AI tooly modulu Počítač (MRK-157) nad stávající pending-action architekturou – AI nikdy nic nespustí přímo.

- `query_computer_status` – přehled PC pro testy / diagnostiku (Jarvis dostává stav z CURRENT STATE sekce modulu).
- `manage_computer` – návrh příkazu (spustit aplikaci ze seznamu PC / vypnout / uspat / zamknout, volitelně
  s časovačem / zrušit časovač). Resolver ověří zařízení, aplikaci a online stav a uloží přesný příkaz do plánu;
  potvrzení ho zařadí do fronty (`service.create_command`, user_context ai_confirm). Mezitím offline PC / zmizelá
  aplikace = StaleTarget.

Model nikdy neposílá cestu ani argumenty – jen název / id aplikace, kterou PC samo nahlásilo.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from database import SessionLocal
from modules.computer import service
from modules.computer.models import Device, DeviceCommand
from mutation_service import MutationRefused, StaleTarget
from text_utils import fold_text
from time_utils import to_local, utc_now

AREA = "computer"
POWER_ACTIONS = ("shutdown", "sleep", "lock")
ACTIONS = ("launch_app",) + POWER_ACTIONS
MAX_DELAY_MINUTES = service.MAX_DELAY_SECONDS // 60


def _fold(text) -> str:
    return " ".join(fold_text(str(text or "")).split())


def _local(dt) -> str | None:
    return to_local(dt).strftime("%d.%m. %H:%M") if dt else None


# ===== čtení =====

def query_computer_status(db: Session) -> dict:
    now = utc_now()
    service.expire_stale(db, now)
    devices = db.query(Device).filter(Device.revoked_at.is_(None)).order_by(Device.id).all()
    items = []
    for d in devices:
        status = d.status or {}
        apps = {a["id"]: a["name"] for a in (d.apps or [])}
        recent = (db.query(DeviceCommand).filter(DeviceCommand.device_id == d.id)
                  .order_by(DeviceCommand.id.desc()).limit(5).all())
        items.append({
            "name": d.name,
            "online": service.is_online(d, now),
            "last_seen": _local(d.last_seen_at),
            "cpu_percent": status.get("cpu_percent"),
            "ram_percent": status.get("ram_percent"),
            "disks": [f"{x['name']} {x['free_gb']:g}/{x['total_gb']:g} GB volno" for x in status.get("disks") or []],
            "running": [apps.get(a, a) for a in status.get("running") or []],
            "apps": list(apps.values()),
            "recent_commands": [{"what": service.command_label(c.kind, c.payload or {}, d), "status": c.status,
                                 "at": _local(c.created_at), "result": c.result_message} for c in recent],
        })
    out = {"devices": items, "timezone": "Europe/Prague"}
    if not items:
        out["hint"] = "Žádný počítač není spárovaný – v Hubu stránka Počítač → Spárovat."
    return out


# ===== návrh příkazu =====

def _pick_device(db: Session, device: str | None) -> Device:
    devices = db.query(Device).filter(Device.revoked_at.is_(None)).order_by(Device.id).all()
    if not devices:
        raise MutationRefused("not_found", "Žádný počítač není spárovaný.")
    if device:
        wanted = _fold(device)
        hits = [d for d in devices if wanted in _fold(d.name) or _fold(d.name) in wanted]
        if len(hits) == 1:
            return hits[0]
        if len(devices) > 1:
            raise MutationRefused("ambiguous_target", "Který počítač?",
                                  candidates=[{"name": d.name} for d in devices])
    if len(devices) == 1:
        return devices[0]
    raise MutationRefused("ambiguous_target", "Který počítač?", candidates=[{"name": d.name} for d in devices])


def _pick_app(device: Device, app: str | None) -> dict:
    apps = device.apps or []
    if not app:
        raise MutationRefused("invalid_changes", "Kterou aplikaci spustit?",
                              candidates=[{"name": a["name"]} for a in apps])
    wanted = _fold(app)
    exact = [a for a in apps if wanted in (a["id"], _fold(a["name"]))]
    hits = exact or [a for a in apps if wanted in _fold(a["name"]) or wanted in a["id"]]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise MutationRefused("not_found", f"Aplikace „{app}“ není v seznamu počítače „{device.name}“.",
                              candidates=[{"name": a["name"]} for a in apps])
    raise MutationRefused("ambiguous_target", "Kterou aplikaci?", candidates=[{"name": a["name"]} for a in hits])


def _delay_seconds(delay_minutes) -> int:
    if delay_minutes in (None, ""):
        return 0
    try:
        minutes = float(delay_minutes)
    except (TypeError, ValueError):
        raise MutationRefused("invalid_changes", "Neplatný časovač.") from None
    if not 0 <= minutes <= MAX_DELAY_MINUTES:
        raise MutationRefused("invalid_changes", "Časovač může být nejvýš 4 hodiny.")
    return int(round(minutes * 60))


def propose_control_computer(db: Session, action: str, app: str | None = None, delay_minutes=None,
                             device: str | None = None) -> dict:
    if action not in ACTIONS:
        raise MutationRefused("invalid_changes", "Neznámá akce.")
    target = _pick_device(db, device)
    if action == "launch_app":
        picked = _pick_app(target, app)
        kind, payload = "launch_app", {"app_id": picked["id"]}
    else:
        kind, payload = "power", {"action": action, "delay_seconds": _delay_seconds(delay_minutes)}
    if not service.is_online(target, utc_now()):
        raise MutationRefused("not_found", f"Počítač „{target.name}“ teď není online – příkaz by nikdo nevyzvedl.")
    label = service.command_label(kind, payload, target)
    warnings = []
    if kind == "power" and action == "shutdown":
        warnings.append("Neuložená práce na PC se ztratí. Časovač jde zrušit v Hubu, v aplikaci i z ikony v liště.")
    return {
        "version": 1,
        "kind": "computer_command",
        "device_id": target.id,
        "device_name": target.name,
        "command": {"kind": kind, "payload": payload},
        "preview": {"kind": "create", "entity": "computer_command", "title": f"Počítač „{target.name}“",
                    "count": 1, "items": [{"label": label[:1].upper() + label[1:], "changes": []}],
                    "warnings": warnings},
    }


def propose_manage_computer(db: Session, action: str, app: str | None = None, delay_minutes=None,
                            device: str | None = None) -> dict:
    """Resolver toolu `manage_computer` (MRK-157)."""
    if action == "cancel_timer":
        return propose_cancel_computer_timer(db, device=device)
    return propose_control_computer(db, action, app=app, delay_minutes=delay_minutes, device=device)


def propose_cancel_computer_timer(db: Session, device: str | None = None) -> dict:
    target = _pick_device(db, device)
    if not service.is_online(target, utc_now()):
        raise MutationRefused("not_found", f"Počítač „{target.name}“ teď není online.")
    return {
        "version": 1,
        "kind": "computer_command",
        "device_id": target.id,
        "device_name": target.name,
        "command": {"kind": "power_cancel", "payload": {}},
        "preview": {"kind": "update", "entity": "computer_command", "title": f"Počítač „{target.name}“",
                    "count": 1, "items": [{"label": "Zrušit časovač vypnutí / uspání / zamknutí", "changes": []}],
                    "warnings": []},
    }


def execute_computer_command(plan: dict, user_context: str = "ai_confirm") -> dict:
    """Po potvrzení zařadí přesně příkaz z plánu. PC mezitím offline / odvolané / bez aplikace → StaleTarget."""
    if not isinstance(plan, dict) or plan.get("version") != 1 or plan.get("kind") != "computer_command":
        raise ValueError("Neplatný plán příkazu pro počítač")
    command = plan.get("command") or {}
    db = SessionLocal()
    try:
        try:
            cmd = service.create_command(db, int(plan["device_id"]), command.get("kind"), command.get("payload"),
                                         user_context=user_context)
        except service.DeviceError as err:
            raise StaleTarget(err.message) from None
        db.commit()
        return {"command_id": cmd.id, "device": plan.get("device_name"), "label": service.command_label(
            cmd.kind, cmd.payload or {}, None), "note": "Příkaz odeslán – PC ho provede do pár sekund."}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
