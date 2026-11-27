"""computer_devices

MRK-155: Jarvis na PC – spárovaná zařízení (`devices`, v DB jen hash tokenu), jednorázové párovací kódy
(`device_pairing_codes`, jen hash) a fronta potvrzených příkazů (`device_commands`). Jen aditivní; downgrade
tabulky zahodí (párování by se muselo zopakovat, ostatní data Hubu se nemění).

Revision ID: 0037_computer_devices
Revises: 0036_wot_stats_snapshots
"""
from alembic import op
import sqlalchemy as sa

revision = "0037_computer_devices"
down_revision = "0036_wot_stats_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("agent_version", sa.String(length=40), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.JSON(), nullable=True),
        sa.Column("apps", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_devices_id"), "devices", ["id"], unique=False)
    op.create_table(
        "device_pairing_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index(op.f("ix_device_pairing_codes_id"), "device_pairing_codes", ["id"], unique=False)
    op.create_table(
        "device_commands",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("result_message", sa.String(length=300), nullable=True),
        sa.Column("user_context", sa.String(length=20), nullable=True),
        sa.CheckConstraint("kind IN ('launch_app', 'power', 'power_cancel')", name="ck_device_commands_kind"),
        sa.CheckConstraint("status IN ('queued', 'delivered', 'succeeded', 'failed', 'expired')",
                           name="ck_device_commands_status"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_device_commands_id"), "device_commands", ["id"], unique=False)
    op.create_index("ix_device_commands_device_status", "device_commands", ["device_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_device_commands_device_status", table_name="device_commands")
    op.drop_index(op.f("ix_device_commands_id"), table_name="device_commands")
    op.drop_table("device_commands")
    op.drop_index(op.f("ix_device_pairing_codes_id"), table_name="device_pairing_codes")
    op.drop_table("device_pairing_codes")
    op.drop_index(op.f("ix_devices_id"), table_name="devices")
    op.drop_table("devices")
