"""REST Tradingu (MRK-141) – `GET /trading`. Auth a brána vypnutého modulu (404) platí automaticky (router se
připojuje přes `ModuleIntegrations.routers`). Jen čtení, žádný zápis do standa-trading."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from modules.trading import service

router = APIRouter(prefix="/trading", tags=["trading"])


@router.get("")
def trading_overview(date: str | None = None):
    """`?date=YYYY-MM-DD` = report za daný obchodní den (jinak poslední)."""
    try:
        report_date = service.parse_report_date(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Datum reportu ve tvaru RRRR-MM-DD.") from None
    return service.overview(report_date=report_date)
