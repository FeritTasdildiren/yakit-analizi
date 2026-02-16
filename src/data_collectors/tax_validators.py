"""
Vergi parametreleri doğrulama (validasyon) modülü.

Yeni vergi kaydı oluşturulmadan veya güncellemeden önce çalıştırılan
iş kuralları doğrulamaları. Temporal çakışma kontrolü dahil.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tax_parameters import TaxParameter


class TaxValidationError(Exception):
    """Vergi parametresi doğrulama hatası."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class TaxValidationErrors(Exception):
    """Birden fazla doğrulama hatasını toplayan istisna sınıfı."""

    def __init__(self, errors: list[TaxValidationError]) -> None:
        self.errors = errors
        messages = "; ".join(f"[{e.field}] {e.message}" for e in errors)
        super().__init__(f"Doğrulama hataları: {messages}")


def validate_otv_fields(
    otv_rate: Decimal | None,
    otv_fixed_tl: Decimal | None,
) -> list[TaxValidationError]:
    """
    ÖTV alanlarını doğrular.

    Kurallar:
    - otv_rate veya otv_fixed_tl'den en az biri dolu olmalıdır.
    - otv_fixed_tl pozitif olmalıdır (verilmişse).
    - otv_rate negatif olmamalıdır (verilmişse).

    Args:
        otv_rate: ÖTV yüzdesel oranı (opsiyonel).
        otv_fixed_tl: ÖTV sabit tutar TRY/litre (opsiyonel).

    Returns:
        Doğrulama hatalarının listesi (boş ise hata yok).
    """
    errors: list[TaxValidationError] = []

    # En az biri dolu olmalı
    if otv_rate is None and otv_fixed_tl is None:
        errors.append(
            TaxValidationError(
                field="otv_rate/otv_fixed_tl",
                message="ÖTV oranı veya sabit tutar alanlarından en az biri dolu olmalıdır",
            )
        )

    # otv_fixed_tl pozitif olmalı
    if otv_fixed_tl is not None and otv_fixed_tl <= Decimal("0"):
        errors.append(
            TaxValidationError(
                field="otv_fixed_tl",
                message=f"ÖTV sabit tutar pozitif olmalıdır, verilen: {otv_fixed_tl}",
            )
        )

    # otv_rate negatif olmamalı
    if otv_rate is not None and otv_rate < Decimal("0"):
        errors.append(
            TaxValidationError(
                field="otv_rate",
                message=f"ÖTV oranı negatif olamaz, verilen: {otv_rate}",
            )
        )

    return errors


def validate_kdv_rate(kdv_rate: Decimal) -> list[TaxValidationError]:
    """
    KDV oranını doğrular.

    Kurallar:
    - 0 ile 1 arasında olmalıdır (0 ve 1 dahil).

    Args:
        kdv_rate: KDV oranı (ör: 0.18 = %18).

    Returns:
        Doğrulama hatalarının listesi (boş ise hata yok).
    """
    errors: list[TaxValidationError] = []

    if kdv_rate < Decimal("0") or kdv_rate > Decimal("1"):
        errors.append(
            TaxValidationError(
                field="kdv_rate",
                message=f"KDV oranı 0 ile 1 arasında olmalıdır, verilen: {kdv_rate}",
            )
        )

    return errors


def validate_date_range(
    valid_from: date,
    valid_to: date | None,
) -> list[TaxValidationError]:
    """
    Tarih aralığı doğrulaması.

    Kurallar:
    - valid_to verilmişse, valid_from'dan sonra olmalıdır.

    Args:
        valid_from: Geçerlilik başlangıç tarihi.
        valid_to: Geçerlilik bitiş tarihi (opsiyonel).

    Returns:
        Doğrulama hatalarının listesi (boş ise hata yok).
    """
    errors: list[TaxValidationError] = []

    if valid_to is not None and valid_to < valid_from:
        errors.append(
            TaxValidationError(
                field="valid_from/valid_to",
                message=(
                    f"Bitiş tarihi ({valid_to}) başlangıç tarihinden ({valid_from}) "
                    f"önce olamaz"
                ),
            )
        )

    return errors


def validate_fuel_type(fuel_type: str) -> list[TaxValidationError]:
    """
    Yakıt tipi doğrulaması.

    Args:
        fuel_type: Yakıt tipi dizgesi.

    Returns:
        Doğrulama hatalarının listesi (boş ise hata yok).
    """
    errors: list[TaxValidationError] = []
    valid_types = {"benzin", "motorin", "lpg"}

    if fuel_type not in valid_types:
        errors.append(
            TaxValidationError(
                field="fuel_type",
                message=(
                    f"Geçersiz yakıt tipi: '{fuel_type}'. "
                    f"Geçerli değerler: {', '.join(sorted(valid_types))}"
                ),
            )
        )

    return errors


