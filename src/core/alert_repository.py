"""
Alert repository'si.

alerts tablosu için CRUD işlemleri.
Tüm veritabanı erişimi async olarak çalışır.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.alerts import Alert

logger = logging.getLogger(__name__)


async def create_alert(
    session: AsyncSession,
    alert_level: str,
    alert_type: str,
    title: str,
    message: str,
    metric_name: str,
    metric_value: Decimal,
    threshold_value: Decimal,
    fuel_type: str | None = None,
    threshold_config_id: int | None = None,
    risk_score_id: int | None = None,
    channels_sent: list[str] | None = None,
) -> Alert:
    """
    Yeni bir alert oluşturur.

    Returns:
        Oluşturulan Alert nesnesi.
    """
    alert = Alert(
        alert_level=alert_level,
        alert_type=alert_type,
        fuel_type=fuel_type,
        title=title,
        message=message,
        metric_name=metric_name,
        metric_value=metric_value,
        threshold_value=threshold_value,
        threshold_config_id=threshold_config_id,
        risk_score_id=risk_score_id,
        channels_sent=channels_sent,
    )
    session.add(alert)
    await session.flush()
    logger.info(
        "Alert oluşturuldu: id=%s, level=%s, type=%s",
        alert.id,
        alert_level,
        alert_type,
    )
    return alert


async def get_alert_by_id(
    session: AsyncSession,
    alert_id: int,
) -> Optional[Alert]:
    """ID ile alert getirir."""
    stmt = select(Alert).where(Alert.id == alert_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_alerts(
    session: AsyncSession,
    fuel_type: str | None = None,
    unread_only: bool = False,
    unresolved_only: bool = False,
    limit: int = 100,
) -> Sequence[Alert]:
    """
    Alert'leri filtreli olarak döndürür.

    Args:
        session: Async veritabanı oturumu.
        fuel_type: Yakıt tipi filtresi (None ise tümü).
        unread_only: Sadece okunmamışları getir.
        unresolved_only: Sadece çözülmemişleri getir.
        limit: Maksimum kayıt sayısı.

    Returns:
        Alert listesi.
    """
    stmt = select(Alert).order_by(Alert.created_at.desc()).limit(limit)

    conditions = []
    if fuel_type is not None:
        conditions.append(Alert.fuel_type == fuel_type)
    if unread_only:
        conditions.append(Alert.is_read == False)  # noqa: E712
    if unresolved_only:
        conditions.append(Alert.is_resolved == False)  # noqa: E712

    if conditions:
        stmt = stmt.where(and_(*conditions))

    result = await session.execute(stmt)
    return result.scalars().all()


async def get_unread_alerts(
    session: AsyncSession,
    limit: int = 100,
) -> Sequence[Alert]:
    """Okunmamış alert'leri döndürür."""
    return await get_alerts(session, unread_only=True, limit=limit)


async def get_unresolved_alerts(
    session: AsyncSession,
    limit: int = 100,
) -> Sequence[Alert]:
    """Çözülmemiş alert'leri döndürür."""
    return await get_alerts(session, unresolved_only=True, limit=limit)


async def mark_alert_read(
    session: AsyncSession,
    alert_id: int,
) -> Optional[Alert]:
    """
    Alert'i okundu olarak işaretler.

    Returns:
        Güncellenen Alert veya None.
    """
    stmt = (
        update(Alert)
        .where(Alert.id == alert_id)
        .values(is_read=True)
        .returning(Alert)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if row is not None:
        logger.info("Alert okundu olarak işaretlendi: id=%s", alert_id)

    return row


async def resolve_alert(
    session: AsyncSession,
    alert_id: int,
    resolved_reason: str | None = None,
) -> Optional[Alert]:
    """
    Alert'i çözüldü olarak işaretler.

    Args:
        session: Async veritabanı oturumu.
        alert_id: Çözülecek alert ID'si.
        resolved_reason: Çözüm nedeni açıklaması.

    Returns:
        Güncellenen Alert veya None.
    """
    stmt = (
        update(Alert)
        .where(Alert.id == alert_id)
        .values(
            is_resolved=True,
            resolved_at=datetime.utcnow(),
            resolved_reason=resolved_reason,
        )
        .returning(Alert)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if row is not None:
        logger.info(
            "Alert çözüldü: id=%s, neden=%s",
            alert_id,
            resolved_reason,
        )

    return row
