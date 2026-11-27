"""MRK-105: zdroje WoT (kredity, zlato, volné XP, bondy) automaticky z Wargaming API přes propojený účet.

Průběh: `/wot` → „Propojit s Wargamingem“ → `start_login` (jednorázový `state` + allowlistovaný origin z
`FRONTEND_ORIGINS`) → přihlášení u Wargamingu → návrat na `<origin>/wot/connect/<state>?status=ok&access_token=…` →
stránka pošle parametry na `POST /wot/account/connect` → `connect` ověří state, token hned vyzkouší (`account/info`
private) a uloží ho zašifrovaný (`WOT_TOKEN_KEY`, Fernet). Scheduler (hodinově) a tlačítko volají `sync`: token
před koncem platnosti prodlouží (`auth/prolongate`), načte zdroje a zapíše je s `source="wargaming"`.

Bezpečnost: token nikdy v odpovědi API, logu (access log redaguje `access_token`, viz `redact_access_log`), Aktivitě
ani AI kontextu; chyby jen jako kód. Vypršelý / zrušený token = stav „expired“ a výzva k novému přihlášení.
Ruční zápis zdrojů (`POST /wot/resource`) zůstává jako záloha.
"""
from __future__ import annotations

import logging
import re
import secrets
import threading
import time as _time
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

import wot_mastery_service
import wot_stats_service
import wot_wargaming
from activity_service import log_activity
from env_config import env_str
from models import WotAccountLink, WotResource
from text_utils import format_num_cz
from time_utils import utc_now

RESOURCE_KEYS = ("credits", "gold", "free_xp", "bonds")
LABELS = {"credits": "Credits", "gold": "Gold", "free_xp": "Free XP", "bonds": "Bonds"}
SOURCE = "wargaming"
STATE_TTL_SECONDS = 600
PROLONG_BEFORE = timedelta(days=3)
SYNC_EVERY = timedelta(minutes=50)  # hodinový scheduler + otevření stránky nezdvojí požadavky
STATE_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")

ERROR_TEXT = {
    **{k: v for k, v in wot_mastery_service.ERROR_TEXT.items() if k not in ("not_found", "private")},
    "not_found": "Wargaming účet se nenašel.",
    "key_missing": "Na serveru chybí WOT_TOKEN_KEY – bez něj se přihlášení k Wargamingu neuloží.",
    "token_invalid": "Přihlášení k Wargamingu vypršelo nebo bylo zrušeno – propoj účet znovu.",
    "bad_state": "Odkaz z přihlášení je neplatný nebo starý – zkus propojení znovu.",
    "cancelled": "Přihlášení u Wargamingu bylo zrušeno.",
    "bad_origin": "Adresa Hubu není v FRONTEND_ORIGINS.",
}


class AccountError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status
        self.message = ERROR_TEXT.get(code, "Propojení s Wargamingem se nepovedlo.")


# ---------- šifrování tokenu ----------


def _fernet() -> Fernet | None:
    key = env_str("WOT_TOKEN_KEY").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        return None


def _encrypt(token: str) -> str:
    f = _fernet()
    if f is None:
        raise AccountError("key_missing", 503)
    return f.encrypt(token.encode()).decode()


def _decrypt(link: WotAccountLink) -> str | None:
    f = _fernet()
    if f is None:
        return None
    try:
        return f.decrypt(link.token_enc.encode()).decode()
    except (InvalidToken, ValueError):
        return None


# ---------- jednorázový state přihlášení (v paměti, jeden worker) ----------

_states: dict[str, tuple[float, str]] = {}
_states_lock = threading.Lock()


def _allowed_origins() -> set[str]:
    raw = env_str("FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    return {o.strip().rstrip("/") for o in raw.split(",") if o.strip()}


def start_login(origin: str, client: wot_wargaming.Client | None, monotonic=_time.monotonic) -> dict:
    """→ {location}: adresa přihlášení u Wargamingu. Návrat jen na allowlistovaný origin Hubu."""
    if client is None:
        raise AccountError("not_configured", 503)
    if _fernet() is None:
        raise AccountError("key_missing", 503)
    origin = (origin or "").strip().rstrip("/")
    if origin not in _allowed_origins():
        raise AccountError("bad_origin")
    state = secrets.token_urlsafe(24)
    now = monotonic()
    with _states_lock:
        for k in [k for k, (exp, _) in _states.items() if exp < now]:
            del _states[k]
        _states[state] = (now + STATE_TTL_SECONDS, origin)
    return {"location": client.login_url(f"{origin}/wot/connect/{state}")}


def _take_state(state: str, monotonic=_time.monotonic) -> bool:
    if not isinstance(state, str) or not STATE_RE.match(state):
        return False
    with _states_lock:
        item = _states.pop(state, None)
    return item is not None and item[0] >= monotonic()


# ---------- propojení ----------


def _link(db: Session) -> WotAccountLink | None:
    return db.query(WotAccountLink).order_by(WotAccountLink.id).first()


def _from_unix(value: int) -> datetime:
    return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)


