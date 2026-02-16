"""
Brent petrol fiyatı veri toplama servisi.

Birincil kaynak: yfinance (BZ=F ticker — Brent Crude Oil Futures)
Fallback: Yahoo Finance web API (httpx ile doğrudan)

CIF Med tahmini: Brent × 7.45 + 20 (premium) USD/ton
"""

import asyncio
import json
import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx
import yfinance as yf
from pydantic import BaseModel, Field

from src.config.settings import settings

logger = logging.getLogger(__name__)

# --- Sabitler ---
BRENT_TICKER = "BZ=F"
BRENT_MIN_USD = Decimal("20")
BRENT_MAX_USD = Decimal("200")
CIF_MED_MULTIPLIER = Decimal("7.45")
CIF_MED_PREMIUM = Decimal("20")
HTTPX_TIMEOUT = 30.0


# --- Pydantic Modeller ---


class BrentData(BaseModel):
    """Brent petrol fiyat verisi."""

    trade_date: date = Field(description="İşlem tarihi")
    brent_usd_bbl: Decimal = Field(description="Brent fiyatı (USD/varil)")
    cif_med_estimate_usd_ton: Decimal = Field(description="Tahmini CIF Med fiyatı (USD/ton)")
    source: str = Field(description="Veri kaynağı: yfinance, yahoo_web, manual")
    raw_data: dict | None = Field(default=None, description="Ham API yanıtı (audit trail)")


# --- Yardımcı Fonksiyonlar ---


def estimate_cif_med(brent_usd_bbl: Decimal) -> Decimal:
    """
    CIF Med (Akdeniz) tahmini hesaplar.

    Formül: CIF Med ≈ Brent × 7.45 + 20 (premium)
    1 varil ≈ 7.45 galon × yoğunluk faktörü ile ton'a dönüşüm + nakliye primi.

    Args:
        brent_usd_bbl: Brent petrol fiyatı (USD/varil)

    Returns:
        Tahmini CIF Med fiyatı (USD/ton)
    """
    return brent_usd_bbl * CIF_MED_MULTIPLIER + CIF_MED_PREMIUM


def _safe_decimal(value: float | str | None) -> Decimal | None:
    """Float değeri güvenli şekilde Decimal'e dönüştürür."""
    if value is None:
        return None
    try:
        # Float → str → Decimal yolu ile hassasiyet kaybını önle
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        logger.warning("Decimal dönüşüm hatası: %s", value)
        return None


# --- Ana Veri Çekme Fonksiyonları ---


async def fetch_brent_daily(target_date: date) -> BrentData | None:
    """
    Belirli bir tarih için Brent petrol fiyatını çeker.

    Strateji:
    1. yfinance ile dene (birincil)
    2. Başarısızsa fallback kaynağı dene
    3. Retry: exponential backoff ile settings.RETRY_COUNT kadar

    Args:
        target_date: İstenen tarih

    Returns:
        BrentData veya veri bulunamazsa None
    """
    # Önce yfinance dene
    for attempt in range(1, settings.RETRY_COUNT + 1):
        try:
            result = await _fetch_via_yfinance(target_date)
            if result is not None:
                return result
            logger.warning(
                "yfinance'dan veri alınamadı (tarih: %s, deneme: %d/%d)",
                target_date,
                attempt,
                settings.RETRY_COUNT,
            )
        except Exception:
            logger.exception(
                "yfinance hatası (tarih: %s, deneme: %d/%d)",
                target_date,
                attempt,
                settings.RETRY_COUNT,
            )

        if attempt < settings.RETRY_COUNT:
            backoff = settings.RETRY_BACKOFF ** attempt
            logger.info("%.1f saniye bekleniyor (exponential backoff)", backoff)
            await asyncio.sleep(backoff)

    # Fallback: Yahoo Finance web API
    logger.info("Fallback kaynağa geçiliyor: %s", settings.BRENT_FALLBACK_SOURCE)
    for attempt in range(1, settings.RETRY_COUNT + 1):
        try:
            result = await _fetch_via_yahoo_web(target_date)
            if result is not None:
                return result
        except Exception:
            logger.exception(
                "Fallback hatası (tarih: %s, deneme: %d/%d)",
                target_date,
                attempt,
                settings.RETRY_COUNT,
            )

        if attempt < settings.RETRY_COUNT:
            backoff = settings.RETRY_BACKOFF ** attempt
            await asyncio.sleep(backoff)

    logger.error("Brent verisi hiçbir kaynaktan alınamadı: %s", target_date)
    return None


async def fetch_brent_range(start: date, end: date) -> list[BrentData]:
    """
    Tarih aralığı için Brent petrol fiyatlarını toplu çeker.

    yfinance'ın download() metodu aralık sorgusunu desteklediğinden
    tek seferde tüm veriyi çekmeye çalışır.

    Args:
        start: Başlangıç tarihi (dahil)
        end: Bitiş tarihi (dahil)

    Returns:
        BrentData listesi (boş olabilir)
    """
    results: list[BrentData] = []

    for attempt in range(1, settings.RETRY_COUNT + 1):
        try:
            data = await _fetch_range_via_yfinance(start, end)
            if data:
                return data
        except Exception:
            logger.exception(
                "yfinance aralık sorgusu hatası (deneme: %d/%d)",
                attempt,
                settings.RETRY_COUNT,
            )

        if attempt < settings.RETRY_COUNT:
            backoff = settings.RETRY_BACKOFF ** attempt
            await asyncio.sleep(backoff)

    # Fallback: Gün gün çek
    logger.info("Toplu çekim başarısız, gün gün fallback ile deneniyor")
    current = start
    while current <= end:
        daily_result = await fetch_brent_daily(current)
        if daily_result is not None:
            results.append(daily_result)
        current += timedelta(days=1)

    return results


