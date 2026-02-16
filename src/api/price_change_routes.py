"""
Fiyat degisiklikleri API endpoint'leri.

Gecmis akaryakit fiyat degisikliklerini (zam/indirim) sorgulama ve kayit API'si.
Tum endpoint'ler /api/v1/price-changes prefix'i altindadir.
"""

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_db
from src.core.price_change_repository import (
    get_latest_price_change,
    get_latest_price_changes_all,
    get_price_changes_by_fuel,
    upsert_price_change,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/price-changes", tags=["Fiyat Degisiklikleri"])


# --- Response / Request Modelleri ---


class PriceChangeResponse(BaseModel):
    """Fiyat degisikligi yaniti."""

    id: int
    fuel_type: str
    change_date: date
    direction: str
    old_price: Decimal
    new_price: Decimal
    change_amount: Decimal
    change_pct: Decimal
    mbe_at_change: Decimal | None = None
    source: str
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PriceChangeListResponse(BaseModel):
    """Fiyat degisiklikleri listesi yaniti."""

    count: int
    data: list[PriceChangeResponse]


class PriceChangeCreateRequest(BaseModel):
    """Yeni fiyat degisikligi olusturma istegi."""

    fuel_type: str = Field(description="Yakit tipi: benzin, motorin, lpg")
    change_date: date = Field(description="Degisiklik tarihi")
    old_price: Decimal = Field(description="Eski pompa fiyati TL/litre")
    new_price: Decimal = Field(description="Yeni pompa fiyati TL/litre")
    mbe_at_change: Decimal | None = Field(
        default=None,
        description="Degisiklik anindaki MBE degeri (opsiyonel)",
    )
    source: str = Field(default="manual", description="Veri kaynagi")
    notes: str | None = Field(default=None, description="Ek notlar")

    @field_validator("fuel_type")
    @classmethod
    def validate_fuel_type(cls, v: str) -> str:
        """Yakit tipini dogrular."""
        valid_types = {"benzin", "motorin", "lpg"}
        if v not in valid_types:
            msg = f"Gecersiz yakit tipi: '{v}'. Gecerli: {', '.join(sorted(valid_types))}"
            raise ValueError(msg)
        return v

    @field_validator("old_price", "new_price")
    @classmethod
    def validate_prices(cls, v: Decimal) -> Decimal:
        """Fiyatlarin pozitif olmasini dogrular."""
        if v <= Decimal("0"):
            msg = f"Fiyat sifir veya negatif olamaz: {v}"
            raise ValueError(msg)
        return v


# --- Endpoint'ler ---


@router.get(
    "/latest",
    response_model=PriceChangeListResponse,
    summary="Tum yakit tipleri icin en son fiyat degisiklikleri",
    description="Benzin, motorin ve LPG icin en guncel fiyat degisikliklerini dondurur.",
)
async def get_latest_changes(
    db: AsyncSession = Depends(get_db),
) -> PriceChangeListResponse:
    """Tum yakit tipleri icin en son fiyat degisikliklerini dondurur."""
    results = await get_latest_price_changes_all(db)

    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Henuz fiyat degisikligi kaydi bulunmuyor",
        )

    return PriceChangeListResponse(
        count=len(results),
        data=[PriceChangeResponse.model_validate(r) for r in results],
    )


@router.get(
    "/{fuel_type}",
    response_model=PriceChangeListResponse,
    summary="Belirli yakit tipi icin fiyat degisiklikleri tarihcesi",
    description="Istenen yakit tipi icin fiyat degisiklik tarihcesini listeler (en yeni ilk).",
)
async def get_changes_by_fuel(
    fuel_type: str,
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
        description="Maksimum kayit sayisi",
    ),
    db: AsyncSession = Depends(get_db),
) -> PriceChangeListResponse:
    """Belirli yakit tipi icin fiyat degisiklikleri tarihcesini dondurur."""
    _validate_fuel_type(fuel_type)

    results = await get_price_changes_by_fuel(db, fuel_type, limit=limit)

    return PriceChangeListResponse(
        count=len(results),
        data=[PriceChangeResponse.model_validate(r) for r in results],
    )


@router.post(
    "",
    response_model=PriceChangeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Yeni fiyat degisikligi kaydi olustur",
    description=(
        "Yeni bir akaryakit fiyat degisikligi (zam/indirim) kaydi ekler. "
        "direction ve change_amount/change_pct otomatik hesaplanir."
    ),
)
async def create_change(
    payload: PriceChangeCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> PriceChangeResponse:
    """Yeni fiyat degisikligi kaydi olusturur."""
    # Degisim miktari ve yuzdesi hesapla
    change_amount = payload.new_price - payload.old_price
    change_pct = (change_amount / payload.old_price) * Decimal("100")

    # Yon belirle
    if change_amount > Decimal("0"):
        direction = "increase"
    elif change_amount < Decimal("0"):
        direction = "decrease"
    else:
        direction = "no_change"

    result = await upsert_price_change(
        session=db,
        fuel_type=payload.fuel_type,
        change_date=payload.change_date,
        direction=direction,
        old_price=payload.old_price,
        new_price=payload.new_price,
        change_amount=change_amount,
        change_pct=change_pct,
        mbe_at_change=payload.mbe_at_change,
        source=payload.source,
        notes=payload.notes,
    )

    return PriceChangeResponse.model_validate(result)


# --- Yardimci Fonksiyonlar ---


def _validate_fuel_type(fuel_type: str) -> None:
    """Yakit tipini dogrular."""
    valid_types = {"benzin", "motorin", "lpg"}
    if fuel_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Gecersiz yakit tipi: '{fuel_type}'. Gecerli: {', '.join(sorted(valid_types))}",
        )
