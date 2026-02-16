"""
Vergi parametreleri veritabanı erişim katmanı (repository).

Akaryakıt ÖTV ve KDV oranlarının temporal CRUD işlemlerini yönetir.
Tüm fonksiyonlar async/await patternini kullanır ve AsyncSession ile çalışır.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_collectors.tax_validators import (
    TaxValidationErrors,
    validate_tax_parameter,
)
from src.models.tax_parameters import TaxParameter

logger = logging.getLogger(__name__)


# --- Pydantic-benzeri veri taşıma sınıfı (repository katmanı için) ---

class TaxParameterCreate:
    """
    Yeni vergi parametresi oluşturmak için veri taşıma nesnesi.

    Not: Bu sınıf API katmanındaki Pydantic modelinden bağımsızdır.
    Repository doğrudan bu sınıfla veya keyword argümanlarla çağrılabilir.
    """

    def __init__(
        self,
        fuel_type: str,
        kdv_rate: Decimal,
        valid_from: date,
        otv_rate: Decimal | None = None,
        otv_fixed_tl: Decimal | None = None,
        gazette_reference: str | None = None,
        notes: str | None = None,
        created_by: str = "system",
    ) -> None:
        self.fuel_type = fuel_type
        self.otv_rate = otv_rate
        self.otv_fixed_tl = otv_fixed_tl
        self.kdv_rate = kdv_rate
        self.valid_from = valid_from
        self.gazette_reference = gazette_reference
        self.notes = notes
        self.created_by = created_by


async def get_current_tax(
    session: AsyncSession,
    fuel_type: str,
    ref_date: date | None = None,
) -> TaxParameter | None:
    """
    Belirtilen yakıt tipi için referans tarihindeki geçerli vergi kaydını döndürür.

    Temporal sorgu mantığı:
    - valid_from <= ref_date
    - valid_to IS NULL veya valid_to >= ref_date

    Birden fazla eşleşme varsa en güncel valid_from'a sahip kayıt döner.

    Args:
        session: Async veritabanı oturumu.
        fuel_type: Yakıt tipi ('benzin', 'motorin', 'lpg').
        ref_date: Referans tarih. None ise bugünün tarihi kullanılır.

    Returns:
        TaxParameter nesnesi veya None (kayıt bulunamazsa).
    """
    if ref_date is None:
        ref_date = date.today()

    stmt = (
        select(TaxParameter)
        .where(
            and_(
                TaxParameter.fuel_type == fuel_type,
                TaxParameter.valid_from <= ref_date,
                or_(
                    TaxParameter.valid_to.is_(None),
                    TaxParameter.valid_to >= ref_date,
                ),
            )
        )
        .order_by(TaxParameter.valid_from.desc())
        .limit(1)
    )

    result = await session.execute(stmt)
    tax = result.scalar_one_or_none()

    if tax is None:
        logger.warning(
            "Vergi kaydı bulunamadı: fuel_type=%s, ref_date=%s",
            fuel_type,
            ref_date,
        )

    return tax


async def get_all_current_taxes(
    session: AsyncSession,
    ref_date: date | None = None,
) -> list[TaxParameter]:
    """
    Tüm yakıt tipleri için güncel (aktif) vergi kayıtlarını döndürür.

    ref_date verilmezse valid_to IS NULL olan kayıtları getirir.
    ref_date verilmişse o tarihteki geçerli kayıtları getirir.

    Args:
        session: Async veritabanı oturumu.
        ref_date: Referans tarih. None ise sadece aktif kayıtlar (valid_to IS NULL).

    Returns:
        TaxParameter listesi.
    """
    if ref_date is None:
        # Sadece aktif kayıtlar (valid_to IS NULL)
        stmt = (
            select(TaxParameter)
            .where(TaxParameter.valid_to.is_(None))
            .order_by(TaxParameter.fuel_type)
        )
    else:
        # Belirli tarihteki geçerli kayıtlar
        stmt = (
            select(TaxParameter)
            .where(
                and_(
                    TaxParameter.valid_from <= ref_date,
                    or_(
                        TaxParameter.valid_to.is_(None),
                        TaxParameter.valid_to >= ref_date,
                    ),
                )
            )
            .order_by(TaxParameter.fuel_type, TaxParameter.valid_from.desc())
        )

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_tax_history(
    session: AsyncSession,
    fuel_type: str,
) -> list[TaxParameter]:
    """
    Belirtilen yakıt tipi için tüm vergi geçmişini döndürür.

    Tarihsel sıralamayla (en yeniden en eskiye) döner.

    Args:
        session: Async veritabanı oturumu.
        fuel_type: Yakıt tipi ('benzin', 'motorin', 'lpg').

    Returns:
        TaxParameter listesi (valid_from DESC sıralı).
    """
    stmt = (
        select(TaxParameter)
        .where(TaxParameter.fuel_type == fuel_type)
        .order_by(TaxParameter.valid_from.desc())
    )

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_tax_by_id(
    session: AsyncSession,
    tax_id: int,
) -> TaxParameter | None:
    """
    ID ile vergi kaydını döndürür.

    Args:
        session: Async veritabanı oturumu.
        tax_id: Vergi kaydı ID'si.

    Returns:
        TaxParameter nesnesi veya None.
    """
    stmt = select(TaxParameter).where(TaxParameter.id == tax_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_tax_parameter(
    session: AsyncSession,
    data: TaxParameterCreate,
) -> TaxParameter:
    """
    Yeni vergi parametresi kaydı oluşturur (atomik transaction).

    İşlem sırası:
    1. Veri doğrulaması yapılır (senkron kurallar).
    2. Aynı yakıt tipi için aktif (valid_to IS NULL) kayıt aranır.
    3. Aktif kayıt bulunursa, valid_to = yeni valid_from - 1 gün olarak güncellenir.
    4. Yeni kayıt eklenir.
    5. Tüm işlem tek transaction içinde gerçekleşir.

    Args:
        session: Async veritabanı oturumu.
        data: Yeni vergi parametresi verileri.

    Returns:
        Oluşturulan TaxParameter nesnesi.

    Raises:
        TaxValidationErrors: Doğrulama hataları varsa.
    """
    # Adım 1: Senkron doğrulama
    validate_tax_parameter(
        fuel_type=data.fuel_type,
        otv_rate=data.otv_rate,
        otv_fixed_tl=data.otv_fixed_tl,
        kdv_rate=data.kdv_rate,
        valid_from=data.valid_from,
    )

    # Adım 2: Önceki aktif kaydı bul ve kapat
    # (valid_to IS NULL ve aynı fuel_type olan kayıt)
    previous_active_stmt = (
        select(TaxParameter)
        .where(
            and_(
                TaxParameter.fuel_type == data.fuel_type,
                TaxParameter.valid_to.is_(None),
            )
        )
        .with_for_update()  # Pessimistic locking — eşzamanlı güncellemeyi engelle
    )

    result = await session.execute(previous_active_stmt)
    previous_active = result.scalar_one_or_none()

    if previous_active is not None:
        # Önceki kaydın valid_to alanını yeni kaydın valid_from - 1 gün olarak ayarla
        new_valid_to = data.valid_from - timedelta(days=1)

        # Eğer önceki kaydın valid_from'u yeni valid_to'dan sonraysa hata
        if previous_active.valid_from > new_valid_to:
            from src.data_collectors.tax_validators import TaxValidationError

            raise TaxValidationErrors([
                TaxValidationError(
                    field="valid_from",
                    message=(
                        f"Yeni kayıt başlangıç tarihi ({data.valid_from}) "
                        f"mevcut aktif kaydın başlangıç tarihinden ({previous_active.valid_from}) "
                        f"önce veya aynı gün olamaz"
                    ),
                )
            ])

        # Atomik güncelleme
        update_stmt = (
            update(TaxParameter)
            .where(TaxParameter.id == previous_active.id)
            .values(valid_to=new_valid_to)
        )
        await session.execute(update_stmt)

        logger.info(
            "Önceki aktif vergi kaydı kapatıldı: id=%d, fuel_type=%s, "
            "yeni valid_to=%s",
            previous_active.id,
            previous_active.fuel_type,
            new_valid_to,
        )

    # Adım 3: Yeni kaydı oluştur
    new_tax = TaxParameter(
        fuel_type=data.fuel_type,
        otv_rate=data.otv_rate,
        otv_fixed_tl=data.otv_fixed_tl,
        kdv_rate=data.kdv_rate,
        valid_from=data.valid_from,
        valid_to=None,  # Yeni kayıt her zaman aktif olarak başlar
        gazette_reference=data.gazette_reference,
        notes=data.notes,
        created_by=data.created_by,
    )

    session.add(new_tax)
    await session.flush()  # ID ataması için flush (commit dependency injection'da yapılır)

    logger.info(
        "Yeni vergi kaydı oluşturuldu: id=%d, fuel_type=%s, "
        "otv_fixed_tl=%s, kdv_rate=%s, valid_from=%s",
        new_tax.id,
        new_tax.fuel_type,
        new_tax.otv_fixed_tl,
        new_tax.kdv_rate,
        new_tax.valid_from,
    )

    return new_tax


async def update_tax_parameter(
    session: AsyncSession,
    tax_id: int,
    otv_rate: Decimal | None = None,
    otv_fixed_tl: Decimal | None = None,
    kdv_rate: Decimal | None = None,
    gazette_reference: str | None = None,
    notes: str | None = None,
) -> TaxParameter | None:
    """
    Mevcut vergi parametresini günceller.

    Sadece belirtilen alanlar güncellenir (partial update).
    valid_from ve valid_to bu fonksiyonla güncellenemez (temporal bütünlük).

    Args:
        session: Async veritabanı oturumu.
        tax_id: Güncellenecek kayıt ID'si.
        otv_rate: Yeni ÖTV oranı (opsiyonel).
        otv_fixed_tl: Yeni ÖTV sabit tutar (opsiyonel).
        kdv_rate: Yeni KDV oranı (opsiyonel).
        gazette_reference: Yeni Resmi Gazete referansı (opsiyonel).
        notes: Yeni notlar (opsiyonel).

    Returns:
        Güncellenen TaxParameter nesnesi veya None (kayıt bulunamazsa).

    Raises:
        TaxValidationErrors: Doğrulama hataları varsa.
    """
    # Mevcut kaydı bul
    existing = await get_tax_by_id(session, tax_id)
    if existing is None:
        return None

    # Güncellenecek değerleri belirle
    new_otv_rate = otv_rate if otv_rate is not None else existing.otv_rate
    new_otv_fixed_tl = otv_fixed_tl if otv_fixed_tl is not None else existing.otv_fixed_tl
    new_kdv_rate = kdv_rate if kdv_rate is not None else existing.kdv_rate

    # Doğrulama
    validate_tax_parameter(
        fuel_type=existing.fuel_type,
        otv_rate=new_otv_rate,
        otv_fixed_tl=new_otv_fixed_tl,
        kdv_rate=new_kdv_rate,
        valid_from=existing.valid_from,
        valid_to=existing.valid_to,
    )

    # Güncelleme değerlerini hazırla
    update_values: dict = {}
    if otv_rate is not None:
        update_values["otv_rate"] = otv_rate
    if otv_fixed_tl is not None:
        update_values["otv_fixed_tl"] = otv_fixed_tl
    if kdv_rate is not None:
        update_values["kdv_rate"] = kdv_rate
    if gazette_reference is not None:
        update_values["gazette_reference"] = gazette_reference
    if notes is not None:
        update_values["notes"] = notes

    if not update_values:
        logger.info("Güncellenecek alan yok: tax_id=%d", tax_id)
        return existing

    # Güncelle
    update_stmt = (
        update(TaxParameter)
        .where(TaxParameter.id == tax_id)
        .values(**update_values)
    )
    await session.execute(update_stmt)

    # Güncellenmiş kaydı yeniden yükle
    await session.refresh(existing)

    logger.info(
        "Vergi kaydı güncellendi: id=%d, güncellenen alanlar=%s",
        tax_id,
        list(update_values.keys()),
    )

    return existing
