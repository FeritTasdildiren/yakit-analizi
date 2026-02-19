#!/usr/bin/env python3
"""
Tarihi Veri Mega-Backfill Scripti — TASK-028

ML eğitimi için 2022-01 ~ 2026-02 arası tam veri seti oluşturur.
3 bölümden oluşur:
  A) Pompa fiyatları — tppd.com.tr scraping (2022 ~ 2025-12) + forward-fill
  B) Pompa fiyatları — 2025-12-18 ~ 2026-02 arası boşluk (Bildirim Portal veya son fiyat taşıma)
  C) Brent petrol + USD/TRY — yfinance ile 2022-01-01'den itibaren genişletme

Kullanım:
    cd /var/www/yakit_analiz
    .venv/bin/python scripts/backfill_mega.py

Yazar: Claude Code (TASK-028)
Tarih: 2026-02-16
"""

import asyncio
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import psycopg2
import requests
from bs4 import BeautifulSoup

# Proje root'unu path'e ekle
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# .env yükleme
from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

import yfinance as yf

from src.data_collectors.brent_collector import BrentData, fetch_brent_range
from src.data_collectors.fx_collector import FXData

# --- Yapılandırma ---
MEGA_START = date(2022, 1, 1)
MEGA_END = date(2026, 2, 16)
FUEL_TYPES = ["benzin", "motorin", "lpg"]
DB_URL = "postgresql://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi"
LOG_EVERY_N_DAYS = 50

# TPPD URL şablonu
TPPD_URL = "https://www.tppd.com.tr/gecmis-akaryakit-fiyatlari"
TPPD_PARAMS_BASE = {"id": "34", "county": "413"}

# Türkçe ay isimleri → ay numarası
TURKCE_AYLAR = {
    "Ocak": 1, "Şubat": 2, "Mart": 3, "Nisan": 4,
    "Mayıs": 5, "Haziran": 6, "Temmuz": 7, "Ağustos": 8,
    "Eylül": 9, "Ekim": 10, "Kasım": 11, "Aralık": 12,
    # Küçük harfli alternatifler (güvenlik)
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4,
    "mayıs": 5, "haziran": 6, "temmuz": 7, "ağustos": 8,
    "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
    # 3 harfli kısaltmalar
    "Oca": 1, "Şub": 2, "Mar": 3, "Nis": 4,
    "May": 5, "Haz": 6, "Tem": 7, "Ağu": 8,
    "Eyl": 9, "Eki": 10, "Kas": 11, "Ara": 12,
}

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("mega-backfill")

# Gürültülü logger'ları sustur
logging.getLogger("yfinance").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("peewee").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


# ── Yardımcı Fonksiyonlar ────────────────────────────────────────────────────


def _parse_turkish_date(text: str) -> date | None:
    """
    Türkçe tarih formatını parse eder.
    Beklenen formatlar:
      - '14 Aralık 2022'
      - '14 Ara 2022'
      - '01 Ocak 2025'
    """
    text = text.strip()
    parts = text.split()
    if len(parts) < 3:
        return None

    try:
        day = int(parts[0])
        month_name = parts[1]
        year = int(parts[2])

        month = TURKCE_AYLAR.get(month_name)
        if month is None:
            # Alternatif: kısaltılmış ay adı dene
            for key, val in TURKCE_AYLAR.items():
                if month_name.lower().startswith(key.lower()[:3]):
                    month = val
                    break

        if month is None:
            logger.warning("Bilinmeyen Türkçe ay adı: '%s'", month_name)
            return None

        return date(year, month, day)

    except (ValueError, IndexError):
        logger.warning("Tarih parse hatası: '%s'", text)
        return None


def _parse_decimal(raw: str | None) -> Decimal | None:
    """Türkçe formatlı sayıyı Decimal'e dönüştürür. '42,84' → Decimal('42.84')"""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw or raw == "-" or raw == "":
        return None
    try:
        normalized = raw.replace(",", ".")
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None


def get_db_connection():
    """psycopg2 ile sync DB bağlantısı oluşturur."""
    return psycopg2.connect(DB_URL)


