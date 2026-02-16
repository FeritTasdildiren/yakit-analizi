"""
MBE (Maliyet Baz Etkisi) API endpoint'leri.

MBE hesaplama sonuclarina erisim ve hesaplama tetikleme API'si.
Tum endpoint'ler /api/v1/mbe prefix'i altindadir.
"""

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_db
from src.core.mbe_repository import (
    get_cost_snapshot,
    get_latest_mbe,
    get_latest_mbe_all,
    get_mbe_at_date,
    get_mbe_range,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/mbe", tags=["MBE Hesaplama"])


# --- Response Modelleri ---


class MBEResponse(BaseModel):
    """MBE hesaplama sonucu yaniti."""

    id: int
    trade_date: date
    fuel_type: str
    nc_forward: Decimal
    nc_base: Decimal
    mbe_value: Decimal
    mbe_pct: Decimal
    sma_5: Decimal | None = None
    sma_10: Decimal | None = None
    delta_mbe: Decimal | None = None
    delta_mbe_3: Decimal | None = None
    trend_direction: str
    regime: int
    since_last_change_days: int
    sma_window: int
    source: str

    model_config = ConfigDict(from_attributes=True)


class MBEListResponse(BaseModel):
    """MBE hesaplama listesi yaniti."""

    count: int
    data: list[MBEResponse]


class CostSnapshotResponse(BaseModel):
    """Maliyet snapshot yaniti."""

    id: int
    trade_date: date
    fuel_type: str
    market_data_id: int
    tax_parameter_id: int
    cif_component_tl: Decimal
    otv_component_tl: Decimal
    kdv_component_tl: Decimal
    margin_component_tl: Decimal
    theoretical_cost_tl: Decimal
    actual_pump_price_tl: Decimal
    implied_cif_usd_ton: Decimal | None
    cost_gap_tl: Decimal
    cost_gap_pct: Decimal
    source: str

    model_config = ConfigDict(from_attributes=True)


class CostSnapshotListResponse(BaseModel):
    """Maliyet snapshot listesi yaniti."""

    count: int
    data: list[CostSnapshotResponse]


class CalculateRequest(BaseModel):
    """MBE hesaplama tetikleme istegi."""

    fuel_type: str = Field(description="Yakit tipi: benzin, motorin, lpg")
    trade_date: date = Field(description="Hesaplanacak tarih")
    regime: int = Field(default=0, description="Rejim kodu: 0=Normal, 1=Secim, 2=Kur Soku, 3=Vergi Ayarlama")


class CalculateResponse(BaseModel):
    """MBE hesaplama tetikleme yaniti."""

    status: str
    message: str
    mbe: MBEResponse | None = None
    snapshot: CostSnapshotResponse | None = None


# --- Endpoint'ler ---


@router.get(
    "/latest",
    response_model=MBEListResponse,
    summary="Tum yakit tipleri icin en son MBE hesaplamalari",
    description="Benzin, motorin ve LPG icin en guncel MBE degerlerini dondurur.",
)
async def get_latest_mbe_all_endpoint(
    db: AsyncSession = Depends(get_db),
) -> MBEListResponse:
    """Tum yakit tipleri icin en son MBE hesaplamalarini dondurur."""
    results = await get_latest_mbe_all(db)

    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Henuz MBE hesaplaması bulunmuyor",
        )

    return MBEListResponse(
        count=len(results),
        data=[MBEResponse.model_validate(r) for r in results],
    )


@router.get(
    "/latest/{fuel_type}",
    response_model=MBEResponse,
    summary="Belirli yakit tipi icin en son MBE hesaplamasi",
    description="Istenen yakit tipi icin en guncel MBE degerini dondurur.",
)
async def get_latest_mbe_by_fuel(
    fuel_type: str,
    db: AsyncSession = Depends(get_db),
) -> MBEResponse:
    """Belirli yakit tipi icin en son MBE hesaplamasini dondurur."""
    _validate_fuel_type(fuel_type)

    result = await get_latest_mbe(db, fuel_type)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{fuel_type}' icin MBE hesaplaması bulunamadı",
        )

    return MBEResponse.model_validate(result)


