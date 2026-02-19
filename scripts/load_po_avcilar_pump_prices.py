#!/usr/bin/env python3
"""
TASK-062: PO Istanbul/Avcilar CSV pump price loader.

Reads po_avcilar_2020_2026.csv and UPSERTs pump prices into daily_market_data.
Each CSV row (date, benzin, motorin, lpg) becomes 3 DB rows (one per fuel_type).

Steps:
  1. NULL all existing pump_price_tl_lt values in the table
  2. UPSERT CSV rows with pump_price_tl_lt, source='po_istanbul_avcilar',
     data_quality_flag='verified'
  3. For rows that don't exist yet (dates before DB range), INSERT new rows
  4. LPG NULL values in CSV are preserved as NULL in DB

Usage:
  python3 load_po_avcilar_pump_prices.py
"""

import csv
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation

import psycopg2
from psycopg2.extras import execute_values

# --- Configuration ---
DB_DSN = "host=localhost port=5433 dbname=yakit_analizi user=yakit_analizi password=yakit2026secure"
CSV_PATH = "/var/www/yakit_analiz/data/po_avcilar_2020_2026.csv"
SOURCE = "po_istanbul_avcilar"
QUALITY_FLAG = "verified"

FUEL_TYPES = ["benzin", "motorin", "lpg"]


def safe_decimal(value: str) -> Decimal | None:
    """Convert string to Decimal, return None for empty/invalid values."""
    if not value or not value.strip():
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        print(f"  WARNING: Invalid decimal value: '{value}'")
        return None


def load_csv(path: str) -> list[dict]:
    """Load CSV and return list of dicts with date, benzin, motorin, lpg."""
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append({
                "date": row["date"].strip(),
                "benzin": safe_decimal(row["benzin"]),
                "motorin": safe_decimal(row["motorin"]),
                "lpg": safe_decimal(row["lpg"]),
            })
    return rows


