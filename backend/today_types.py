"""Sdílené typy režimu Dnes (MRK-20) – list grafu importů, aby je mohli používat poskytovatelé modulů
(`*_integrations.py`) bez importu today_service (ten importuje registr modulů → cyklus)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class TodayItem:
    """Normalizovaná položka (jen pro režim Dnes – žádný univerzální model entit)."""
    id: str                      # ref záznamu „reminder:5" / u upozornění bez záznamu „notification:9"
    type: str                    # reminder | exam | assignment | planner | notification
    title: str
    subtitle: str = ""
    area: str | None = None
    date: str | None = None      # pražské datum (ISO)
    time: str | None = None      # pražský čas „HH:MM" nebo None (celý den)
    status: str = "open"         # upcoming | due | past | done | overdue | open
    priority: int | None = None  # pořadí z denního plánu
    severity: str | None = None  # important | warning | info (upozornění)
    href: str | None = None
    source_id: int | None = None
    # Roadmap 4H: co jde udělat přímo z řádku (jen id akcí, žádné URL ani příkazy):
    # complete (připomínka / úkol), snooze (připomínka), record_result (zkouška → otevřít záznam).
    actions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class TodayContext:
    db: Any
    now_utc: datetime
    today: date
    now_local_naive: datetime
    # Mezivýsledky poskytovatelů v rámci jednoho požadavku (např. názvy předmětů pro školu).
    cache: dict[str, Any] = field(default_factory=dict)


UPCOMING_DAYS = 7
