"""Příspěvky modulu Počítač (MRK-155, MRK-157) – REST (`/devices/*` pro uživatele, `/device/agent/*` pro agenta),
„Co se změnilo“ a AI kontext (krátký stav PC – jediný zdroj stavu pro Jarvise). Tool `manage_computer` je
v tool_registry.py (`modules/computer/ai_actions.py`): návrhy příkazů – vždy přes pending akci a potvrzení
(docs/computer.md).
"""
from __future__ import annotations

from context_format import short
from module_contracts import ChangeSource, ContextRequest, ContextSection, ModuleIntegrations, event_changes
from modules.computer import service
from modules.computer.models import Device
from modules.computer.router import agent_router, router
from modules.computer.service import EVENTS
from time_utils import utc_now

# „Co se změnilo“: párování / odvolání PC a výsledky příkazů
CHANGES = ChangeSource("computer", from_event=event_changes({"device": "/devices", "command": "/devices"}, {
    "computer.device.paired": "Spárován počítač", "computer.device.revoked": "Odvolán počítač",
    "computer.command.completed": "Příkaz pro počítač proveden", "computer.command.failed": "Příkaz pro počítač selhal",
    "computer.command.expired": "Příkaz pro počítač propadl",
}))

# Slova pro routing toolů (bez diakritiky, hledá se jako podřetězec ve „ text “) – rozkazy pro PC i dotazy na stav.
KEYWORDS = ("pocitac", " pc ", " pc?", " pc,", " pc.", "notebook", "spust", " pust ", "vypni", "vypnout", "vypnuti",
            "uspi ", "uspat", "uspani", "zamkni", "zamknout", "zamknuti", "zapni ", "jarvis pro pc")


def context_computer(req: ContextRequest) -> list[str]:
    """Stav spárovaných PC z posledního heartbeatu (bez sítě, bez LLM)."""
    now = utc_now()
    lines = []
    for d in req.db.query(Device).filter(Device.revoked_at.is_(None)).order_by(Device.id).limit(3):
        apps = {a["id"]: a["name"] for a in (d.apps or [])}
        running = [apps.get(a, a) for a in ((d.status or {}).get("running") or [])]
        state = "online" if service.is_online(d, now) else "offline"
        parts = [f"Počítač „{short(d.name, 30)}“: {state}"]
        if running:
            parts.append("běží " + ", ".join(short(r, 25) for r in running[:5]))
        if apps:
            parts.append("umí spustit " + ", ".join(short(n, 25) for n in list(apps.values())[:10]))
        last = service.list_commands(req.db, d.id, 1)
        if last:
            c = last[0]
            parts.append(f"poslední příkaz {short(c['label'], 40)}: {c['status']}")
        lines.append("; ".join(parts))
    return lines or ["Počítač: žádný spárovaný (stránka Počítač → Spárovat)."]


INTEGRATIONS = ModuleIntegrations(
    changes=(CHANGES,),
    context=(ContextSection("computer", KEYWORDS, order=95, build=context_computer),),
    routers=(router, agent_router),
)

__all__ = ["EVENTS", "INTEGRATIONS"]
