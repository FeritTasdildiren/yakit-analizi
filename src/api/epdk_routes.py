"""
EPDK Pompa Fiyatı API Rotaları

FastAPI router — EPDK verilerini sorgulama ve tetikleme endpoint'leri.

Endpoint'ler:
    GET  /api/v1/epdk/prices/latest        → En güncel pompa fiyatları
    GET  /api/v1/epdk/prices/{date}         → Belirli tarihe ait fiyatlar
    GET  /api/v1/epdk/prices/il/{il_kodu}   → Belirli il için canlı fiyatlar
    POST /api/v1/epdk/fetch                 → Admin: EPDK'dan veri çekmeyi tetikle
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.data_collectors.epdk_collector import (
    BUYUK_5_IL,
    PumpPriceData,
    fetch_pump_prices,
    fetch_turkey_average,
)
from src.data_collectors.epdk_validators import (
    validate_pump_prices,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/epdk",
    tags=["EPDK Pompa Fiyatları"],
)


# ── Response Modelleri ────────────────────────────────────────────────────────


class PumpPriceResponse(BaseModel):
    """Tek bir pompa fiyatı yanıtı."""

    trade_date: date
    fuel_type: str
    pump_price_tl_lt: str = Field(description="Fiyat (string olarak — Decimal hassasiyetini korumak için)")
    source: str
    il_kodu: str | None = None
    dagitici_sayisi: int


class PricesListResponse(BaseModel):
    """Fiyat listesi yanıtı."""

    count: int
    data: list[PumpPriceResponse]


class TurkeyAverageResponse(BaseModel):
    """Turkiye ortalama fiyat yaniti."""

    tarih: date
    benzin: str | None = None
    motorin: str | None = None
    lpg: str | None = None
    kaynak_il_sayisi: int


class FetchTriggerRequest(BaseModel):
    """Admin fetch tetikleme istegi."""

    il_kodlari: list[str] | None = Field(
        default=None,
        description="Çekilecek il kodları. None ise büyük 5 il çekilir.",
    )
    tarih: date | None = Field(
        default=None,
        description="İstenen tarih. None ise güncel fiyatlar.",
    )


class FetchTriggerResponse(BaseModel):
    """Admin fetch tetikleme yaniti."""

    status: str
    message: str
    fetched_count: int
    data: list[PumpPriceResponse]
    validation_warnings: list[str] = Field(default_factory=list)


# ── Yardımcı Fonksiyonlar ────────────────────────────────────────────────────


def _pump_price_to_response(pp: PumpPriceData) -> PumpPriceResponse:
    """PumpPriceData'yı PumpPriceResponse'a dönüştürür."""
    return PumpPriceResponse(
        trade_date=pp.trade_date,
        fuel_type=pp.fuel_type,
        pump_price_tl_lt=str(pp.pump_price_tl_lt),
        source=pp.source,
        il_kodu=pp.il_kodu,
        dagitici_sayisi=pp.dagitici_sayisi,
    )


# ── Endpoint'ler ─────────────────────────────────────────────────────────────


@router.get(
    "/prices/latest",
    response_model=TurkeyAverageResponse,
    summary="En guncel Turkiye ortalama pompa fiyatlari",
    description="Buyuk 5 il (Istanbul, Ankara, Izmir, Bursa, Antalya) uzerinden Turkiye ortalamasi hesaplar.",
)
async def get_latest_prices() -> TurkeyAverageResponse:
    """En güncel Türkiye ortalaması pompa fiyatlarını döndürür."""
    try:
        averages = await fetch_turkey_average()
    except Exception as exc:
        logger.exception("EPDK fiyat çekme hatası.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"EPDK servisine erişilemedi: {exc}",
        ) from exc

    if not averages:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="EPDK'dan fiyat verisi alınamadı.",
        )

    return TurkeyAverageResponse(
        tarih=date.today(),
        benzin=str(averages["benzin"]) if "benzin" in averages else None,
        motorin=str(averages["motorin"]) if "motorin" in averages else None,
        lpg=str(averages["lpg"]) if "lpg" in averages else None,
        kaynak_il_sayisi=len(BUYUK_5_IL),
    )


@router.get(
    "/prices/{tarih}",
    response_model=TurkeyAverageResponse,
    summary="Belirli tarihe ait Turkiye ortalama pompa fiyatlari",
    description="Verilen tarih icin buyuk 5 ilin ortalamasini hesaplar. Tarih formatı: YYYY-MM-DD",
)
async def get_prices_by_date(tarih: date) -> TurkeyAverageResponse:
    """Belirli bir tarih için Türkiye ortalaması pompa fiyatlarını döndürür."""
    try:
        averages = await fetch_turkey_average(tarih=tarih)
    except Exception as exc:
        logger.exception("EPDK fiyat çekme hatası: tarih=%s", tarih)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"EPDK servisine erişilemedi: {exc}",
        ) from exc

    if not averages:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{tarih} tarihi için EPDK fiyat verisi bulunamadı.",
        )

    return TurkeyAverageResponse(
        tarih=tarih,
        benzin=str(averages["benzin"]) if "benzin" in averages else None,
        motorin=str(averages["motorin"]) if "motorin" in averages else None,
        lpg=str(averages["lpg"]) if "lpg" in averages else None,
        kaynak_il_sayisi=len(BUYUK_5_IL),
    )


@router.get(
    "/prices/il/{il_kodu}",
    response_model=PricesListResponse,
    summary="Belirli il icin canli pompa fiyatlari",
    description="EPDK'dan belirtilen il icin dagitici bazli ortalama fiyatlari ceker.",
)
async def get_prices_by_il(
    il_kodu: str,
    tarih: date | None = Query(default=None, description="Tarih filtresi (YYYY-MM-DD). Bos ise guncel."),
) -> PricesListResponse:
    """Belirli bir il için EPDK pompa fiyatlarını döndürür."""
    # İl kodu doğrulama (01-81 arası)
    try:
        il_no = int(il_kodu)
        if not (1 <= il_no <= 81):
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Geçersiz il kodu: '{il_kodu}'. 01 ile 81 arasında olmalıdır.",
        )

    # İl kodunu 2 haneli string'e çevir (ör: '6' → '06')
    il_kodu_normalized = il_kodu.zfill(2)

    try:
        prices = await fetch_pump_prices(il_kodu=il_kodu_normalized, tarih=tarih)
    except Exception as exc:
        logger.exception("EPDK fiyat çekme hatası: il_kodu=%s", il_kodu_normalized)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"EPDK servisine erişilemedi: {exc}",
        ) from exc

    if not prices:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"İl {il_kodu_normalized} için fiyat verisi bulunamadı.",
        )

    response_data = [_pump_price_to_response(p) for p in prices]

    return PricesListResponse(
        count=len(response_data),
        data=response_data,
    )


@router.post(
    "/fetch",
    response_model=FetchTriggerResponse,
    summary="Admin: EPDK'dan veri cekmeyi tetikle",
    description="Belirtilen iller (veya buyuk 5 il) icin EPDK'dan fiyat verisi ceker ve dogrulama yapar.",
    status_code=status.HTTP_200_OK,
)
async def trigger_epdk_fetch(
    request: FetchTriggerRequest | None = None,
) -> FetchTriggerResponse:
    """
    Admin endpoint'i: EPDK'dan veri çekmeyi tetikler.

    İl kodları belirtilmezse büyük 5 il çekilir.
    Çekilen veriler doğrulanır ve uyarılar raporlanır.
    """
    il_kodlari = (request.il_kodlari if request and request.il_kodlari else list(BUYUK_5_IL.keys()))
    tarih = request.tarih if request else None

    logger.info(
        "Admin EPDK fetch tetiklendi: il_kodlari=%s, tarih=%s",
        il_kodlari,
        tarih,
    )

    all_prices: list[PumpPriceData] = []
    validation_warnings: list[str] = []

    for il_kodu in il_kodlari:
        try:
            prices = await fetch_pump_prices(il_kodu=il_kodu, tarih=tarih)
            all_prices.extend(prices)

            # Her yakıt tipi için doğrulama
            for fuel_type in ("benzin", "motorin", "lpg"):
                fuel_prices = [
                    p.pump_price_tl_lt for p in prices if p.fuel_type == fuel_type
                ]
                if fuel_prices:
                    report = validate_pump_prices(
                        prices=fuel_prices,
                        fuel_type=fuel_type,
                        il_kodu=il_kodu,
                    )
                    for warning in report.warnings:
                        validation_warnings.append(warning.message)
                    for error in report.errors:
                        validation_warnings.append(f"[HATA] {error.message}")

        except Exception as exc:
            logger.error("İl %s fetch hatası: %s", il_kodu, exc)
            validation_warnings.append(f"İl {il_kodu} çekilemedi: {exc}")

    response_data = [_pump_price_to_response(p) for p in all_prices]

    return FetchTriggerResponse(
        status="success" if all_prices else "partial",
        message=f"{len(all_prices)} fiyat kaydı çekildi ({len(il_kodlari)} il).",
        fetched_count=len(all_prices),
        data=response_data,
        validation_warnings=validation_warnings,
    )