def connect(db: Session, data: dict, client: wot_wargaming.Client | None, now: datetime | None = None,
            monotonic=_time.monotonic) -> dict:
    """Návrat z přihlášení. Nic necommituje (volající)."""
    now = now or utc_now()
    if client is None:
        raise AccountError("not_configured", 503)
    if not _take_state(data.get("state"), monotonic):
        raise AccountError("bad_state")
    if data.get("status") != "ok":
        raise AccountError("cancelled")
    token, account_id, expires = data.get("access_token"), data.get("account_id"), data.get("expires_at")
    try:
        account_id, expires = int(account_id), int(expires)
    except (TypeError, ValueError):
        raise AccountError("invalid_response") from None
    if not isinstance(token, str) or not 10 <= len(token) <= 200 or account_id <= 0:
        raise AccountError("invalid_response")
    token_enc = _encrypt(token)
    try:
        values = client.private_resources(account_id, token)  # token hned ověří (patří k účtu, platí)
    except wot_wargaming.WargamingError as exc:
        raise AccountError(exc.code, 502 if exc.code in ("unavailable", "rate_limited") else 400) from None
    link = _link(db)
    if link is None:
        link = WotAccountLink(connected_at=now)
        db.add(link)
    link.account_id, link.token_enc, link.expires_at = account_id, token_enc, _from_unix(expires)
    link.status, link.last_error, link.connected_at, link.last_sync_at = "connected", None, now, now
    db.flush()
    log_activity(db, "wot", "update", "WoT: účet propojen s Wargamingem – zdroje se budou načítat samy",
                 entity_type="WotAccountLink", entity_id=link.id, user_context="manual")
    _apply(db, values, now, "manual")
    wot_stats_service.record_resources(db, values, now)  # MRK-153
    return status(db, client)


def disconnect(db: Session, client: wot_wargaming.Client | None) -> dict:
    link = _link(db)
    if link is None:
        return status(db, client)
    token = _decrypt(link)
    if client is not None and token and link.status == "connected":
        try:
            client.logout(token)
        except wot_wargaming.WargamingError:
            pass  # odhlášení je jen zdvořilost – token stejně zapomeneme
    log_activity(db, "wot", "delete", "WoT: propojení s Wargamingem zrušeno (zdroje zůstávají, dál ručně)",
                 entity_type="WotAccountLink", entity_id=link.id, user_context="manual")
    db.delete(link)
    db.flush()
    return status(db, client)


# ---------- synchronizace ----------


def _apply(db: Session, values: dict, now: datetime, user_context: str) -> list[str]:
    changes = []
    existing = {r.resource: r for r in db.query(WotResource).filter(WotResource.resource.in_(RESOURCE_KEYS))}
    for key in RESOURCE_KEYS:
        value = values.get(key)
        if value is None:
            continue
        row = existing.get(key)
        if row is None:
            row = WotResource(resource=key, amount=float(value))
            db.add(row)
            changes.append(f"{LABELS[key]} {format_num_cz(value)}")
        elif float(row.amount or 0) != float(value):
            changes.append(f"{LABELS[key]} {format_num_cz(row.amount or 0)} → {format_num_cz(value)}")
            row.amount = float(value)
        row.source, row.updated_at = SOURCE, now
    db.flush()
    if changes:
        log_activity(db, "wot", "update", "WoT zdroje z Wargamingu: " + ", ".join(changes),
                     entity_type="WotResource", user_context=user_context,
                     dedupe_key=f"wot-resources-sync:{now.isoformat()}")
    return changes


def _cas(db: Session, link: WotAccountLink, snapshot: str, values: dict, *, connected_only: bool = False) -> bool:
    """Zápis přihlašovacích údajů jen proti verzi tokenu, kterou tento běh načetl (compare-and-set). Souběžný běh
    (scheduler, otevření /wot, ruční sync, nové propojení) mezitím mohl token prodloužit nebo vyměnit – pak se nic
    nepřepíše a starý token nesmí zneplatnit novou verzi propojení."""
    q = db.query(WotAccountLink).filter(WotAccountLink.id == link.id, WotAccountLink.token_enc == snapshot)
    if connected_only:
        q = q.filter(WotAccountLink.status == "connected")
    won = q.update(values, synchronize_session=False) == 1
    db.flush()
    db.expire(link)
    return won


