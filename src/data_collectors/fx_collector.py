"""
USD/TRY döviz kuru veri toplama servisi.

Birincil kaynak: TCMB EVDS API (Türkiye Cumhuriyet Merkez Bankası Elektronik Veri Dağıtım Sistemi)
Serie: TP.DK.USD.S.YTL (USD/TRY satış kuru)
Fallback: Yahoo Finance USDTRY=X ticker

API Dökümantasyonu: https://evds2.tcmb.gov.tr/index.php?/evds/userDocs
"""

import asyncio
import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx
import yfinance as yf
from pydantic import BaseModel, Field

from src.config.settings import settings

logger = logging.getLogger(__name__)

# --- Sabitler ---
TCMB_EVDS_BASE_URL = "https://evds2.tcmb.gov.tr/service/evds/"
TCMB_USD_TRY_SERIE = "TP.DK.USD.S.YTL"
YAHOO_USDTRY_TICKER = "USDTRY=X"
FX_MIN = Decimal("1")
FX_MAX = Decimal("100")
HTTPX_TIMEOUT = 30.0


# --- Pydantic Modeller ---


class FXData(BaseModel):
    """USD/TRY döviz kuru verisi."""

    trade_date: date = Field(description="İşlem tarihi")
    usd_try_rate: Decimal = Field(description="USD/TRY satış kuru")
    source: str = Field(description="Veri kaynağı: tcmb_evds, yfinance_fx, manual")
    raw_data: dict | None = Field(default=None, description="Ham API yanıtı (audit trail)")


# --- Yardımcı Fonksiyonlar ---


def _safe_decimal(value: float | str | None) -> Decimal | None:
    """Değeri güvenli şekilde Decimal'e dönüştürür."""
    if value is None:
        return None
    try:
        # Türkçe ondalık ayırıcı kontrolü (TCMB virgül kullanabilir)
        if isinstance(value, str):
            value = value.replace(",", ".")
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        logger.warning("Decimal dönüşüm hatası: %s", value)
        return None


def _format_tcmb_date(d: date) -> str:
    """Tarihi TCMB EVDS formatına dönüştürür: DD-MM-YYYY."""
    return d.strftime("%d-%m-%Y")


# --- Ana Veri Çekme Fonksiyonları ---


async def fetch_usd_try_daily(target_date: date) -> FXData | None:
    """
    Belirli bir tarih için USD/TRY döviz kurunu çeker.

    Strateji:
    1. TCMB EVDS API (birincil)
    2. Başarısızsa Yahoo Finance USDTRY=X (fallback)
    3. Retry: exponential backoff

    Args:
        target_date: İstenen tarih

    Returns:
        FXData veya veri bulunamazsa None
    """
    # Önce TCMB EVDS dene
    for attempt in range(1, settings.RETRY_COUNT + 1):
        try:
            result = await _fetch_via_tcmb_evds(target_date, target_date)
            if result:
                return result[0]
            logger.warning(
                "TCMB EVDS'den veri alınamadı (tarih: %s, deneme: %d/%d)",
                target_date,
                attempt,
                settings.RETRY_COUNT,
            )
        except Exception:
            logger.exception(
                "TCMB EVDS hatası (tarih: %s, deneme: %d/%d)",
                target_date,
                attempt,
                settings.RETRY_COUNT,
            )

        if attempt < settings.RETRY_COUNT:
            backoff = settings.RETRY_BACKOFF ** attempt
            logger.info("%.1f saniye bekleniyor (exponential backoff)", backoff)
            await asyncio.sleep(backoff)

    # Fallback: Yahoo Finance
    logger.info("TCMB EVDS başarısız, Yahoo Finance fallback'e geçiliyor")
    for attempt in range(1, settings.RETRY_COUNT + 1):
        try:
            result = await _fetch_via_yahoo_fx(target_date)
            if result is not None:
                return result
        except Exception:
            logger.exception(
                "Yahoo FX fallback hatası (tarih: %s, deneme: %d/%d)",
                target_date,
                attempt,
                settings.RETRY_COUNT,
            )

        if attempt < settings.RETRY_COUNT:
            backoff = settings.RETRY_BACKOFF ** attempt
            await asyncio.sleep(backoff)

    logger.error("USD/TRY verisi hiçbir kaynaktan alınamadı: %s", target_date)
    return None