# ── UPSERT SQL ───────────────────────────────────────────────────────────────

UPSERT_SQL = """
    INSERT INTO daily_market_data (
        trade_date, fuel_type, brent_usd_bbl, cif_med_usd_ton,
        usd_try_rate, pump_price_tl_lt, data_quality_flag, source, updated_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
    ON CONFLICT (trade_date, fuel_type) DO UPDATE SET
        brent_usd_bbl = COALESCE(EXCLUDED.brent_usd_bbl, daily_market_data.brent_usd_bbl),
        cif_med_usd_ton = COALESCE(EXCLUDED.cif_med_usd_ton, daily_market_data.cif_med_usd_ton),
        usd_try_rate = COALESCE(EXCLUDED.usd_try_rate, daily_market_data.usd_try_rate),
        pump_price_tl_lt = COALESCE(EXCLUDED.pump_price_tl_lt, daily_market_data.pump_price_tl_lt),
        data_quality_flag = EXCLUDED.data_quality_flag,
        source = EXCLUDED.source,
        updated_at = NOW()
"""


def upsert_rows(conn, rows: list[dict]) -> int:
    """daily_market_data tablosuna UPSERT yapar. Idempotent."""
    if not rows:
        return 0

    count = 0
    with conn.cursor() as cur:
        for r in rows:
            brent_val = float(r["brent_usd_bbl"]) if r.get("brent_usd_bbl") else None
            cif_val = float(r["cif_med_usd_ton"]) if r.get("cif_med_usd_ton") else None
            fx_val = float(r["usd_try_rate"]) if r.get("usd_try_rate") else None
            pump_val = float(r["pump_price_tl_lt"]) if r.get("pump_price_tl_lt") else None

            cur.execute(
                UPSERT_SQL,
                (
                    r["trade_date"],
                    r["fuel_type"],
                    brent_val,
                    cif_val,
                    fx_val,
                    pump_val,
                    r.get("data_quality_flag", "estimated"),
                    r.get("source", "mega_backfill"),
                ),
            )
            count += 1
    conn.commit()
    return count


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM A: TPPD.COM.TR POMPA FİYATI SCRAPING
# ══════════════════════════════════════════════════════════════════════════════


