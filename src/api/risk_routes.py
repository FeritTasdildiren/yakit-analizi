"""
Risk skoru API endpoint'leri.

Risk skorlarını sorgulama ve hesaplama tetikleme.
Tüm endpoint'ler /api/v1/risk prefix'i altındadır.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_db
from src.core.risk_repository import (
    get_high_risk_days,
    get_latest_risk,
    get_risk_range,
    upsert_risk_score,
)
from src.core.risk_engine import (
    RiskComponents,
    calculate_risk_score,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/risk", tags=["Risk Skorları"])


# --- Pydantic Modelleri ---


class RiskScoreResponse(BaseModel):
    """Risk skoru yanıt şeması."""

    id: int
    trade_date: date
    fuel_type: str
    composite_score: Decimal
    mbe_component: Decimal
    fx_volatility_component: Decimal
    political_delay_component: Decimal
    threshold_breach_component: Decimal
    trend_momentum_component: Decimal
    system_mode: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class RiskCalculateRequest(BaseModel):
    """Risk skoru hesaplama isteği."""

    trade_date: date
    fuel_type: str
    mbe_value: Decimal = Field(description="MBE değeri")
    fx_volatility: Decimal = Field(description="FX volatilite değeri")
    political_delay: Decimal = Field(description="Politik gecikme gün sayısı")
    threshold_breach: Decimal = Field(description="Eşik ihlali değeri (0-1)")
    trend_momentum: Decimal = Field(description="Trend momentum değeri")


class RiskCalculateResponse(BaseModel):
    """Risk skoru hesaplama yanıtı."""

    composite_score: str
    mbe_component: str
    fx_volatility_component: str
    political_delay_component: str
    threshold_breach_component: str
    trend_momentum_component: str
    system_mode: str
    saved: bool


class RiskScoreListResponse(BaseModel):
    """Risk skoru liste yanıtı."""

    count: int
    data: list[RiskScoreResponse]


# --- Endpoint'ler ---


@router.get(
    "/latest",
    response_model=RiskScoreListResponse,
    summary="Tüm yakıt tipleri için en son risk skorları",
)
async def get_latest_all(
    db: AsyncSession = Depends(get_db),
) -> RiskScoreListResponse:
    """Her yakıt tipi için en güncel risk skorunu döndürür."""
    results = []
    for fuel_type in ("benzin", "motorin", "lpg"):
        record = await get_latest_risk(db, fuel_type)
        if record is not None:
            results.append(RiskScoreResponse.model_validate(record))

    return RiskScoreListResponse(count=len(results), data=results)


@router.get(
    "/latest/{fuel_type}",
    response_model=RiskScoreResponse,
    summary="Belirli yakıt tipi için en son risk skoru",
)
async def get_latest_by_fuel(
    fuel_type: str,
    db: AsyncSession = Depends(get_db),
) -> RiskScoreResponse:
    """Belirtilen yakıt tipi için en güncel risk skorunu döndürür."""
    if fuel_type not in {"benzin", "motorin", "lpg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Geçersiz yakıt tipi: '{fuel_type}'",
        )

    record = await get_latest_risk(db, fuel_type)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{fuel_type}' için risk skoru bulunamadı",
        )

    return RiskScoreResponse.model_validate(record)


@router.get(
    "/range/{fuel_type}",
    response_model=RiskScoreListResponse,
    summary="Tarih aralığında risk skorları",
)
async def get_range(
    fuel_type: str,
    start_date: date = Query(description="Başlangıç tarihi"),
    end_date: date = Query(description="Bitiş tarihi"),
    db: AsyncSession = Depends(get_db),
) -> RiskScoreListResponse:
    """Belirtilen tarih aralığındaki risk skorlarını döndürür."""
    if fuel_type not in {"benzin", "motorin", "lpg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Geçersiz yakıt tipi: '{fuel_type}'",
        )

    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Başlangıç tarihi bitiş tarihinden sonra olamaz",
        )

    records = await get_risk_range(db, fuel_type, start_date, end_date)
    data = [RiskScoreResponse.model_validate(r) for r in records]

    return RiskScoreListResponse(count=len(data), data=data)


@router.post(
    "/calculate",
    response_model=RiskCalculateResponse,
    summary="Risk skoru hesapla ve kaydet",
)
async def calculate_and_save(
    payload: RiskCalculateRequest,
    db: AsyncSession = Depends(get_db),
) -> RiskCalculateResponse:
    """
    Verilen bileşenlerle risk skoru hesaplar ve veritabanına kaydeder.

    Request body:
    - **trade_date**: İşlem tarihi
    - **fuel_type**: Yakıt tipi (benzin, motorin, lpg)
    - **mbe_value**: MBE değeri
    - **fx_volatility**: FX volatilite
    - **political_delay**: Politik gecikme gün sayısı
    - **threshold_breach**: Eşik ihlali (0-1)
    - **trend_momentum**: Trend momentum
    """
    if payload.fuel_type not in {"benzin", "motorin", "lpg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Geçersiz yakıt tipi: '{payload.fuel_type}'",
        )

    # Risk skorunu hesapla
    components = RiskComponents(
        mbe_value=payload.mbe_value,
        fx_volatility=payload.fx_volatility,
        political_delay=payload.political_delay,
        threshold_breach=payload.threshold_breach,
        trend_momentum=payload.trend_momentum,
    )

    result = calculate_risk_score(components)

    # Veritabanına kaydet
    try:
        await upsert_risk_score(
            session=db,
            trade_date=payload.trade_date,
            fuel_type=payload.fuel_type,
            composite_score=result.composite_score,
            mbe_component=result.mbe_component,
            fx_volatility_component=result.fx_volatility_component,
            political_delay_component=result.political_delay_component,
            threshold_breach_component=result.threshold_breach_component,
            trend_momentum_component=result.trend_momentum_component,
            weight_vector=result.weight_vector,
            system_mode=result.system_mode,
        )
        saved = True
    except Exception as e:
        logger.exception("Risk skoru kaydetme hatası")
        saved = False

    return RiskCalculateResponse(
        composite_score=str(result.composite_score),
        mbe_component=str(result.mbe_component),
        fx_volatility_component=str(result.fx_volatility_component),
        political_delay_component=str(result.political_delay_component),
        threshold_breach_component=str(result.threshold_breach_component),
        trend_momentum_component=str(result.trend_momentum_component),
        system_mode=result.system_mode,
        saved=saved,
    )
