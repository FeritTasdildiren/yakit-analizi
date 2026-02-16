"""
Telegram kullanici modeli.

telegram_users tablosu: Telegram bot kullanicilarinin bilgilerini,
onay durumunu ve bildirim tercihlerini saklar.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class TelegramUser(Base):
    """Telegram kullanici tablosu."""

    __tablename__ = "telegram_users"

    # --- Birincil Anahtar ---
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        comment="Telegram kullanici ID (chat_id)",
    )

    # --- Kimlik Bilgileri ---
    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Telegram kullanici adi",
    )

    first_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Telegram adi",
    )

    last_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Telegram soyadi",
    )

    phone_number: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="Telefon numarasi",
    )

    # --- Durum Bilgileri ---
    is_approved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
        comment="Admin tarafindan onaylandi mi?",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("TRUE"),
        comment="Aktif kullanici mi?",
    )

    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
        comment="Admin yetkisi var mi?",
    )

    # --- Tercihler ---
    notification_preferences: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Bildirim tercihleri (fuel_types, alert_levels vs.)",
    )

    # --- Zaman Damgalari ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="Kayit tarihi",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        onupdate=text("NOW()"),
        comment="Son guncelleme tarihi",
    )

    # --- Meta ---
    __table_args__ = (
        {"comment": "Telegram bot kullanicilari ve onay durumlari"},
    )

    def __repr__(self) -> str:
        return (
            f"<TelegramUser(id={self.telegram_id}, "
            f"username={self.username}, "
            f"approved={self.is_approved})>"
        )
