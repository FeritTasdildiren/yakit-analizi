"""
Gecmis fiyat degisiklikleri modeli.

price_changes tablosu: Akaryakit pompa fiyat degisikliklerini (zam/indirim)
tarihsel olarak kaydeder. Her (fuel_type, change_date) cifti benzersizdir.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, direction_enum, fuel_type_enum


class PriceChange(Base):
    """Gecmis fiyat degisiklikleri tablosu."""

    __tablename__ = "price_changes"

    # --- Birincil Anahtar ---
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Otomatik artan birincil anahtar",
    )

    # --- Zorunlu Alanlar ---
    fuel_type: Mapped[str] = mapped_column(
        fuel_type_enum,
        nullable=False,
        comment="Yakit tipi: benzin, motorin, lpg",
    )

    change_date: Mapped[datetime] = mapped_column(
        Date,
        nullable=False,
        comment="Fiyat degisiklik tarihi",
    )

    direction: Mapped[str] = mapped_column(
        direction_enum,
        nullable=False,
        comment="Degisim yonu: increase, decrease, no_change",
    )

    # --- Fiyat Verileri (Decimal hassasiyeti icin NUMERIC) ---
    old_price: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="Degisiklik oncesi pompa fiyati (TL/litre)",
    )

    new_price: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="Degisiklik sonrasi pompa fiyati (TL/litre)",
    )

    change_amount: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="Degisim miktari TL (new_price - old_price)",
    )

    change_pct: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="Degisim yuzdesi ((new - old) / old * 100)",
    )

    mbe_at_change: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=True,
        comment="Degisiklik anindaki MBE degeri (TL/litre)",
    )

    # --- Opsiyonel Alanlar ---
    source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        server_default="manual",
        comment="Veri kaynagi: epdk, manual, system",
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Ek notlar",
    )

    # --- Zaman Damgalari ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="Kayit olusturulma zamani",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        onupdate=text("NOW()"),
        comment="Son guncelleme zamani",
    )

    # --- Kisitlamalar ---
    __table_args__ = (
        UniqueConstraint(
            "fuel_type",
            "change_date",
            name="uq_price_change_fuel_date",
        ),
        Index("idx_price_change_date", "change_date"),
        Index("idx_price_change_fuel_date", "fuel_type", "change_date"),
        Index("idx_price_change_direction", "direction"),
        {"comment": "Gecmis akaryakit fiyat degisiklikleri (zam/indirim)"},
    )

    def __repr__(self) -> str:
        return (
            f"<PriceChange(id={self.id}, "
            f"fuel={self.fuel_type}, "
            f"date={self.change_date}, "
            f"direction={self.direction}, "
            f"old={self.old_price}, "
            f"new={self.new_price})>"
        )