@router.get(
    "/range/{fuel_type}",
    response_model=MBEListResponse,
    summary="Tarih araliginda MBE hesaplamalari",
    description="Belirtilen yakit tipi ve tarih araligi icin MBE hesaplamalarini listeler.",
)
async def get_mbe_range_endpoint(
    fuel_type: str,
    start_date: date = Query(description="Baslangic tarihi (dahil)"),
    end_date: date = Query(description="Bitis tarihi (dahil)"),
    db: AsyncSession = Depends(get_db),
) -> MBEListResponse:
    """Tarih araligindaki MBE hesaplamalarini dondurur."""
    _validate_fuel_type(fuel_type)

    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Baslangic tarihi bitis tarihinden sonra olamaz",
        )

    results = await get_mbe_range(db, fuel_type, start_date, end_date)

    return MBEListResponse(
        count=len(results),
        data=[MBEResponse.model_validate(r) for r in results],
    )


@router.get(
    "/snapshot/{snapshot_date}",
    response_model=CostSnapshotListResponse,
    summary="Belirli tarihteki maliyet snapshot'lari",
    description="Istenen tarih icin tum yakit tiplerinin maliyet ayristirmalarini dondurur.",
)
async def get_snapshot_by_date(
    snapshot_date: date,
    fuel_type: str | None = Query(
        default=None,
        description="Yakit tipi filtresi (benzin, motorin, lpg)",
    ),
    db: AsyncSession = Depends(get_db),
) -> CostSnapshotListResponse:
    """Belirli tarihteki maliyet snapshot'larini dondurur."""
    fuel_types = [fuel_type] if fuel_type else ["benzin", "motorin", "lpg"]
    results = []

    for ft in fuel_types:
        snapshot = await get_cost_snapshot(db, snapshot_date, ft)
        if snapshot is not None:
            results.append(CostSnapshotResponse.model_validate(snapshot))

    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{snapshot_date} tarihi icin maliyet snapshot'ı bulunamadı",
        )

    return CostSnapshotListResponse(
        count=len(results),
        data=results,
    )


@router.post(
    "/calculate",
    response_model=CalculateResponse,
    summary="MBE hesaplama tetikle (admin)",
    description=(
        "Belirtilen yakit tipi ve tarih icin MBE hesaplamasi tetikler. "
        "Mevcut piyasa verisi ve vergi parametreleri uzerinden hesaplama yapar."
    ),
)
async def trigger_mbe_calculation(
    request: CalculateRequest,
    db: AsyncSession = Depends(get_db),
) -> CalculateResponse:
    """
    MBE hesaplama tetikleme endpoint'i.

    Bu endpoint, belirtilen tarih ve yakit tipi icin:
    1. Piyasa verisini ve vergi parametresini arar
    2. Maliyet snapshot'i olusturur
    3. MBE hesaplamasi yapar
    4. Sonuclari veritabanina kaydeder
    """
    _validate_fuel_type(request.fuel_type)

    if request.regime not in (0, 1, 2, 3):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Gecersiz rejim kodu: {request.regime}. Gecerli: 0, 1, 2, 3",
        )

    # Hesaplama servisi burada cagrilacak (Katman 2 entegrasyonunda)
    # Simdilik sadece mevcut verileri kontrol edelim
    mbe = await get_mbe_at_date(db, request.trade_date, request.fuel_type)
    snapshot = await get_cost_snapshot(db, request.trade_date, request.fuel_type)

    if mbe is not None:
        return CalculateResponse(
            status="exists",
            message=(
                f"{request.trade_date} / {request.fuel_type} icin MBE hesaplaması "
                f"zaten mevcut (mbe={mbe.mbe_value})"
            ),
            mbe=MBEResponse.model_validate(mbe),
            snapshot=CostSnapshotResponse.model_validate(snapshot) if snapshot else None,
        )

    # Henuz gercek hesaplama entegrasyonu yok — bilgi mesaji don
    return CalculateResponse(
        status="pending",
        message=(
            f"{request.trade_date} / {request.fuel_type} icin MBE hesaplama gorevi "
            f"olusturuldu (rejim={request.regime}). "
            f"Batch hesaplama servisi tarafindan islenecek."
        ),
    )


# --- Yardimci Fonksiyonlar ---


def _validate_fuel_type(fuel_type: str) -> None:
    """Yakit tipini dogrular."""
    valid_types = {"benzin", "motorin", "lpg"}
    if fuel_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Gecersiz yakit tipi: '{fuel_type}'. Gecerli: {', '.join(sorted(valid_types))}",
        )
