"""
Rejim olayları repository'si.

regime_events tablosu için CRUD işlemleri.
Tüm veritabanı erişimi async olarak çalışır.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional, Sequence

from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.regime_events import RegimeEvent

logger = logging.getLogger(__name__)


async def create_regime_event(
    session: AsyncSession,
    event_type: str,
    event_name: str,
    start_date: date,
    end_date: date,
    impact_score: int,
    source: str = "manual",
    description: str | None = None,
) -> RegimeEvent:
    """
    Yeni rejim olayı oluşturur.

    Args:
        session: Async veritabanı oturumu.
        event_type: Olay tipi (election, holiday, ...).
        event_name: Olay adı.
        start_date: Başlangıç tarihi.
        end_date: Bitiş tarihi.
        impact_score: Etki skoru (0-10).
        source: Veri kaynağı.
        description: Ek açıklama.

    Returns:
        Oluşturulan RegimeEvent.
    """
    event = RegimeEvent(
        event_type=event_type,
        event_name=event_name,
        start_date=start_date,
        end_date=end_date,
        impact_score=impact_score,
        source=source,
        description=description,
        is_active=True,
    )
    session.add(event)
    await session.flush()
    logger.info(
        "Rejim olayı oluşturuldu: id=%s, tip=%s, ad=%s",
        event.id,
        event_type,
        event_name,
    )
    return event


async def get_regime_event_by_id(
    session: AsyncSession,
    event_id: int,
) -> Optional[RegimeEvent]:
    """ID ile rejim olayı getirir."""
    stmt = select(RegimeEvent).where(RegimeEvent.id == event_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_active_events(
    session: AsyncSession,
    ref_date: Optional[date] = None,
) -> Sequence[RegimeEvent]:
    """
    Aktif rejim olaylarını döndürür.

    Args:
        session: Async veritabanı oturumu.
        ref_date: Referans tarih. None ise bugün.

    Returns:
        Aktif RegimeEvent listesi.
    """
    if ref_date is None:
        ref_date = date.today()

    stmt = (
        select(RegimeEvent)
        .where(
            and_(
                RegimeEvent.is_active == True,  # noqa: E712
                RegimeEvent.start_date <= ref_date,
                RegimeEvent.end_date >= ref_date,
            )
        )
        .order_by(RegimeEvent.impact_score.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_event_history(
    session: AsyncSession,
    event_type: Optional[str] = None,
    limit: int = 50,
) -> Sequence[RegimeEvent]:
    """
    Rejim olayı geçmişini döndürür.

    Args:
        session: Async veritabanı oturumu.
        event_type: Filtrelenecek olay tipi (None ise tümü).
        limit: Maksimum kayıt sayısı.

    Returns:
        RegimeEvent listesi (en yeniden en eskiye).
    """
    stmt = select(RegimeEvent).order_by(RegimeEvent.start_date.desc()).limit(limit)

    if event_type is not None:
        stmt = stmt.where(RegimeEvent.event_type == event_type)

    result = await session.execute(stmt)
    return result.scalars().all()


async def deactivate_event(
    session: AsyncSession,
    event_id: int,
) -> Optional[RegimeEvent]:
    """
    Rejim olayını deaktif eder.

    Args:
        session: Async veritabanı oturumu.
        event_id: Deaktif edilecek olay ID'si.

    Returns:
        Güncellenen RegimeEvent veya None.
    """
    stmt = (
        update(RegimeEvent)
        .where(RegimeEvent.id == event_id)
        .values(is_active=False)
        .returning(RegimeEvent)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if row is not None:
        logger.info("Rejim olayı deaktif edildi: id=%s", event_id)

    return row
