"""wow_character_media

MRK-139: WoW hrdinské karty – URL avataru a celého renderu postavy z Blizzard API (character-media). Jen dva nové
nullable sloupce; downgrade je odebere (data jsou jen kopie z API, obnoví je další synchronizace).

Revision ID: 0032_wow_character_media
Revises: 0031_wow_characters
"""
from alembic import op
import sqlalchemy as sa

revision = "0032_wow_character_media"
down_revision = "0031_wow_characters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("wow_characters", sa.Column("avatar_url", sa.String(length=500), nullable=True))
    op.add_column("wow_characters", sa.Column("render_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("wow_characters", "render_url")
    op.drop_column("wow_characters", "avatar_url")
