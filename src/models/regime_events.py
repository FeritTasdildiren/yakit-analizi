"""
Politik/ekonomik/takvimsel rejim olayları modeli.

regime_events tablosu: seçim, bayram, ekonomik kriz, vergi değişikliği,
jeopolitik gerilim gibi olayları tanımlar. Her olay bir etki skoru (0-10)
ve aktiflik durumu taşır.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, regime_type_enum


class RegimeEvent(Base):
    """Politik/ekonomik rejim olayları tablosu."""

    __tablename__ = "regime_events"

    # --- Birincil Anahtar ---
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Otomatik artan birincil anahtar",
    )

    # --- Olay Bilgileri ---
    event_type: Mapped[str] = mapped_column(
        regime_type_enum,
        nullable=False,
        comment="Olay tipi: election, holiday, economic_crisis, tax_change, geopolitical, other",
    )

    event_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Olay adı (ör: 2026 Yerel Seçimler, Kurban Bayramı)",
    )

    start_date: Mapped[datetime] = mapped_column(
        Date,
        nullable=False,
        comment="Olayın başlangıç tarihi",
    )

    end_date: Mapped[datetime] = mapped_column(
        Date,
        nullable=False,
        comment="Olayın bitiş tarihi",
    )

    impact_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Etki skoru (0-10 arası, 10 = en yüksek etki)",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("TRUE"),
        comment="Olay aktif mi (devam ediyor mu)?",
    )

    source: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default="manual",
        comment="Veri kaynağı (manual, api, scraper)",
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Olay hakkında ek açıklama",
    )

    # --- Zaman Damgaları ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="Kayıt oluşturulma zamanı",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        onupdate=text("NOW()"),
        comment="Son güncelleme zamanı",
    )

    # --- Kısıtlamalar ve İndeksler ---
    __table_args__ = (
        Index("idx_regime_event_type", "event_type"),
        Index("idx_regime_active", "is_active", postgresql_where=text("is_active = TRUE")),
        Index("idx_regime_dates", "start_date", "end_date"),
        {"comment": "Politik/ekonomik rejim olayları — seçim, kriz, bayram vb."},
    )

    def __repr__(self) -> str:
        return (
            f"<RegimeEvent(id={self.id}, type={self.event_type}, "
            f"name='{self.event_name}', impact={self.impact_score}, "
            f"active={self.is_active})>"
        )
