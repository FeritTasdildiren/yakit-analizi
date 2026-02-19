"""
006: Telegram kullanici tablosu olusturma.

Tablolar: telegram_users

Revision ID: 006_telegram_users
Revises: 005_ml_predictions
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic revision bilgileri
revision = "006_telegram_users"
down_revision = "005_ml_predictions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Telegram kullanici tablosunu olusturur."""

    op.create_table(
        "telegram_users",
        sa.Column("telegram_id", sa.BigInteger(), primary_key=True,
                  comment="Telegram kullanici ID (chat_id)"),
        sa.Column("username", sa.String(255), nullable=True,
                  comment="Telegram kullanici adi"),
        sa.Column("first_name", sa.String(255), nullable=True,
                  comment="Telegram adi"),
        sa.Column("last_name", sa.String(255), nullable=True,
                  comment="Telegram soyadi"),
        sa.Column("phone_number", sa.String(20), nullable=True,
                  comment="Telefon numarasi"),
        sa.Column("is_approved", sa.Boolean(), nullable=False,
                  server_default=sa.text("FALSE"),
                  comment="Admin tarafindan onaylandi mi?"),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("TRUE"),
                  comment="Aktif kullanici mi?"),
        sa.Column("is_admin", sa.Boolean(), nullable=False,
                  server_default=sa.text("FALSE"),
                  comment="Admin yetkisi var mi?"),
        sa.Column("notification_preferences", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False,
                  server_default=sa.text("'{}'::jsonb"),
                  comment="Bildirim tercihleri"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()"),
                  comment="Kayit tarihi"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()"),
                  comment="Son guncelleme tarihi"),
        comment="Telegram bot kullanicilari ve onay durumlari",
    )

    # --- updated_at Trigger ---
    op.execute("""
        CREATE TRIGGER update_telegram_users_updated_at
        BEFORE UPDATE ON telegram_users
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    """Telegram kullanici tablosunu kaldirir."""

    # Trigger'i kaldir
    op.execute(
        "DROP TRIGGER IF EXISTS update_telegram_users_updated_at ON telegram_users;"
    )

    # Tabloyu kaldir
    op.drop_table("telegram_users")
