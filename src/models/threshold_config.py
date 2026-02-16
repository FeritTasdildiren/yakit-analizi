"""
Dinamik eşik parametreleri modeli.

threshold_config tablosu: risk skoru, MBE değeri gibi metrikler için
uyarı eşiklerini dinamik olarak tanımlar. Hysteresis (açılış/kapanış)
destekler, cooldown süresi ve rejim modifier ile esneklik sağlar.
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, alert_level_enum, fuel_type_enum


class ThresholdConfig(Base):
    """Dinamik eşik parametreleri tablosu."""

    __tablename__ = "threshold_config"

    # --- Birincil Anahtar ---
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Otomatik artan birincil anahtar",
    )

    # --- Eşik Tanımlama ---
    fuel_type: Mapped[str | None] = mapped_column(
        fuel_type_enum,
        nullable=True,
        comment="Yakıt tipi (NULL ise tüm yakıt tipleri için geçerli)",
    )

    metric_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Metrik adı (ör: risk_score, mbe_value, fx_volatility)",
    )

    alert_level: Mapped[str] = mapped_column(
        alert_level_enum,
        nullable=False,
        comment="Uyarı seviyesi: info, warning, critical",
    )

    # --- Hysteresis Eşikleri ---
    threshold_open: Mapped[float] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="Eşik açılış değeri (bu değer aşılınca alarm tetiklenir)",
    )

    threshold_close: Mapped[float] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="Eşik kapanış değeri (bu değerin altına düşünce alarm kapanır)",
    )

    # --- Cooldown ---
    cooldown_hours: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("24"),
        comment="Aynı alarm tekrar tetiklenmeden önce beklenecek saat",
    )

    # --- Rejim Modifier ---
    regime_modifier: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Rejim bazlı eşik düzeltici (ör: {'election': 0.85, 'holiday': 0.90})",
    )

    # --- Versiyon ve Temporal ---
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
        comment="Konfigürasyon versiyonu",
    )

    valid_from: Mapped[datetime] = mapped_column(
        Date,
        nullable=False,
        comment="Geçerlilik başlangıç tarihi",
    )

    valid_to: Mapped[datetime | None] = mapped_column(
        Date,
        nullable=True,
        comment="Geçerlilik bitiş tarihi (NULL = hâlâ geçerli)",
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
        Index("idx_threshold_metric_level", "metric_name", "alert_level"),
        Index("idx_threshold_fuel", "fuel_type"),
        Index(
            "idx_threshold_active",
            "metric_name",
            postgresql_where=text("valid_to IS NULL"),
        ),
        {"comment": "Dinamik eşik parametreleri — hysteresis, cooldown, rejim modifier"},
    )

    def __repr__(self) -> str:
        return (
            f"<ThresholdConfig(id={self.id}, metric={self.metric_name}, "
            f"level={self.alert_level}, open={self.threshold_open}, "
            f"close={self.threshold_close})>"
        )

    @property
    def is_active(self) -> bool:
        """Kaydın hâlâ geçerli olup olmadığını döndürür."""
        return self.valid_to is None
