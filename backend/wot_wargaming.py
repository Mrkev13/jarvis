"""Klient Wargaming API pro World of Tanks (MRK-106) – jen čtení VEŘEJNÝCH dat účtu, jen server.

Konfigurace (env, hodnoty jen na serveru – nikdy v repu, logu ani v odpovědi API):
- `WG_APPLICATION_ID` – aplikace z developers.wargaming.net (stejná jako pro obrázky tanků, docs/game-assets.md);
- `WG_REGION` (`eu` | `na` | `asia`, výchozí `eu`);
- `WOT_NICKNAME` – přezdívka hráče; `account_id` se dohledá přes `account/list` (type=exact).

Použité metody (developers.wargaming.net, ověřeno 2026-11-24): `account/list`, `tanks/stats` (`mark_of_mastery`
0 = žádný, 1 = 3. třída, 2 = 2. třída, 3 = 1. třída, 4 = Ace Tanker – jen NEJVYŠŠÍ odznak, ne počet) a
`encyclopedia/vehicles` (název, tag, tier, národ). Veřejná data: stačí `application_id`, žádný `access_token`.

MRK-105 – SOUKROMÁ data účtu (kredity, zlato, volné XP, bondy) přes Wargaming OpenID (ověřeno 2026-11-27):
`auth/login` (prohlížeč, `redirect_uri` dostane `status`, `access_token`, `expires_at`, `account_id`), `account/info`
s `access_token` (`private.credits|gold|free_xp|bonds`), `auth/prolongate` (POST, nový token, nejvýš 2 týdny) a
`auth/logout` (POST). Token posílá jen tento modul a jen v těle / parametrech požadavku na pevný host.

Bezpečnost: HTTPS na pevné hosty, bez přesměrování, timeout, omezená velikost odpovědi. Chyby nesou jen kód
(`WargamingError.code`), nikdy URL (obsahuje application_id) ani odpověď serveru.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

import requests

from env_config import env_str

HOSTS = {"eu": "api.worldoftanks.eu", "na": "api.worldoftanks.com", "asia": "api.worldoftanks.asia"}
APP_ID_RE = re.compile(r"^[0-9a-f]{16,64}$")
NICKNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,24}$")
TIMEOUT = 15
MAX_BYTES = 4 * 1024 * 1024
VEHICLE_BATCH = 100  # encyclopedia/vehicles: nejvýš 100 tank_id na požadavek


class WargamingError(Exception):
    """`code`: not_configured | not_found | unauthorized | rate_limited | unavailable | invalid_response | private |
    token_invalid (MRK-105: vypršelý / zrušený access_token)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Config:
    application_id: str
    region: str
    nickname: str

    @property
    def api_root(self) -> str:
        return f"https://{HOSTS[self.region]}/wot"


def load_config() -> Config | None:
    """None = Wargaming API není nastavené (stránka pak jen ukáže návod, ruční M-ka fungují dál)."""
    app_id = env_str("WG_APPLICATION_ID").strip().lower()
    nickname = env_str("WOT_NICKNAME").strip()
    region = (env_str("WG_REGION") or "eu").strip().lower()
    if not APP_ID_RE.match(app_id) or not NICKNAME_RE.match(nickname) or region not in HOSTS:
        return None
    return Config(app_id, region, nickname)


def config_status() -> dict:
    """Bezpečný popis pro UI – bez application_id i přezdívky."""
    cfg = load_config()
    return {"configured": cfg is not None, "region": cfg.region if cfg else None}


Transport = Callable[..., Any]

# kódy chyb Wargaming API (`error.message`) → náš kód
_API_ERRORS = {
    "INVALID_APPLICATION_ID": "unauthorized", "APPLICATION_IS_BLOCKED": "unauthorized",
    "INVALID_IP_ADDRESS": "unauthorized", "REQUEST_LIMIT_EXCEEDED": "rate_limited",
    "SOURCE_NOT_AVAILABLE": "unavailable", "ACCOUNT_ID_NOT_SPECIFIED": "not_found",
    "INVALID_ACCOUNT_ID": "not_found", "INVALID_ACCESS_TOKEN": "token_invalid",
}
TOKEN_TTL_SECONDS = 14 * 24 * 3600  # nejvíc, co auth/login i auth/prolongate dovolí


