"""
Politik gecikme takip modeli.

political_delay_history tablosu: MBE eşik değerini aştığında beklenen
fiyat değişikliğinin ne kadar geciktiğini, birikmiş basıncı ve
ilişkili rejim olaylarını kaydeder.
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, fuel_type_enum


class PoliticalDelayHistory(Base):
    """Politik gecikme takip tablosu."""

    __tablename__ = "political_delay_history"

    # --- Birincil Anahtar ---
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Otomatik artan birincil anahtar",
    )

    # --- Yakıt Tipi ---
    fuel_type: Mapped[str] = mapped_column(
        fuel_type_enum,
        nullable=False,
        comment="Yakıt tipi: benzin, motorin, lpg",
    )

    # --- Tarih Bilgileri ---
    expected_change_date: Mapped[datetime] = mapped_column(
        Date,
        nullable=False,
        comment="Beklenen fiyat değişikliği tarihi (MBE eşiği aşıldığında)",
    )

    actual_change_date: Mapped[datetime | None] = mapped_column(
        Date,
        nullable=True,
        comment="Gerçek fiyat değişikliği tarihi (NULL = henüz zam gelmedi)",
    )

    delay_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        comment="Gecikme gün sayısı (actual - expected veya bugün - expected)",
    )

    # --- MBE Değerleri ---
    mbe_at_expected: Mapped[float] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="Beklenen tarihte MBE değeri",
    )

    mbe_at_actual: Mapped[float | None] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=True,
        comment="Gerçek zam tarihindeki MBE değeri (NULL = henüz zam gelmedi)",
    )

    # --- Basınç ---
    accumulated_pressure_pct: Mapped[float] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        server_default=text("0"),
        comment="Birikmiş basınç yüzdesi (MBE × gün formülüyle hesaplanan)",
    )

    # --- Durum ---
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="watching",
        comment="Takip durumu: watching, closed, absorbed, partial_close",
    )

    # --- İlişkiler (FK) ---
    regime_event_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("regime_events.id", ondelete="SET NULL"),
        nullable=True,
        comment="İlişkili rejim olayı (seçim, bayram vb.)",
    )

    price_change_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="İlişkili fiyat değişikliği kaydı ID (nullable FK — gelecekte price_changes tablosuna bağlanacak)",
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
        Index("idx_delay_fuel_date", "fuel_type", "expected_change_date"),
        Index(
            "idx_delay_pending",
            "status",
            postgresql_where=text("status = 'watching'"),
        ),
        Index("idx_delay_regime", "regime_event_id"),
        {"comment": "Politik gecikme takibi — beklenen/gerçek zam tarihleri, basınç birikimi"},
    )

    def __repr__(self) -> str:
        return (
            f"<PoliticalDelayHistory(id={self.id}, fuel={self.fuel_type}, "
            f"expected={self.expected_change_date}, actual={self.actual_change_date}, "
            f"delay={self.delay_days}, status={self.status})>"
        )
