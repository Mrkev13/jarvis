"""Klient Blizzard Battle.net profile API pro WoW (MRK-127) – jen čtení, jen server.

Konfigurace (env, hodnoty jen na serveru – nikdy v repu, logu ani v odpovědi API):
- `BATTLENET_CLIENT_ID`, `BATTLENET_CLIENT_SECRET` – API client z develop.battle.net (client credentials);
- `WOW_REGION` (`eu` | `us` | `kr` | `tw`, výchozí `eu`);
- `WOW_NAMESPACE` – profile namespace verze hry: retail `profile-eu`, Classic varianty např. `profile-classic1x-eu`,
  `profile-classicann-eu`, WoW: Forever `profile-forever-eu` (výchozí `profile-<region>`). Který zná tvou postavu,
  ověří `backend/scripts/check_battlenet.py` (vypisuje jen stavy);
- `WOW_LOCALE` (výchozí `en_GB` – Blizzard češtinu nemá).

Bezpečnost: HTTPS na pevné hosty Blizzardu, bez přesměrování, timeout, omezená velikost odpovědi. Token se drží jen
v paměti procesu. Chyby nesou jen kód (`BattleNetError.code`), nikdy URL, token ani odpověď serveru.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

import requests

from env_config import env_str

REGIONS = ("eu", "us", "kr", "tw")
NAMESPACE_RE = re.compile(r"^profile(-classic[a-z0-9]*|-forever)?-(eu|us|kr|tw)$")
# MRK-130: WoW Forever nemá realmy (jeden megaserver) – postava = „jméno-příjmení", v DB s tímhle realm_slug.
REALMLESS = "forever"
LOCALE_RE = re.compile(r"^[a-z]{2}_[A-Z]{2}$")
TOKEN_URL = "https://oauth.battle.net/token"
TIMEOUT = 10
MAX_BYTES = 512 * 1024


class BattleNetError(Exception):
    """`code`: not_configured | not_found | unauthorized | rate_limited | unavailable | invalid_response."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Config:
    client_id: str
    client_secret: str
    region: str
    namespace: str
    locale: str

    @property
    def api_host(self) -> str:
        return f"https://{self.region}.api.blizzard.com"


def load_config() -> Config | None:
    """None = WoW API není nastavené (modul pak jen ukáže návod)."""
    client_id, secret = env_str("BATTLENET_CLIENT_ID"), env_str("BATTLENET_CLIENT_SECRET")
    if not client_id or not secret:
        return None
    region = (env_str("WOW_REGION") or "eu").lower()
    if region not in REGIONS:
        return None
    namespace = env_str("WOW_NAMESPACE") or f"profile-{region}"
    if not NAMESPACE_RE.match(namespace) or not namespace.endswith(f"-{region}"):
        return None
    locale = env_str("WOW_LOCALE") or "en_GB"
    if not LOCALE_RE.match(locale):
        locale = "en_GB"
    return Config(client_id, secret, region, namespace, locale)


def config_status() -> dict:
    """Bezpečný popis konfigurace pro UI (žádné hodnoty klíčů)."""
    cfg = load_config()
    if cfg is None:
        return {"configured": False, "region": None, "namespace": None}
    return {"configured": True, "region": cfg.region, "namespace": cfg.namespace}


# Transport je výměnný (testy: fake bez sítě). Signatura jako requests.request.
Transport = Callable[..., Any]

_lock = threading.Lock()
_token: dict[str, Any] = {"value": None, "expires": 0.0, "key": None}


def reset_token_cache() -> None:
    with _lock:
        _token.update(value=None, expires=0.0, key=None)


def _read_json(resp) -> dict:
    body = resp.content if hasattr(resp, "content") else b""
    if body is None or len(body) > MAX_BYTES:
        raise BattleNetError("invalid_response")
    try:
        data = resp.json()
    except Exception:
        raise BattleNetError("invalid_response") from None
    if not isinstance(data, dict):
        raise BattleNetError("invalid_response")
    return data


def _status_error(status: int) -> BattleNetError:
    if status == 404:
        return BattleNetError("not_found")
    if status in (401, 403):
        return BattleNetError("unauthorized")
    if status == 429:
        return BattleNetError("rate_limited")
    return BattleNetError("unavailable")


def _access_token(cfg: Config, transport: Transport, now: Callable[[], float]) -> str:
    key = (cfg.client_id, cfg.region)
    with _lock:
        if _token["value"] and _token["key"] == key and _token["expires"] > now() + 60:
            return _token["value"]
    try:
        resp = transport("POST", TOKEN_URL, auth=(cfg.client_id, cfg.client_secret),
                         data={"grant_type": "client_credentials"}, timeout=TIMEOUT, allow_redirects=False)
    except BattleNetError:
        raise
    except Exception:
        raise BattleNetError("unavailable") from None
    if resp.status_code != 200:
        # 401 z tokenu = špatné client ID / secret
        raise BattleNetError("unauthorized" if resp.status_code in (400, 401, 403) else "unavailable")
    data = _read_json(resp)
    value, expires_in = data.get("access_token"), data.get("expires_in")
    if not isinstance(value, str) or not value or not isinstance(expires_in, (int, float)):
        raise BattleNetError("invalid_response")
    with _lock:
        _token.update(value=value, expires=now() + float(expires_in), key=key)
    return value


class Client:
    def __init__(self, cfg: Config, transport: Transport | None = None, now: Callable[[], float] = time.monotonic):
        self.cfg = cfg
        self.transport = transport or requests.request
        self.now = now

    def _get(self, path: str) -> dict:
        token = _access_token(self.cfg, self.transport, self.now)
        url = f"{self.cfg.api_host}{path}"
        params = {"namespace": self.cfg.namespace, "locale": self.cfg.locale}
        try:
            resp = self.transport("GET", url, params=params, headers={"Authorization": f"Bearer {token}"},
                                  timeout=TIMEOUT, allow_redirects=False)
        except BattleNetError:
            raise
        except Exception:
            raise BattleNetError("unavailable") from None
        if resp.status_code == 401:
            reset_token_cache()  # token mohl vypršet dřív – příště nový
        if resp.status_code != 200:
            raise _status_error(resp.status_code)
        return _read_json(resp)

    @staticmethod
    def _char_path(realm_slug: str, name_key: str) -> str:
        if realm_slug == REALMLESS:  # Forever: /profile/wow/character/{jmeno-prijmeni}
            return f"/profile/wow/character/{quote(name_key, safe='-')}"
        return f"/profile/wow/character/{quote(realm_slug, safe='-')}/{quote(name_key, safe='')}"

    def character(self, realm_slug: str, name_key: str) -> dict:
        return self._get(self._char_path(realm_slug, name_key))

    def professions(self, realm_slug: str, name_key: str) -> dict | None:
        """Profese – ne každý namespace je má (404 = None, ostatní chyby se propagují)."""
        try:
            return self._get(self._char_path(realm_slug, name_key) + "/professions")
        except BattleNetError as err:
            if err.code == "not_found":
                return None
            raise


def client() -> Client | None:
    cfg = load_config()
    return Client(cfg) if cfg else None
