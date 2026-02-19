"""
Predictor v5 — Label Üretim Modülü.

pump_price günlük farklarından binary label, first_event ve net_amount_3d hesaplar.
Her takvim günü D için (D HARİÇ) D+1, D+2, D+3 penceresi incelenir.
Sistem 7/7 çalışır — hafta sonu ve tatil dahil forward-fill uygulanır.

Kullanım:
    from src.predictor_v5.labels import compute_labels
    df = compute_labels("benzin", date(2024, 1, 1), date(2026, 2, 1))
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

# --- Sabitler (TASK-045 config.py paralel, hard-code default) ---
LABEL_WINDOW_DAYS: int = 3
THRESHOLD_TL: Decimal = Decimal("0.25")
FORWARD_FILL_MAX_DAYS: int = 15
VALID_FUEL_TYPES: set[str] = {"benzin", "motorin", "lpg"}

# DB bağlantı URL'i — ortam değişkeninden veya default
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL_SYNC",
    "postgresql://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi",
)


# ─────────────────── yardımcı fonksiyonlar ───────────────────


def _safe_decimal(value: Any) -> Decimal | None:
    """float → str → Decimal güvenli dönüşüm. None/NaN → None döner."""
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        if d.is_nan() or d.is_infinite():
            return None
        return d
    except (InvalidOperation, ValueError, TypeError):
        return None


def _get_connection(dsn: str | None = None) -> psycopg2.extensions.connection:
    """Sync psycopg2 bağlantısı döner (Celery uyumlu)."""
    return psycopg2.connect(dsn or DATABASE_URL)


def _fetch_pump_prices(
    fuel_type: str,
    start_date: date,
    end_date: date,
    conn: psycopg2.extensions.connection | None = None,
) -> dict[date, Decimal]:
    """
    DB'den pump_price_tl_lt verilerini çeker.

    Returns:
        {trade_date: Decimal(pump_price)} sözlüğü (yalnızca NULL olmayanlar)
    """
    own_conn = conn is None
    if own_conn:
        conn = _get_connection()

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT trade_date, pump_price_tl_lt
                FROM daily_market_data
                WHERE fuel_type = %s
                  AND trade_date BETWEEN %s AND %s
                  AND pump_price_tl_lt IS NOT NULL
                ORDER BY trade_date
                """,
                (fuel_type, start_date, end_date),
            )
            rows = cur.fetchall()
    finally:
        if own_conn:
            conn.close()

    result: dict[date, Decimal] = {}
    for row in rows:
        price = _safe_decimal(row["pump_price_tl_lt"])
        if price is not None:
            result[row["trade_date"]] = price

    return result


def _forward_fill_prices(
    raw_prices: dict[date, Decimal],
    start_date: date,
    end_date: date,
) -> dict[date, Decimal | None]:
    """
    Her takvim günü için pump_price oluşturur (forward-fill).

    Kurallar:
    - Mevcut fiyat varsa doğrudan kullanılır
    - Yoksa son bilinen fiyat forward-fill edilir (max 15 gün)
    - 15 günden fazla boşlukta None döner
    """
    filled: dict[date, Decimal | None] = {}
    last_known: Decimal | None = None
    last_known_date: date | None = None

    # start_date öncesinde bir fiyat olabilir — raw_prices'tan en yakın geçmiş tarihi bul
    if raw_prices:
        before_start = [d for d in raw_prices if d < start_date]
        if before_start:
            closest = max(before_start)
            last_known = raw_prices[closest]
            last_known_date = closest

    current = start_date
    while current <= end_date:
        if current in raw_prices:
            filled[current] = raw_prices[current]
            last_known = raw_prices[current]
            last_known_date = current
        elif last_known is not None and last_known_date is not None:
            gap_days = (current - last_known_date).days
            if gap_days <= FORWARD_FILL_MAX_DAYS:
                filled[current] = last_known
            else:
                filled[current] = None
        else:
            filled[current] = None
        current += timedelta(days=1)

    return filled


