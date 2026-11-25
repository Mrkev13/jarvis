"""Příspěvky Tradingu (MRK-141) – jen REST stránky. Žádné vyhledávání, Dnes, AI kontext ani tooly: trading je
oblast financí a finance do AI nejde (MRK-60, finance_ai_policy.py). Notifikace řeší notifications_service (MRK-140)."""
from __future__ import annotations

from module_contracts import ModuleIntegrations
from modules.trading.router import router

INTEGRATIONS = ModuleIntegrations(routers=(router,))
