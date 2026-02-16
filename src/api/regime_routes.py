"""
Rejim olayları API endpoint'leri.

Politik/ekonomik rejim olaylarını yönetme.
Tüm endpoint'ler /api/v1/regime prefix'i altındadır.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_db
from src.core.regime_repository import (
    create_regime_event,
    deactivate_event,
    get_active_events,
    get_event_history,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/regime", tags=["Rejim Olayları"])

# --- Geçerli Olay Tipleri ---
VALID_EVENT_TYPES = {"election", "holiday", "economic_crisis", "tax_change", "geopolitical", "other"}


# --- Pydantic Modelleri ---


class RegimeEventResponse(BaseModel):
    """Rejim olayı yanıt şeması."""

    id: int
    event_type: str
    event_name: str
    start_date: date
    end_date: date
    impact_score: int
    is_active: bool
    source: str
    description: str | None = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class RegimeEventCreateRequest(BaseModel):
    """Rejim olayı oluşturma isteği."""

    event_type: str
    event_name: str = Field(min_length=1, max_length=255)
    start_date: date
    end_date: date
    impact_score: int = Field(ge=0, le=10)
    source: str = "manual"
    description: str | None = None

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        if v not in VALID_EVENT_TYPES:
            msg = f"Geçersiz olay tipi: '{v}'. Geçerli: {', '.join(sorted(VALID_EVENT_TYPES))}"
            raise ValueError(msg)
        return v

    @field_validator("end_date")
    @classmethod
    def validate_end_date(cls, v: date, info) -> date:
        start = info.data.get("start_date")
        if start is not None and v < start:
            raise ValueError("Bitiş tarihi başlangıç tarihinden önce olamaz")
        return v


class RegimeEventListResponse(BaseModel):
    """Rejim olayı liste yanıtı."""

    count: int
    data: list[RegimeEventResponse]


# --- Endpoint'ler ---


@router.get(
    "/active",
    response_model=RegimeEventListResponse,
    summary="Aktif rejim olayları",
)
async def get_active(
    ref_date: date | None = Query(
        default=None,
        description="Referans tarih (varsayılan: bugün)",
    ),
    db: AsyncSession = Depends(get_db),
) -> RegimeEventListResponse:
    """Belirtilen tarihte aktif olan rejim olaylarını döndürür."""
    events = await get_active_events(db, ref_date=ref_date)
    data = [RegimeEventResponse.model_validate(e) for e in events]
    return RegimeEventListResponse(count=len(data), data=data)


@router.get(
    "/history",
    response_model=RegimeEventListResponse,
    summary="Rejim olayı geçmişi",
)
async def get_history(
    event_type: str | None = Query(
        default=None,
        description="Olay tipi filtresi",
    ),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> RegimeEventListResponse:
    """Rejim olayı geçmişini döndürür."""
    if event_type is not None and event_type not in VALID_EVENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Geçersiz olay tipi: '{event_type}'",
        )

    events = await get_event_history(db, event_type=event_type, limit=limit)
    data = [RegimeEventResponse.model_validate(e) for e in events]
    return RegimeEventListResponse(count=len(data), data=data)


@router.post(
    "/",
    response_model=RegimeEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Yeni rejim olayı oluştur",
)
async def create_event(
    payload: RegimeEventCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> RegimeEventResponse:
    """
    Yeni bir rejim olayı kaydı oluşturur.

    Request body:
    - **event_type**: Olay tipi (election, holiday, economic_crisis, tax_change, geopolitical, other)
    - **event_name**: Olay adı
    - **start_date**: Başlangıç tarihi
    - **end_date**: Bitiş tarihi
    - **impact_score**: Etki skoru (0-10)
    - **source**: Veri kaynağı (varsayılan: manual)
    - **description**: Ek açıklama (opsiyonel)
    """
    event = await create_regime_event(
        session=db,
        event_type=payload.event_type,
        event_name=payload.event_name,
        start_date=payload.start_date,
        end_date=payload.end_date,
        impact_score=payload.impact_score,
        source=payload.source,
        description=payload.description,
    )
    return RegimeEventResponse.model_validate(event)


@router.put(
    "/{event_id}/deactivate",
    response_model=RegimeEventResponse,
    summary="Rejim olayını deaktif et",
)
async def deactivate(
    event_id: int,
    db: AsyncSession = Depends(get_db),
) -> RegimeEventResponse:
    """Belirtilen rejim olayını deaktif eder."""
    event = await deactivate_event(db, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ID={event_id} olan rejim olayı bulunamadı",
        )
    return RegimeEventResponse.model_validate(event)