# --- Dahili Veri Çekme Fonksiyonları ---


async def _fetch_via_yfinance(target_date: date) -> BrentData | None:
    """
    yfinance kütüphanesi ile Brent fiyatı çeker.

    yfinance senkron çalıştığından asyncio.to_thread ile sarmalanır.
    """

    def _sync_fetch() -> dict | None:
        ticker = yf.Ticker(BRENT_TICKER)
        # target_date ve sonraki gün arasında veri çek
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
            "volume": int(row.get("Volume", 0)),
        }

    raw = await asyncio.to_thread(_sync_fetch)
    if raw is None:
        return None

    close_price = _safe_decimal(raw.get("close"))
    if close_price is None or close_price < BRENT_MIN_USD or close_price > BRENT_MAX_USD:
        logger.warning(
            "Brent fiyatı geçerli aralık dışında: %s (beklenen: %s-%s)",
            close_price,
            BRENT_MIN_USD,
            BRENT_MAX_USD,
        )
        return None

    return BrentData(
        trade_date=target_date,
        brent_usd_bbl=close_price,
        cif_med_estimate_usd_ton=estimate_cif_med(close_price),
        source="yfinance",
        raw_data=raw,
    )


async def _fetch_range_via_yfinance(start: date, end: date) -> list[BrentData]:
    """yfinance ile tarih aralığı için toplu veri çeker."""

    def _sync_fetch_range() -> list[dict]:
        ticker = yf.Ticker(BRENT_TICKER)
        # end + 1 gün (yfinance end-exclusive)
        end_str = (end + timedelta(days=1)).isoformat()
        hist = ticker.history(start=start.isoformat(), end=end_str)

        if hist.empty:
            return []

        rows = []
        for idx, row in hist.iterrows():
            trade_date = idx.date() if hasattr(idx, "date") else idx
            rows.append({
                "date": str(trade_date),
                "open": float(row.get("Open", 0)),
                "high": float(row.get("High", 0)),
                "low": float(row.get("Low", 0)),
                "close": float(row.get("Close", 0)),
                "volume": int(row.get("Volume", 0)),
            })
        return rows

    raw_list = await asyncio.to_thread(_sync_fetch_range)
    results: list[BrentData] = []

    for raw in raw_list:
        close_price = _safe_decimal(raw.get("close"))
        if close_price is None or close_price < BRENT_MIN_USD or close_price > BRENT_MAX_USD:
            logger.warning("Aralık dışı Brent fiyatı atlanıyor: %s (%s)", raw.get("date"), close_price)
            continue

        trade_date = date.fromisoformat(raw["date"])
        results.append(
            BrentData(
                trade_date=trade_date,
                brent_usd_bbl=close_price,
                cif_med_estimate_usd_ton=estimate_cif_med(close_price),
                source="yfinance",
                raw_data=raw,
            )
        )

    return results


async def _fetch_via_yahoo_web(target_date: date) -> BrentData | None:
    """
    Yahoo Finance web API üzerinden Brent fiyatı çeker (fallback).

    Yahoo Finance chart API: v8/finance/chart/{ticker}
    """
    import time

    # Unix timestamp dönüşümü
    from datetime import datetime, timezone

    start_ts = int(datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc).timestamp())
    end_ts = start_ts + 86400  # +1 gün

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{BRENT_TICKER}"
    params = {
        "period1": start_ts,
        "period2": end_ts,
        "interval": "1d",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; YakitAnalizi/1.0)",
    }

    async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

    # Yanıttan fiyat çıkar
    try:
        result = data["chart"]["result"][0]
        indicators = result["indicators"]["quote"][0]
        close_values = indicators.get("close", [])

        if not close_values or close_values[0] is None:
            return None

        close_price = _safe_decimal(close_values[0])
        if close_price is None or close_price < BRENT_MIN_USD or close_price > BRENT_MAX_USD:
            logger.warning("Yahoo web fallback: aralık dışı fiyat: %s", close_price)
            return None

        raw_payload = {
            "source": "yahoo_web_api",
            "timestamp": time.time(),
            "response_meta": result.get("meta", {}),
            "close": float(close_price),
        }

        return BrentData(
            trade_date=target_date,
            brent_usd_bbl=close_price,
            cif_med_estimate_usd_ton=estimate_cif_med(close_price),
            source="yahoo_web",
            raw_data=raw_payload,
        )

    except (KeyError, IndexError, TypeError) as e:
        logger.error("Yahoo web API yanıt ayrıştırma hatası: %s", e)
        # Ham yanıtı loglayalım (debug için)
        logger.debug("Ham yanıt: %s", json.dumps(data, indent=2)[:500])
        return None
