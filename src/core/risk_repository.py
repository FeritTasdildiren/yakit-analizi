"""
Risk skoru repository'si.

risk_scores tablosu için CRUD ve UPSERT işlemleri.
Tüm veritabanı erişimi async olarak çalışır.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import select, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.risk_scores import RiskScore

logger = logging.getLogger(__name__)


async def upsert_risk_score(
    session: AsyncSession,
    trade_date: date,
    fuel_type: str,
    composite_score: Decimal,
    mbe_component: Decimal,
    fx_volatility_component: Decimal,
    political_delay_component: Decimal,
    threshold_breach_component: Decimal,
    trend_momentum_component: Decimal,
    weight_vector: dict,
    system_mode: str = "normal",
    triggered_alerts: list[str] | None = None,
) -> RiskScore:
    """
    Risk skorunu UPSERT (ON CONFLICT DO UPDATE) ile kaydeder.

    (trade_date, fuel_type) çifti varsa günceller, yoksa ekler.

    Returns:
        Eklenen/güncellenen RiskScore nesnesi.
    """
    stmt = pg_insert(RiskScore).values(
        trade_date=trade_date,
        fuel_type=fuel_type,
        composite_score=composite_score,
        mbe_component=mbe_component,
        fx_volatility_component=fx_volatility_component,
        political_delay_component=political_delay_component,
        threshold_breach_component=threshold_breach_component,
        trend_momentum_component=trend_momentum_component,
        weight_vector=weight_vector,
        system_mode=system_mode,
        triggered_alerts=triggered_alerts,
    )

    stmt = stmt.on_conflict_do_update(
        constraint="uq_risk_score_date_fuel",
        set_={
            "composite_score": stmt.excluded.composite_score,
            "mbe_component": stmt.excluded.mbe_component,
            "fx_volatility_component": stmt.excluded.fx_volatility_component,
            "political_delay_component": stmt.excluded.political_delay_component,
            "threshold_breach_component": stmt.excluded.threshold_breach_component,
            "trend_momentum_component": stmt.excluded.trend_momentum_component,
            "weight_vector": stmt.excluded.weight_vector,
            "system_mode": stmt.excluded.system_mode,
            "triggered_alerts": stmt.excluded.triggered_alerts,
        },
    ).returning(RiskScore)

    result = await session.execute(stmt)
    row = result.scalar_one()
    logger.info(
        "Risk skoru UPSERT: tarih=%s, yakıt=%s, skor=%s",
        trade_date,
        fuel_type,
        composite_score,
    )
    return row


async def get_latest_risk(
    session: AsyncSession,
    fuel_type: str,
) -> Optional[RiskScore]:
    """Belirli yakıt tipi için en son risk skorunu döndürür."""
    stmt = (
        select(RiskScore)
        .where(RiskScore.fuel_type == fuel_type)
        .order_by(RiskScore.trade_date.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_risk_range(
    session: AsyncSession,
    fuel_type: str,
    start_date: date,
    end_date: date,
) -> Sequence[RiskScore]:
    """Tarih aralığında risk skorlarını döndürür."""
    stmt = (
        select(RiskScore)
        .where(
            and_(
                RiskScore.fuel_type == fuel_type,
                RiskScore.trade_date >= start_date,
                RiskScore.trade_date <= end_date,
            )
        )
        .order_by(RiskScore.trade_date.asc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_high_risk_days(
    session: AsyncSession,
    fuel_type: str,
    min_score: Decimal = Decimal("0.60"),
    limit: int = 30,
) -> Sequence[RiskScore]:
    """Yüksek risk skorlu günleri döndürür."""
    stmt = (
        select(RiskScore)
        .where(
            and_(
                RiskScore.fuel_type == fuel_type,
                RiskScore.composite_score >= min_score,
            )
        )
        .order_by(RiskScore.trade_date.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()
