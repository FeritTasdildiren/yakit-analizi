"""
ML tahmin modeli.

ml_predictions tablosu: her (fuel_type, prediction_date) cifti icin
siniflandirma tahmini (hike/stable/cut), olasiliklar, beklenen TL/L
degisim ve SHAP aciklamalarini saklar.
"""

from datetime import date, datetime
from decimal import Decimal

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

from src.models.base import Base, fuel_type_enum


class MLPrediction(Base):
    """ML tahmin kayitlari tablosu."""

    __tablename__ = "ml_predictions"

    # --- Birincil Anahtar ---
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Otomatik artan birincil anahtar",
    )

    # --- Tanimlayici Alanlar ---
    fuel_type: Mapped[str] = mapped_column(
        fuel_type_enum,
        nullable=False,
        comment="Yakit tipi: benzin, motorin, lpg",
    )

    prediction_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Tahmin tarihi",
    )

    # --- Siniflandirma Sonuclari ---
    predicted_direction: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="Tahmin yonu: hike, stable, cut",
    )

    probability_hike: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4),
        nullable=False,
        comment="Zam olasiligi (0.0000-1.0000)",
    )

    probability_stable: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4),
        nullable=False,
        comment="Sabit olasiligi (0.0000-1.0000)",
    )

    probability_cut: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4),
        nullable=False,
        comment="Indirim olasiligi (0.0000-1.0000)",
    )

    # --- Regresyon Sonucu ---
    expected_change_tl: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=8, scale=4),
        nullable=True,
        comment="Beklenen degisim TL/L",
    )

    # --- Model Bilgisi ---
    model_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Kullanilan model versiyonu (orn: v1, v2)",
    )

    system_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="full",
        comment="Sistem modu: full, partial, safe",
    )

    # --- SHAP Aciklamalar ---
    shap_top_features: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Top-5 SHAP feature katkilari",
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

    # --- Kisitlamalar ve Indeksler ---
    __table_args__ = (
        UniqueConstraint(
            "fuel_type",
            "prediction_date",
            name="uq_ml_pred_fuel_date",
        ),
        Index("idx_ml_pred_date", "prediction_date"),
        Index("idx_ml_pred_fuel_date", "fuel_type", "prediction_date"),
        Index(
            "idx_ml_pred_hike",
            "probability_hike",
            postgresql_where=text("probability_hike >= 0.50"),
        ),
        {"comment": "ML tahmin kayitlari — siniflandirma, regresyon, SHAP"},
    )

    def __repr__(self) -> str:
        return (
            f"<MLPrediction(id={self.id}, date={self.prediction_date}, "
            f"fuel={self.fuel_type}, dir={self.predicted_direction}, "
            f"p_hike={self.probability_hike})>"
        )
