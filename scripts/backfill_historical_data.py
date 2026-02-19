#!/usr/bin/env python3
"""
Tarihi Veri Backfill Scripti — TASK-026

Son 90 gun (2025-11-18 ~ 2026-02-16) icin Brent petrol ve USD/TRY
doviz kuru verilerini ceker ve daily_market_data tablosuna UPSERT ile yazar.

Kullanim:
    cd /var/www/yakit_analiz
    .venv/bin/python scripts/backfill_historical_data.py

Strateji:
    1. fetch_brent_range() ile toplu Brent verisi cek
    2. fetch_usd_try_range() ile toplu FX verisi cek
    3. Her trade_date icin 3 satir (benzin, motorin, lpg) UPSERT yap
    4. Hafta sonlari/tatiller icin veri gelmeyebilir — normal

Yazar: Claude Code (TASK-026)
Tarih: 2026-02-16
"""

import asyncio
import logging
import os
import sys
from datetime import date
from decimal import Decimal

import psycopg2

# Proje root'unu path'e ekle
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# .env yukleme (settings.py'nin calismasi icin)
from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.data_collectors.brent_collector import BrentData, fetch_brent_range
from src.data_collectors.fx_collector import FXData, fetch_usd_try_range

# --- Yapilandirma ---
BACKFILL_START = date(2025, 11, 18)
BACKFILL_END = date(2026, 2, 16)
FUEL_TYPES = ["benzin", "motorin", "lpg"]
DB_URL = "postgresql://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi"
LOG_EVERY_N_DAYS = 10

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill")

# yfinance ve httpx loglarini sustur
logging.getLogger("yfinance").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("peewee").setLevel(logging.WARNING)


def get_db_connection():
    """psycopg2 ile sync DB baglantisi olusturur."""
    return psycopg2.connect(DB_URL)


UPSERT_SQL = """
    INSERT INTO daily_market_data (
        trade_date, fuel_type, brent_usd_bbl, cif_med_usd_ton,
        usd_try_rate, data_quality_flag, source, updated_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
    ON CONFLICT (trade_date, fuel_type) DO UPDATE SET
        brent_usd_bbl = COALESCE(EXCLUDED.brent_usd_bbl, daily_market_data.brent_usd_bbl),
        cif_med_usd_ton = COALESCE(EXCLUDED.cif_med_usd_ton, daily_market_data.cif_med_usd_ton),
        usd_try_rate = COALESCE(EXCLUDED.usd_try_rate, daily_market_data.usd_try_rate),
        data_quality_flag = EXCLUDED.data_quality_flag,
        source = EXCLUDED.source,
        updated_at = NOW()
"""


def upsert_market_data(conn, rows: list[dict]) -> int:
    """
    daily_market_data tablosuna UPSERT yapar.

    ON CONFLICT (trade_date, fuel_type) DO UPDATE ile mevcut kayitlari gunceller.
    COALESCE ile mevcut veriyi korur (sadece NULL olani doldurur).

    Args:
        conn: psycopg2 connection
        rows: dict listesi

    Returns:
        Etkilenen satir sayisi
    """
    if not rows:
        return 0

    count = 0
    with conn.cursor() as cur:
        for r in rows:
            brent_val = float(r["brent_usd_bbl"]) if r.get("brent_usd_bbl") else None
            cif_val = float(r["cif_med_usd_ton"]) if r.get("cif_med_usd_ton") else None
            fx_val = float(r["usd_try_rate"]) if r.get("usd_try_rate") else None

            cur.execute(
                UPSERT_SQL,
                (
                    r["trade_date"],
                    r["fuel_type"],
                    brent_val,
                    cif_val,
                    fx_val,
                    r.get("data_quality_flag", "estimated"),
                    r.get("source", "backfill"),
                ),
            )
            count += 1
    conn.commit()
    return count