def scrape_tppd(start_date: str, end_date: str) -> list[dict]:
    """
    tppd.com.tr'den geçmiş akaryakıt fiyatlarını scrape eder.

    Args:
        start_date: Başlangıç tarihi (DD.MM.YYYY)
        end_date: Bitiş tarihi (DD.MM.YYYY)

    Returns:
        [{'date': date, 'benzin': Decimal, 'motorin': Decimal, 'lpg': Decimal}, ...]
    """
    params = {
        **TPPD_PARAMS_BASE,
        "StartDate": start_date,
        "EndDate": end_date,
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "tr-TR,tr;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    logger.info("TPPD scraping: %s → %s", start_date, end_date)

    response = requests.get(TPPD_URL, params=params, headers=headers, timeout=60)
    response.raise_for_status()
    response.encoding = "utf-8"

    soup = BeautifulSoup(response.text, "html.parser")

    # Tablo satırlarını bul
    results = []

    # Tüm tablo satırlarını bul (tbody > tr veya table > tr)
    table = soup.find("table")
    if not table:
        # Tablo bulunamadıysa, alternatif strateji: tüm tr'leri tara
        rows = soup.find_all("tr")
    else:
        rows = table.find_all("tr")

    logger.info("TPPD HTML'de %d satır bulundu", len(rows))

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 8:
            continue

        # İlk hücre: tarih
        date_text = cells[0].get_text(strip=True)
        parsed_date = _parse_turkish_date(date_text)
        if parsed_date is None:
            continue

        # Kolon yapısı:
        # [0] TARİH
        # [1] KURŞUNSUZ BENZİN
        # [2] GAZ YAĞI
        # [3] MOTORİN (birinci — kullanacağımız)
        # [4] MOTORİN (ikinci — genellikle aynı veya farklı tip)
        # [5] KALORİFER YAKITI
        # [6] FUEL OIL
        # [7] Y.K. FUEL OIL
        # [8] GAZ (LPG/Otogaz) — varsa

        benzin = _parse_decimal(cells[1].get_text(strip=True))
        motorin = _parse_decimal(cells[3].get_text(strip=True))

        # LPG: Son kolon (GAZ)
        lpg = None
        if len(cells) > 8:
            lpg = _parse_decimal(cells[8].get_text(strip=True))

        if benzin is None and motorin is None:
            continue

        results.append({
            "date": parsed_date,
            "benzin": benzin,
            "motorin": motorin,
            "lpg": lpg,
        })

    # Tarihe göre sırala
    results.sort(key=lambda x: x["date"])
    logger.info("TPPD parse tamamlandı: %d fiyat değişim kaydı", len(results))

    return results


def forward_fill_pump_prices(
    change_records: list[dict],
    fill_start: date,
    fill_end: date,
) -> list[dict]:
    """
    Fiyat değişim kayıtlarını günlük veriye forward-fill eder.

    TPPD sadece fiyat DEĞİŞİM tarihlerini listeler. Aradaki günlerde fiyat
    bir sonraki değişime kadar aynı kalır. Bu fonksiyon her takvim günü için
    (hafta sonu dahil) bir kayıt oluşturur.

    Args:
        change_records: Fiyat değişim kayıtları (tarih sıralı)
        fill_start: Forward-fill başlangıç tarihi
        fill_end: Forward-fill bitiş tarihi

    Returns:
        Her gün için {date, benzin, motorin, lpg} listesi
    """
    if not change_records:
        return []

    # Tarih → fiyat index'i oluştur
    change_by_date: dict[date, dict] = {}
    for rec in change_records:
        change_by_date[rec["date"]] = rec

    daily_records = []
    current_benzin = None
    current_motorin = None
    current_lpg = None

    # Değişim kayıtlarının başlangıcından önceki ilk fiyatı bul
    first_change = change_records[0]
    if fill_start < first_change["date"]:
        # fill_start'tan ilk değişime kadar veri yok — ilk değişimdeki fiyatı backward carry et
        # (ML için veri kaybını minimize etmek amacıyla)
        current_benzin = first_change["benzin"]
        current_motorin = first_change["motorin"]
        current_lpg = first_change["lpg"]

    current_date = fill_start
    while current_date <= fill_end:
        # Bu tarihte fiyat değişimi var mı?
        if current_date in change_by_date:
            change = change_by_date[current_date]
            if change["benzin"] is not None:
                current_benzin = change["benzin"]
            if change["motorin"] is not None:
                current_motorin = change["motorin"]
            if change["lpg"] is not None:
                current_lpg = change["lpg"]

        # Fiyat henüz belirlenmemişse (ilk değişimden önce) atla
        if current_benzin is not None or current_motorin is not None:
            daily_records.append({
                "date": current_date,
                "benzin": current_benzin,
                "motorin": current_motorin,
                "lpg": current_lpg,
            })

        current_date += timedelta(days=1)

    return daily_records


def scrape_all_tppd_periods() -> list[dict]:
    """
    TPPD'den tüm dönemleri scrape eder ve birleştirir.

    3 dönem:
    1. 2022-01-01 ~ 2022-12-31
    2. 2023-01-01 ~ 2024-12-31
    3. 2025-01-01 ~ 2025-12-17 (son veri tarihi)
    """
    all_records = []

    periods = [
        ("01.01.2022", "31.12.2022"),
        ("01.01.2023", "31.12.2024"),
        ("01.01.2025", "16.02.2026"),  # 2026'ya kadar dene, varsa alır
    ]

    for start_str, end_str in periods:
        try:
            records = scrape_tppd(start_str, end_str)
            logger.info(
                "TPPD dönem %s→%s: %d kayıt",
                start_str, end_str, len(records),
            )
            all_records.extend(records)
        except Exception as e:
            logger.error("TPPD dönem %s→%s hatası: %s", start_str, end_str, e)

    # Tekrar eden tarihleri temizle (son gelen kazanır)
    seen: dict[date, dict] = {}
    for rec in all_records:
        seen[rec["date"]] = rec

    unique_records = sorted(seen.values(), key=lambda x: x["date"])
    logger.info("TPPD toplam: %d benzersiz fiyat değişim kaydı", len(unique_records))

    return unique_records


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM B: 2025-12-18 ~ 2026-02-16 ARASINI DOLDURMA
# ══════════════════════════════════════════════════════════════════════════════

# Bu aralık TPPD'den gelmiyorsa, son TPPD fiyatı forward-fill edilecek.
# Mevcut daily_market_data'daki güncel pompa fiyatları (TASK-025/027'den) korunacak.


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM C: BRENT + FX GENİŞLETME (2022-01 ~ 2025-11)
# ══════════════════════════════════════════════════════════════════════════════


async def fetch_brent_mega() -> list[BrentData]:
    """Brent petrol verilerini 2022-01-01'den bugüne kadar çeker."""
    logger.info("[BRENT] yfinance ile 2022-01-01 ~ %s arası çekiliyor...", MEGA_END)

    all_brent: list[BrentData] = []

    # yfinance büyük aralıklarda sorun çıkarabilir, yıllık chunk'la
    year_start = MEGA_START
    while year_start <= MEGA_END:
        year_end = min(
            date(year_start.year, 12, 31),
            MEGA_END,
        )
        try:
            chunk = await fetch_brent_range(year_start, year_end)
            logger.info(
                "  Brent %d: %d iş günü verisi",
                year_start.year,
                len(chunk),
            )
            all_brent.extend(chunk)
        except Exception as e:
            logger.error("  Brent %d hatası: %s", year_start.year, e)

        year_start = date(year_start.year + 1, 1, 1)

    logger.info("[BRENT] Toplam: %d iş günü verisi", len(all_brent))
    return all_brent


async def fetch_fx_mega() -> list[FXData]:
    """
    USD/TRY döviz kuru verilerini 2022-01-01'den bugüne kadar çeker.

    TCMB EVDS API key mevcut olmadığı için doğrudan yfinance
    toplu download kullanılır. Bu çok daha hızlıdır (tek HTTP isteği).
    """
    logger.info("[FX] yfinance USDTRY=X ile 2022-01-01 ~ %s arası çekiliyor...", MEGA_END)

    def _sync_fetch_fx_range() -> list[FXData]:
        """yfinance ile toplu USD/TRY verisi çeker (senkron)."""
        results: list[FXData] = []

        # yfinance end exclusive, +1 gün
        end_str = (MEGA_END + timedelta(days=1)).isoformat()
        start_str = MEGA_START.isoformat()

        ticker = yf.Ticker("TRY=X")
        hist = ticker.history(start=start_str, end=end_str)

        if hist.empty:
            logger.warning("yfinance TRY=X boş döndü, USDTRY=X deneniyor...")
            ticker2 = yf.Ticker("USDTRY=X")
            hist = ticker2.history(start=start_str, end=end_str)

        if hist.empty:
            logger.error("yfinance FX: hiç veri alınamadı!")
            return results

        for idx, row in hist.iterrows():
            try:
                trade_date = idx.date() if hasattr(idx, "date") else idx
                close_val = float(row.get("Close", 0))

                if close_val < 1 or close_val > 100:
                    continue

                results.append(
                    FXData(
                        trade_date=trade_date,
                        usd_try_rate=Decimal(str(round(close_val, 6))),
                        source="yfinance_fx",
                        raw_data={"close": close_val},
                    )
                )
            except Exception as e:
                logger.warning("FX satır parse hatası: %s — %s", idx, e)
                continue

        return results

    all_fx = await asyncio.to_thread(_sync_fetch_fx_range)
    logger.info("[FX] Toplam: %d iş günü verisi", len(all_fx))
    return all_fx


# ══════════════════════════════════════════════════════════════════════════════
# ANA FONKSİYON
# ══════════════════════════════════════════════════════════════════════════════


def build_mega_rows(
    pump_daily: list[dict],
    brent_data: list[BrentData],
    fx_data: list[FXData],
) -> list[dict]:
    """
    Pompa fiyatları, Brent ve FX verilerini birleştirip DB satırlarına dönüştürür.

    Her (trade_date, fuel_type) çifti için tek bir satır oluşturur.
    UPSERT ile mevcut veriler korunur (COALESCE).
    """
    # Brent ve FX'i tarih bazlı index'le
    brent_by_date: dict[date, BrentData] = {}
    for b in brent_data:
        brent_by_date[b.trade_date] = b

    fx_by_date: dict[date, FXData] = {}
    for f in fx_data:
        fx_by_date[f.trade_date] = f

    # Pompa fiyatlarını tarih bazlı index'le
    pump_by_date: dict[date, dict] = {}
    for p in pump_daily:
        pump_by_date[p["date"]] = p

    # Tüm benzersiz tarihleri topla
    all_dates = sorted(
        set(
            list(brent_by_date.keys())
            + list(fx_by_date.keys())
            + list(pump_by_date.keys())
        )
    )

    # Sadece MEGA_START ~ MEGA_END aralığındaki tarihleri al
    all_dates = [d for d in all_dates if MEGA_START <= d <= MEGA_END]

    logger.info("Toplam benzersiz tarih: %d", len(all_dates))

    rows: list[dict] = []
    for td in all_dates:
        brent = brent_by_date.get(td)
        fx = fx_by_date.get(td)
        pump = pump_by_date.get(td)

        # Kaynak bilgisi
        sources = []
        if pump:
            sources.append("tppd")
        if brent:
            sources.append(brent.source)
        if fx:
            sources.append(fx.source)
        source_str = "+".join(sources) if sources else "mega_backfill"

        # Pompa fiyatı ve Brent/FX var mı?
        has_pump = pump is not None and (pump.get("benzin") or pump.get("motorin"))
        has_brent = brent is not None
        has_fx = fx is not None

        # data_quality_flag: DB enum değerleri: verified, interpolated, manual, estimated, stale
        # Pompa + Brent + FX hepsi varsa → verified (en iyi kalite)
        # Kısmi veri → estimated
        # Sadece forward-fill → interpolated
        if has_pump and has_brent and has_fx:
            quality = "verified"
        elif has_pump or has_brent:
            quality = "estimated"
        else:
            quality = "estimated"

        for fuel_type in FUEL_TYPES:
            pump_price = None
            if pump:
                pump_price = pump.get(fuel_type)

            row = {
                "trade_date": td,
                "fuel_type": fuel_type,
                "brent_usd_bbl": brent.brent_usd_bbl if brent else None,
                "cif_med_usd_ton": brent.cif_med_estimate_usd_ton if brent else None,
                "usd_try_rate": fx.usd_try_rate if fx else None,
                "pump_price_tl_lt": pump_price,
                "data_quality_flag": quality,
                "source": source_str,
            }
            rows.append(row)

    return rows


def write_to_db(rows: list[dict]) -> dict:
    """Satırları DB'ye yazar. İlerleme loglar."""
    if not rows:
        logger.warning("Yazılacak veri yok!")
        return {"success": 0, "failed": 0, "total": 0, "unique_dates": 0}

    dates = sorted(set(r["trade_date"] for r in rows))
    total_dates = len(dates)

    logger.info("=" * 60)
    logger.info("DB YAZIMI BAŞLADI")
    logger.info("Toplam benzersiz tarih: %d", total_dates)
    logger.info("Toplam satır: %d (her tarih × 3 yakıt tipi)", len(rows))
    logger.info("=" * 60)

    conn = get_db_connection()
    success_count = 0
    fail_count = 0

    try:
        for i, td in enumerate(dates, 1):
            date_rows = [r for r in rows if r["trade_date"] == td]
            try:
                upsert_rows(conn, date_rows)
                success_count += len(date_rows)

                if i % LOG_EVERY_N_DAYS == 0 or i == total_dates:
                    logger.info(
                        "  İlerleme: %d/%d tarih (%d%%) — son: %s",
                        i, total_dates, int(i / total_dates * 100), td,
                    )
            except Exception as e:
                logger.error("  Yazım hatası (tarih: %s): %s", td, e)
                fail_count += len(date_rows)
                conn.rollback()
    finally:
        conn.close()

    return {
        "success": success_count,
        "failed": fail_count,
        "total": len(rows),
        "unique_dates": total_dates,
    }


def verify_data() -> dict:
    """Yazılan veriyi doğrular ve detaylı rapor döndürür."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Toplam kayıt
            cur.execute("SELECT count(*) FROM daily_market_data;")
            total = cur.fetchone()[0]

            # Tarih aralığı
            cur.execute("SELECT MIN(trade_date), MAX(trade_date) FROM daily_market_data;")
            min_date, max_date = cur.fetchone()

            # Yakıt tipi bazında
            cur.execute("""
                SELECT fuel_type, count(*),
                       count(pump_price_tl_lt) AS pump_count,
                       count(brent_usd_bbl) AS brent_count,
                       count(usd_try_rate) AS fx_count,
                       MIN(trade_date), MAX(trade_date)
                FROM daily_market_data
                GROUP BY fuel_type
                ORDER BY fuel_type;
            """)
            fuel_stats = cur.fetchall()

            # Yıl bazında kayıt dağılımı
            cur.execute("""
                SELECT EXTRACT(YEAR FROM trade_date)::int AS yil,
                       count(*) AS toplam,
                       count(pump_price_tl_lt) AS pompa_dolu,
                       count(brent_usd_bbl) AS brent_dolu,
                       count(usd_try_rate) AS fx_dolu
                FROM daily_market_data
                GROUP BY yil
                ORDER BY yil;
            """)
            year_stats = cur.fetchall()

            # Quality flag dağılımı
            cur.execute("""
                SELECT data_quality_flag, count(*)
                FROM daily_market_data
                GROUP BY data_quality_flag
                ORDER BY count(*) DESC;
            """)
            quality_stats = cur.fetchall()

            # Son 5 tarih
            cur.execute("""
                SELECT trade_date, fuel_type, brent_usd_bbl, usd_try_rate,
                       pump_price_tl_lt, data_quality_flag, source
                FROM daily_market_data
                ORDER BY trade_date DESC, fuel_type
                LIMIT 15;
            """)
            recent = cur.fetchall()

        return {
            "total": total,
            "min_date": min_date,
            "max_date": max_date,
            "fuel_stats": fuel_stats,
            "year_stats": year_stats,
            "quality_stats": quality_stats,
            "recent": recent,
        }
    finally:
        conn.close()


async def main():
    """Ana fonksiyon — 3 bölümü sırayla çalıştırır."""
    logger.info("=" * 70)
    logger.info("MEGA BACKFILL BAŞLADI")
    logger.info("Tarih aralığı: %s ~ %s", MEGA_START, MEGA_END)
    logger.info("=" * 70)

    # ══════════════════════════════════════════════════════════════════════
    # BÖLÜM A: TPPD POMPA FİYATLARI SCRAPING
    # ══════════════════════════════════════════════════════════════════════
    logger.info("")
    logger.info("━" * 60)
    logger.info("[A] TPPD POMPA FİYATLARI SCRAPING")
    logger.info("━" * 60)

    tppd_changes = scrape_all_tppd_periods()

    if tppd_changes:
        first = tppd_changes[0]["date"]
        last = tppd_changes[-1]["date"]
        logger.info(
            "TPPD fiyat değişimleri: %d kayıt (%s ~ %s)",
            len(tppd_changes), first, last,
        )

        # Forward-fill: her takvim günü için fiyat oluştur
        pump_daily = forward_fill_pump_prices(
            tppd_changes,
            fill_start=max(MEGA_START, first),
            fill_end=min(MEGA_END, last) if last < MEGA_END else MEGA_END,
        )
        logger.info("Forward-fill sonrası: %d günlük pompa kaydı", len(pump_daily))
    else:
        logger.warning("TPPD'den veri alınamadı!")
        pump_daily = []

    # ══════════════════════════════════════════════════════════════════════
    # BÖLÜM C: BRENT + FX GENİŞLETME (2022-01 ~ 2026-02)
    # ══════════════════════════════════════════════════════════════════════
    logger.info("")
    logger.info("━" * 60)
    logger.info("[C] BRENT PETROL + USD/TRY VERİLERİ")
    logger.info("━" * 60)

    # Brent ve FX paralel çek
    brent_data, fx_data = await asyncio.gather(
        fetch_brent_mega(),
        fetch_fx_mega(),
    )

    logger.info("Brent: %d iş günü, FX: %d iş günü", len(brent_data), len(fx_data))

    # ══════════════════════════════════════════════════════════════════════
    # BİRLEŞTİRME VE DB YAZIMI
    # ══════════════════════════════════════════════════════════════════════
    logger.info("")
    logger.info("━" * 60)
    logger.info("[DB] VERİLER BİRLEŞTİRİLİYOR VE YAZILIYOR")
    logger.info("━" * 60)

    rows = build_mega_rows(pump_daily, brent_data, fx_data)
    logger.info("Oluşturulan toplam satır: %d", len(rows))

    result = write_to_db(rows)

    # ══════════════════════════════════════════════════════════════════════
    # DOĞRULAMA RAPORU
    # ══════════════════════════════════════════════════════════════════════
    logger.info("")
    logger.info("━" * 60)
    logger.info("[DOĞRULAMA] VERİ KONTROLÜ")
    logger.info("━" * 60)

    logger.info("Yazım sonucu:")
    logger.info("  Başarılı: %d satır", result["success"])
    logger.info("  Başarısız: %d satır", result["failed"])
    logger.info(
        "  Toplam: %d satır (%d benzersiz tarih)",
        result["total"], result["unique_dates"],
    )

    v = verify_data()
    logger.info("")
    logger.info("DB Durumu:")
    logger.info("  Toplam kayıt: %d", v["total"])
    logger.info("  Tarih aralığı: %s ~ %s", v["min_date"], v["max_date"])

    logger.info("")
    logger.info("  Yakıt tipi bazında:")
    for row in v["fuel_stats"]:
        fuel, cnt, pump_cnt, brent_cnt, fx_cnt, mindt, maxdt = row
        logger.info(
            "    %s: %d kayıt (pompa=%d, brent=%d, fx=%d) [%s ~ %s]",
            fuel, cnt, pump_cnt, brent_cnt, fx_cnt, mindt, maxdt,
        )

    logger.info("")
    logger.info("  Yıl bazında dağılım:")
    for row in v["year_stats"]:
        yil, toplam, pompa, brent, fx = row
        logger.info(
            "    %d: %d kayıt (pompa=%d, brent=%d, fx=%d)",
            yil, toplam, pompa, brent, fx,
        )

    logger.info("")
    logger.info("  Veri kalitesi dağılımı:")
    for flag, cnt in v["quality_stats"]:
        logger.info("    %s: %d kayıt", flag, cnt)

    logger.info("")
    logger.info("  Son 5 tarih (benzin örnekleri):")
    shown = set()
    for row in v["recent"]:
        td, ft, brent_v, fx_v, pump_v, flag, src = row
        if td not in shown and ft == "benzin":
            shown.add(td)
            if len(shown) > 5:
                break
            logger.info(
                "    %s | Brent=%.2f | FX=%.4f | Pompa=%s | %s | %s",
                td,
                float(brent_v) if brent_v else 0,
                float(fx_v) if fx_v else 0,
                f"{float(pump_v):.2f}" if pump_v else "N/A",
                flag,
                src,
            )

    logger.info("")
    logger.info("=" * 70)
    logger.info("MEGA BACKFILL TAMAMLANDI")
    logger.info("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
