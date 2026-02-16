"""
Günlük piyasa verisi modeli.

daily_market_data tablosu: Brent petrol, döviz kuru, CIF Med,
pompa fiyatı ve dağıtım marjı verilerini tutar.
Her (trade_date, fuel_type) çifti benzersizdir.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, data_quality_enum, fuel_type_enum


class DailyMarketData(Base):
    """Günlük piyasa verisi tablosu."""

    __tablename__ = "daily_market_data"

    # --- Birincil Anahtar ---
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Otomatik artan birincil anahtar",
    )

    # --- Zorunlu Alanlar ---
    trade_date: Mapped[datetime] = mapped_column(
        Date,
        nullable=False,
        comment="İşlem tarihi",
    )

    fuel_type: Mapped[str] = mapped_column(
        fuel_type_enum,
        nullable=False,
        comment="Yakıt tipi: benzin, motorin, lpg",
    )

    # --- Fiyat Verileri (Decimal hassasiyeti için NUMERIC) ---
    cif_med_usd_ton: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=True,
        comment="CIF Akdeniz fiyatı (USD/ton)",
    )

    usd_try_rate: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=True,
        comment="USD/TRY döviz kuru (TCMB satış)",
    )

    pump_price_tl_lt: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=True,
        comment="Pompa fiyatı (TL/litre)",
    )

    brent_usd_bbl: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=True,
        comment="Brent petrol fiyatı (USD/varil)",
    )

    distribution_margin_tl: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=True,
        comment="Dağıtım marjı (TL)",
    )

    # --- Meta Veriler ---
    data_quality_flag: Mapped[str] = mapped_column(
        data_quality_enum,
        nullable=False,
        server_default="verified",
        comment="Veri kalite bayrağı: verified, interpolated, manual, estimated, stale",
    )

    source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Veri kaynağı: tcmb_evds, yfinance, fallback_xe, manual",
    )

    raw_payload: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="API'den gelen ham JSON yanıt (audit trail)",
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

    # --- Kısıtlamalar ---
    __table_args__ = (
        UniqueConstraint(
            "trade_date",
            "fuel_type",
            name="uq_daily_market_date_fuel",
        ),
        Index("idx_daily_market_date", "trade_date"),
        Index("idx_daily_market_fuel_date", "fuel_type", "trade_date"),
        Index(
            "idx_daily_market_quality",
            "data_quality_flag",
            postgresql_where=text("data_quality_flag != 'verified'"),
        ),
        {"comment": "Günlük piyasa verileri — Brent, döviz kuru, CIF Med, pompa fiyatı"},
    )

    def __repr__(self) -> str:
        return (
            f"<DailyMarketData(id={self.id}, "
            f"date={self.trade_date}, "
            f"fuel={self.fuel_type}, "
            f"brent={self.brent_usd_bbl}, "
            f"usd_try={self.usd_try_rate})>"
        )
