"""
Politik gecikme repository'si.

political_delay_history tablosu için CRUD işlemleri.
Tüm veritabanı erişimi async olarak çalışır.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import select, update, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.political_delay_history import PoliticalDelayHistory

logger = logging.getLogger(__name__)


async def create_delay_record(
    session: AsyncSession,
    fuel_type: str,
    expected_change_date: date,
    mbe_at_expected: Decimal,
    regime_event_id: int | None = None,
) -> PoliticalDelayHistory:
    """
    Yeni gecikme takip kaydı oluşturur (WATCHING durumuna geçişte).

    Returns:
        Oluşturulan PoliticalDelayHistory.
    """
    record = PoliticalDelayHistory(
        fuel_type=fuel_type,
        expected_change_date=expected_change_date,
        mbe_at_expected=mbe_at_expected,
        status="watching",
        regime_event_id=regime_event_id,
    )
    session.add(record)
    await session.flush()
    logger.info(
        "Gecikme kaydı oluşturuldu: id=%s, yakıt=%s, beklenen=%s",
        record.id,
        fuel_type,
        expected_change_date,
    )
    return record


async def get_delay_by_id(
    session: AsyncSession,
    record_id: int,
) -> Optional[PoliticalDelayHistory]:
    """ID ile gecikme kaydı getirir."""
    stmt = select(PoliticalDelayHistory).where(PoliticalDelayHistory.id == record_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_pending_delays(
    session: AsyncSession,
    fuel_type: str | None = None,
) -> Sequence[PoliticalDelayHistory]:
    """
    Bekleyen (watching) gecikme kayıtlarını döndürür.

    Args:
        session: Async veritabanı oturumu.
        fuel_type: Yakıt tipi filtresi (None ise tümü).

    Returns:
        PoliticalDelayHistory listesi.
    """
    stmt = (
        select(PoliticalDelayHistory)
        .where(PoliticalDelayHistory.status == "watching")
        .order_by(PoliticalDelayHistory.expected_change_date.asc())
    )

    if fuel_type is not None:
        stmt = stmt.where(PoliticalDelayHistory.fuel_type == fuel_type)

    result = await session.execute(stmt)
    return result.scalars().all()


async def close_delay_record(
    session: AsyncSession,
    record_id: int,
    actual_change_date: date,
    delay_days: int,
    mbe_at_actual: Decimal,
    accumulated_pressure_pct: Decimal,
    status: str = "closed",
    price_change_id: int | None = None,
) -> Optional[PoliticalDelayHistory]:
    """
    Gecikme kaydını kapatır (zam geldi veya absorbe edildi).

    Args:
        session: Async veritabanı oturumu.
        record_id: Kapatılacak kayıt ID'si.
        actual_change_date: Gerçek değişiklik tarihi.
        delay_days: Gecikme gün sayısı.
        mbe_at_actual: Kapanış tarihindeki MBE değeri.
        accumulated_pressure_pct: Birikmiş basınç yüzdesi.
        status: Kapanış durumu (closed, absorbed, partial_close).
        price_change_id: İlişkili fiyat değişikliği ID.

    Returns:
        Güncellenen PoliticalDelayHistory veya None.
    """
    stmt = (
        update(PoliticalDelayHistory)
        .where(PoliticalDelayHistory.id == record_id)
        .values(
            actual_change_date=actual_change_date,
            delay_days=delay_days,
            mbe_at_actual=mbe_at_actual,
            accumulated_pressure_pct=accumulated_pressure_pct,
            status=status,
            price_change_id=price_change_id,
        )
        .returning(PoliticalDelayHistory)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if row is not None:
        logger.info(
            "Gecikme kaydı kapatıldı: id=%s, durum=%s, gecikme=%d gün",
            record_id,
            status,
            delay_days,
        )

    return row


async def get_delay_history(
    session: AsyncSession,
    fuel_type: str,
    limit: int = 50,
) -> Sequence[PoliticalDelayHistory]:
    """
    Belirli yakıt tipi için gecikme geçmişini döndürür.

    Args:
        session: Async veritabanı oturumu.
        fuel_type: Yakıt tipi.
        limit: Maksimum kayıt sayısı.

    Returns:
        PoliticalDelayHistory listesi (en yeniden en eskiye).
    """
    stmt = (
        select(PoliticalDelayHistory)
        .where(PoliticalDelayHistory.fuel_type == fuel_type)
        .order_by(PoliticalDelayHistory.expected_change_date.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_delay_stats(
    session: AsyncSession,
    fuel_type: str,
) -> dict:
    """
    Belirli yakıt tipi için gecikme istatistiklerini hesaplar.

    Sadece kapatılmış (closed, partial_close) kayıtları sayar.

    Returns:
        Dict: count, avg_delay, max_delay, min_delay, std_delay
    """
    stmt = (
        select(
            func.count(PoliticalDelayHistory.id).label("count"),
            func.avg(PoliticalDelayHistory.delay_days).label("avg_delay"),
            func.max(PoliticalDelayHistory.delay_days).label("max_delay"),
            func.min(PoliticalDelayHistory.delay_days).label("min_delay"),
            func.stddev_pop(PoliticalDelayHistory.delay_days).label("std_delay"),
        )
        .where(
            and_(
                PoliticalDelayHistory.fuel_type == fuel_type,
                PoliticalDelayHistory.status.in_(["closed", "partial_close"]),
            )
        )
    )
    result = await session.execute(stmt)
    row = result.one()

    return {
        "fuel_type": fuel_type,
        "count": row.count or 0,
        "avg_delay": str(round(row.avg_delay, 2)) if row.avg_delay is not None else "0",
        "max_delay": row.max_delay or 0,
        "min_delay": row.min_delay or 0,
        "std_delay": str(round(row.std_delay, 2)) if row.std_delay is not None else "0",
    }
