"""
Piyasa verisi API endpoint'leri.

Brent petrol, döviz kuru ve piyasa verilerine erişim sağlayan REST API.
Tüm endpoint'ler /api/v1/market-data prefix'i altındadır.
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_db
from src.data_collectors import brent_collector, fx_collector
from src.data_collectors.market_data_repository import (
    check_gaps,
    get_data_range,
    get_latest_data,
    upsert_market_data,
)
from src.data_collectors.validators import validate_brent, validate_fx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/market-data", tags=["Piyasa Verisi"])


# --- Response Modelleri ---


class MarketDataResponse(BaseModel):
    """Tekil piyasa verisi yanıtı."""

    id: int
    trade_date: date
    fuel_type: str
    brent_usd_bbl: Decimal | None = None
    cif_med_usd_ton: Decimal | None = None
    usd_try_rate: Decimal | None = None
    pump_price_tl_lt: Decimal | None = None
    distribution_margin_tl: Decimal | None = None
    data_quality_flag: str
    source: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FetchResponse(BaseModel):
    """Veri çekme işlemi sonucu."""

    status: str = Field(description="İşlem durumu: success, partial, error")
    brent_fetched: bool = Field(default=False, description="Brent verisi çekildi mi?")
    fx_fetched: bool = Field(default=False, description="FX verisi çekildi mi?")
    records_upserted: int = Field(default=0, description="Eklenen/güncellenen kayıt sayısı")
    errors: list[str] = Field(default_factory=list, description="Hata mesajları")
    warnings: list[str] = Field(default_factory=list, description="Uyarı mesajları")


class GapResponse(BaseModel):
    """Boşluk tespit sonucu."""

    fuel_type: str
    start_date: date
    end_date: date
    total_days: int
    missing_days: int
    missing_dates: list[date]


# --- Endpoint'ler ---


@router.get(
    "/latest",
    response_model=list[MarketDataResponse],
    summary="Son piyasa verilerini getir",
    description="Her yakıt tipi (benzin, motorin, lpg) için en son kaydı döndürür.",
)
async def get_latest(
    db: AsyncSession = Depends(get_db),
) -> list[MarketDataResponse]:
    """Her yakıt tipi için en güncel piyasa verisini döndürür."""
    results = []
    for fuel_type in ("benzin", "motorin", "lpg"):
        record = await get_latest_data(db, fuel_type)
        if record is not None:
            results.append(MarketDataResponse.model_validate(record))

    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Henüz piyasa verisi bulunmuyor",
        )

    return results


@router.get(
    "/{target_date}",
    response_model=list[MarketDataResponse],
    summary="Belirli tarih için piyasa verilerini getir",
    description="İstenen tarih için tüm yakıt tiplerinin piyasa verilerini döndürür.",
)
async def get_by_date(
    target_date: date,
    fuel_type: str | None = Query(
        default=None,
        description="Yakıt tipi filtresi (benzin, motorin, lpg)",
    ),
    db: AsyncSession = Depends(get_db),
) -> list[MarketDataResponse]:
    """Belirli bir tarih (ve opsiyonel yakıt tipi) için piyasa verisini döndürür."""
    fuel_types = [fuel_type] if fuel_type else ["benzin", "motorin", "lpg"]
    results = []

    for ft in fuel_types:
        records = await get_data_range(db, ft, target_date, target_date)
        for record in records:
            results.append(MarketDataResponse.model_validate(record))

    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{target_date} tarihi için piyasa verisi bulunamadı",
        )

    return results


@router.post(
    "/fetch",
    response_model=FetchResponse,
    summary="Piyasa verisi çekme işlemini tetikle (admin)",
    description=(
        "Brent petrol fiyatı ve USD/TRY döviz kurunu çeker, "
        "doğrular ve veritabanına kaydeder. Admin tetiklemesi için."
    ),
)
async def trigger_fetch(
    target_date: date = Query(
        default=None,
        description="Çekilecek tarih (varsayılan: bugün)",
    ),
    db: AsyncSession = Depends(get_db),
) -> FetchResponse:
    """
    Brent ve FX verilerini çeker, doğrular, kaydeder.

    Bu endpoint admin tarafından manuel tetikleme için kullanılır.
    Otomatik çekim Celery beat scheduler üzerinden yapılır.
    """
    if target_date is None:
        target_date = date.today()

    response = FetchResponse(status="success")
    fuel_types = ["benzin", "motorin", "lpg"]

    # 1. Brent fiyatı çek
    brent_data = await brent_collector.fetch_brent_daily(target_date)
    if brent_data is not None:
        is_valid, errors = validate_brent(brent_data)
        if is_valid:
            response.brent_fetched = True
        else:
            response.warnings.extend(errors)
            # Doğrulama uyarılarına rağmen kaydet ama flag'le
            logger.warning("Brent doğrulama uyarısı, 'estimated' olarak kaydedilecek")
    else:
        response.errors.append(f"Brent verisi çekilemedi: {target_date}")

    # 2. USD/TRY kuru çek
    fx_data = await fx_collector.fetch_usd_try_daily(target_date)
    if fx_data is not None:
        is_valid, errors = validate_fx(fx_data)
        if is_valid:
            response.fx_fetched = True
        else:
            response.warnings.extend(errors)
    else:
        response.errors.append(f"USD/TRY verisi çekilemedi: {target_date}")

    # 3. Her yakıt tipi için kaydet
    for fuel_type in fuel_types:
        try:
            quality_flag = "verified"

            # Doğrulama başarısız olduysa flag'i ayarla
            if brent_data and not validate_brent(brent_data)[0]:
                quality_flag = "estimated"
            if fx_data and not validate_fx(fx_data)[0]:
                quality_flag = "estimated"

            await upsert_market_data(
                session=db,
                trade_date=target_date,
                fuel_type=fuel_type,
                brent_usd_bbl=brent_data.brent_usd_bbl if brent_data else None,
                cif_med_usd_ton=brent_data.cif_med_estimate_usd_ton if brent_data else None,
                usd_try_rate=fx_data.usd_try_rate if fx_data else None,
                data_quality_flag=quality_flag,
                source=_determine_source(brent_data, fx_data),
                raw_payload=_build_raw_payload(brent_data, fx_data),
            )
            response.records_upserted += 1

        except Exception as e:
            logger.exception("Kayıt hatası: %s / %s", target_date, fuel_type)
            response.errors.append(f"Kayıt hatası ({fuel_type}): {str(e)}")

    # Durum belirleme
    if response.errors and not response.brent_fetched and not response.fx_fetched:
        response.status = "error"
    elif response.errors or response.warnings:
        response.status = "partial"

    return response


@router.get(
    "/gaps",
    response_model=list[GapResponse],
    summary="Veri boşluklarını tespit et",
    description="Belirtilen tarih aralığında eksik piyasa verilerini listeler.",
)
async def get_gaps(
    start_date: date = Query(
        description="Başlangıç tarihi",
    ),
    end_date: date = Query(
        default=None,
        description="Bitiş tarihi (varsayılan: bugün)",
    ),
    fuel_type: str | None = Query(
        default=None,
        description="Yakıt tipi filtresi (benzin, motorin, lpg)",
    ),
    db: AsyncSession = Depends(get_db),
) -> list[GapResponse]:
    """Tarih aralığındaki eksik verileri tespit eder."""
    if end_date is None:
        end_date = date.today()

    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Başlangıç tarihi bitiş tarihinden sonra olamaz",
        )

    fuel_types = [fuel_type] if fuel_type else ["benzin", "motorin", "lpg"]
    results: list[GapResponse] = []
    total_days = (end_date - start_date).days + 1

    for ft in fuel_types:
        missing = await check_gaps(db, ft, start_date, end_date)
        results.append(
            GapResponse(
                fuel_type=ft,
                start_date=start_date,
                end_date=end_date,
                total_days=total_days,
                missing_days=len(missing),
                missing_dates=missing,
            )
        )

    return results


# --- Yardımcı Fonksiyonlar ---


def _determine_source(
    brent_data: brent_collector.BrentData | None,
    fx_data: fx_collector.FXData | None,
) -> str:
    """Veri kaynaklarını birleştirerek source alanını oluşturur."""
    sources = []
    if brent_data:
        sources.append(brent_data.source)
    if fx_data:
        sources.append(fx_data.source)
    return "+".join(sources) if sources else "unknown"


def _build_raw_payload(
    brent_data: brent_collector.BrentData | None,
    fx_data: fx_collector.FXData | None,
) -> dict | None:
    """Ham veri payload'ını birleştirir (audit trail)."""
    payload: dict = {}
    if brent_data and brent_data.raw_data:
        payload["brent"] = brent_data.raw_data
    if fx_data and fx_data.raw_data:
        payload["fx"] = fx_data.raw_data
    return payload if payload else None
