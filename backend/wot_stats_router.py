"""REST statistik WoT (MRK-153) – `/wot/stats`. Auth a brána vypnutého modulu WoT platí automaticky (router se
připojuje přes `ModuleIntegrations.routers`). Jen čtení uložených snímků, žádné volání Wargaming API."""
from __future__ import annotations

from fastapi import APIRouter

import database
import wot_stats_service as service

router = APIRouter(prefix="/wot/stats", tags=["wot"])


@router.get("")
def wot_stats(period: str = "week"):
    db = database.SessionLocal()
    try:
        return service.stats(db, period)
    finally:
        db.close()
