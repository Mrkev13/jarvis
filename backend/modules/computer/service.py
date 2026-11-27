"""Doménová logika modulu Počítač (MRK-155) – párování PC s agentem Jarvise, stav a fronta potvrzených příkazů.

Bezpečnost (docs/computer.md):
- Token zařízení i párovací kód se v DB drží jen jako SHA-256 hash; plaintext token vidí jen agent při párování.
- Token platí jen pro `/device/agent/*` (router.py); session cookie tam nestačí a token jinde neplatí (main.require_auth).
- Odvolání (`revoked_at`) token okamžitě zneplatní a čekající příkazy propadnou.
- Příkaz smí být jen z allowlistu (`launch_app` s id aplikace, kterou agent sám nahlásil; `power`; `power_cancel`) a
  platí krátce (`COMMAND_TTL`) – vypnuté PC si ho nikdy nevyzvedne pozdě.

Audit: párování, odvolání, přejmenování, zařazení příkazu a jeho výsledek / propadnutí jdou do Aktivity ve stejné
transakci (fakta přes `append_domain_event`). Heartbeat (`last_seen_at`, `status`, `apps`) a čas vyzvednutí příkazu
(`delivered_at`) jsou provozní telemetrie bez Aktivity – stejně jako `last_seen_at` přihlašovací session.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from activity_service import log_activity
from domain_events import ActivityProjection, append_domain_event
from modules.computer.models import COMMAND_KINDS, Device, DeviceCommand, DevicePairingCode
from time_utils import utc_now

AREA = "computer"
PAIRING_TTL = timedelta(minutes=10)
COMMAND_TTL = timedelta(minutes=2)
DELIVERED_TIMEOUT = timedelta(minutes=10)   # vyzvednutý příkaz bez výsledku → propadne
ONLINE_WINDOW = timedelta(seconds=90)       # heartbeat agenta chodí každých ~30 s
POLL_TOUCH = timedelta(seconds=30)          # vyzvedávání příkazů obnoví last_seen nejvýš jednou za 30 s
MAX_ACTIVE_DEVICES = 5
MAX_APPS = 50
MAX_DISKS = 12
MAX_DELAY_SECONDS = 4 * 3600
POWER_ACTIONS = {"shutdown": "vypnout", "sleep": "uspat", "lock": "zamknout"}
PLATFORMS = ("windows",)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # bez 0/O a 1/I
CODE_LEN = 8
APP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
EVENTS = ("computer.device.paired", "computer.device.revoked", "computer.command.completed",
          "computer.command.failed", "computer.command.expired")


class DeviceError(Exception):
    """Neplatný požadavek (`status` = HTTP kód, `message` česky)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_code(code: str | None) -> str:
    return re.sub(r"[\s-]", "", str(code or "")).upper()