class Client:
    def __init__(self, cfg: Config, transport: Transport | None = None):
        self.cfg = cfg
        self.transport = transport or requests.request

    def _get(self, method: str, params: dict, http: str = "GET") -> Any:
        url = f"{self.cfg.api_root}/{method}/"
        payload = {"application_id": self.cfg.application_id, **params}
        try:
            if http == "POST":  # token v těle, ne v URL
                resp = self.transport("POST", url, data=payload, timeout=TIMEOUT, allow_redirects=False)
            else:
                resp = self.transport("GET", url, params=payload, timeout=TIMEOUT, allow_redirects=False)
        except WargamingError:
            raise
        except Exception:
            raise WargamingError("unavailable") from None
        if resp.status_code == 429:
            raise WargamingError("rate_limited")
        if resp.status_code != 200:
            raise WargamingError("unavailable")
        body = resp.content if hasattr(resp, "content") else b""
        if body is None or len(body) > MAX_BYTES:
            raise WargamingError("invalid_response")
        try:
            data = resp.json()
        except Exception:
            raise WargamingError("invalid_response") from None
        if not isinstance(data, dict):
            raise WargamingError("invalid_response")
        if data.get("status") == "error":
            err = data.get("error") if isinstance(data.get("error"), dict) else {}
            raise WargamingError(_API_ERRORS.get(str(err.get("message", "")), "invalid_response"))
        if data.get("status") != "ok" or "data" not in data:
            raise WargamingError("invalid_response")
        return data["data"]

    def account_id(self) -> int:
        """Přesná shoda přezdívky (bez ohledu na velikost písmen, jak ji vrací API)."""
        rows = self._get("account/list", {"search": self.cfg.nickname, "type": "exact", "fields": "account_id,nickname"})
        if not isinstance(rows, list):
            raise WargamingError("invalid_response")
        for row in rows:
            if (isinstance(row, dict) and isinstance(row.get("account_id"), int)
                    and str(row.get("nickname", "")).lower() == self.cfg.nickname.lower()):
                return row["account_id"]
        raise WargamingError("not_found")

    def tank_stats(self, account_id: int) -> list[dict]:
        """→ [{tank_id, mark_of_mastery, battles}] všech odehraných tanků. Skrytý profil (data null) = `private`."""
        data = self._get("tanks/stats", {"account_id": str(account_id),
                                         "fields": "tank_id,mark_of_mastery,all.battles"})
        rows = data.get(str(account_id)) if isinstance(data, dict) else None
        if rows is None:
            raise WargamingError("private")
        if not isinstance(rows, list):
            raise WargamingError("invalid_response")
        out = []
        for r in rows:
            if not isinstance(r, dict) or not _int(r.get("tank_id")):
                continue
            mastery = r.get("mark_of_mastery")
            battles = (r.get("all") or {}).get("battles") if isinstance(r.get("all"), dict) else None
            out.append({"tank_id": r["tank_id"], "mark_of_mastery": mastery if mastery in (0, 1, 2, 3, 4) else 0,
                        "battles": battles if _int(battles) is not None else None})
        return out

    # ---------- MRK-105: soukromá data přes access_token ----------

    def login_url(self, redirect_uri: str) -> str:
        """Adresa přihlášení Wargaming OpenID, kam se přesměruje prohlížeč (bez síťového volání)."""
        from urllib.parse import urlencode
        query = urlencode({"application_id": self.cfg.application_id, "redirect_uri": redirect_uri,
                           "expires_at": TOKEN_TTL_SECONDS, "display": "page"})
        return f"{self.cfg.api_root}/auth/login/?{query}"

    def private_resources(self, account_id: int, access_token: str) -> dict[str, int | None]:
        """→ {credits, gold, free_xp, bonds}. `private` null = token nepatří k účtu / neplatí → token_invalid."""
        data = self._get("account/info", {"account_id": str(account_id), "access_token": access_token,
                                          "fields": "private.credits,private.gold,private.free_xp,private.bonds"},
                         http="POST")
        row = data.get(str(account_id)) if isinstance(data, dict) else None
        if row is None:
            raise WargamingError("not_found")
        private = row.get("private") if isinstance(row, dict) else None
        if not isinstance(private, dict):
            raise WargamingError("token_invalid")
        return {k: _int(private.get(k)) for k in ("credits", "gold", "free_xp", "bonds")}

    def prolongate(self, access_token: str) -> tuple[str, int]:
        """Nový token (platnost nejvýš 2 týdny) → (access_token, expires_at UNIX)."""
        data = self._get("auth/prolongate", {"access_token": access_token, "expires_at": TOKEN_TTL_SECONDS}, http="POST")
        token = data.get("access_token") if isinstance(data, dict) else None
        expires = _int(data.get("expires_at"), 1, 2**40) if isinstance(data, dict) else None  # UNIX > 10^9
        if not isinstance(token, str) or not token or len(token) > 200 or not expires:
            raise WargamingError("invalid_response")
        return token, expires

    def logout(self, access_token: str) -> None:
        self._get("auth/logout", {"access_token": access_token}, http="POST")

    def vehicles(self, tank_ids: list[int]) -> dict[int, dict]:
        """Tankopedie pro dané tanky (po dávkách) → {tank_id: {name, short_name, tag, tier, nation, type}}."""
        out: dict[int, dict] = {}
        for i in range(0, len(tank_ids), VEHICLE_BATCH):
            chunk = tank_ids[i:i + VEHICLE_BATCH]
            data = self._get("encyclopedia/vehicles", {"tank_id": ",".join(str(t) for t in chunk),
                                                       "fields": "tank_id,name,short_name,tag,tier,nation,type"})
            if not isinstance(data, dict):
                raise WargamingError("invalid_response")
            for key, v in data.items():
                if isinstance(v, dict) and str(key).isdigit():
                    out[int(key)] = {
                        "name": _text(v.get("name"), 100), "short_name": _text(v.get("short_name"), 60),
                        "tag": _text(v.get("tag"), 100), "tier": v.get("tier") if _int(v.get("tier"), 1, 11) else None,
                        "nation": _text(v.get("nation"), 20), "type": _text(v.get("type"), 20),
                    }
        return out


def _int(value, lo: int = 0, hi: int = 10**9) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi else None


def _text(value, limit: int) -> str | None:
    return value.strip()[:limit] or None if isinstance(value, str) and value.strip() else None


def client() -> Client | None:
    cfg = load_config()
    return Client(cfg) if cfg else None
