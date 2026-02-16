"""
MBE (Maliyet Baz Etkisi) hesaplama sonuclari modeli.

mbe_calculations tablosu: Her gun icin hesaplanan MBE degeri,
hareketli ortalamalar, trend ve rejim bilgilerini saklar.
FK: cost_base_snapshots. UniqueConstraint(trade_date, fuel_type).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, direction_enum, fuel_type_enum


class MBECalculation(Base):
    """MBE hesaplama sonuclari tablosu."""

    __tablename__ = "mbe_calculations"

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

    # --- Foreign Key ---
    cost_snapshot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cost_base_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        comment="Iliskili maliyet snapshot kaydi",
    )

    # --- NC (Net Cost) Hesaplamalari ---
    nc_forward: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="NC_forward = (CIF * FX) / rho (bugunun net maliyeti TL/litre)",
    )

    nc_base: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="NC_base: Son zam tarihindeki pompa fiyatindan ters hesaplama",
    )

    # --- MBE Degerleri ---
    mbe_value: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="MBE degeri TL/litre = SMA(NC_forward) - SMA(NC_base)",
    )

    mbe_pct: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="MBE yuzdesi = mbe_value / nc_base * 100",
    )

    # --- Hareketli Ortalamalar ---
    sma_5: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=True,
        comment="5 gunluk basit hareketli ortalama (NC_forward)",
    )

    sma_10: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=True,
        comment="10 gunluk basit hareketli ortalama (NC_forward)",
    )

    # --- Delta MBE ---
    delta_mbe: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=True,
        comment="MBE gunluk degisim = MBE_t - MBE_(t-1)",
    )

    delta_mbe_3: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=True,
        comment="MBE 3 gunluk degisim = MBE_t - MBE_(t-3)",
    )

    # --- Trend ve Rejim ---
    trend_direction: Mapped[str] = mapped_column(
        direction_enum,
        nullable=False,
        comment="Trend yonu: increase, decrease, no_change",
    )

    regime: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="Rejim kodu: 0=Normal, 1=Secim, 2=Kur Soku, 3=Vergi Ayarlama",
    )

    since_last_change_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="Son fiyat degisikliginden bu yana gecen gun sayisi",
    )

    # --- SMA Pencere Genisligi ---
    sma_window: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="5",
        comment="Kullanilan SMA pencere genisligi (rejime bagli)",
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

    # --- Relationship ---
    cost_snapshot = relationship("CostBaseSnapshot", lazy="selectin")

    # --- Kisitlamalar ---
    __table_args__ = (
        UniqueConstraint(
            "trade_date",
            "fuel_type",
            name="uq_mbe_calc_date_fuel",
        ),
        Index("idx_mbe_calc_date", "trade_date"),
        Index("idx_mbe_calc_fuel_date", "fuel_type", "trade_date"),
        Index("idx_mbe_calc_regime", "regime"),
        Index("idx_mbe_calc_snapshot", "cost_snapshot_id"),
        {"comment": "MBE (Maliyet Baz Etkisi) hesaplama sonuclari"},
    )

    def __repr__(self) -> str:
        return (
            f"<MBECalculation(id={self.id}, "
            f"date={self.trade_date}, "
            f"fuel={self.fuel_type}, "
            f"mbe={self.mbe_value}, "
            f"trend={self.trend_direction}, "
            f"regime={self.regime})>"
        )
