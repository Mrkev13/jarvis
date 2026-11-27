"""Modely modulu Počítač (MRK-155). Registrují se do společné `Base` (models.py je importuje), migrace 0037.

- `Device` – spárovaný počítač s agentem Jarvise. V DB je jen SHA-256 hash tokenu zařízení. Odvolání nastaví
  `revoked_at` (token okamžitě přestane platit); řádek se nemaže – příkazy na něj odkazují (historie).
- `DevicePairingCode` – jednorázový párovací kód (v DB jen hash), platí 10 minut, použije se jednou.
- `DeviceCommand` – potvrzený příkaz pro počítač s krátkou platností; agent si ho vyzvedne a nahlásí výsledek.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String

from database import Base

COMMAND_KINDS = ("launch_app", "power", "power_cancel")
COMMAND_STATES = ("queued", "delivered", "succeeded", "failed", "expired")


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(80), nullable=False)
    platform = Column(String(20), nullable=False, default="windows")
    agent_version = Column(String(40), nullable=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    status = Column(JSON, nullable=True)  # poslední heartbeat (vytížení, disky, co běží) – přepisuje se, bez historie
    apps = Column(JSON, nullable=True)    # aplikace, které agent umí spustit: [{"id", "name"}]


class DevicePairingCode(Base):
    __tablename__ = "device_pairing_codes"

    id = Column(Integer, primary_key=True, index=True)
    code_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="RESTRICT"), nullable=True)


class DeviceCommand(Base):
    __tablename__ = "device_commands"
    __table_args__ = (
        Index("ix_device_commands_device_status", "device_id", "status"),
        CheckConstraint("kind IN ('launch_app', 'power', 'power_cancel')", name="ck_device_commands_kind"),
        CheckConstraint("status IN ('queued', 'delivered', 'succeeded', 'failed', 'expired')",
                        name="ck_device_commands_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False)
    kind = Column(String(20), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="queued")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    delivered_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    result_message = Column(String(300), nullable=True)
    user_context = Column(String(20), nullable=True)
