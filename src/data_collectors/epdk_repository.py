"""
EPDK Pompa Fiyatı Repository Modülü

daily_market_data tablosuna UPSERT işlemi gerçekleştirir.
ON CONFLICT (trade_date, fuel_type) DO UPDATE SET pump_price_tl_lt = ...

SQLAlchemy async kullanır.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_collectors.epdk_collector import PumpPriceData
from src.models.market_data import DailyMarketData

logger = logging.getLogger(__name__)


async def upsert_pump_price(
    session: AsyncSession,
    price_data: PumpPriceData,
) -> DailyMarketData:
    """
    Tek bir pompa fiyatı kaydını daily_market_data tablosuna UPSERT eder.

    ON CONFLICT (trade_date, fuel_type) DO UPDATE SET
        pump_price_tl_lt = EXCLUDED.pump_price_tl_lt,
        source = 'epdk_xml',
        data_quality_flag = 'verified'

    Args:
        session: SQLAlchemy async session.
        price_data: Yazılacak pompa fiyatı verisi.

    Returns:
        UPSERT edilen DailyMarketData satırı.
    """
    values = {
        "trade_date": price_data.trade_date,
        "fuel_type": price_data.fuel_type,
        "pump_price_tl_lt": price_data.pump_price_tl_lt,
        "source": "epdk_xml",
        "data_quality_flag": "verified",
    }

    stmt = pg_insert(DailyMarketData).values(**values)

    stmt = stmt.on_conflict_do_update(
        constraint="uq_daily_market_date_fuel",
        set_={
            "pump_price_tl_lt": stmt.excluded.pump_price_tl_lt,
            "source": "epdk_xml",
            "data_quality_flag": "verified",
        },
    )

    # RETURNING ile eklenen/güncellenen satırı al
    stmt = stmt.returning(DailyMarketData)

    result = await session.execute(stmt)
    row = result.scalar_one()

    logger.info(
        "UPSERT tamamlandı: trade_date=%s, fuel_type=%s, pump_price=%s TL/lt",
        price_data.trade_date,
        price_data.fuel_type,
        price_data.pump_price_tl_lt,
    )

    return row


async def upsert_pump_prices_batch(
    session: AsyncSession,
    prices: list[PumpPriceData],
) -> list[DailyMarketData]:
    """
    Birden fazla pompa fiyatını toplu olarak UPSERT eder.

    Her kayıt ayrı ayrı UPSERT edilir (PostgreSQL RETURNING desteği için).
    Tüm işlem tek transaction içinde yapılır.

    Args:
        session: SQLAlchemy async session.
        prices: Yazılacak pompa fiyatı listesi.

    Returns:
        UPSERT edilen DailyMarketData listesi.
    """
    results: list[DailyMarketData] = []

    for price_data in prices:
        try:
            row = await upsert_pump_price(session, price_data)
            results.append(row)
        except Exception:
            logger.exception(
                "UPSERT hatası: trade_date=%s, fuel_type=%s",
                price_data.trade_date,
                price_data.fuel_type,
            )
            raise

    logger.info("Toplu UPSERT tamamlandı: %d kayıt işlendi.", len(results))
    return results


async def get_pump_price_by_date(
    session: AsyncSession,
    trade_date: date,
    fuel_type: str | None = None,
) -> list[DailyMarketData]:
    """
    Belirli bir tarihe ait pompa fiyatlarını getirir.

    Args:
        session: SQLAlchemy async session.
        trade_date: İstenilen tarih.
        fuel_type: Yakıt tipi filtresi (opsiyonel). None ise tüm yakıt tipleri.

    Returns:
        DailyMarketData listesi.
    """
    stmt = (
        select(DailyMarketData)
        .where(DailyMarketData.trade_date == trade_date)
    )

    if fuel_type is not None:
        stmt = stmt.where(DailyMarketData.fuel_type == fuel_type)

    stmt = stmt.order_by(DailyMarketData.fuel_type)

    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    logger.debug("Sorgu: trade_date=%s, fuel_type=%s — %d kayıt bulundu.", trade_date, fuel_type, len(rows))
    return rows


async def get_latest_pump_prices(
    session: AsyncSession,
) -> list[DailyMarketData]:
    """
    En son tarihli pompa fiyatlarını getirir.

    Returns:
        En güncel DailyMarketData listesi.
    """
    # Önce en son tarihi bul
    latest_date_stmt = (
        select(DailyMarketData.trade_date)
        .where(DailyMarketData.source == "epdk_xml")
        .order_by(DailyMarketData.trade_date.desc())
        .limit(1)
    )
    result = await session.execute(latest_date_stmt)
    latest_date = result.scalar_one_or_none()

    if latest_date is None:
        logger.info("Veritabanında EPDK pompa fiyatı bulunamadı.")
        return []

    return await get_pump_price_by_date(session, latest_date)


async def get_previous_day_average(
    session: AsyncSession,
    trade_date: date,
    fuel_type: str,
) -> Decimal | None:
    """
    Belirtilen tarihten bir önceki günün ortalama fiyatını getirir.
    Günlük değişim doğrulaması için kullanılır.

    Args:
        session: SQLAlchemy async session.
        trade_date: Referans tarih (bu tarihten ÖNCEKİ en yakın kayıt bulunur).
        fuel_type: Yakıt tipi.

    Returns:
        Önceki günün ortalama fiyatı veya None.
    """
    stmt = (
        select(DailyMarketData.pump_price_tl_lt)
        .where(
            DailyMarketData.trade_date < trade_date,
            DailyMarketData.fuel_type == fuel_type,
            DailyMarketData.source == "epdk_xml",
        )
        .order_by(DailyMarketData.trade_date.desc())
        .limit(1)
    )

    result = await session.execute(stmt)
    previous_price = result.scalar_one_or_none()

    if previous_price is not None:
        logger.debug(
            "Önceki gün fiyatı bulundu: fuel_type=%s, trade_date<%s → %s TL/lt",
            fuel_type,
            trade_date,
            previous_price,
        )

    return previous_price
