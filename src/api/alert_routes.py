"""
Alert API endpoint'leri.

Sistem alert'lerini sorgulama ve yönetme.
Tüm endpoint'ler /api/v1/alerts prefix'i altındadır.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_db
from src.core.alert_repository import (
    get_alerts,
    get_alert_by_id,
    mark_alert_read,
    resolve_alert,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/alerts", tags=["Alert'ler"])


# --- Pydantic Modelleri ---


class AlertResponse(BaseModel):
    """Alert yanıt şeması."""

    id: int
    alert_level: str
    alert_type: str
    fuel_type: str | None = None
    title: str
    message: str
    metric_name: str
    metric_value: Decimal
    threshold_value: Decimal
    channels_sent: list[str] | None = None
    is_read: bool
    is_resolved: bool
    resolved_at: datetime | None = None
    resolved_reason: str | None = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class AlertListResponse(BaseModel):
    """Alert liste yanıtı."""

    count: int
    data: list[AlertResponse]


class ResolveRequest(BaseModel):
    """Alert çözümleme isteği."""

    reason: str | None = None


# --- Endpoint'ler ---


@router.get(
    "/",
    response_model=AlertListResponse,
    summary="Alert'leri listele",
)
async def list_alerts(
    unread: bool = Query(default=False, description="Sadece okunmamışları getir"),
    unresolved: bool = Query(default=False, description="Sadece çözülmemişleri getir"),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> AlertListResponse:
    """
    Alert'leri filtreli olarak döndürür.

    Query parametreleri:
    - **unread**: True ise sadece okunmamış alert'ler
    - **unresolved**: True ise sadece çözülmemiş alert'ler
    """
    records = await get_alerts(
        db,
        unread_only=unread,
        unresolved_only=unresolved,
        limit=limit,
    )
    data = [AlertResponse.model_validate(r) for r in records]
    return AlertListResponse(count=len(data), data=data)


@router.get(
    "/{fuel_type}",
    response_model=AlertListResponse,
    summary="Yakıt tipine göre alert'ler",
)
async def list_alerts_by_fuel(
    fuel_type: str,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> AlertListResponse:
    """Belirtilen yakıt tipi için alert'leri döndürür."""
    if fuel_type not in {"benzin", "motorin", "lpg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Geçersiz yakıt tipi: '{fuel_type}'",
        )

    records = await get_alerts(db, fuel_type=fuel_type, limit=limit)
    data = [AlertResponse.model_validate(r) for r in records]
    return AlertListResponse(count=len(data), data=data)


@router.put(
    "/{alert_id}/read",
    response_model=AlertResponse,
    summary="Alert'i okundu olarak işaretle",
)
async def mark_read(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
) -> AlertResponse:
    """Belirtilen alert'i okundu olarak işaretler."""
    alert = await mark_alert_read(db, alert_id)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ID={alert_id} olan alert bulunamadı",
        )
    return AlertResponse.model_validate(alert)


@router.put(
    "/{alert_id}/resolve",
    response_model=AlertResponse,
    summary="Alert'i çözüldü olarak işaretle",
)
async def resolve(
    alert_id: int,
    payload: ResolveRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> AlertResponse:
    """
    Belirtilen alert'i çözüldü olarak işaretler.

    Request body (opsiyonel):
    - **reason**: Çözüm nedeni açıklaması
    """
    reason = payload.reason if payload else None
    alert = await resolve_alert(db, alert_id, resolved_reason=reason)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ID={alert_id} olan alert bulunamadı",
        )
    return AlertResponse.model_validate(alert)
