"""MRK-140: notifikace z paper tradingu (externí stack standa-trading, read-only API).

Konektor jen čte (home-server.md §4): `GET /health`, `/report`, `/summary` s hlavičkou `X-API-Key`.
Výsledkem jsou kandidáti pro `notifications_service.generate_notifications`:

  * `trading_report`  – denní report (info), 1× za obchodní den, vyprší po 4 dnech (páteční přes víkend)
  * `trading_alert`   – strategie vypnutá pojistkou na drawdown (important), vyprší po 14 dnech
  * `trading_health`  – API nedostupné / špatný klíč / chyba běhu / stará data (warning); samo se vyřeší
                        v `_resolve_if_no_longer_relevant`, jakmile je zase vše v pořádku

Oblast je `finance`, takže je `finance_ai_policy.is_finance_notification` odfiltruje z AI (MRK-60).
Bez `TRADING_API_URL` modul nic nedělá. Výpadek konektoru = „zdroj nedostupný“, nikdy výjimka ven.
Neplatná odpověď (jiný tvar, nečitelné datum…) je taky výpadek: vrátí `trading_health`, nikdy prázdný seznam –
prázdný výsledek by `_resolve_if_no_longer_relevant` vyhodnotil jako zotavení a upozornění by zmizelo.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from typing import Callable

from env_config import env_str

log = logging.getLogger(__name__)

AREA = "finance"
SOURCE_TYPE = "trading"
ACTION_URL = "/finance"
BENCHMARK = "buy_hold_spy"
TIMEOUT_S = 5
STALE_DATA_DAYS = 5          # pátek → středa ráno je ještě v pořádku (prodloužený víkend)
REPORT_MAX_AGE_DAYS = 4      # starší report už nevytvářet (např. po výpadku Hubu)
REPORT_TTL_DAYS = 4
ALERT_TTL_DAYS = 14
MAX_LISTED_FILLS = 6

TRADING_NOTIFICATION_TYPES = frozenset({"trading_report", "trading_alert", "trading_health"})
HEALTH_KEY = "trading_health"
INVALID_RESPONSE = "Trading API vrátilo neplatnou odpověď – stav paper tradingu nejde ověřit."

Fetch = Callable[[str], object]


class TradingApiError(Exception):
    """Zdroj nedostupný – text je bezpečný pro zobrazení (žádné URL ani klíč)."""


def _http_get(path: str) -> object:
    base = env_str("TRADING_API_URL").rstrip("/")
    req = urllib.request.Request(f"{base}{path}", headers={"X-API-Key": env_str("TRADING_API_KEY")})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise TradingApiError(
                "Trading API odmítá klíč – zkontroluj TRADING_API_KEY v .env Hubu i standa-trading.") from None
        raise TradingApiError(f"Trading API vrátilo chybu {e.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise TradingApiError(
            f"Trading API neodpovídá ({e.__class__.__name__}). Zkontroluj kontejnery standa-trading.") from None


def _api_date(value) -> date:
    """Datum z API jen jako text YYYY-MM-DD (fromisoformat by bral i „20261123“ a podobné tvary)."""
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("invalid date")
    return date.fromisoformat(value)


def is_configured() -> bool:
    return bool(env_str("TRADING_API_URL"))


def _usd(x) -> str:
    return f"{float(x):,.0f}".replace(",", " ") + " USD"


def _pct(x) -> str:
    return f"{float(x):+.2f} %".replace(".", ",")


def _label(name: str) -> str:
    return "SPY (benchmark)" if name == BENCHMARK else name


def report_message(rep: dict) -> str:
    accounts = [a for a in rep.get("accounts", []) if a.get("total") is not None]
    bench = next((a for a in accounts if a.get("name") == BENCHMARK), None)

    lines = []
    for a in accounts:
        line = f"{_label(a['name'])}: {_usd(a['total'])} ({_pct(a['return_pct'])})"
        if bench and a["name"] != BENCHMARK:
            line += f", vs SPY {_pct(float(a['return_pct']) - float(bench['return_pct']))}"
        lines.append(line)

    fills = rep.get("fills") or []
    if fills:
        shown = [
            f"{'nákup' if f['side'] == 'buy' else 'prodej'} {f['qty']}× {f['symbol']} ({f['strategy']})"
            for f in fills[:MAX_LISTED_FILLS]
        ]
        more = f" a dalších {len(fills) - MAX_LISTED_FILLS}" if len(fills) > MAX_LISTED_FILLS else ""
        lines.append("Obchody: " + ", ".join(shown) + more + ".")
    else:
        lines.append("Žádné obchody.")

    signals = len(rep.get("signals") or [])
    if signals:
        lines.append(f"Nové signály na další obchodní den: {signals}.")
    return "\n".join(lines)


def health_candidate(candidate_cls, message: str):
    """Upozornění na nedostupný / neověřitelný trading. Používá ho i notifications_service při nečekané chybě."""
    return candidate_cls(dedupe_key=HEALTH_KEY, area=AREA, title="Paper trading: problém", message=message,
                         severity="warning", notification_type="trading_health", source_type=SOURCE_TYPE,
                         source_id=None, action_url=ACTION_URL, expires_at=None)


def trading_candidates(candidate_cls, today: date, fetch: Fetch | None = None) -> list:
    """Kandidáti notifikací. `candidate_cls` = NotificationCandidate (předává se zvenku kvůli kruhovému importu),
    `fetch` jen pro testy (jinak HTTP). Při nastaveném API nikdy nevrátí „nic“ kvůli chybě – vždy health."""
    if fetch is None:
        if not is_configured():
            return []
        fetch = _http_get

    try:
        h = fetch("/health")
        rep = fetch("/report")
        summary = fetch("/summary")
    except TradingApiError as e:
        log.warning("trading notifications: %s", e)
        return [health_candidate(candidate_cls, str(e))]

    try:
        if not isinstance(h, dict) or not isinstance(rep, dict) or not isinstance(summary, list):
            raise TypeError("unexpected response shape")
        return _candidates_from(candidate_cls, today, h, rep, summary)
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        log.warning("trading notifications: invalid API response (%s)", e.__class__.__name__)
        return [health_candidate(candidate_cls, INVALID_RESPONSE)]


def _candidates_from(candidate_cls, today: date, h: dict, rep: dict, summary: list) -> list:
    def cand(**kw):
        return candidate_cls(area=AREA, source_type=SOURCE_TYPE, source_id=None, action_url=ACTION_URL, **kw)

    def health(message: str):
        return health_candidate(candidate_cls, message)

    out = []

    # ── Zdraví ──
    if not h.get("ok"):
        job = next((r.get("job") for r in h.get("last_runs", []) if r.get("status") == "error"), "?")
        out.append(health(f"Poslední běh '{job}' v standa-trading skončil chybou (docker compose logs worker)."))
    data_until = h.get("data_until")
    if data_until is not None and (today - _api_date(data_until)).days > STALE_DATA_DAYS:
        out.append(health(f"Data jsou stará – poslední svíčka {data_until}. Sběr dat asi neběží."))
    # Dva problémy najednou → jedna notifikace (stejný dedupe_key), zprávy spojené.
    health_items = [c for c in out if c.notification_type == "trading_health"]
    if len(health_items) > 1:
        out = [health(" ".join(c.message for c in health_items))]

    # ── Denní report ──
    rep_date = rep.get("date")
    d = _api_date(rep_date) if rep_date is not None else None
    if d is not None and (today - d).days <= REPORT_MAX_AGE_DAYS:
        out.append(cand(
            dedupe_key=f"trading_report:{d.isoformat()}", title=f"Paper trading {d.day}. {d.month}.",
            message=report_message(rep), severity="info", notification_type="trading_report",
            expires_at=datetime.combine(d, datetime.min.time()) + timedelta(days=REPORT_TTL_DAYS),
        ))

    # ── Strategie vypnutá pojistkou ──
    for a in summary:
        reason = a.get("disabled_reason") or ""
        if not a.get("active") and "drawdown" in reason:
            out.append(cand(
                dedupe_key=f"trading_disabled:{a['name']}", title=f"Strategie {a['name']} vypnuta",
                message=f"Pojistka: {reason}. Pozice byly prodány.", severity="important",
                notification_type="trading_alert",
                expires_at=datetime.combine(today, datetime.min.time()) + timedelta(days=ALERT_TTL_DAYS),
            ))
    return out