def _compute_single_label(
    run_date: date,
    prices: dict[date, Decimal | None],
    fuel_type: str,
) -> dict[str, Any] | None:
    """
    Tek bir run_date için label hesaplar.

    Args:
        run_date: D günü
        prices: forward-fill uygulanmış fiyat sözlüğü
        fuel_type: yakıt tipi

    Returns:
        Label dict veya None (yeterli veri yoksa)
    """
    # ref = pump_price_asof(D, 18:30) — D günündeki son bilinen fiyat
    ref = prices.get(run_date)
    if ref is None:
        return None

    # D+1, D+2, D+3 fiyatları kontrol et
    window_prices: list[Decimal | None] = []
    for i in range(1, LABEL_WINDOW_DAYS + 1):
        d_plus_i = run_date + timedelta(days=i)
        window_prices.append(prices.get(d_plus_i))

    # Pencere sonunun tarihi
    label_window_end = run_date + timedelta(days=LABEL_WINDOW_DAYS)

    # Yeterli veri kontrolü — en az D+1 fiyatı olmalı
    if window_prices[0] is None:
        return None

    # ── daily_diff hesaplama ──
    # daily_diff[i] = price(D+i) - price(D+i-1), i = 1,2,3
    # price(D+0) = ref
    prev_price = ref
    daily_diffs: list[Decimal | None] = []
    for i in range(LABEL_WINDOW_DAYS):
        current_price = window_prices[i]
        if current_price is not None and prev_price is not None:
            daily_diffs.append(current_price - prev_price)
            prev_price = current_price
        else:
            daily_diffs.append(None)
            if current_price is not None:
                prev_price = current_price

    # ── y_binary: herhangi bir |daily_diff| >= 0.25 ise 1 ──
    y_binary = 0
    for dd in daily_diffs:
        if dd is not None and abs(dd) >= THRESHOLD_TL:
            y_binary = 1
            break

    # ── first_event: önce günlük, sonra kümülatif fallback ──
    first_event_direction = 0
    first_event_amount = Decimal("0")
    first_event_type = "none"

    # 1) Günlük kontrol
    for dd in daily_diffs:
        if dd is not None and abs(dd) >= THRESHOLD_TL:
            first_event_amount = dd
            first_event_direction = 1 if dd > 0 else -1
            first_event_type = "daily"
            break

    # 2) Kümülatif fallback (günlükte bulunamadıysa)
    if first_event_type == "none" and y_binary == 0:
        for i in range(LABEL_WINDOW_DAYS):
            current_price = window_prices[i]
            if current_price is not None:
                cumul = current_price - ref
                if abs(cumul) >= THRESHOLD_TL:
                    first_event_amount = cumul
                    first_event_direction = 1 if cumul > 0 else -1
                    first_event_type = "cumulative"
                    y_binary = 1  # kümülatif de label'ı tetikler
                    break

    # ── net_amount_3d = pump_price(D+3) - ref ──
    d3_price = window_prices[LABEL_WINDOW_DAYS - 1]  # D+3
    if d3_price is not None:
        net_amount_3d = d3_price - ref
    else:
        # D+3 yoksa mevcut son bilinen fiyatı kullan
        net_amount_3d = None
        for i in range(LABEL_WINDOW_DAYS - 1, -1, -1):
            if window_prices[i] is not None:
                net_amount_3d = window_prices[i] - ref
                break
        if net_amount_3d is None:
            net_amount_3d = Decimal("0")

    return {
        "run_date": run_date,
        "fuel_type": fuel_type,
        "y_binary": y_binary,
        "first_event_direction": first_event_direction,
        "first_event_amount": first_event_amount,
        "first_event_type": first_event_type,
        "net_amount_3d": net_amount_3d,
        "ref_price": ref,
        "label_window_end": label_window_end,
    }


# ─────────────────── ana fonksiyon ───────────────────


