"""Modely WoW (MRK-127). Registrují se do společné `Base` (models.py je importuje), migrace 0031.

Postava = jméno + realm, které Standa sleduje. Údaje (level, třída, item level, profese) jsou snapshot z Blizzard API
(Battle.net profile API) s časem poslední synchronizace; výpadek API nechá poslední známý stav.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, Date, DateTime, Integer, String, Text, UniqueConstraint

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
    # MRK-139 (migrace 0032): obrázky z Blizzard character-media – jen URL z oficiálních hostů render.worldofwarcraft.com
    avatar_url = Column(String(500), nullable=True)
    render_url = Column(String(500), nullable=True)
    last_login_at = Column(DateTime, nullable=True)    # naive UTC
    sync_status = Column(String(20), nullable=False, default="pending")
    last_synced_at = Column(DateTime, nullable=True)   # poslední ÚSPĚŠNÁ synchronizace
    last_attempt_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------- MRK-128: sbírky (migrace 0033) ----------

WISH_KINDS = ("mount", "pet", "achievement")


class WowCollectionSnapshot(Base):
    """Denní snapshot sbírky účtu (mounti a pets jsou v API účtové, bere se první postava se stavem `ok`).

    Jeden řádek na den (Europe/Prague); další synchronizace téhož dne ho přepíše. None = endpoint data nedal.
    """
    __tablename__ = "wow_collection_snapshots"
    __table_args__ = (UniqueConstraint("day", name="uq_wow_collection_snapshots_day"),)

    id = Column(Integer, primary_key=True, index=True)
    day = Column(Date, nullable=False)
    mounts = Column(Integer, nullable=True)
    pets = Column(Integer, nullable=True)
    achievements = Column(Integer, nullable=True)        # počet dokončených
    achievement_points = Column(Integer, nullable=True)
    source_character_id = Column(Integer, nullable=True)  # bez FK – postava jde přestat sledovat, historie zůstává
    updated_at = Column(DateTime, nullable=False)         # naive UTC


class WowWish(Base):
    """Seznam „chci získat“. Položka se odškrtne sama, když ji API ukáže v sbírce (shoda názvu bez velikosti písmen)."""
    __tablename__ = "wow_wishes"
    __table_args__ = (
        UniqueConstraint("kind", "name_key", name="uq_wow_wishes_kind_name"),
        CheckConstraint("kind IN ('mount', 'pet', 'achievement')", name="ck_wow_wishes_kind"),
    )

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(20), nullable=False)
    name = Column(String(120), nullable=False)
    name_key = Column(String(120), nullable=False)
    acquired_at = Column(DateTime, nullable=True)          # naive UTC; None = ještě chybí
    created_at = Column(DateTime, nullable=False)
