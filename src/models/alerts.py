"""
Sistem alert'leri modeli.

alerts tablosu: risk motoru veya eşik kontrolünden üretilen
alarmları saklar. Her alarm bir seviye (info/warning/critical),
ilişkili metrik değeri, gönderildiği kanallar ve çözüm durumu taşır.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, alert_level_enum, fuel_type_enum


class Alert(Base):
    """Sistem alert'leri tablosu."""

    __tablename__ = "alerts"

    # --- Birincil Anahtar ---
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Otomatik artan birincil anahtar",
    )

    # --- Alarm Bilgileri ---
    alert_level: Mapped[str] = mapped_column(
        alert_level_enum,
        nullable=False,
        comment="Alarm seviyesi: info, warning, critical",
    )

    alert_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Alarm tipi (ör: risk_threshold, mbe_threshold, fx_spike)",
    )

    fuel_type: Mapped[str | None] = mapped_column(
        fuel_type_enum,
        nullable=True,
        comment="İlgili yakıt tipi (NULL ise genel alarm)",
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Alarm başlığı",
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Alarm detay mesajı",
    )

    # --- Metrik Değerleri ---
    metric_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Tetikleyen metrik adı (ör: composite_score, mbe_value)",
    )

    metric_value: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="Tetikleyen metrik değeri",
    )

    threshold_value: Mapped[float] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="Aşılan eşik değeri",
    )

    # --- İlişkiler (FK) ---
    threshold_config_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("threshold_config.id", ondelete="SET NULL"),
        nullable=True,
        comment="İlişkili eşik konfigürasyonu",
    )

    risk_score_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("risk_scores.id", ondelete="SET NULL"),
        nullable=True,
        comment="İlişkili risk skoru kaydı",
    )

    # --- Gönderim ve Durum ---
    channels_sent: Mapped[list | None] = mapped_column(
        ARRAY(String(50)),
        nullable=True,
        comment="Gönderildiği kanallar (telegram, email, webhook, dashboard)",
    )

    is_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
        comment="Okundu mu?",
    )

    is_resolved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
        comment="Çözüldü mü?",
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Çözüm zamanı",
    )

    resolved_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Çözüm nedeni açıklaması",
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
        Index("idx_alert_level", "alert_level"),
        Index("idx_alert_fuel", "fuel_type"),
        Index(
            "idx_alert_unread",
            "is_read",
            postgresql_where=text("is_read = FALSE"),
        ),
        Index(
            "idx_alert_unresolved",
            "is_resolved",
            postgresql_where=text("is_resolved = FALSE"),
        ),
        Index("idx_alert_created", "created_at"),
        {"comment": "Sistem alert'leri — risk eşiği ihlalleri, uyarılar"},
    )

    def __repr__(self) -> str:
        return (
            f"<Alert(id={self.id}, level={self.alert_level}, "
            f"type={self.alert_type}, fuel={self.fuel_type}, "
            f"read={self.is_read}, resolved={self.is_resolved})>"
        )