def _expire(db: Session, link: WotAccountLink, snapshot: str) -> dict:
    link_id, connected_at = link.id, link.connected_at
    if not _cas(db, link, snapshot, {"status": "expired", "last_error": "token_invalid"}, connected_only=True):
        return {"result": "superseded"}
    log_activity(db, "wot", "update", "WoT: přihlášení k Wargamingu vypršelo – propoj účet znovu",
                 entity_type="WotAccountLink", entity_id=link_id, user_context="system",
                 dedupe_key=f"wot-token-expired:{link_id}:{connected_at.isoformat()}")
    return {"result": "token_invalid"}


def sync(db: Session, client: wot_wargaming.Client | None, now: datetime | None = None, force: bool = False,
         user_context: str = "scheduler") -> dict:
    """→ {result: ok | skipped | not_connected | superseded | <kód chyby>, changes?}. Nic necommituje.
    `superseded` = jiný běh mezitím token prodloužil / vyměnil; tento běh nic nepřepsal."""
    now = now or utc_now()
    link = _link(db)
    if link is None or link.status != "connected":
        return {"result": "not_connected"}
    if client is None:
        return {"result": "not_configured"}
    if not force and link.last_sync_at and now - link.last_sync_at < SYNC_EVERY:
        return {"result": "skipped"}
    snapshot, account_id, expires_at = link.token_enc, int(link.account_id), link.expires_at
    token = _decrypt(link)
    if token is None:  # chybí / změnil se WOT_TOKEN_KEY → token nejde přečíst
        _cas(db, link, snapshot, {"last_error": "key_missing"})
        return {"result": "key_missing"}
    if expires_at <= now:
        return _expire(db, link, snapshot)
    try:
        if expires_at - now < PROLONG_BEFORE:
            token, expires = client.prolongate(token)
            new_enc = _encrypt(token)
            if not _cas(db, link, snapshot, {"token_enc": new_enc, "expires_at": _from_unix(expires)}, connected_only=True):
                return {"result": "superseded"}
            snapshot = new_enc
        values = client.private_resources(account_id, token)
    except wot_wargaming.WargamingError as exc:
        if exc.code == "token_invalid":
            return _expire(db, link, snapshot)
        _cas(db, link, snapshot, {"last_error": exc.code})
        return {"result": exc.code}
    # odpověď patří k verzi propojení, kterou běh načetl – mezitím nové propojení / odpojení = nic nezapisovat
    if not _cas(db, link, snapshot, {"last_sync_at": now, "last_error": None}, connected_only=True):
        return {"result": "superseded"}
    changes = _apply(db, values, now, user_context)
    wot_stats_service.record_resources(db, values, now)  # MRK-153: zdroje v čase (jen při změně)
    return {"result": "ok", "changes": len(changes)}


# ---------- čtení ----------


def _iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def status(db: Session, client: wot_wargaming.Client | None) -> dict:
    """Stav pro UI – nikdy token ani account_id."""
    link = _link(db)
    rows = {r.resource: r for r in db.query(WotResource).filter(WotResource.resource.in_(RESOURCE_KEYS))}
    error = link.last_error if link else None
    return {
        "configured": client is not None and _fernet() is not None,
        "missing": [n for n, ok in (("WG_APPLICATION_ID", client is not None), ("WOT_TOKEN_KEY", _fernet() is not None))
                    if not ok],
        "connected": link is not None and link.status == "connected",
        "status": link.status if link else "not_connected",
        "expires_at": _iso(link.expires_at) if link else None,
        "last_sync_at": _iso(link.last_sync_at) if link else None,
        "error": error, "error_text": ERROR_TEXT.get(error) if error else None,
        "resources": {k: {"amount": rows[k].amount, "source": rows[k].source, "updated_at": _iso(rows[k].updated_at)}
                      for k in RESOURCE_KEYS if k in rows},
    }


# ---------- access log bez tokenu ----------

_TOKEN_RE = re.compile(r"(access_token=)[^&\s\"']+")


class _RedactTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_TOKEN_RE.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str):
            record.msg = _TOKEN_RE.sub(r"\1***", record.msg)
        return True


def redact_access_log() -> None:
    """Pojistka: kdyby `access_token` někdy prošel v URL (např. ruční pokus), uvicorn ho do access logu nezapíše."""
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, _RedactTokens) for f in logger.filters):
            logger.addFilter(_RedactTokens())