def _clean_text(value, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


# ---------- čtení ----------


def is_online(device: Device, now: datetime) -> bool:
    return bool(device.last_seen_at and not device.revoked_at and now - device.last_seen_at <= ONLINE_WINDOW)


def device_dict(device: Device, now: datetime) -> dict:
    return {
        "id": device.id, "name": device.name, "platform": device.platform, "agent_version": device.agent_version,
        "created_at": _iso(device.created_at), "last_seen_at": _iso(device.last_seen_at),
        "revoked": device.revoked_at is not None, "online": is_online(device, now),
        "status": device.status or None, "apps": device.apps or [],
    }


def command_dict(cmd: DeviceCommand) -> dict:
    return {
        "id": cmd.id, "device_id": cmd.device_id, "kind": cmd.kind, "payload": cmd.payload or {},
        "status": cmd.status, "label": command_label(cmd.kind, cmd.payload or {}, None),
        "created_at": _iso(cmd.created_at), "expires_at": _iso(cmd.expires_at),
        "delivered_at": _iso(cmd.delivered_at), "completed_at": _iso(cmd.completed_at),
        "result_message": cmd.result_message,
    }


def list_devices(db: Session, now: datetime | None = None) -> list[dict]:
    now = now or utc_now()
    rows = db.query(Device).filter(Device.revoked_at.is_(None)).order_by(Device.id).all()
    return [device_dict(d, now) for d in rows]


def get_device(db: Session, device_id: int, *, active: bool = True) -> Device:
    device = db.get(Device, device_id)
    if device is None or (active and device.revoked_at is not None):
        raise DeviceError(404, "Zařízení neexistuje nebo bylo odvoláno.")
    return device


def list_commands(db: Session, device_id: int, limit: int = 20) -> list[dict]:
    rows = (db.query(DeviceCommand).filter(DeviceCommand.device_id == device_id)
            .order_by(DeviceCommand.id.desc()).limit(max(1, min(limit, 100))).all())
    return [command_dict(c) for c in rows]


def authenticate(db: Session, token: str | None) -> Device | None:
    """Token z hlavičky agenta → aktivní zařízení, jinak None (neplatný, odvolaný)."""
    if not token or len(token) > 200:
        return None
    device = db.query(Device).filter(Device.token_hash == hash_secret(token)).first()
    return device if device is not None and device.revoked_at is None else None


# ---------- párování ----------


def create_pairing_code(db: Session, now: datetime | None = None) -> dict:
    """Nový jednorázový kód; dřívější nepoužité kódy tím přestanou platit (platí vždy jen jeden)."""
    now = now or utc_now()
    active = db.query(Device).filter(Device.revoked_at.is_(None)).count()
    if active >= MAX_ACTIVE_DEVICES:
        raise DeviceError(409, f"Spárovat jde nejvýš {MAX_ACTIVE_DEVICES} zařízení – nejdřív nějaké odvolej.")
    (db.query(DevicePairingCode)
     .filter(DevicePairingCode.used_at.is_(None), DevicePairingCode.expires_at > now)
     .update({DevicePairingCode.expires_at: now}, synchronize_session=False))
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
    row = DevicePairingCode(code_hash=hash_secret(code), created_at=now, expires_at=now + PAIRING_TTL)
    db.add(row)
    db.flush()
    log_activity(db, AREA, "pairing_code", "Vytvořen párovací kód pro počítač (platí 10 min)",
                 entity_type="device_pairing_code", entity_id=row.id, user_context="manual")
    return {"code": f"{code[:4]}-{code[4:]}", "expires_at": _iso(row.expires_at)}


def pair(db: Session, code: str, name: str, platform: str = "windows", agent_version: str | None = None,
         now: datetime | None = None) -> tuple[Device, str]:
    """Vymění platný párovací kód za token zařízení (plaintext se vrací jen tady, v DB je hash)."""
    now = now or utc_now()
    clean = normalize_code(code)
    row = None
    if len(clean) == CODE_LEN:
        row = db.query(DevicePairingCode).filter(DevicePairingCode.code_hash == hash_secret(clean)).first()
    platform = (platform or "").strip().lower()
    if row is not None and platform not in PLATFORMS:
        raise DeviceError(422, "Nepodporovaná platforma.")
    # Atomický claim (review #138): kód spotřebuje jen ten, komu podmíněný UPDATE změní řádek. Souběžný druhý
    # požadavek (i se zastaralým načteným řádkem) dostane 0 řádků → 401; v PostgreSQL čeká na zámek řádku.
    claimed = 0
    if row is not None:
        claimed = (db.query(DevicePairingCode)
                   .filter(DevicePairingCode.id == row.id, DevicePairingCode.used_at.is_(None),
                           DevicePairingCode.expires_at > now)
                   .update({DevicePairingCode.used_at: now}, synchronize_session=False))
    if claimed != 1:
        raise DeviceError(401, "Párovací kód neplatí – vytvoř v Hubu nový.")
    if db.query(Device).filter(Device.revoked_at.is_(None)).count() >= MAX_ACTIVE_DEVICES:
        raise DeviceError(409, f"Spárovat jde nejvýš {MAX_ACTIVE_DEVICES} zařízení – nejdřív nějaké odvolej.")
    name = _clean_text(name, 80) or "Počítač"
    token = secrets.token_urlsafe(32)
    device = Device(name=name, platform=platform, agent_version=_clean_text(agent_version, 40) or None,
                    token_hash=hash_secret(token), created_at=now, last_seen_at=now)
    db.add(device)
    db.flush()
    (db.query(DevicePairingCode).filter(DevicePairingCode.id == row.id)
     .update({DevicePairingCode.device_id: device.id}, synchronize_session=False))
    append_domain_event(
        db, event_type="computer.device.paired", aggregate_type="device", aggregate_id=device.id,
        payload={"device_id": device.id, "platform": platform}, now=now,
        activity=ActivityProjection(AREA, "device_paired", f"Spárován počítač „{name}“", entity_type="device",
                                    entity_id=device.id, user_context="manual"),
    )
    return device, token


def rename(db: Session, device_id: int, name: str) -> Device:
    device = get_device(db, device_id)
    new = _clean_text(name, 80)
    if not new:
        raise DeviceError(422, "Název nesmí být prázdný.")
    if new != device.name:
        old = device.name
        device.name = new
        log_activity(db, AREA, "device_renamed", f"Počítač „{old}“ přejmenován na „{new}“", entity_type="device",
                     entity_id=device.id, delta={"name": {"old": old, "new": new}}, user_context="manual")
    return device


def revoke(db: Session, device_id: int, now: datetime | None = None) -> Device:
    """Odvolá zařízení: token přestane platit hned, čekající příkazy propadnou. Řádek zůstává (historie příkazů)."""
    now = now or utc_now()
    device = get_device(db, device_id)
    # CAS: souběžné druhé odvolání nic nezapíše ani nevytvoří druhou událost
    if (db.query(Device).filter(Device.id == device.id, Device.revoked_at.is_(None))
            .update({Device.revoked_at: now}, synchronize_session=False)) != 1:
        raise DeviceError(404, "Zařízení neexistuje nebo bylo odvoláno.")
    db.refresh(device)
    pending = (db.query(DeviceCommand)
               .filter(DeviceCommand.device_id == device.id, DeviceCommand.status.in_(("queued", "delivered"))).all())
    for cmd in pending:
        _expire(db, cmd, device, now, "Zařízení bylo odvoláno.")
    append_domain_event(
        db, event_type="computer.device.revoked", aggregate_type="device", aggregate_id=device.id,
        payload={"device_id": device.id}, now=now,
        activity=ActivityProjection(AREA, "device_revoked", f"Odvolán počítač „{device.name}“", entity_type="device",
                                    entity_id=device.id, user_context="manual"),
    )
    return device


# ---------- heartbeat (telemetrie, bez Aktivity) ----------


def _num(value, lo: float, hi: float) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(v, 1) if lo <= v <= hi else None


def sanitize_status(status: dict | None, app_ids: set[str]) -> dict:
    """Jen známá pole s rozumnými mezemi – nic dalšího z PC se neukládá."""
    status = status if isinstance(status, dict) else {}
    disks = []
    for d in (status.get("disks") or [])[:MAX_DISKS]:
        if not isinstance(d, dict):
            continue
        free, total = _num(d.get("free_gb"), 0, 1e6), _num(d.get("total_gb"), 0, 1e6)
        name = _clean_text(d.get("name"), 10)
        if name and free is not None and total:
            disks.append({"name": name, "free_gb": free, "total_gb": total})
    running = [a for a in (status.get("running") or []) if isinstance(a, str) and a in app_ids][:MAX_APPS]
    uptime = _num(status.get("uptime_minutes"), 0, 10_000_000)
    return {"cpu_percent": _num(status.get("cpu_percent"), 0, 100), "ram_percent": _num(status.get("ram_percent"), 0, 100),
            "disks": disks, "running": running, "uptime_minutes": int(uptime) if uptime is not None else None}


def sanitize_apps(apps) -> list[dict]:
    out, seen = [], set()
    for a in (apps or [])[:MAX_APPS]:
        if not isinstance(a, dict):
            continue
        app_id = str(a.get("id") or "").strip().lower()
        name = _clean_text(a.get("name"), 80)
        if APP_ID_RE.match(app_id) and name and app_id not in seen:
            seen.add(app_id)
            out.append({"id": app_id, "name": name})
    return out


def heartbeat(db: Session, device: Device, status: dict | None, apps, agent_version: str | None = None,
              now: datetime | None = None) -> None:
    now = now or utc_now()
    clean_apps = sanitize_apps(apps)
    device.apps = clean_apps
    device.status = sanitize_status(status, {a["id"] for a in clean_apps})
    device.last_seen_at = now
    if agent_version:
        device.agent_version = _clean_text(agent_version, 40)


# ---------- příkazy ----------


def command_label(kind: str, payload: dict, device: Device | None) -> str:
    if kind == "launch_app":
        app_id = payload.get("app_id")
        name = next((a["name"] for a in ((device.apps if device else None) or []) if a.get("id") == app_id),
                    payload.get("app_name") or app_id)
        return f"spustit {name}"
    if kind == "power":
        verb = POWER_ACTIONS.get(payload.get("action"), payload.get("action"))
        delay = int(payload.get("delay_seconds") or 0)
        return f"{verb} za {delay // 60} min" if delay >= 60 else (f"{verb} za {delay} s" if delay else verb)
    if kind == "power_cancel":
        return "zrušit časovač vypnutí"
    return kind


def _validate(device: Device, kind: str, payload: dict | None) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    if kind not in COMMAND_KINDS:
        raise DeviceError(422, "Neznámý příkaz.")
    if kind == "launch_app":
        app_id = str(payload.get("app_id") or "").strip().lower()
        app = next((a for a in (device.apps or []) if a.get("id") == app_id), None)
        if app is None:
            raise DeviceError(422, "Tuhle aplikaci počítač nenahlásil – spustit jde jen aplikace z jeho seznamu.")
        return {"app_id": app_id, "app_name": app["name"]}
    if kind == "power":
        action = str(payload.get("action") or "")
        if action not in POWER_ACTIONS:
            raise DeviceError(422, "Neznámá akce napájení.")
        try:
            delay = int(payload.get("delay_seconds") or 0)
        except (TypeError, ValueError):
            raise DeviceError(422, "Neplatný časovač.")
        if not 0 <= delay <= MAX_DELAY_SECONDS:
            raise DeviceError(422, "Časovač může být nejvýš 4 hodiny.")
        return {"action": action, "delay_seconds": delay}
    return {}


def create_command(db: Session, device_id: int, kind: str, payload: dict | None, *, user_context: str = "manual",
                   now: datetime | None = None) -> DeviceCommand:
    """Zařadí POTVRZENÝ příkaz (tlačítko v Hubu = potvrzení; Jarvis sem jde až po pending akci – MRK-157)."""
    now = now or utc_now()
    expire_stale(db, now)
    device = get_device(db, device_id)
    clean = _validate(device, kind, payload)
    if not is_online(device, now):
        raise DeviceError(409, f"Počítač „{device.name}“ není online – příkaz by nikdo nevyzvedl.")
    cmd = DeviceCommand(device_id=device.id, kind=kind, payload=clean, status="queued", created_at=now,
                        expires_at=now + COMMAND_TTL, user_context=_clean_text(user_context, 20) or None)
    db.add(cmd)
    db.flush()
    log_activity(db, AREA, "command_queued", f"Počítač „{device.name}“: {command_label(kind, clean, device)}",
                 entity_type="device_command", entity_id=cmd.id, user_context=cmd.user_context)
    return cmd


def _transition(db: Session, cmd: DeviceCommand, from_states: tuple[str, ...], values: dict, extra=None) -> bool:
    """Podmíněný přechod stavu (CAS): uspěje jen z očekávaného stavu; jinak se nic nezapíše (souběh vyhrál jiný)."""
    q = db.query(DeviceCommand).filter(DeviceCommand.id == cmd.id, DeviceCommand.status.in_(from_states))
    if extra is not None:
        q = q.filter(extra)
    if q.update(values, synchronize_session=False) != 1:
        return False
    db.refresh(cmd)
    return True


def _expire(db: Session, cmd: DeviceCommand, device: Device | None, now: datetime, reason: str,
            from_states: tuple[str, ...] = ("queued", "delivered")) -> bool:
    if not _transition(db, cmd, from_states, {DeviceCommand.status: "expired", DeviceCommand.completed_at: now,
                                              DeviceCommand.result_message: reason[:300]}):
        return False
    name = device.name if device else "?"
    append_domain_event(
        db, event_type="computer.command.expired", aggregate_type="command", aggregate_id=cmd.id,
        payload={"command_id": cmd.id, "device_id": cmd.device_id, "kind": cmd.kind}, now=now,
        activity=ActivityProjection(AREA, "command_expired",
                                    f"Počítač „{name}“: {command_label(cmd.kind, cmd.payload or {}, device)} – propadlo",
                                    entity_type="device_command", entity_id=cmd.id, user_context="system"),
    )
    return True


def expire_stale(db: Session, now: datetime | None = None) -> int:
    """Propadnou příkazy, které PC nevyzvedlo včas, a vyzvednuté bez výsledku (líně při čtení, bez scheduleru)."""
    now = now or utc_now()
    db.flush()  # session může mít autoflush vypnutý – dotaz musí vidět stav z téže transakce
    rows = (db.query(DeviceCommand)
            .filter(((DeviceCommand.status == "queued") & (DeviceCommand.expires_at <= now))
                    | ((DeviceCommand.status == "delivered") & (DeviceCommand.delivered_at <= now - DELIVERED_TIMEOUT)))
            .all())
    done = 0
    for cmd in rows:
        state = cmd.status
        reason = "PC příkaz nevyzvedlo včas." if state == "queued" else "PC nepotvrdilo provedení."
        done += _expire(db, cmd, db.get(Device, cmd.device_id), now, reason, from_states=(state,))
    return done


def take_commands(db: Session, device: Device, now: datetime | None = None) -> list[dict]:
    """Agent vyzvedne čekající platné příkazy (jen svoje); stav → delivered."""
    now = now or utc_now()
    expire_stale(db, now)
    if not device.last_seen_at or now - device.last_seen_at >= POLL_TOUCH:
        device.last_seen_at = now
    rows = (db.query(DeviceCommand)
            .filter(DeviceCommand.device_id == device.id, DeviceCommand.status == "queued",
                    DeviceCommand.expires_at > now)
            .order_by(DeviceCommand.id).limit(10).all())
    # Atomický claim (review #138): příkaz vrátí jen poll, kterému podmíněný UPDATE queued→delivered změní řádek –
    # dva souběžné polly tak nikdy nedostanou tentýž příkaz (agent by ho provedl dvakrát).
    won = [c for c in rows
           if _transition(db, c, ("queued",), {DeviceCommand.status: "delivered", DeviceCommand.delivered_at: now},
                          extra=DeviceCommand.expires_at > now)]
    return [{"id": c.id, "kind": c.kind, "payload": c.payload or {}, "expires_at": _iso(c.expires_at)} for c in won]


def complete_command(db: Session, device: Device, command_id: int, ok: bool, message: str | None = None,
                     now: datetime | None = None) -> DeviceCommand:
    now = now or utc_now()
    cmd = db.get(DeviceCommand, command_id)
    if cmd is None or cmd.device_id != device.id:
        raise DeviceError(404, "Příkaz neexistuje.")
    values = {DeviceCommand.status: "succeeded" if ok else "failed", DeviceCommand.completed_at: now,
              DeviceCommand.result_message: _clean_text(message, 300) or None}
    if not _transition(db, cmd, ("delivered",), values):
        raise DeviceError(409, "Příkaz už je uzavřený.")
    label = command_label(cmd.kind, cmd.payload or {}, device)
    summary = f"Počítač „{device.name}“: {label} – " + ("hotovo" if ok else f"selhalo{': ' + cmd.result_message if cmd.result_message else ''}")
    append_domain_event(
        db, event_type="computer.command.completed" if ok else "computer.command.failed", aggregate_type="command",
        aggregate_id=cmd.id, payload={"command_id": cmd.id, "device_id": device.id, "kind": cmd.kind}, now=now,
        activity=ActivityProjection(AREA, "command_done" if ok else "command_failed", summary[:300],
                                    entity_type="device_command", entity_id=cmd.id, user_context="system"),
    )
    return cmd
