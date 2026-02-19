"""
Predictor v5 — Label Uretim Modulu
===================================
pump_price gunluk farklarindan binary label, first_event ve net_amount_3d hesaplama.

Kullanim:
    from src.predictor_v5.labels import compute_labels
    df = compute_labels("benzin", date(2024, 1, 1), date(2024, 12, 31))
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import pandas as pd
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config'den yuklenen sabitler
# ---------------------------------------------------------------------------
try:
    from src.predictor_v5.config import (
        THRESHOLD_TL as THRESHOLD,
        LABEL_WINDOW as LABEL_WINDOW_DAYS,
        FF_MAX_LOOKBACK as MAX_FF_LOOKBACK,
        FUEL_TYPES,
    )
    VALID_FUEL_TYPES = tuple(FUEL_TYPES)
except ImportError:
    # Fallback: config.py henuz yoksa hard-code
    THRESHOLD = Decimal("0.25")
    LABEL_WINDOW_DAYS = 3
    MAX_FF_LOOKBACK = 15
    VALID_FUEL_TYPES = ("benzin", "motorin", "lpg")

DB_DSN = "postgresql://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi" 


# ---------------------------------------------------------------------------
# Yardimci fonksiyonlar
# ---------------------------------------------------------------------------

def _safe_decimal(value) -> Optional[Decimal]:
    """float/int/str -> Decimal donusumu. None -> None."""
    if value is None:
        return None
    # float -> str -> Decimal (IEEE 754 artefaktlarini onler)
    return Decimal(str(value))


def _fetch_pump_prices(
    fuel_type: str,
    start_date: date,
    end_date: date,
    dsn: str = DB_DSN,
) -> dict[date, Decimal]:
    """
    DB'den pump_price_tl_lt degerlerini ceker.
    Dondurur: {trade_date: Decimal(pump_price)} sozlugu.
    """
    query = """
        SELECT trade_date, pump_price_tl_lt
        FROM daily_market_data
        WHERE fuel_type = %s
          AND trade_date BETWEEN %s AND %s
        ORDER BY trade_date
    """
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(query, (fuel_type, start_date, end_date))
            rows = cur.fetchall()
    finally:
        conn.close()

    prices: dict[date, Decimal] = {}
    for trade_date, pump_price in rows:
        if pump_price is not None:
            prices[trade_date] = _safe_decimal(pump_price)
    return prices


def _forward_fill_prices(
    prices: dict[date, Decimal],
    start_date: date,
    end_date: date,
    max_lookback: int = MAX_FF_LOOKBACK,
) -> dict[date, Optional[Decimal]]:
    """
    Her takvim gunu icin pump_price dondurur.
    Eksik gunlerde son bilinen degeri forward-fill eder (max_lookback sinirli).
    """
    filled: dict[date, Optional[Decimal]] = {}
    last_known: Optional[Decimal] = None
    last_known_date: Optional[date] = None

    current = start_date
    while current <= end_date:
        if current in prices:
            last_known = prices[current]
            last_known_date = current
            filled[current] = last_known
        elif last_known is not None and last_known_date is not None:
            gap = (current - last_known_date).days
            if gap <= max_lookback:
                filled[current] = last_known
            else:
                filled[current] = None
        else:
            filled[current] = None
        current += timedelta(days=1)

    return filled


def _compute_single_label(
    run_date: date,
    filled_prices: dict[date, Optional[Decimal]],
    threshold: Decimal = THRESHOLD,
    window: int = LABEL_WINDOW_DAYS,
) -> Optional[dict]:
    """
    Tek bir run_date (D) icin label hesaplar.
    D+1 .. D+window takvim gunlerini inceler.
    Dondurur: label dict veya None (veri yetersiz).
    """
    ref = filled_prices.get(run_date)
    if ref is None:
        return None

    # D+1 .. D+window fiyatlarini topla
    window_prices: list[tuple[date, Optional[Decimal]]] = []
    for i in range(1, window + 1):
        d = run_date + timedelta(days=i)
        price = filled_prices.get(d)
        window_prices.append((d, price))

    # Tum pencere gunlerinde fiyat olmali (FF sonrasi)
    for d, p in window_prices:
        if p is None:
            return None

    # --- daily_diff hesaplama ---
    # daily_diff[i] = pump_price(D+i) - pump_price(D+i-1)
    # i=1: pump_price(D+1) - pump_price(D)
    prev_price = ref
    daily_diffs: list[tuple[int, Decimal]] = []  # (i, diff)
    for i, (d, price) in enumerate(window_prices, start=1):
        diff = price - prev_price
        daily_diffs.append((i, diff))
        prev_price = price

    # --- y_binary ---
    y_binary = 0
    for _, diff in daily_diffs:
        if abs(diff) >= threshold:
            y_binary = 1
            break

    # --- first_event ---
    first_event_direction = 0
    first_event_amount = Decimal("0")
    first_event_type = "none"

    # Adim 1: Gunluk degisimlerde esigi asan ilk gun
    for i, diff in daily_diffs:
        if abs(diff) >= threshold:
            first_event_direction = 1 if diff > 0 else -1
            first_event_amount = diff
            first_event_type = "daily"
            break

    # Adim 2: Gunlukte bulunamadiysa kumulatif kontrol (fallback)
    if first_event_type == "none":
        for i, (d, price) in enumerate(window_prices, start=1):
            cumul_diff = price - ref
            if abs(cumul_diff) >= threshold:
                first_event_direction = 1 if cumul_diff > 0 else -1
                first_event_amount = cumul_diff
                first_event_type = "cumulative"
                y_binary = 1  # kumulatif de bir olay
                break

    # --- net_amount_3d ---
    net_amount_3d = window_prices[-1][1] - ref

    # --- label_window_end ---
    label_window_end = run_date + timedelta(days=window)

    return {
        "run_date": run_date,
        "y_binary": y_binary,
        "first_event_direction": first_event_direction,
        "first_event_amount": first_event_amount,
        "first_event_type": first_event_type,
        "net_amount_3d": net_amount_3d,
        "ref_price": ref,
        "label_window_end": label_window_end,
    }


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------

def compute_labels(
    fuel_type: str,
    start_date: date,
    end_date: date,
    dsn: str = DB_DSN,
    threshold: Decimal = THRESHOLD,
    window: int = LABEL_WINDOW_DAYS,
    max_ff_lookback: int = MAX_FF_LOOKBACK,
) -> pd.DataFrame:
    """
    Belirtilen yakit tipi ve tarih araligi icin label DataFrame'i uretir.

    Her takvim gunu D icin D+1..D+window penceresi incelenir.
    Binary label, first_event ve net_amount_3d hesaplanir.

    Args:
        fuel_type: "benzin", "motorin", "lpg"
        start_date: Label uretiminin baslayacagi tarih (D)
        end_date: Label uretiminin bitecegi tarih (D)
        dsn: PostgreSQL baglanti string'i
        threshold: Esik degeri (Decimal, default 0.25 TL/L)
        window: Label penceresi (takvim gunu, default 3)
        max_ff_lookback: Forward-fill max lookback (takvim gunu)

    Returns:
        DataFrame: run_date, fuel_type, y_binary, first_event_direction,
                   first_event_amount, first_event_type, net_amount_3d,
                   ref_price, label_window_end
    """
    if fuel_type not in VALID_FUEL_TYPES:
        raise ValueError(f"Gecersiz yakit tipi: {fuel_type}. Gecerli: {VALID_FUEL_TYPES}")

    if start_date > end_date:
        raise ValueError(f"start_date ({start_date}) > end_date ({end_date})")

    # DB'den veriyi cek: start_date - max_ff_lookback .. end_date + window
    # FF icin onceki gunlere, pencere icin sonraki gunlere ihtiyacimiz var
    fetch_start = start_date - timedelta(days=max_ff_lookback)
    fetch_end = end_date + timedelta(days=window)

    logger.info(
        "Label uretimi: fuel=%s, range=%s..%s, fetch=%s..%s",
        fuel_type, start_date, end_date, fetch_start, fetch_end,
    )

    raw_prices = _fetch_pump_prices(fuel_type, fetch_start, fetch_end, dsn=dsn)
    logger.info("DB'den %d kayit cekildi", len(raw_prices))

    if not raw_prices:
        logger.warning("Hic pump_price verisi bulunamadi: %s %s..%s", fuel_type, fetch_start, fetch_end)
        return _empty_dataframe(fuel_type)

    filled_prices = _forward_fill_prices(raw_prices, fetch_start, fetch_end, max_lookback=max_ff_lookback)

    # Her gun icin label hesapla
    labels: list[dict] = []
    current = start_date
    while current <= end_date:
        result = _compute_single_label(current, filled_prices, threshold=threshold, window=window)
        if result is not None:
            result["fuel_type"] = fuel_type
            labels.append(result)
        else:
            logger.debug("Label uretilemedi: %s %s (veri yetersiz)", fuel_type, current)
        current += timedelta(days=1)

    if not labels:
        return _empty_dataframe(fuel_type)

    df = pd.DataFrame(labels)
    # Kolon siralamasi
    col_order = [
        "run_date", "fuel_type", "y_binary", "first_event_direction",
        "first_event_amount", "first_event_type", "net_amount_3d",
        "ref_price", "label_window_end",
    ]
    df = df[col_order]

    logger.info(
        "Label uretimi tamamlandi: %d satir, y_binary=1 orani: %.1f%%",
        len(df),
        (df["y_binary"].sum() / len(df) * 100) if len(df) > 0 else 0,
    )

    return df


def _empty_dataframe(fuel_type: str) -> pd.DataFrame:
    """Bos ama dogru kolonlara sahip DataFrame."""
    return pd.DataFrame(columns=[
        "run_date", "fuel_type", "y_binary", "first_event_direction",
        "first_event_amount", "first_event_type", "net_amount_3d",
        "ref_price", "label_window_end",
    ])


# ---------------------------------------------------------------------------
# Tum yakit tipleri icin toplu uretim
# ---------------------------------------------------------------------------

def compute_all_labels(
    start_date: date,
    end_date: date,
    dsn: str = DB_DSN,
    threshold: Decimal = THRESHOLD,
    window: int = LABEL_WINDOW_DAYS,
) -> pd.DataFrame:
    """3 yakit tipi icin label uretip birlestirir."""
    frames = []
    for ft in VALID_FUEL_TYPES:
        df = compute_labels(ft, start_date, end_date, dsn=dsn, threshold=threshold, window=window)
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else _empty_dataframe("benzin")
