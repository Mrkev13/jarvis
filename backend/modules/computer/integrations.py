"""Příspěvky modulu Počítač (MRK-155) – zatím jen REST (`/devices/*` pro uživatele, `/device/agent/*` pro agenta).

Stránka Počítač a AI tooly přijdou s MRK-157; tady je backendový základ: párování,
stav, fronta potvrzených příkazů a jejich události v „Co se změnilo“ (docs/computer.md).
"""
from __future__ import annotations

from module_contracts import ChangeSource, ModuleIntegrations, event_changes
from modules.computer.router import agent_router, router
from modules.computer.service import EVENTS

# „Co se změnilo“: párování / odvolání PC a výsledky příkazů (odkaz na stránku přijde s MRK-157)
CHANGES = ChangeSource("computer", from_event=event_changes({}, {
    "computer.device.paired": "Spárován počítač", "computer.device.revoked": "Odvolán počítač",
    "computer.command.completed": "Příkaz pro počítač proveden", "computer.command.failed": "Příkaz pro počítač selhal",
    "computer.command.expired": "Příkaz pro počítač propadl",
}))

INTEGRATIONS = ModuleIntegrations(changes=(CHANGES,), routers=(router, agent_router))

__all__ = ["EVENTS", "INTEGRATIONS"]
