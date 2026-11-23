"""Modely WoW (MRK-127). Registrují se do společné `Base` (models.py je importuje), migrace 0031.

Postava = jméno + realm, které Standa sleduje. Údaje (level, třída, item level, profese) jsou snapshot z Blizzard API
(Battle.net profile API) s časem poslední synchronizace; výpadek API nechá poslední známý stav.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String, Text, UniqueConstraint

from database import Base

SYNC_STATES = ("pending", "ok", "not_found", "error")


class WowCharacter(Base):
    __tablename__ = "wow_characters"
    __table_args__ = (
        UniqueConstraint("realm_slug", "name_key", name="uq_wow_characters_realm_name"),
        CheckConstraint("sync_status IN ('pending', 'ok', 'not_found', 'error')", name="ck_wow_characters_sync_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(24), nullable=False)          # jak ho Standa zadal / jak ho vrátí API
    name_key = Column(String(24), nullable=False)      # malými písmeny (cesta v API)
    realm_slug = Column(String(64), nullable=False)    # „golemagg", „pyrewood-village"
    realm_name = Column(String(64), nullable=True)
    target_level = Column(Integer, nullable=True)      # cíl Standy („alt na 60")
    level = Column(Integer, nullable=True)
    class_name = Column(String(40), nullable=True)
    race_name = Column(String(40), nullable=True)
    faction = Column(String(20), nullable=True)
    active_spec = Column(String(40), nullable=True)
    item_level = Column(Integer, nullable=True)        # jen když ho namespace nabízí
    professions_json = Column(Text, nullable=True)     # [{"name": "Mining", "skill": 150, "max": 300}]
    last_login_at = Column(DateTime, nullable=True)    # naive UTC
    sync_status = Column(String(20), nullable=False, default="pending")
    last_synced_at = Column(DateTime, nullable=True)   # poslední ÚSPĚŠNÁ synchronizace
    last_attempt_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
