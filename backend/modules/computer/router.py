"""REST modulu Počítač (MRK-155).

- `/devices/*` – pro uživatele (session auth a brána vypnutého modulu platí automaticky, viz main.require_auth).
- `/device/agent/*` – pro agenta na PC. Session cookie tu nestačí: každý požadavek kromě párování musí nést
  `Authorization: Bearer <token zařízení>`. main.require_auth tuhle cestu propouští právě proto, že ji hlídá
  `require_device` níže; token zařízení naopak jinde neplatí (require_auth čte jen session cookie).
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

import database
from auth_service import client_ip
from modules.computer import service
from time_utils import utc_now

AGENT_PREFIX = "/device/agent"
router = APIRouter(prefix="/devices", tags=["computer"])
agent_router = APIRouter(prefix=AGENT_PREFIX, tags=["computer-agent"])

PAIR_FAILURES_MAX = 5
PAIR_FAILURE_WINDOW = 600.0
MAX_WAIT_SECONDS = 25
_pair_failures: dict[str, deque] = defaultdict(deque)


def _run(fn):
    db = database.SessionLocal()
    try:
        result = fn(db)
        db.commit()
        return result
    except service.DeviceError as err:
        db.rollback()
        raise HTTPException(status_code=err.status, detail=err.message)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------- uživatel (session) ----------


class RenameBody(BaseModel):
    name: str


class CommandBody(BaseModel):
    kind: str
    payload: dict | None = None


@router.get("")
def devices_list():
    def go(db):
        now = utc_now()
        service.expire_stale(db, now)
        return {"devices": service.list_devices(db, now)}
    return _run(go)


@router.post("/pairing-code")
def devices_pairing_code():
    return _run(lambda db: service.create_pairing_code(db))


@router.patch("/{device_id}")
def devices_rename(device_id: int, body: RenameBody):
    return _run(lambda db: {"ok": True, "device": service.device_dict(service.rename(db, device_id, body.name), utc_now())})


@router.post("/{device_id}/revoke")
def devices_revoke(device_id: int):
    return _run(lambda db: {"ok": True, "revoked": service.revoke(db, device_id).revoked_at is not None})


@router.get("/{device_id}/commands")
def devices_commands(device_id: int, limit: int = 20):
    def go(db):
        service.expire_stale(db)
        service.get_device(db, device_id, active=False)
        return {"commands": service.list_commands(db, device_id, limit)}
    return _run(go)


@router.post("/{device_id}/commands")
def devices_command_create(device_id: int, body: CommandBody):
    return _run(lambda db: {"ok": True, "command": service.command_dict(
        service.create_command(db, device_id, body.kind, body.payload, user_context="manual"))})


# ---------- agent (token zařízení) ----------


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def require_device(request: Request) -> str:
    """Ověří token zařízení (bez něj 401). Vrací token – handler si zařízení načte ve vlastní session."""
    token = _bearer(request)
    db = database.SessionLocal()
    try:
        if service.authenticate(db, token) is None:
            raise HTTPException(status_code=401, detail="Neplatný nebo odvolaný token zařízení.")
    finally:
        db.close()
    return token


def _device(db, token: str):
    device = service.authenticate(db, token)
    if device is None:  # odvoláno mezi ověřením a zápisem
        raise service.DeviceError(401, "Neplatný nebo odvolaný token zařízení.")
    return device


class PairBody(BaseModel):
    code: str
    name: str = ""
    platform: str = "windows"
    agent_version: str | None = None


class HeartbeatBody(BaseModel):
    status: dict | None = None
    apps: list | None = None
    agent_version: str | None = None


class ResultBody(BaseModel):
    ok: bool
    message: str | None = None


def _pair_limited(ip: str, now: float) -> bool:
    q = _pair_failures[ip]
    while q and now - q[0] > PAIR_FAILURE_WINDOW:
        q.popleft()
    return len(q) >= PAIR_FAILURES_MAX


@agent_router.post("/pair")
def agent_pair(body: PairBody, request: Request):
    ip = client_ip(getattr(request.client, "host", None) if request.client else None,
                   request.headers.get("x-forwarded-for"))
    now = time.monotonic()
    if _pair_limited(ip, now):
        raise HTTPException(status_code=429, detail="Příliš mnoho neplatných kódů – zkus to za 10 minut.")

    def go(db):
        device, token = service.pair(db, body.code, body.name, body.platform, body.agent_version)
        return {"device_id": device.id, "name": device.name, "token": token}

    try:
        result = _run(go)
    except HTTPException as err:
        if err.status_code == 401:
            _pair_failures[ip].append(now)
        raise
    _pair_failures.pop(ip, None)
    return result


@agent_router.post("/heartbeat")
def agent_heartbeat(body: HeartbeatBody, token: str = Depends(require_device)):
    def go(db):
        service.heartbeat(db, _device(db, token), body.status, body.apps, body.agent_version)
        return {"ok": True, "server_time": utc_now().isoformat() + "Z"}
    return _run(go)


@agent_router.get("/commands")
async def agent_commands(wait: int = 0, token: str = Depends(require_device)):
    """Long-poll: vrátí čekající příkazy hned, jinak čeká nejvýš `wait` s (0–25) a kontroluje každou sekundu."""
    deadline = time.monotonic() + max(0, min(int(wait), MAX_WAIT_SECONDS))
    while True:
        commands = await run_in_threadpool(_run, lambda db: service.take_commands(db, _device(db, token)))
        if commands or time.monotonic() >= deadline:
            return {"commands": commands}
        await asyncio.sleep(1)


@agent_router.post("/commands/{command_id}/result")
def agent_command_result(command_id: int, body: ResultBody, token: str = Depends(require_device)):
    def go(db):
        cmd = service.complete_command(db, _device(db, token), command_id, body.ok, body.message)
        return {"ok": True, "status": cmd.status}
    return _run(go)
