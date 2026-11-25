"""REST Tradingu (MRK-141) – `GET /trading`. Auth a brána vypnutého modulu (404) platí automaticky (router se
připojuje přes `ModuleIntegrations.routers`). Jen čtení, žádný zápis do standa-trading."""
from __future__ import annotations

from fastapi import APIRouter

from modules.trading import service

router = APIRouter(prefix="/trading", tags=["trading"])


@router.get("")
def trading_overview():
    return service.overview()