async def fetch_all_data():
    """Brent ve FX verilerini async olarak ceker."""
    logger.info("=" * 60)
    logger.info("BACKFILL BASLADI")
    logger.info("Tarih araligi: %s ~ %s", BACKFILL_START, BACKFILL_END)
    total_days = (BACKFILL_END - BACKFILL_START).days + 1
    logger.info("Toplam gun: %d", total_days)
    logger.info("=" * 60)

    # --- 1. Brent verisi cek ---
    logger.info("[1/2] Brent petrol verisi cekiliyor...")
    brent_data: list[BrentData] = []
    try:
        brent_data = await fetch_brent_range(BACKFILL_START, BACKFILL_END)
        logger.info("  Brent: %d gun veri alindi", len(brent_data))
    except Exception as e:
        logger.error("  Brent toplu cekim hatasi: %s", e)

    # --- 2. FX verisi cek ---
    logger.info("[2/2] USD/TRY doviz kuru verisi cekiliyor...")
    fx_data: list[FXData] = []
    try:
        fx_data = await fetch_usd_try_range(BACKFILL_START, BACKFILL_END)
        logger.info("  FX: %d gun veri alindi", len(fx_data))
    except Exception as e:
        logger.error("  FX toplu cekim hatasi: %s", e)

    return brent_data, fx_data


def build_rows(brent_data: list[BrentData], fx_data: list[FXData]) -> list[dict]:
    """
    Brent ve FX verilerini birlestirerek DB satirlari olusturur.

    Her trade_date icin 3 satir (benzin, motorin, lpg).
    Brent ve FX farkli gunlerde veri dondurebilir — birlestirme trade_date uzerinden.
    """
    # trade_date bazli index olustur
    brent_by_date: dict[date, BrentData] = {}
    for b in brent_data:
        brent_by_date[b.trade_date] = b

    fx_by_date: dict[date, FXData] = {}
    for f in fx_data:
        fx_by_date[f.trade_date] = f

    # Tum benzersiz tarihleri topla
    all_dates = sorted(set(list(brent_by_date.keys()) + list(fx_by_date.keys())))

    rows: list[dict] = []
    for td in all_dates:
        brent = brent_by_date.get(td)
        fx = fx_by_date.get(td)

        # Kaynak bilgisi
        sources = []
        if brent:
            sources.append(brent.source)
        if fx:
            sources.append(fx.source)
        source_str = "+".join(sources) if sources else "backfill"

        for fuel_type in FUEL_TYPES:
            row = {
                "trade_date": td,
                "fuel_type": fuel_type,
                "brent_usd_bbl": brent.brent_usd_bbl if brent else None,
                "cif_med_usd_ton": brent.cif_med_estimate_usd_ton if brent else None,
                "usd_try_rate": fx.usd_try_rate if fx else None,
                "data_quality_flag": "estimated",
                "source": source_str,
            }
            rows.append(row)

    return rows


