"""
Piyasa verisi repository katmanı.

Veritabanı CRUD operasyonları — UPSERT, sorgulama ve boşluk tespiti.
Tüm fonksiyonlar async olarak çalışır, AsyncSession kullanır.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.market_data import DailyMarketData

logger = logging.getLogger(__name__)


async def upsert_market_data(
    session: AsyncSession,
    *,
    trade_date: date,
    fuel_type: str,
    brent_usd_bbl: Decimal | None = None,
    cif_med_usd_ton: Decimal | None = None,
    usd_try_rate: Decimal | None = None,
    pump_price_tl_lt: Decimal | None = None,
    distribution_margin_tl: Decimal | None = None,
    data_quality_flag: str = "verified",
    source: str = "",
    raw_payload: dict | None = None,
) -> DailyMarketData:
    """
    Piyasa verisini ekler veya günceller (UPSERT).

    ON CONFLICT (trade_date, fuel_type) DO UPDATE ile çalışır.
    Mevcut kayıt varsa belirtilen alanları günceller, yoksa yeni kayıt oluşturur.

    Args:
        session: Async veritabanı oturumu
        trade_date: İşlem tarihi
        fuel_type: Yakıt tipi (benzin, motorin, lpg)
        brent_usd_bbl: Brent petrol fiyatı (USD/varil)
        cif_med_usd_ton: CIF Akdeniz fiyatı (USD/ton)
        usd_try_rate: USD/TRY döviz kuru
        pump_price_tl_lt: Pompa fiyatı (TL/litre)
        distribution_margin_tl: Dağıtım marjı (TL)
        data_quality_flag: Veri kalite bayrağı
        source: Veri kaynağı
        raw_payload: Ham API yanıtı (JSONB)

    Returns:
        Eklenen veya güncellenen DailyMarketData kaydı
    """
    values = {
        "trade_date": trade_date,
        "fuel_type": fuel_type,
        "source": source,
        "data_quality_flag": data_quality_flag,
    }

    # None olmayan opsiyonel alanları ekle
    if brent_usd_bbl is not None:
        values["brent_usd_bbl"] = brent_usd_bbl
    if cif_med_usd_ton is not None:
        values["cif_med_usd_ton"] = cif_med_usd_ton
    if usd_try_rate is not None:
        values["usd_try_rate"] = usd_try_rate
    if pump_price_tl_lt is not None:
        values["pump_price_tl_lt"] = pump_price_tl_lt
    if distribution_margin_tl is not None:
        values["distribution_margin_tl"] = distribution_margin_tl
    if raw_payload is not None:
        values["raw_payload"] = raw_payload

    # PostgreSQL UPSERT (INSERT ... ON CONFLICT DO UPDATE)
    stmt = pg_insert(DailyMarketData).values(**values)

    # Güncelleme alanları — trade_date ve fuel_type hariç tümü
    update_fields = {k: v for k, v in values.items() if k not in ("trade_date", "fuel_type")}
    update_fields["updated_at"] = text("NOW()")

    stmt = stmt.on_conflict_do_update(
        constraint="uq_daily_market_date_fuel",
        set_=update_fields,
    ).returning(DailyMarketData)

    result = await session.execute(stmt)
    row = result.scalar_one()

    logger.info(
        "Piyasa verisi upsert: %s / %s / %s (kaynak: %s)",
        trade_date,
        fuel_type,
        f"brent={brent_usd_bbl}" if brent_usd_bbl else f"fx={usd_try_rate}",
        source,
    )

    return row


async def get_latest_data(
    session: AsyncSession,
    fuel_type: str,
) -> DailyMarketData | None:
    """
    Belirli yakıt tipi için en son kaydı döndürür.

    Args:
        session: Async veritabanı oturumu
        fuel_type: Yakıt tipi (benzin, motorin, lpg)

    Returns:
        En son DailyMarketData veya None
    """
    stmt = (
        select(DailyMarketData)
        .where(DailyMarketData.fuel_type == fuel_type)
        .order_by(DailyMarketData.trade_date.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_data_range(
    session: AsyncSession,
    fuel_type: str,
    start: date,
    end: date,
) -> list[DailyMarketData]:
    """
    Belirli yakıt tipi ve tarih aralığı için kayıtları döndürür.

    Args:
        session: Async veritabanı oturumu
        fuel_type: Yakıt tipi
        start: Başlangıç tarihi (dahil)
        end: Bitiş tarihi (dahil)

    Returns:
        DailyMarketData listesi (trade_date'e göre sıralı)
    """
    stmt = (
        select(DailyMarketData)
        .where(
            DailyMarketData.fuel_type == fuel_type,
            DailyMarketData.trade_date >= start,
            DailyMarketData.trade_date <= end,
        )
        .order_by(DailyMarketData.trade_date.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def check_gaps(
    session: AsyncSession,
    fuel_type: str,
    start: date,
    end: date,
) -> list[date]:
    """
    Belirli yakıt tipi ve tarih aralığında eksik günleri tespit eder.

    Veritabanındaki mevcut tarihler ile beklenen tarihler karşılaştırılır.

    Args:
        session: Async veritabanı oturumu
        fuel_type: Yakıt tipi
        start: Başlangıç tarihi
        end: Bitiş tarihi

    Returns:
        Eksik tarihlerin listesi
    """
    # Mevcut tarihleri çek
    stmt = (
        select(DailyMarketData.trade_date)
        .where(
            DailyMarketData.fuel_type == fuel_type,
            DailyMarketData.trade_date >= start,
            DailyMarketData.trade_date <= end,
        )
    )
    result = await session.execute(stmt)
    existing_dates: set[date] = {row[0] for row in result.all()}

    # Beklenen tarihleri oluştur ve eksikleri bul
    missing: list[date] = []
    current = start
    while current <= end:
        if current not in existing_dates:
            missing.append(current)
        current += timedelta(days=1)

    if missing:
        logger.info(
            "%s için %d eksik gün tespit edildi (%s — %s)",
            fuel_type,
            len(missing),
            start,
            end,
        )

    return missing


async def get_previous_data(
    session: AsyncSession,
    fuel_type: str,
    before_date: date,
) -> DailyMarketData | None:
    """
    Belirli bir tarihten önceki en son kaydı döndürür.

    Günlük değişim kontrolü için kullanılır.

    Args:
        session: Async veritabanı oturumu
        fuel_type: Yakıt tipi
        before_date: Bu tarihten önceki kayıt aranır

    Returns:
        Önceki DailyMarketData veya None
    """
    stmt = (
        select(DailyMarketData)
        .where(
            DailyMarketData.fuel_type == fuel_type,
            DailyMarketData.trade_date < before_date,
        )
        .order_by(DailyMarketData.trade_date.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
