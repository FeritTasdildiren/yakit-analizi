"""
Politik gecikme API endpoint'leri.

Gecikme takibi ve istatistikler.
Tüm endpoint'ler /api/v1/delays prefix'i altındadır.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_db
from src.core.delay_repository import (
    get_delay_history,
    get_delay_stats,
    get_pending_delays,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/delays", tags=["Politik Gecikme"])


# --- Pydantic Modelleri ---


class DelayRecordResponse(BaseModel):
    """Gecikme kaydı yanıt şeması."""

    id: int
    fuel_type: str
    expected_change_date: date
    actual_change_date: date | None = None
    delay_days: int
    mbe_at_expected: Decimal
    mbe_at_actual: Decimal | None = None
    accumulated_pressure_pct: Decimal
    status: str
    regime_event_id: int | None = None
    price_change_id: int | None = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class DelayListResponse(BaseModel):
    """Gecikme kaydı liste yanıtı."""

    count: int
    data: list[DelayRecordResponse]


class DelayStatsResponse(BaseModel):
    """Gecikme istatistikleri yanıtı."""

    fuel_type: str
    count: int
    avg_delay: str
    max_delay: int
    min_delay: int
    std_delay: str


# --- Endpoint'ler ---


@router.get(
    "/pending",
    response_model=DelayListResponse,
    summary="Bekleyen gecikme kayıtları",
)
async def list_pending(
    fuel_type: str | None = Query(
        default=None,
        description="Yakıt tipi filtresi (benzin, motorin, lpg)",
    ),
    db: AsyncSession = Depends(get_db),
) -> DelayListResponse:
    """Watching durumundaki (bekleyen) gecikme kayıtlarını döndürür."""
    if fuel_type is not None and fuel_type not in {"benzin", "motorin", "lpg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Geçersiz yakıt tipi: '{fuel_type}'",
        )

    records = await get_pending_delays(db, fuel_type=fuel_type)
    data = [DelayRecordResponse.model_validate(r) for r in records]
    return DelayListResponse(count=len(data), data=data)


@router.get(
    "/history/{fuel_type}",
    response_model=DelayListResponse,
    summary="Gecikme geçmişi",
)
async def list_history(
    fuel_type: str,
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> DelayListResponse:
    """Belirtilen yakıt tipi için gecikme geçmişini döndürür."""
    if fuel_type not in {"benzin", "motorin", "lpg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Geçersiz yakıt tipi: '{fuel_type}'",
        )

    records = await get_delay_history(db, fuel_type, limit=limit)
    data = [DelayRecordResponse.model_validate(r) for r in records]
    return DelayListResponse(count=len(data), data=data)


@router.get(
    "/stats/{fuel_type}",
    response_model=DelayStatsResponse,
    summary="Gecikme istatistikleri",
)
async def get_stats(
    fuel_type: str,
    db: AsyncSession = Depends(get_db),
) -> DelayStatsResponse:
    """
    Belirtilen yakıt tipi için gecikme istatistiklerini döndürür.

    Sadece kapatılmış (closed, partial_close) kayıtları hesaba katar.
    """
    if fuel_type not in {"benzin", "motorin", "lpg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Geçersiz yakıt tipi: '{fuel_type}'",
        )

    stats = await get_delay_stats(db, fuel_type)
    return DelayStatsResponse(**stats)