def write_to_db(rows: list[dict]) -> dict:
    """Satirlari DB'ye yazar. Ilerleme loglar."""
    if not rows:
        logger.warning("Yazilacak veri yok!")
        return {"success": 0, "failed": 0, "total": 0, "unique_dates": 0}

    # Tarihlere gore grupla (ilerleme logu icin)
    dates = sorted(set(r["trade_date"] for r in rows))
    total_dates = len(dates)

    logger.info("=" * 60)
    logger.info("DB YAZIMI BASLADI")
    logger.info("Toplam benzersiz tarih: %d", total_dates)
    logger.info("Toplam satir: %d (her tarih x 3 yakit tipi)", len(rows))
    logger.info("=" * 60)

    conn = get_db_connection()
    success_count = 0
    fail_count = 0

    try:
        # Tarihlere gore batch yaz
        for i, td in enumerate(dates, 1):
            date_rows = [r for r in rows if r["trade_date"] == td]
            try:
                upsert_market_data(conn, date_rows)
                success_count += len(date_rows)

                # Her LOG_EVERY_N_DAYS gunde bir log
                if i % LOG_EVERY_N_DAYS == 0 or i == total_dates:
                    logger.info(
                        "  Ilerleme: %d/%d tarih (%d%%) - son: %s",
                        i,
                        total_dates,
                        int(i / total_dates * 100),
                        td,
                    )
            except Exception as e:
                logger.error("  Yazim hatasi (tarih: %s): %s", td, e)
                fail_count += len(date_rows)
                # Hata durumunda connection'i rollback yap ve devam et
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
    """Yazilan veriyi dogrular."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Toplam kayit
            cur.execute("SELECT count(*) FROM daily_market_data;")
            total = cur.fetchone()[0]

            # Tarih araligi
            cur.execute("SELECT MIN(trade_date), MAX(trade_date) FROM daily_market_data;")
            min_date, max_date = cur.fetchone()

            # Yakit tipi basina
            cur.execute(
                """
                SELECT fuel_type, count(*), MIN(trade_date), MAX(trade_date)
                FROM daily_market_data
                GROUP BY fuel_type
                ORDER BY fuel_type;
                """
            )
            fuel_stats = cur.fetchall()

            # Son kayitlar
            cur.execute(
                """
                SELECT trade_date, fuel_type, brent_usd_bbl, usd_try_rate, source
                FROM daily_market_data
                ORDER BY trade_date DESC, fuel_type
                LIMIT 15;
                """
            )
            recent = cur.fetchall()

            # Brent dolu kayit sayisi
            cur.execute(
                "SELECT count(*) FROM daily_market_data WHERE brent_usd_bbl IS NOT NULL;"
            )
            brent_count = cur.fetchone()[0]

            # FX dolu kayit sayisi
            cur.execute(
                "SELECT count(*) FROM daily_market_data WHERE usd_try_rate IS NOT NULL;"
            )
            fx_count = cur.fetchone()[0]

        return {
            "total": total,
            "min_date": min_date,
            "max_date": max_date,
            "fuel_stats": fuel_stats,
            "recent": recent,
            "brent_filled": brent_count,
            "fx_filled": fx_count,
        }
    finally:
        conn.close()


async def main():
    """Ana fonksiyon."""
    try:
        # 1. Veri cek
        brent_data, fx_data = await fetch_all_data()

        if not brent_data and not fx_data:
            logger.error("Hicbir veri cekilemedi! Script sonlandiriliyor.")
            return

        # 2. Satirlar olustur
        rows = build_rows(brent_data, fx_data)
        logger.info("Olusturulan satir sayisi: %d", len(rows))

        # 3. DB'ye yaz
        result = write_to_db(rows)

        # 4. Ozet rapor
        logger.info("=" * 60)
        logger.info("BACKFILL TAMAMLANDI")
        logger.info("  Basarili: %d satir", result["success"])
        logger.info("  Basarisiz: %d satir", result["failed"])
        logger.info(
            "  Toplam: %d satir (%d benzersiz tarih)",
            result["total"],
            result["unique_dates"],
        )
        logger.info("=" * 60)

        # 5. Dogrulama
        logger.info("")
        logger.info("DOGRULAMA:")
        v = verify_data()
        logger.info("  Toplam kayit: %d", v["total"])
        logger.info("  Tarih araligi: %s ~ %s", v["min_date"], v["max_date"])
        logger.info("  Brent dolu: %d kayit", v["brent_filled"])
        logger.info("  FX dolu: %d kayit", v["fx_filled"])
        logger.info("")
        logger.info("  Yakit tipi bazinda:")
        for fuel, cnt, mindt, maxdt in v["fuel_stats"]:
            logger.info("    %s: %d kayit (%s ~ %s)", fuel, cnt, mindt, maxdt)
        logger.info("")
        logger.info("  Son 5 tarih:")
        shown_dates = set()
        for row in v["recent"]:
            td = row[0]
            if td not in shown_dates and len(shown_dates) < 5:
                shown_dates.add(td)
                brent_val = float(row[2]) if row[2] else 0
                fx_val = float(row[3]) if row[3] else 0
                logger.info(
                    "    %s | %s | Brent=%.2f | FX=%.4f | %s",
                    row[0],
                    row[1],
                    brent_val,
                    fx_val,
                    row[4],
                )

    except Exception:
        logger.exception("Backfill sirasinda beklenmeyen hata")
        raise


if __name__ == "__main__":
    asyncio.run(main())
