"""
Gunluk maliyet ayristirma snapshot modeli.

cost_base_snapshots tablosu: Her gun icin akaryakit maliyet bilesenleri
(CIF, OTV, KDV, marj) ve teorik/gercek fiyat karsilastirmasini saklar.
FK: daily_market_data, tax_parameters. UniqueConstraint(trade_date, fuel_type).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, fuel_type_enum


class CostBaseSnapshot(Base):
    """Gunluk maliyet ayristirma snapshot tablosu."""

    __tablename__ = "cost_base_snapshots"

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
        comment="Islem tarihi",
    )

    fuel_type: Mapped[str] = mapped_column(
        fuel_type_enum,
        nullable=False,
        comment="Yakit tipi: benzin, motorin, lpg",
    )

    # --- Foreign Key'ler ---
    market_data_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("daily_market_data.id", ondelete="CASCADE"),
        nullable=False,
        comment="Iliskili piyasa verisi kaydi",
    )

    tax_parameter_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tax_parameters.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Iliskili vergi parametresi kaydi",
    )

    # --- Maliyet Bilesenleri (Decimal hassasiyeti icin NUMERIC) ---
    cif_component_tl: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="CIF bileseni TL/litre = (CIF_USD_ton * USD_TRY) / rho",
    )

    otv_component_tl: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="OTV bileseni TL/litre",
    )

    kdv_component_tl: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="KDV bileseni TL/litre",
    )

    margin_component_tl: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="Toplam marj bileseni TL/litre (dagitim + bayi)",
    )

    # --- Teorik ve Gercek Fiyatlar ---
    theoretical_cost_tl: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="Teorik maliyet TL/litre = (CIF + OTV) * (1 + KDV) + marj",
    )

    actual_pump_price_tl: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="Gercek pompa fiyati TL/litre",
    )

    # --- Ters Hesaplama ---
    implied_cif_usd_ton: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=True,
        comment="Pompa fiyatindan ters hesaplanan ima edilen CIF (USD/ton)",
    )

    # --- Fark Analizi ---
    cost_gap_tl: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="Maliyet farki TL = actual_pump - theoretical_cost",
    )

    cost_gap_pct: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="Maliyet farki yuzdesi = cost_gap_tl / theoretical_cost * 100",
    )

    # --- Meta ---
    source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        server_default="system",
        comment="Hesaplama kaynagi",
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

    # --- Relationship'ler ---
    market_data = relationship("DailyMarketData", lazy="selectin")
    tax_parameter = relationship("TaxParameter", lazy="selectin")

    # --- Kisitlamalar ---
    __table_args__ = (
        UniqueConstraint(
            "trade_date",
            "fuel_type",
            name="uq_cost_snapshot_date_fuel",
        ),
        Index("idx_cost_snapshot_date", "trade_date"),
        Index("idx_cost_snapshot_fuel_date", "fuel_type", "trade_date"),
        Index("idx_cost_snapshot_market_data", "market_data_id"),
        Index("idx_cost_snapshot_tax_param", "tax_parameter_id"),
        {"comment": "Gunluk maliyet ayristirma snapshot'lari"},
    )

    def __repr__(self) -> str:
        return (
            f"<CostBaseSnapshot(id={self.id}, "
            f"date={self.trade_date}, "
            f"fuel={self.fuel_type}, "
            f"theoretical={self.theoretical_cost_tl}, "
            f"actual={self.actual_pump_price_tl}, "
            f"gap={self.cost_gap_tl})>"
        )