def main():
    print("=" * 60)
    print("TASK-062: PO Istanbul/Avcilar Pump Price Loader")
    print("=" * 60)

    # 1. Load CSV
    print(f"\n[1/4] Loading CSV: {CSV_PATH}")
    csv_rows = load_csv(CSV_PATH)
    total_csv = len(csv_rows)
    lpg_null_count = sum(1 for r in csv_rows if r["lpg"] is None)
    lpg_filled_count = total_csv - lpg_null_count
    print(f"  Total CSV rows: {total_csv}")
    print(f"  Date range: {csv_rows[0]['date']} -> {csv_rows[-1]['date']}")
    print(f"  LPG filled: {lpg_filled_count}, LPG NULL: {lpg_null_count}")

    # 2. Connect to DB
    print(f"\n[2/4] Connecting to DB...")
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # 3. NULL all existing pump prices
        print("\n[3/4] NULLing all existing pump_price_tl_lt values...")
        cur.execute("SELECT count(*) FROM daily_market_data WHERE pump_price_tl_lt IS NOT NULL")
        before_count = cur.fetchone()[0]
        print(f"  Rows with pump_price before: {before_count}")

        cur.execute("""
            UPDATE daily_market_data
            SET pump_price_tl_lt = NULL,
                updated_at = NOW()
        """)
        print(f"  Updated {cur.rowcount} rows to NULL")

        # 4. UPSERT from CSV
        print("\n[4/4] UPSERTing CSV data...")

        # Build tuples: (trade_date, fuel_type, pump_price, source, quality_flag)
        upsert_rows = []
        for row in csv_rows:
            for fuel in FUEL_TYPES:
                price = row[fuel]
                # Skip if price is None (LPG NULLs) — we still need to
                # ensure the row exists but pump_price stays NULL
                upsert_rows.append((
                    row["date"],
                    fuel,
                    price,  # None for NULL LPG
                    SOURCE,
                    QUALITY_FLAG,
                ))

        # Use ON CONFLICT UPSERT
        # For existing rows: update pump_price, source, quality_flag
        # For new rows: INSERT with minimal data (no brent/fx/cif)
        upsert_sql = """
            INSERT INTO daily_market_data (
                trade_date, fuel_type, pump_price_tl_lt,
                source, data_quality_flag, created_at, updated_at
            )
            VALUES %s
            ON CONFLICT (trade_date, fuel_type)
            DO UPDATE SET
                pump_price_tl_lt = EXCLUDED.pump_price_tl_lt,
                source = CASE
                    WHEN daily_market_data.brent_usd_bbl IS NOT NULL
                    THEN daily_market_data.source || '+po_avcilar'
                    ELSE EXCLUDED.source
                END,
                data_quality_flag = EXCLUDED.data_quality_flag,
                updated_at = NOW()
        """

        template = "(%s, %s::fuel_type_enum, %s, %s, %s::data_quality_enum, NOW(), NOW())"

        batch_size = 500
        total_upserted = 0
        for i in range(0, len(upsert_rows), batch_size):
            batch = upsert_rows[i:i + batch_size]
            execute_values(cur, upsert_sql, batch, template=template, page_size=batch_size)
            total_upserted += len(batch)
            if total_upserted % 1500 == 0 or total_upserted == len(upsert_rows):
                print(f"  Progress: {total_upserted}/{len(upsert_rows)} rows upserted")

        # Commit
        conn.commit()
        print(f"\n  COMMITTED: {total_upserted} rows upserted successfully")

        # 5. Verification
        print("\n" + "=" * 60)
        print("VERIFICATION")
        print("=" * 60)

        # Total records
        cur.execute("SELECT count(*) FROM daily_market_data")
        total_db = cur.fetchone()[0]
        print(f"\nTotal DB records: {total_db}")

        # Per fuel type
        cur.execute("""
            SELECT fuel_type, count(*),
                   count(pump_price_tl_lt) AS pump_filled,
                   count(*) - count(pump_price_tl_lt) AS pump_null,
                   min(trade_date), max(trade_date)
            FROM daily_market_data
            GROUP BY fuel_type
            ORDER BY fuel_type
        """)
        print("\nPer fuel type:")
        print(f"  {'fuel_type':<10} {'total':>6} {'pump_filled':>12} {'pump_null':>10} {'min_date':>12} {'max_date':>12}")
        for row in cur.fetchall():
            print(f"  {row[0]:<10} {row[1]:>6} {row[2]:>12} {row[3]:>10} {str(row[4]):>12} {str(row[5]):>12}")

        # Source breakdown
        cur.execute("""
            SELECT source, count(*)
            FROM daily_market_data
            GROUP BY source
            ORDER BY count(*) DESC
        """)
        print("\nSource breakdown:")
        for row in cur.fetchall():
            print(f"  {row[0]:<45} {row[1]:>5}")

        # First 5 records
        cur.execute("""
            SELECT trade_date, fuel_type, pump_price_tl_lt, source
            FROM daily_market_data
            WHERE fuel_type = 'benzin'
            ORDER BY trade_date ASC
            LIMIT 5
        """)
        print("\nFirst 5 benzin records:")
        for row in cur.fetchall():
            print(f"  {row[0]} | {row[1]:<8} | pump={row[2]} | source={row[3]}")

        # Last 5 records
        cur.execute("""
            SELECT trade_date, fuel_type, pump_price_tl_lt, source
            FROM daily_market_data
            WHERE fuel_type = 'benzin'
            ORDER BY trade_date DESC
            LIMIT 5
        """)
        print("\nLast 5 benzin records:")
        for row in cur.fetchall():
            print(f"  {row[0]} | {row[1]:<8} | pump={row[2]} | source={row[3]}")

        # LPG NULL check
        cur.execute("""
            SELECT count(*) FROM daily_market_data
            WHERE fuel_type = 'lpg' AND pump_price_tl_lt IS NULL
        """)
        lpg_db_null = cur.fetchone()[0]
        print(f"\nLPG pump_price NULL count in DB: {lpg_db_null}")

        # LPG first non-null
        cur.execute("""
            SELECT trade_date, pump_price_tl_lt
            FROM daily_market_data
            WHERE fuel_type = 'lpg' AND pump_price_tl_lt IS NOT NULL
            ORDER BY trade_date ASC
            LIMIT 3
        """)
        print("LPG first non-null records:")
        for row in cur.fetchall():
            print(f"  {row[0]} | {row[1]}")

        # Date range with pump prices
        cur.execute("""
            SELECT min(trade_date), max(trade_date)
            FROM daily_market_data
            WHERE pump_price_tl_lt IS NOT NULL
        """)
        pump_range = cur.fetchone()
        print(f"\nPump price date range: {pump_range[0]} -> {pump_range[1]}")

        # Rows without pump price (outside CSV range)
        cur.execute("""
            SELECT fuel_type, count(*)
            FROM daily_market_data
            WHERE pump_price_tl_lt IS NULL
            GROUP BY fuel_type
            ORDER BY fuel_type
        """)
        print("\nRows WITHOUT pump price (per fuel):")
        for row in cur.fetchall():
            print(f"  {row[0]:<10} {row[1]:>5}")

        print("\n" + "=" * 60)
        print("TASK-062 COMPLETED SUCCESSFULLY")
        print("=" * 60)

    except Exception as e:
        conn.rollback()
        print(f"\nERROR: {e}")
        print("Transaction ROLLED BACK")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