def compute_labels(
    fuel_type: str,
    start_date: date,
    end_date: date,
    conn: psycopg2.extensions.connection | None = None,
) -> pd.DataFrame:
    """
    Belirtilen yakıt tipi ve tarih aralığı için label DataFrame üretir.

    Args:
        fuel_type: "benzin", "motorin" veya "lpg"
        start_date: Label üretimi başlangıç tarihi (D)
        end_date: Label üretimi bitiş tarihi (D)
        conn: Opsiyonel psycopg2 bağlantısı (test enjeksiyonu için)

    Returns:
        pd.DataFrame — kolonlar: run_date, fuel_type, y_binary,
        first_event_direction, first_event_amount, first_event_type,
        net_amount_3d, ref_price, label_window_end

    Raises:
        ValueError: Geçersiz fuel_type
    """
    if fuel_type not in VALID_FUEL_TYPES:
        raise ValueError(
            f"Geçersiz fuel_type: {fuel_type!r}. "
            f"Geçerli değerler: {VALID_FUEL_TYPES}"
        )

    if start_date > end_date:
        raise ValueError(
            f"start_date ({start_date}) > end_date ({end_date})"
        )

    logger.info(
        "Label üretimi başlıyor: %s [%s → %s]",
        fuel_type, start_date, end_date,
    )

    # DB'den veri çek — label penceresi için end_date + LABEL_WINDOW_DAYS gün fazlası
    # Ayrıca forward-fill için start_date - FORWARD_FILL_MAX_DAYS gün öncesi
    fetch_start = start_date - timedelta(days=FORWARD_FILL_MAX_DAYS)
    fetch_end = end_date + timedelta(days=LABEL_WINDOW_DAYS)

    raw_prices = _fetch_pump_prices(fuel_type, fetch_start, fetch_end, conn=conn)

    if not raw_prices:
        logger.warning("Hiç pump_price verisi bulunamadı: %s [%s → %s]", fuel_type, fetch_start, fetch_end)
        return _empty_dataframe()

    # Forward-fill uygula
    prices = _forward_fill_prices(raw_prices, fetch_start, fetch_end)

    # Her takvim günü için label hesapla
    labels: list[dict[str, Any]] = []
    current = start_date
    while current <= end_date:
        label = _compute_single_label(current, prices, fuel_type)
        if label is not None:
            labels.append(label)
        current += timedelta(days=1)

    if not labels:
        logger.warning("Hiç label üretilemedi: %s [%s → %s]", fuel_type, start_date, end_date)
        return _empty_dataframe()

    df = pd.DataFrame(labels)

    # Tip dönüşümleri
    df["run_date"] = pd.to_datetime(df["run_date"]).dt.date
    df["label_window_end"] = pd.to_datetime(df["label_window_end"]).dt.date
    df["y_binary"] = df["y_binary"].astype(int)
    df["first_event_direction"] = df["first_event_direction"].astype(int)

    logger.info(
        "Label üretimi tamamlandı: %s — %d satır, %d pozitif (%.1f%%)",
        fuel_type,
        len(df),
        df["y_binary"].sum(),
        100 * df["y_binary"].mean() if len(df) > 0 else 0,
    )

    return df


def compute_labels_all_fuels(
    start_date: date,
    end_date: date,
    conn: psycopg2.extensions.connection | None = None,
) -> pd.DataFrame:
    """3 yakıt tipi için label üretir ve birleştirir."""
    frames: list[pd.DataFrame] = []
    for ft in sorted(VALID_FUEL_TYPES):
        df = compute_labels(ft, start_date, end_date, conn=conn)
        if not df.empty:
            frames.append(df)
    if not frames:
        return _empty_dataframe()
    return pd.concat(frames, ignore_index=True)


def _empty_dataframe() -> pd.DataFrame:
    """Boş ama doğru kolonlara sahip DataFrame döner."""
    return pd.DataFrame(
        columns=[
            "run_date",
            "fuel_type",
            "y_binary",
            "first_event_direction",
            "first_event_amount",
            "first_event_type",
            "net_amount_3d",
            "ref_price",
            "label_window_end",
        ]
    )