async def fetch_usd_try_range(start: date, end: date) -> list[FXData]:
    """
    Tarih aralığı için USD/TRY döviz kurlarını toplu çeker.

    TCMB EVDS aralık sorgusunu desteklediğinden tek seferde çeker.

    Args:
        start: Başlangıç tarihi (dahil)
        end: Bitiş tarihi (dahil)

    Returns:
        FXData listesi (boş olabilir)
    """
    # Önce TCMB EVDS ile toplu çek
    for attempt in range(1, settings.RETRY_COUNT + 1):
        try:
            results = await _fetch_via_tcmb_evds(start, end)
            if results:
                return results
        except Exception:
            logger.exception(
                "TCMB EVDS aralık sorgusu hatası (deneme: %d/%d)",
                attempt,
                settings.RETRY_COUNT,
            )

        if attempt < settings.RETRY_COUNT:
            backoff = settings.RETRY_BACKOFF ** attempt
            await asyncio.sleep(backoff)

    # Fallback: Gün gün Yahoo Finance
    logger.info("TCMB toplu çekim başarısız, gün gün fallback ile deneniyor")
    results: list[FXData] = []
    current = start
    while current <= end:
        daily_result = await fetch_usd_try_daily(current)
        if daily_result is not None:
            results.append(daily_result)
        current += timedelta(days=1)

    return results


# --- Dahili Veri Çekme Fonksiyonları ---


async def _fetch_via_tcmb_evds(start: date, end: date) -> list[FXData]:
    """
    TCMB EVDS API'den USD/TRY satış kuru çeker.

    API Detayları:
    - Base URL: https://evds2.tcmb.gov.tr/service/evds/
    - Serie: TP.DK.USD.S.YTL
    - Auth: Header'da key parametresi
    - Tarih formatı: DD-MM-YYYY
    """
    if not settings.TCMB_EVDS_API_KEY:
        logger.warning("TCMB_EVDS_API_KEY tanımlı değil, TCMB EVDS atlanıyor")
        return []

    params = {
        "series": TCMB_USD_TRY_SERIE,
        "startDate": _format_tcmb_date(start),
        "endDate": _format_tcmb_date(end),
        "type": "json",
    }
    headers = {
        "key": settings.TCMB_EVDS_API_KEY,
        "User-Agent": "YakitAnalizi/1.0",
    }

    async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
        response = await client.get(TCMB_EVDS_BASE_URL, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

    results: list[FXData] = []

    # TCMB EVDS yanıt yapısı: {"items": [{"Tarih": "DD-MM-YYYY", "TP_DK_USD_S_YTL": "36.1234"}, ...]}
    items = data.get("items", [])
    if not items:
        logger.warning("TCMB EVDS yanıtında veri bulunamadı: %s - %s", start, end)
        return []

    for item in items:
        try:
            # Tarih ayrıştırma (DD-MM-YYYY formatı)
            date_str = item.get("Tarih", "")
            if not date_str:
                continue
            parts = date_str.split("-")
            trade_date = date(int(parts[2]), int(parts[1]), int(parts[0]))

            # Kur değeri (alan adı nokta yerine alt çizgi kullanır)
            rate_key = TCMB_USD_TRY_SERIE.replace(".", "_")
            rate_value = item.get(rate_key)
            if rate_value is None:
                # Alternatif alan adı dene
                rate_value = item.get("TP_DK_USD_S_YTL")

            rate = _safe_decimal(rate_value)
            if rate is None or rate < FX_MIN or rate > FX_MAX:
                logger.warning("Geçersiz USD/TRY kuru atlanıyor: %s (%s)", trade_date, rate)
                continue

            results.append(
                FXData(
                    trade_date=trade_date,
                    usd_try_rate=rate,
                    source="tcmb_evds",
                    raw_data=item,
                )
            )

        except (ValueError, IndexError, KeyError) as e:
            logger.warning("TCMB EVDS satır ayrıştırma hatası: %s — %s", item, e)
            continue

    logger.info("TCMB EVDS'den %d kayıt alındı (%s — %s)", len(results), start, end)
    return results


async def _fetch_via_yahoo_fx(target_date: date) -> FXData | None:
    """
    Yahoo Finance USDTRY=X ticker'ından döviz kuru çeker (fallback).

    yfinance senkron çalıştığından asyncio.to_thread ile sarmalanır.
    """

    def _sync_fetch() -> dict | None:
        ticker = yf.Ticker(YAHOO_USDTRY_TICKER)
        start_str = target_date.isoformat()
        end_str = (target_date + timedelta(days=1)).isoformat()
        hist = ticker.history(start=start_str, end=end_str)

        if hist.empty:
            return None

        row = hist.iloc[0]
        return {
            "date": target_date.isoformat(),
            "open": float(row.get("Open", 0)),
            "high": float(row.get("High", 0)),
            "low": float(row.get("Low", 0)),
            "close": float(row.get("Close", 0)),
            "source": "yfinance_fx",
        }

    raw = await asyncio.to_thread(_sync_fetch)
    if raw is None:
        return None

    rate = _safe_decimal(raw.get("close"))
    if rate is None or rate < FX_MIN or rate > FX_MAX:
        logger.warning("Yahoo FX: aralık dışı kur: %s", rate)
        return None

    return FXData(
        trade_date=target_date,
        usd_try_rate=rate,
        source="yfinance_fx",
        raw_data=raw,
    )
