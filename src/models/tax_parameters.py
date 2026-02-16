"""
ÖTV ve KDV vergi parametreleri modeli.

Akaryakıt vergilerini temporal (zamana bağlı) olarak yöneten tablo.
Her kayıt belirli bir tarih aralığında geçerli olan vergi oranlarını tutar.
valid_to = NULL ise kayıt hâlâ aktiftir.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    func,
)

from src.models.base import Base, fuel_type_enum


class TaxParameter(Base):
    """
    Akaryakıt ÖTV ve KDV vergi parametreleri tablosu.

    Türkiye'de ÖTV genellikle sabit TL/litre olarak uygulanır (otv_fixed_tl).
    Bazı dönemlerde yüzdesel oran (otv_rate) da kullanılabilir.
    Her iki alan da NULL olabilir, ancak en az biri dolu olmalıdır (uygulama katmanında kontrol).

    Attributes:
        id: Benzersiz kayıt kimliği (BIGSERIAL)
        fuel_type: Yakıt tipi (benzin, motorin, lpg)
        otv_rate: ÖTV yüzdesel oranı (opsiyonel)
        otv_fixed_tl: ÖTV sabit tutar TRY/litre (Türkiye'de genelde bu kullanılır)
        kdv_rate: KDV oranı (0-1 arasında, ör: 0.18 = %18)
        valid_from: Geçerlilik başlangıç tarihi
        valid_to: Geçerlilik bitiş tarihi (NULL = hâlâ geçerli)
        gazette_reference: Resmi Gazete referans numarası
        notes: Ek notlar
        created_by: Kaydı oluşturan kullanıcı/sistem
        created_at: Oluşturulma zamanı (UTC)
        updated_at: Son güncelleme zamanı (UTC)
    """

    __tablename__ = "tax_parameters"

    # --- Birincil Anahtar ---
    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # --- Yakıt Tipi ---
    fuel_type = Column(
        fuel_type_enum,
        nullable=False,
        comment="Yakıt tipi: benzin, motorin veya lpg",
    )

    # --- ÖTV Alanları ---
    otv_rate = Column(
        Numeric(18, 8),
        nullable=True,
        comment="ÖTV yüzdesel oranı (opsiyonel)",
    )
    otv_fixed_tl = Column(
        Numeric(18, 8),
        nullable=True,
        comment="ÖTV sabit tutar TRY/litre — Türkiye'de genelde bu kullanılır",
    )

    # --- KDV ---
    kdv_rate = Column(
        Numeric(18, 8),
        nullable=False,
        comment="KDV oranı (0-1 aralığında, ör: 0.18 = %18)",
    )

    # --- Temporal Alanlar ---
    valid_from = Column(
        Date,
        nullable=False,
        comment="Geçerlilik başlangıç tarihi",
    )
    valid_to = Column(
        Date,
        nullable=True,
        comment="Geçerlilik bitiş tarihi — NULL ise hâlâ geçerli",
    )

    # --- Referans ve Notlar ---
    gazette_reference = Column(
        String(255),
        nullable=True,
        comment="Resmi Gazete referans numarası",
    )
    notes = Column(
        Text,
        nullable=True,
        comment="Ek notlar",
    )

    # --- Audit Alanları ---
    created_by = Column(
        String(100),
        nullable=False,
        default="system",
        server_default="system",
        comment="Kaydı oluşturan kullanıcı veya sistem",
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Oluşturulma zamanı (UTC)",
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Son güncelleme zamanı (UTC)",
    )

    # --- Index'ler ---
    __table_args__ = (
        # Yakıt tipi ve geçerlilik tarihine göre hızlı sorgulama
        Index("idx_tax_fuel_valid", "fuel_type", valid_from.desc()),
        # Aktif (hâlâ geçerli) kayıtlar için partial index
        Index(
            "idx_tax_active",
            "fuel_type",
            postgresql_where=(valid_to.is_(None)),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<TaxParameter(id={self.id}, fuel_type='{self.fuel_type}', "
            f"otv_fixed_tl={self.otv_fixed_tl}, kdv_rate={self.kdv_rate}, "
            f"valid_from={self.valid_from}, valid_to={self.valid_to})>"
        )

    @property
    def is_active(self) -> bool:
        """Kaydın hâlâ geçerli olup olmadığını döndürür."""
        return self.valid_to is None

    @property
    def display_otv(self) -> str:
        """ÖTV bilgisini okunabilir formatta döndürür."""
        if self.otv_fixed_tl is not None:
            return f"{self.otv_fixed_tl} TL/lt"
        if self.otv_rate is not None:
            return f"%{self.otv_rate * 100}"
        return "Tanımsız"
