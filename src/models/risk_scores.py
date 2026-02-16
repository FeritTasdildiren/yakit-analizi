"""
Günlük risk skoru modeli.

risk_scores tablosu: her (trade_date, fuel_type) çifti için hesaplanan
bileşik risk skorunu ve bileşenlerini tutar. Risk skoru 0-1 arasında,
1 = en yüksek risk. Her bileşenin ağırlıkları weight_vector JSONB'de saklanır.
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, fuel_type_enum


class RiskScore(Base):
    """Günlük risk skoru tablosu."""

    __tablename__ = "risk_scores"

    # --- Birincil Anahtar ---
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Otomatik artan birincil anahtar",
    )

    # --- Tanımlayıcı Alanlar ---
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

    # --- Bileşik Risk Skoru ---
    composite_score: Mapped[float] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="Bileşik risk skoru (0-1 arası, 1 = en yüksek risk)",
    )

    # --- Bileşenler ---
    mbe_component: Mapped[float] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="Normalize edilmiş MBE bileşeni (0-1)",
    )

    fx_volatility_component: Mapped[float] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="Normalize edilmiş FX volatilite bileşeni (0-1)",
    )

    political_delay_component: Mapped[float] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="Normalize edilmiş politik gecikme bileşeni (0-1)",
    )

    threshold_breach_component: Mapped[float] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="Normalize edilmiş eşik ihlali bileşeni (0-1)",
    )

    trend_momentum_component: Mapped[float] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="Normalize edilmiş trend momentum bileşeni (0-1)",
    )

    # --- Ağırlık Vektörü ---
    weight_vector: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Bileşen ağırlıkları (ör: {'mbe': 0.30, 'fx': 0.15, ...})",
    )

    # --- Tetiklenen Alarmlar ---
    triggered_alerts: Mapped[list | None] = mapped_column(
        ARRAY(String(100)),
        nullable=True,
        comment="Bu skor ile tetiklenen alarm ID'leri",
    )

    # --- Sistem Modu ---
    system_mode: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="normal",
        comment="Sistem modu: normal, high_alert, crisis",
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
        UniqueConstraint(
            "trade_date",
            "fuel_type",
            name="uq_risk_score_date_fuel",
        ),
        Index("idx_risk_score_date", "trade_date"),
        Index("idx_risk_score_fuel_date", "fuel_type", "trade_date"),
        Index(
            "idx_risk_score_high",
            "composite_score",
            postgresql_where=text("composite_score >= 0.60"),
        ),
        {"comment": "Günlük risk skorları — bileşik skor ve bileşenler"},
    )

    def __repr__(self) -> str:
        return (
            f"<RiskScore(id={self.id}, date={self.trade_date}, "
            f"fuel={self.fuel_type}, score={self.composite_score}, "
            f"mode={self.system_mode})>"
        )
