"""Trading (MRK-141): přehled paper tradingu z read-only API stacku standa-trading. Bez DB, bez LLM.

Čte stejný konektor jako notifikace (MRK-140, `trading_notifications.fetch_json`): `/health`, `/report`, `/summary`.
Z odpovědí se vezmou jen známá pole (whitelist) – nic syrového se nepřeposílá. Výpadek / špatný klíč / jiný tvar
odpovědi = stav s čitelnou zprávou, nikdy výjimka ven ani URL / klíč v odpovědi.

Finance do AI nejde (MRK-60): modul nemá AI kontext ani tooly; data jsou jen pro stránku.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Callable
from urllib.parse import quote

import trading_notifications as tn
from time_utils import today_local

MAX_FILLS = 50
MAX_SIGNALS = 50
MAX_RUNS = 10
EQUITY_DAYS = 90
MAX_EQUITY_POINTS = 400
MAX_POSITIONS = 100
MAX_ORDERS = 30
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
Fetch = Callable[[str], object]


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _text(value, limit: int = 60) -> str | None:
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def _strategies(rep: dict, summary: list) -> list[dict]:
    """Účty z reportu (kapitál, výnos) doplněné stavem ze summary (aktivní / vypnutá pojistkou)."""
    state = {a.get("name"): a for a in summary if isinstance(a, dict) and isinstance(a.get("name"), str)}
    rows: dict[str, dict] = {}
    for a in [*(rep.get("accounts") or []), *summary]:
        if not isinstance(a, dict) or not isinstance(a.get("name"), str):
            continue
        name = a["name"][:60]
        row = rows.setdefault(name, {"name": name, "label": "SPY (benchmark)" if name == tn.BENCHMARK else name,
                                     "benchmark": name == tn.BENCHMARK, "total": None, "return_pct": None,
                                     "active": True, "disabled_reason": None})
        if row["total"] is None:
            row["total"] = _num(a.get("total"))
        if row["return_pct"] is None:
            row["return_pct"] = _num(a.get("return_pct"))
        src = state.get(name, a)
        if "active" in src:
            row["active"] = bool(src.get("active"))
        row["disabled_reason"] = _text(src.get("disabled_reason"), 200) or row["disabled_reason"]
    bench = rows.get(tn.BENCHMARK)
    for row in rows.values():
        row["vs_spy"] = (round(row["return_pct"] - bench["return_pct"], 4)
                         if bench and not row["benchmark"] and row["return_pct"] is not None
                         and bench["return_pct"] is not None else None)
    # nejlepší strategie nahoře, benchmark vždy poslední (je to měřítko, ne strategie)
    return sorted(rows.values(), key=lambda r: (r["benchmark"], -(r["return_pct"] if r["return_pct"] is not None else -1e9),
                                                r["name"]))


def _fills(rep: dict) -> list[dict]:
    out = []
    for f in (rep.get("fills") or [])[:MAX_FILLS]:
        if not isinstance(f, dict) or f.get("side") not in ("buy", "sell") or not _text(f.get("symbol"), 20):
            continue
        out.append({"strategy": _text(f.get("strategy")), "side": f["side"], "symbol": _text(f["symbol"], 20),
                    "qty": _num(f.get("qty"))})
    return out


def _signals(rep: dict) -> list[dict]:
    out = []
    for s in (rep.get("signals") or [])[:MAX_SIGNALS]:
        if not isinstance(s, dict) or not _text(s.get("symbol"), 20):
            continue
        out.append({"strategy": _text(s.get("strategy")), "action": _text(s.get("action"), 20),
                    "symbol": _text(s["symbol"], 20)})
    return out


def _health(h: dict, today: date) -> dict:
    data_until = h.get("data_until")
    until = tn._api_date(data_until) if data_until is not None else None
    runs = []
    for r in (h.get("last_runs") or [])[:MAX_RUNS]:
        if isinstance(r, dict) and _text(r.get("job")):
            at = next((_text(r.get(k), 40) for k in ("finished_at", "at", "started_at") if _text(r.get(k), 40)), None)
            runs.append({"job": _text(r.get("job")), "status": _text(r.get("status"), 20), "at": at})
    return {"ok": bool(h.get("ok")), "data_until": until.isoformat() if until else None,
            "stale": bool(until and (today - until).days > tn.STALE_DATA_DAYS), "runs": runs}


def _day(value) -> str | None:
    """YYYY-MM-DD jen když je to opravdu datum; jinak None (nic se nehádá)."""
    try:
        return tn._api_date(value).isoformat()
    except (TypeError, ValueError):
        return None


def _equity(rows) -> list[dict]:
    """`/equity/{strategie}` → denní body kapitálu a drawdownu, seřazené podle data."""
    if not isinstance(rows, list):
        raise TypeError("equity")
    out = []
    for r in rows[-MAX_EQUITY_POINTS:]:
        d = _day(r.get("date")) if isinstance(r, dict) else None
        total = _num(r.get("total")) if isinstance(r, dict) else None
        if d and total is not None:
            out.append({"date": d, "total": total, "drawdown_pct": _num(r.get("drawdown_pct"))})
    return sorted(out, key=lambda p: p["date"])


def _positions(rows) -> list[dict]:
    if not isinstance(rows, list):
        raise TypeError("positions")
    out = []
    for p in rows[:MAX_POSITIONS]:
        if not isinstance(p, dict) or not _text(p.get("symbol"), 20):
            continue
        out.append({"strategy": _text(p.get("strategy")), "symbol": _text(p["symbol"], 20), "qty": _num(p.get("qty")),
                    "avg_price": _num(p.get("avg_price")), "last_close": _num(p.get("last_close")),
                    "opened_date": _day(p.get("opened_date")), "last_date": _day(p.get("last_date")),
                    "pnl_pct": _num(p.get("pnl_pct")), "pnl_usd": _num(p.get("pnl_usd"))})
    return out


def _orders(rows) -> list[dict]:
    if not isinstance(rows, list):
        raise TypeError("orders")
    out = []
    for o in rows[:MAX_ORDERS]:
        if not isinstance(o, dict) or o.get("side") not in ("buy", "sell") or not _text(o.get("symbol"), 20):
            continue
        out.append({"id": o.get("id") if isinstance(o.get("id"), int) else None, "strategy": _text(o.get("strategy")),
                    "side": o["side"], "symbol": _text(o["symbol"], 20), "qty": _num(o.get("qty")),
                    "created_date": _day(o.get("created_date")), "fill_date": _day(o.get("fill_date")),
                    "fill_price": _num(o.get("fill_price")), "fee": _num(o.get("fee"))})
    return out


def _optional(fetch: Fetch, path: str, parse):
    """Doplňková data (graf, pozice, pokyny): výpadek / jiný tvar jen vynechá sekci, přehled zůstane."""
    try:
        return parse(fetch(path))
    except (tn.TradingApiError, TypeError, ValueError, KeyError, AttributeError):
        return None


def parse_report_date(raw: str | None) -> str | None:
    """`?date=` stránky → YYYY-MM-DD, nebo ValueError (REST vrátí 400)."""
    if raw in (None, ""):
        return None
    if not isinstance(raw, str) or not DATE_RE.match(raw):
        raise ValueError("date")
    return date.fromisoformat(raw).isoformat()


def overview(*, fetch: Fetch | None = None, today: date | None = None, report_date: str | None = None) -> dict:
    """Celý přehled pro stránku. `fetch` jen pro testy (jinak HTTP konektor). `report_date` = report za daný den
    (`/report?date=`); jinak poslední."""
    if fetch is None:
        if not tn.is_configured():
            return {"configured": False, "status": "not_configured"}
        fetch = tn.fetch_json
    today = today or today_local()
    try:
        h, summary = fetch("/health"), fetch("/summary")
        rep = fetch(f"/report?date={report_date}" if report_date else "/report")
    except tn.TradingApiError as e:
        return {"configured": True, "status": "unavailable", "message": str(e)}
    try:
        if not isinstance(h, dict) or not isinstance(rep, dict) or not isinstance(summary, list):
            raise TypeError("unexpected response shape")
        rep_date = rep.get("date")
        report_date = tn._api_date(rep_date).isoformat() if rep_date is not None else None
        strategies = _strategies(rep, summary)
        best = next((s for s in strategies if not s["benchmark"] and s["vs_spy"] is not None), None)
        out = {
            "configured": True, "status": "ok", "health": _health(h, today), "report_date": report_date,
            "strategies": strategies, "fills": _fills(rep), "signals": _signals(rep),
            "best": best["name"] if best else None,
        }
    except (TypeError, ValueError, KeyError, AttributeError):
        return {"configured": True, "status": "invalid", "message": tn.INVALID_RESPONSE}
    # MRK-141: doplňky z dalších endpointů – každý zvlášť, výpadek jen skryje svou sekci
    equity = {s["name"]: _optional(fetch, f"/equity/{quote(s['name'], safe='')}?days={EQUITY_DAYS}", _equity)
              for s in strategies}
    out["equity"] = {k: v for k, v in equity.items() if v}
    out["positions"] = _optional(fetch, "/positions", _positions)
    out["orders_pending"] = _optional(fetch, "/orders?status=pending", _orders)
    out["orders_filled"] = _optional(fetch, "/orders?status=filled", _orders)
    return out