async def validate_no_overlap(
    session: AsyncSession,
    fuel_type: str,
    valid_from: date,
    valid_to: date | None = None,
    exclude_id: int | None = None,
) -> list[TaxValidationError]:
    """
    Aynı yakıt tipi için çakışan tarih aralığı olup olmadığını kontrol eder.

    Temporal çakışma mantığı:
    - Mevcut kayıt: [A.valid_from, A.valid_to]
    - Yeni kayıt:   [B.valid_from, B.valid_to]
    - Çakışma: A.valid_from <= B.valid_to AND (A.valid_to IS NULL OR A.valid_to >= B.valid_from)

    Not: valid_to = NULL olan aktif kayıtlar, create_tax_parameter fonksiyonunda
    otomatik olarak kapatılır. Bu fonksiyon ek güvenlik katmanıdır.

    Args:
        session: Async veritabanı oturumu.
        fuel_type: Yakıt tipi.
        valid_from: Yeni kaydın başlangıç tarihi.
        valid_to: Yeni kaydın bitiş tarihi (opsiyonel).
        exclude_id: Güncelleme sırasında kendi kaydını hariç tutmak için ID.

    Returns:
        Doğrulama hatalarının listesi (boş ise çakışma yok).
    """
    errors: list[TaxValidationError] = []

    # Çakışma sorgusu oluştur
    conditions = [
        TaxParameter.fuel_type == fuel_type,
        TaxParameter.valid_from <= (valid_to if valid_to is not None else date(9999, 12, 31)),
        or_(
            TaxParameter.valid_to.is_(None),
            TaxParameter.valid_to >= valid_from,
        ),
    ]

    # Güncelleme sırasında kendi kaydını hariç tut
    if exclude_id is not None:
        conditions.append(TaxParameter.id != exclude_id)

    stmt = select(TaxParameter).where(and_(*conditions))
    result = await session.execute(stmt)
    overlapping = result.scalars().all()

    if overlapping:
        overlap_info = ", ".join(
            f"ID={r.id} ({r.valid_from} - {r.valid_to or 'aktif'})"
            for r in overlapping
        )
        errors.append(
            TaxValidationError(
                field="valid_from/valid_to",
                message=(
                    f"{fuel_type} için çakışan tarih aralığı tespit edildi: {overlap_info}"
                ),
            )
        )

    return errors


def validate_tax_parameter(
    fuel_type: str,
    otv_rate: Decimal | None,
    otv_fixed_tl: Decimal | None,
    kdv_rate: Decimal,
    valid_from: date,
    valid_to: date | None = None,
) -> None:
    """
    Tüm senkron doğrulamaları toplu olarak çalıştırır.

    Herhangi bir doğrulama hatası varsa TaxValidationErrors fırlatır.

    Args:
        fuel_type: Yakıt tipi.
        otv_rate: ÖTV yüzdesel oranı.
        otv_fixed_tl: ÖTV sabit tutar.
        kdv_rate: KDV oranı.
        valid_from: Geçerlilik başlangıç tarihi.
        valid_to: Geçerlilik bitiş tarihi (opsiyonel).

    Raises:
        TaxValidationErrors: Doğrulama hataları varsa.
    """
    all_errors: list[TaxValidationError] = []

    all_errors.extend(validate_fuel_type(fuel_type))
    all_errors.extend(validate_otv_fields(otv_rate, otv_fixed_tl))
    all_errors.extend(validate_kdv_rate(kdv_rate))
    all_errors.extend(validate_date_range(valid_from, valid_to))

    if all_errors:
        raise TaxValidationErrors(all_errors)


async def validate_tax_parameter_full(
    session: AsyncSession,
    fuel_type: str,
    otv_rate: Decimal | None,
    otv_fixed_tl: Decimal | None,
    kdv_rate: Decimal,
    valid_from: date,
    valid_to: date | None = None,
    exclude_id: int | None = None,
) -> None:
    """
    Senkron ve asenkron (veritabanı) doğrulamaların tamamını çalıştırır.

    Önce senkron kuralları kontrol eder, sonra veritabanında çakışma kontrolü yapar.

    Args:
        session: Async veritabanı oturumu.
        fuel_type: Yakıt tipi.
        otv_rate: ÖTV yüzdesel oranı.
        otv_fixed_tl: ÖTV sabit tutar.
        kdv_rate: KDV oranı.
        valid_from: Geçerlilik başlangıç tarihi.
        valid_to: Geçerlilik bitiş tarihi (opsiyonel).
        exclude_id: Güncelleme sırasında hariç tutulacak kayıt ID.

    Raises:
        TaxValidationErrors: Doğrulama hataları varsa.
    """
    all_errors: list[TaxValidationError] = []

    # Senkron doğrulamalar
    all_errors.extend(validate_fuel_type(fuel_type))
    all_errors.extend(validate_otv_fields(otv_rate, otv_fixed_tl))
    all_errors.extend(validate_kdv_rate(kdv_rate))
    all_errors.extend(validate_date_range(valid_from, valid_to))

    # Senkron hatalar varsa veritabanına gitmeye gerek yok
    if all_errors:
        raise TaxValidationErrors(all_errors)

    # Asenkron doğrulamalar (veritabanı çakışma kontrolü)
    overlap_errors = await validate_no_overlap(
        session=session,
        fuel_type=fuel_type,
        valid_from=valid_from,
        valid_to=valid_to,
        exclude_id=exclude_id,
    )

    if overlap_errors:
        raise TaxValidationErrors(overlap_errors)
