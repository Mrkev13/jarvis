"""AI nástroj `save_memory` s druhem a platností (MRK-117) – resolver + executor, mimo obří ai.py / tools.py.

Jarvis smí navrhnout dočasnou vzpomínku („tento týden jsem nemocný") s platností. `expires_at` zadává jako pražský
čas (`YYYY-MM-DD` = do konce toho dne, nebo `YYYY-MM-DDTHH:MM`); do DB jde naive UTC (time_utils.local_to_utc).
Zápis dál jen přes pending akci → potvrzení → audit (ai.prepare_write_action / execute_confirm_action).
"""
from __future__ import annotations

from datetime import datetime, time

import memory_service
import tools
from mutation_service import MutationRefused
from statuses import MEMORY_KINDS
from time_utils import local_to_utc, utc_now


def parse_expires_local(value) -> datetime | None:
    """„2026-11-30" → konec dne v Praze; „2026-11-30T18:00" → ten čas. Výsledek naive UTC; None = bez platnosti."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        if len(text) == 10:
            local = datetime.combine(datetime.strptime(text, "%Y-%m-%d").date(), time(23, 59))
        else:
            local = datetime.strptime(text[:16], "%Y-%m-%dT%H:%M")
    except ValueError:
        raise MutationRefused("invalid_expires_at", "expires_at musí být YYYY-MM-DD nebo YYYY-MM-DDTHH:MM (pražský čas).") from None
    return local_to_utc(local)


def _validated(kind, expires_at, now: datetime | None = None) -> tuple[str, datetime | None]:
    expires = parse_expires_local(expires_at)
    if expires is not None and expires <= (now or utc_now()):
        raise MutationRefused("expires_in_past", "Platnost vzpomínky musí být v budoucnosti.")
    if kind not in (None, "") and str(kind).strip().lower() not in MEMORY_KINDS:
        raise MutationRefused("invalid_kind", f"kind musí být jeden z: {', '.join(MEMORY_KINDS)}.")
    try:
        return memory_service.validate_kind(kind, expires), expires
    except memory_service.MemoryError as err:
        # temporary bez platnosti: model se má doptat, do kdy vzpomínka platí
        raise MutationRefused("missing_expires_at", str(err)) from None


def prepare_save_memory(db, area: str = "general", category: str = "context", content: str = "", importance: int = 5,
                        active: bool = True, kind=None, expires_at=None):
    """Resolver: jen kontrola (druh, platnost v budoucnu). None = argumenty se uloží tak, jak jsou."""
    _validated(kind, expires_at)
    return None


def run_save_memory(area: str = "general", category: str = "context", content: str = "", importance: int = 5,
                    active: bool = True, kind=None, expires_at=None, plan=None, user_context: str = "manual"):
    """Executor po potvrzení: platnost znovu převedená (a ověřená – mohla mezitím vypršet)."""
    kind, expires = _validated(kind, expires_at)
    return tools.save_memory(area=area, category=category, content=content, importance=importance, active=active,
                             kind=kind, expires_at=expires, user_context=user_context)
