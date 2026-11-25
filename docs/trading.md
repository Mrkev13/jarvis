# Trading (MRK-141)

Read-only stránka paper tradingu ze samostatného stacku **standa-trading** (strategie SMA / EMA proti SPY).
Modul `trading` (`backend/modules/trading/`, `frontend/modules/trading/`), stránka `/trading` ve skupině „Další“.
Hub nic neobchoduje: jen čte.

## Data

Stejný konektor jako notifikace (MRK-140, `backend/trading_notifications.py`, `fetch_json`).
Čte `GET /health`, `/report` a `/summary` s hlavičkou `X-API-Key`. `modules/trading/service.overview` vezme jen
známá pole (whitelist):

- **strategie** z `report.accounts` + stav ze `summary`: kapitál, výnos, rozdíl proti `buy_hold_spy`, aktivní /
  vypnutá pojistkou s důvodem. Seřazené podle výnosu, benchmark vždy poslední.
- **obchody** posledního obchodního dne (`fills`, jen `buy` / `sell`) a **signály** na další den.
- **zdraví**: `ok`, data do, „stará data“ (víc než 5 dní, stejné pravidlo jako notifikace), poslední běhy úloh.

Doplňky z dalších endpointů API (Standa, 2026-11-25). Každý zvlášť: výpadek nebo jiný tvar skryje jen svou sekci,
přehled zůstane:

| Endpoint | Na stránce |
| --- | --- |
| `/equity/{strategie}?days=90` → `[{date, total, drawdown_pct}]` | **Vývoj kapitálu**: graf všech strategií proti SPY (jedna osa USD, SPY šedý čárkovaný, barva podle jména strategie), legenda s max drawdownem, hodnoty dne při najetí, tabulka hodnot |
| `/positions` → `[{strategy, symbol, qty, avg_price, last_close, pnl_pct, pnl_usd, …}]` | **Otevřené pozice** + souhrn P&L po strategiích |
| `/orders?status=pending` / `filled` → `[{id, strategy, side, symbol, qty, created_date, fill_date, fill_price, fee, …}]` | **Čekající pokyny** a **Historie obchodů** (posledních 30) |
| `/report?date=YYYY-MM-DD` | výběr dne reportu (`GET /trading?date=`, neplatné datum = 400) |

Žádná tabulka, žádná migrace. Každé otevření stránky čte API znovu (3 povinné požadavky + kapitál pro každou
strategii, pozice a 2× pokyny; timeout 5 s každý).

## Stavy

| `status` | Kdy | Stránka |
| --- | --- | --- |
| `ok` | API odpovědělo | přehled |
| `not_configured` | chybí `TRADING_API_URL` | návod k nastavení |
| `unavailable` | výpadek, 401, chyba HTTP | „Paper trading teď nejde ověřit“ + zpráva konektoru |
| `invalid` | jiný tvar odpovědi | totéž, `INVALID_RESPONSE` |

Zprávy nikdy neobsahují URL ani klíč.

## Konfigurace

`.env.production` (jen server), stejné jako MRK-140: `TRADING_API_URL` (v Docker síti `http://trading-api:8000`)
a `TRADING_API_KEY`.

## AI

Trading je oblast financí, a **finance do AI nejde** (MRK-60). Modul nemá `ai_context`, kontextovou sekci ani tooly.
Hlídá to test `test_module_has_no_ai_surface`. Notifikace z tradingu AI filtruje už `finance_ai_policy`.

## Navazuje

- Karta na Řídicím centru: až bude jasné, co z tradingu chceš vidět denně.
- Zrušené pokyny (`/orders?status=cancelled` s `cancel_reason`), pokud budou zajímavé.
