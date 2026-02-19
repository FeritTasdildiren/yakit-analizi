"""
Predictor v5/v6 — Feature Hesaplama Pipeline
==========================================
v6: 13 yeni göreceli feature eklendi (toplam 48 feature).
"""

from __future__ import annotations

import logging
import statistics
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, List, Tuple

import pandas as pd
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
try:
    from src.predictor_v5.config import (
        FEATURE_NAMES,
        FF_MAX_LOOKBACK,
        FUEL_TYPES,
    )
except ImportError:
    FF_MAX_LOOKBACK = 15
    FUEL_TYPES = ["benzin", "motorin", "lpg"]
    FEATURE_NAMES = []

DB_DSN = "postgresql://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi"
VALID_FUEL_TYPES = tuple(FUEL_TYPES)

_STALE_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def _safe_decimal(value) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(str(value))


def _to_float(value) -> float:
    if value is None:
        return 0.0
    return float(value)


def _safe_div(a: float, b: float) -> float:
    if b == 0.0:
        return 0.0
    return a / b


# ---------------------------------------------------------------------------
# Trading-Day Serisi Hesaplamaları
# ---------------------------------------------------------------------------

def _compute_trading_day_indicators(
    trading_days: List[Tuple[date, float]],
    target_date: date,
    max_ff_lookback: int = FF_MAX_LOOKBACK,
) -> dict:
    result = {
        "close": 0.0,
        "return_1d": 0.0,
        "sma_5": 0.0,
        "sma_10": 0.0,
        "vol_5d": 0.0,
        "stale": 0.0,
        "days_since": 0,
    }

    if not trading_days:
        result["stale"] = 1.0
        return result

    relevant = [(d, v) for d, v in trading_days if d <= target_date]
    if not relevant:
        result["stale"] = 1.0
        return result

    last_date, last_value = relevant[-1]
    gap_days = (target_date - last_date).days
    result["days_since"] = gap_days

    if gap_days > max_ff_lookback:
        result["stale"] = 1.0
        return result

    result["close"] = last_value

    if len(relevant) >= 2:
        prev_value = relevant[-2][1]
        result["return_1d"] = _safe_div(last_value - prev_value, prev_value)

    if len(relevant) >= 5:
        vals_5 = [v for _, v in relevant[-5:]]
        result["sma_5"] = sum(vals_5) / 5.0
    elif len(relevant) >= 1:
        vals = [v for _, v in relevant]
        result["sma_5"] = sum(vals) / len(vals)

    if len(relevant) >= 10:
        vals_10 = [v for _, v in relevant[-10:]]
        result["sma_10"] = sum(vals_10) / 10.0
    elif len(relevant) >= 1:
        vals = [v for _, v in relevant]
        result["sma_10"] = sum(vals) / len(vals)

    if len(relevant) >= 6:
        returns = []
        for i in range(-5, 0):
            prev_val = relevant[i - 1][1] if (i - 1) >= -len(relevant) else relevant[0][1]
            cur_val = relevant[i][1]
            ret = _safe_div(cur_val - prev_val, prev_val)
            returns.append(ret)
        if len(returns) >= 2:
            result["vol_5d"] = statistics.stdev(returns)
    elif len(relevant) >= 3:
        returns = []
        for i in range(1, len(relevant)):
            prev_val = relevant[i - 1][1]
            cur_val = relevant[i][1]
            ret = _safe_div(cur_val - prev_val, prev_val)
            returns.append(ret)
        if len(returns) >= 2:
            result["vol_5d"] = statistics.stdev(returns)

    return result


# ---------------------------------------------------------------------------
# DB Sorguları
# ---------------------------------------------------------------------------

def _fetch_brent_fx(
    fuel_type: str,
    target_date: date,
    dsn: str = DB_DSN,
    limit: int = 100,
) -> Tuple[List[Tuple[date, float]], List[Tuple[date, float]]]:
    query = """
        SELECT trade_date, brent_usd_bbl, usd_try_rate
        FROM daily_market_data
        WHERE fuel_type = %s
          AND trade_date <= %s
          AND brent_usd_bbl IS NOT NULL
        ORDER BY trade_date DESC
        LIMIT %s
    """
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(query, (fuel_type, target_date, limit))
            rows = cur.fetchall()
    finally:
        conn.close()

    brent_days: List[Tuple[date, float]] = []
    fx_days: List[Tuple[date, float]] = []

    for trade_date, brent, fx in rows:
        brent_val = _to_float(brent)
        fx_val = _to_float(fx)
        brent_days.append((trade_date, brent_val))
        if fx is not None and fx_val > 0:
            fx_days.append((trade_date, fx_val))

    brent_days.sort(key=lambda x: x[0])
    fx_days.sort(key=lambda x: x[0])

    return brent_days, fx_days


def _fetch_mbe(
    fuel_type: str,
    target_date: date,
    dsn: str = DB_DSN,
    limit: int = 30,
) -> List[dict]:
    query = """
        SELECT trade_date, mbe_value, mbe_pct, nc_forward,
               sma_5, sma_10, delta_mbe, delta_mbe_3,
               since_last_change_days
        FROM mbe_calculations
        WHERE fuel_type = %s AND trade_date <= %s
        ORDER BY trade_date DESC
        LIMIT %s
    """
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(query, (fuel_type, target_date, limit))
            rows = cur.fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        result.append({
            "trade_date": row[0],
            "mbe_value": _to_float(row[1]),
            "mbe_pct": _to_float(row[2]),
            "nc_forward": _to_float(row[3]),
            "sma_5": _to_float(row[4]),
            "sma_10": _to_float(row[5]),
            "delta_mbe": _to_float(row[6]),
            "delta_mbe_3": _to_float(row[7]),
            "since_last_change_days": int(row[8]) if row[8] is not None else 0,
        })

    result.sort(key=lambda x: x["trade_date"])
    return result


def _fetch_risk(
    fuel_type: str,
    target_date: date,
    dsn: str = DB_DSN,
) -> Optional[dict]:
    query = """
        SELECT trade_date, composite_score, mbe_component,
               fx_volatility_component, trend_momentum_component
        FROM risk_scores
        WHERE fuel_type = %s AND trade_date <= %s
        ORDER BY trade_date DESC
        LIMIT 1
    """
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(query, (fuel_type, target_date))
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    return {
        "trade_date": row[0],
        "composite_score": _to_float(row[1]),
        "mbe_component": _to_float(row[2]),
        "fx_volatility_component": _to_float(row[3]),
        "trend_momentum_component": _to_float(row[4]),
    }


def _fetch_cost(
    fuel_type: str,
    target_date: date,
    dsn: str = DB_DSN,
) -> Optional[dict]:
    query = """
        SELECT trade_date, cost_gap_tl, cost_gap_pct, otv_component_tl
        FROM cost_base_snapshots
        WHERE fuel_type = %s AND trade_date <= %s
        ORDER BY trade_date DESC
        LIMIT 1
    """
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(query, (fuel_type, target_date))
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    return {
        "trade_date": row[0],
        "cost_gap_tl": _to_float(row[1]),
        "cost_gap_pct": _to_float(row[2]),
        "otv_component_tl": _to_float(row[3]),
    }


def _fetch_cost_history(
    fuel_type: str,
    target_date: date,
    dsn: str = DB_DSN,
    limit: int = 15,
) -> List[dict]:
    """v6: cost_gap geçmişi — expanding days ve ROC hesaplama için."""
    query = """
        SELECT trade_date, cost_gap_tl, cost_gap_pct
        FROM cost_base_snapshots
        WHERE fuel_type = %s AND trade_date <= %s
        ORDER BY trade_date DESC
        LIMIT %s
    """
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(query, (fuel_type, target_date, limit))
            rows = cur.fetchall()
    finally:
        conn.close()

    result = [{"trade_date": r[0], "cost_gap_tl": _to_float(r[1]), "cost_gap_pct": _to_float(r[2])} for r in rows]
    result.sort(key=lambda x: x["trade_date"])
    return result


def _fetch_price_changes(
    fuel_type: str,
    target_date: date,
    dsn: str = DB_DSN,
    limit: int = 10,
) -> List[dict]:
    """v6: Son fiyat değişiklikleri — interval ve last_change hesaplama için."""
    query = """
        SELECT change_date, change_amount
        FROM price_changes
        WHERE fuel_type = %s AND change_date <= %s
        ORDER BY change_date DESC
        LIMIT %s
    """
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(query, (fuel_type, target_date, limit))
            rows = cur.fetchall()
    finally:
        conn.close()

    result = [{"change_date": r[0], "change_amount": _to_float(r[1])} for r in rows]
    result.sort(key=lambda x: x["change_date"])
    return result


def _fetch_pump_price_history(
    fuel_type: str,
    target_date: date,
    dsn: str = DB_DSN,
    limit: int = 30,
) -> List[Tuple[date, float]]:
    query = """
        SELECT trade_date, pump_price_tl_lt
        FROM daily_market_data
        WHERE fuel_type = %s AND trade_date <= %s
          AND pump_price_tl_lt IS NOT NULL
        ORDER BY trade_date DESC
        LIMIT %s
    """
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(query, (fuel_type, target_date, limit))
            rows = cur.fetchall()
    finally:
        conn.close()

    result = [(r[0], _to_float(r[1])) for r in rows]
    result.sort(key=lambda x: x[0])
    return result


# ---------------------------------------------------------------------------
# v6 Yeni Feature Hesaplama Yardımcıları
# ---------------------------------------------------------------------------

def _compute_v6_features(
    target_date: date,
    mbe_records: List[dict],
    cost_history: List[dict],
    price_changes: List[dict],
    brent_trading_days: List[Tuple[date, float]],
    fx_trading_days: List[Tuple[date, float]],
    cost_record: Optional[dict],
) -> dict:
    """v6: 13 yeni göreceli feature hesapla."""
    features = {}
    
    # 1. mbe_cumulative_5d: Son 5 gün kümülatif MBE
    if len(mbe_records) >= 5:
        features["mbe_cumulative_5d"] = sum(r["mbe_value"] for r in mbe_records[-5:])
    elif mbe_records:
        features["mbe_cumulative_5d"] = sum(r["mbe_value"] for r in mbe_records)
    else:
        features["mbe_cumulative_5d"] = 0.0
    
    # 2. mbe_cumulative_10d: Son 10 gün kümülatif MBE
    if len(mbe_records) >= 10:
        features["mbe_cumulative_10d"] = sum(r["mbe_value"] for r in mbe_records[-10:])
    elif mbe_records:
        features["mbe_cumulative_10d"] = sum(r["mbe_value"] for r in mbe_records)
    else:
        features["mbe_cumulative_10d"] = 0.0
    
    # 3. cost_gap_expanding_days: Maliyet farkı kaç gündür artıyor
    expanding_days = 0
    if len(cost_history) >= 2:
        for i in range(len(cost_history) - 1, 0, -1):
            if abs(cost_history[i]["cost_gap_pct"]) > abs(cost_history[i-1]["cost_gap_pct"]):
                expanding_days += 1
            else:
                break
    features["cost_gap_expanding_days"] = float(expanding_days)
    
    # 4. avg_change_interval: Son 5 değişiklik arasındaki ortalama gün
    if len(price_changes) >= 2:
        intervals = []
        recent_changes = price_changes[-5:]  # Son 5 (veya daha az)
        for i in range(1, len(recent_changes)):
            diff_days = (recent_changes[i]["change_date"] - recent_changes[i-1]["change_date"]).days
            intervals.append(diff_days)
        features["avg_change_interval"] = sum(intervals) / len(intervals) if intervals else 0.0
    else:
        features["avg_change_interval"] = 0.0
    
    # 5. last_change_amount: Son fiyat değişikliğinin büyüklüğü (TL)
    if price_changes:
        features["last_change_amount"] = abs(price_changes[-1]["change_amount"])
    else:
        features["last_change_amount"] = 0.0
    
    # 6. last_change_direction: Son değişiklik yönü (+1/-1/0)
    if price_changes:
        amt = price_changes[-1]["change_amount"]
        features["last_change_direction"] = 1.0 if amt > 0 else (-1.0 if amt < 0 else 0.0)
    else:
        features["last_change_direction"] = 0.0
    
    # 7-8-9. Son pompadan beri Brent/FX/cost_base değişimi
    last_change_date = price_changes[-1]["change_date"] if price_changes else None
    
    if last_change_date:
        # Brent change since last pump change
        brent_at_last = [v for d, v in brent_trading_days if d <= last_change_date]
        brent_now = [v for d, v in brent_trading_days if d <= target_date]
        if brent_at_last and brent_now:
            features["brent_change_since_last_pump"] = brent_now[-1] - brent_at_last[-1]
        else:
            features["brent_change_since_last_pump"] = 0.0
        
        # FX change since last pump change
        fx_at_last = [v for d, v in fx_trading_days if d <= last_change_date]
        fx_now = [v for d, v in fx_trading_days if d <= target_date]
        if fx_at_last and fx_now:
            features["fx_change_since_last_pump"] = fx_now[-1] - fx_at_last[-1]
        else:
            features["fx_change_since_last_pump"] = 0.0
        
        # Cost base change since last pump change
        cost_at_last = [r for r in cost_history if r["trade_date"] <= last_change_date]
        cost_now = [r for r in cost_history if r["trade_date"] <= target_date]
        if cost_at_last and cost_now:
            features["cost_base_change_since_last_pump"] = cost_now[-1]["cost_gap_tl"] - cost_at_last[-1]["cost_gap_tl"]
        else:
            features["cost_base_change_since_last_pump"] = 0.0
    else:
        features["brent_change_since_last_pump"] = 0.0
        features["fx_change_since_last_pump"] = 0.0
        features["cost_base_change_since_last_pump"] = 0.0
    
    # 10. mbe_roc_3d: MBE 3 günlük değişim oranı
    if len(mbe_records) >= 4:
        mbe_now = mbe_records[-1]["mbe_value"]
        mbe_3d_ago = mbe_records[-4]["mbe_value"]
        features["mbe_roc_3d"] = _safe_div(mbe_now - mbe_3d_ago, abs(mbe_3d_ago)) if mbe_3d_ago != 0 else 0.0
    else:
        features["mbe_roc_3d"] = 0.0
    
    # 11. cost_gap_roc_3d: Maliyet farkı 3 günlük değişim oranı
    if len(cost_history) >= 4:
        cg_now = cost_history[-1]["cost_gap_pct"]
        cg_3d = cost_history[-4]["cost_gap_pct"]
        features["cost_gap_roc_3d"] = _safe_div(cg_now - cg_3d, abs(cg_3d)) if cg_3d != 0 else 0.0
    else:
        features["cost_gap_roc_3d"] = 0.0
    
    # 12. brent_fx_interaction: Brent * FX (TL ham petrol maliyeti yaklaşımı)
    brent_now_list = [(d, v) for d, v in brent_trading_days if d <= target_date]
    fx_now_list = [(d, v) for d, v in fx_trading_days if d <= target_date]
    if brent_now_list and fx_now_list:
        features["brent_fx_interaction"] = brent_now_list[-1][1] * fx_now_list[-1][1]
    else:
        features["brent_fx_interaction"] = 0.0
    
    # 13. fx_rate_zscore_20d: FX 20 günlük z-score
    fx_relevant = [(d, v) for d, v in fx_trading_days if d <= target_date]
    if len(fx_relevant) >= 20:
        fx_vals_20 = [v for _, v in fx_relevant[-20:]]
        fx_mean = sum(fx_vals_20) / len(fx_vals_20)
        fx_std = statistics.stdev(fx_vals_20) if len(fx_vals_20) >= 2 else 1.0
        features["fx_rate_zscore_20d"] = _safe_div(fx_vals_20[-1] - fx_mean, fx_std)
    elif len(fx_relevant) >= 2:
        fx_vals = [v for _, v in fx_relevant]
        fx_mean = sum(fx_vals) / len(fx_vals)
        fx_std = statistics.stdev(fx_vals) if len(fx_vals) >= 2 else 1.0
        features["fx_rate_zscore_20d"] = _safe_div(fx_vals[-1] - fx_mean, fx_std)
    else:
        features["fx_rate_zscore_20d"] = 0.0
    
    return features


# ---------------------------------------------------------------------------
# Feature Hesaplama (Pure Logic)
# ---------------------------------------------------------------------------

def _compute_features_from_data(
    target_date: date,
    brent_trading_days: List[Tuple[date, float]],
    fx_trading_days: List[Tuple[date, float]],
    mbe_records: List[dict],
    risk_record: Optional[dict],
    cost_record: Optional[dict],
    max_ff_lookback: int = FF_MAX_LOOKBACK,
    # v6 ek veri
    cost_history: Optional[List[dict]] = None,
    price_changes: Optional[List[dict]] = None,
) -> dict:
    """Ham veriden feature hesaplar. v6: 48 feature."""
    features: dict = {}

    # ---- 1. Brent (5 feature) ----
    brent = _compute_trading_day_indicators(brent_trading_days, target_date, max_ff_lookback)
    features["brent_close"] = brent["close"]
    features["brent_return_1d"] = brent["return_1d"]
    features["brent_sma_5"] = brent["sma_5"]
    features["brent_sma_10"] = brent["sma_10"]
    features["brent_vol_5d"] = brent["vol_5d"]

    # ---- 2. FX (5 feature) ----
    fx = _compute_trading_day_indicators(fx_trading_days, target_date, max_ff_lookback)
    features["fx_close"] = fx["close"]
    features["fx_return_1d"] = fx["return_1d"]
    features["fx_sma_5"] = fx["sma_5"]
    features["fx_sma_10"] = fx["sma_10"]
    features["fx_vol_5d"] = fx["vol_5d"]

    # ---- 3. CIF Proxy (2 feature) ----
    cif_proxy = brent["close"] * fx["close"] / 1000.0 if fx["close"] > 0 else 0.0
    features["cif_proxy"] = cif_proxy

    prev_cif = 0.0
    if len(brent_trading_days) >= 2 and len(fx_trading_days) >= 2:
        brent_relevant = [(d, v) for d, v in brent_trading_days if d <= target_date]
        fx_relevant = [(d, v) for d, v in fx_trading_days if d <= target_date]
        if len(brent_relevant) >= 2 and len(fx_relevant) >= 2:
            prev_brent = brent_relevant[-2][1]
            prev_fx = fx_relevant[-2][1]
            prev_cif = prev_brent * prev_fx / 1000.0 if prev_fx > 0 else 0.0
    features["cif_proxy_return_1d"] = _safe_div(cif_proxy - prev_cif, prev_cif) if prev_cif > 0 else 0.0

    # ---- 4. MBE (6 feature) ----
    if mbe_records:
        latest_mbe = mbe_records[-1]
        features["mbe_value"] = latest_mbe["mbe_value"]
        features["mbe_pct"] = latest_mbe["mbe_pct"]
        features["mbe_sma_5"] = latest_mbe["sma_5"]
        features["mbe_sma_10"] = latest_mbe["sma_10"]
        features["delta_mbe"] = latest_mbe["delta_mbe"]
        features["delta_mbe_3d"] = latest_mbe["delta_mbe_3"]
    else:
        for k in ["mbe_value", "mbe_pct", "mbe_sma_5", "mbe_sma_10", "delta_mbe", "delta_mbe_3d"]:
            features[k] = 0.0

    # ---- 5. NC Forward (3 feature) ----
    nc_values = [r["nc_forward"] for r in mbe_records if r["nc_forward"] != 0.0]
    if nc_values:
        features["nc_forward"] = nc_values[-1]
        if len(nc_values) >= 3:
            features["nc_sma_3"] = sum(nc_values[-3:]) / 3.0
        else:
            features["nc_sma_3"] = sum(nc_values) / len(nc_values)
        if len(nc_values) >= 5:
            features["nc_sma_5"] = sum(nc_values[-5:]) / 5.0
        else:
            features["nc_sma_5"] = sum(nc_values) / len(nc_values)
    else:
        features["nc_forward"] = 0.0
        features["nc_sma_3"] = 0.0
        features["nc_sma_5"] = 0.0

    # ---- 6. Risk (4 feature) ----
    if risk_record:
        features["risk_composite"] = risk_record["composite_score"]
        features["risk_mbe_comp"] = risk_record["mbe_component"]
        features["risk_fx_comp"] = risk_record["fx_volatility_component"]
        features["risk_trend_comp"] = risk_record["trend_momentum_component"]
    else:
        for k in ["risk_composite", "risk_mbe_comp", "risk_fx_comp", "risk_trend_comp"]:
            features[k] = 0.0

    # ---- 7. Cost (3 feature) ----
    if cost_record:
        features["cost_gap_tl"] = cost_record["cost_gap_tl"]
        features["cost_gap_pct"] = cost_record["cost_gap_pct"]
        features["otv_component_tl"] = cost_record["otv_component_tl"]
    else:
        for k in ["cost_gap_tl", "cost_gap_pct", "otv_component_tl"]:
            features[k] = 0.0

    # ---- 8. Temporal (3 feature) ----
    if mbe_records:
        features["days_since_last_change"] = float(mbe_records[-1]["since_last_change_days"])
    else:
        features["days_since_last_change"] = 0.0
    features["day_of_week"] = float(target_date.weekday())
    features["is_weekend"] = 1.0 if target_date.weekday() >= 5 else 0.0

    # ---- 9. Staleness (5 feature) ----
    if mbe_records:
        mbe_gap = (target_date - mbe_records[-1]["trade_date"]).days
        features["mbe_stale"] = 1.0 if mbe_gap > _STALE_THRESHOLD else 0.0
    else:
        features["mbe_stale"] = 1.0

    nc_dates = [r["trade_date"] for r in mbe_records if r["nc_forward"] != 0.0]
    if nc_dates:
        nc_gap = (target_date - nc_dates[-1]).days
        features["nc_stale"] = 1.0 if nc_gap > _STALE_THRESHOLD else 0.0
    else:
        features["nc_stale"] = 1.0

    features["brent_stale"] = brent["stale"]
    features["fx_stale"] = fx["stale"]
    features["cif_stale"] = 1.0 if (brent["stale"] > 0 or fx["stale"] > 0) else 0.0

    # ---- 10. v6 YENİ FEATURE'LAR (13 feature) ----
    v6_features = _compute_v6_features(
        target_date=target_date,
        mbe_records=mbe_records,
        cost_history=cost_history or [],
        price_changes=price_changes or [],
        brent_trading_days=brent_trading_days,
        fx_trading_days=fx_trading_days,
        cost_record=cost_record,
    )
    features.update(v6_features)

    # ---- NaN/None → 0.0 garantisi ----
    for key in features:
        val = features[key]
        if val is None or (isinstance(val, float) and (val != val)):
            features[key] = 0.0

    return features


# ---------------------------------------------------------------------------
# Ana Fonksiyonlar — Public API
# ---------------------------------------------------------------------------

def compute_features(
    fuel_type: str,
    target_date: date,
    dsn: str = DB_DSN,
) -> dict:
    """Tek gün için feature hesaplar (v6: 48 feature)."""
    if fuel_type not in VALID_FUEL_TYPES:
        raise ValueError(f"Geçersiz yakıt tipi: {fuel_type}. Geçerli: {VALID_FUEL_TYPES}")

    logger.info("Feature hesaplama: fuel=%s, date=%s", fuel_type, target_date)

    brent_days, fx_days = _fetch_brent_fx(fuel_type, target_date, dsn=dsn)
    mbe_records = _fetch_mbe(fuel_type, target_date, dsn=dsn)
    risk_record = _fetch_risk(fuel_type, target_date, dsn=dsn)
    cost_record = _fetch_cost(fuel_type, target_date, dsn=dsn)
    # v6 ek sorgular
    cost_history = _fetch_cost_history(fuel_type, target_date, dsn=dsn)
    price_changes = _fetch_price_changes(fuel_type, target_date, dsn=dsn)

    features = _compute_features_from_data(
        target_date=target_date,
        brent_trading_days=brent_days,
        fx_trading_days=fx_days,
        mbe_records=mbe_records,
        risk_record=risk_record,
        cost_record=cost_record,
        cost_history=cost_history,
        price_changes=price_changes,
    )

    ordered = {}
    for name in FEATURE_NAMES:
        ordered[name] = features.get(name, 0.0)

    logger.info("Feature hesaplama tamamlandı: %d feature", len(ordered))
    return ordered


def compute_features_bulk(
    fuel_type: str,
    start_date: date,
    end_date: date,
    dsn: str = DB_DSN,
) -> pd.DataFrame:
    """Tarih aralığı için feature DataFrame'i (v6: 48 feature)."""
    if fuel_type not in VALID_FUEL_TYPES:
        raise ValueError(f"Geçersiz yakıt tipi: {fuel_type}. Geçerli: {VALID_FUEL_TYPES}")
    if start_date > end_date:
        raise ValueError(f"start_date ({start_date}) > end_date ({end_date})")

    logger.info("Bulk feature hesaplama: fuel=%s, range=%s..%s", fuel_type, start_date, end_date)

    brent_days, fx_days = _fetch_brent_fx(fuel_type, end_date, dsn=dsn, limit=2000)
    mbe_all = _fetch_mbe(fuel_type, end_date, dsn=dsn, limit=2000)
    # v6: cost history ve price changes toplu çek
    cost_history_all = _fetch_cost_history(fuel_type, end_date, dsn=dsn, limit=2000)
    price_changes_all = _fetch_price_changes(fuel_type, end_date, dsn=dsn, limit=500)

    rows = []
    current = start_date
    while current <= end_date:
        brent_filtered = [(d, v) for d, v in brent_days if d <= current]
        fx_filtered = [(d, v) for d, v in fx_days if d <= current]
        mbe_filtered = [r for r in mbe_all if r["trade_date"] <= current]
        mbe_recent = mbe_filtered[-30:] if len(mbe_filtered) > 30 else mbe_filtered

        # v6: tarih filtreleme
        cost_hist_filtered = [r for r in cost_history_all if r["trade_date"] <= current][-15:]
        price_chg_filtered = [r for r in price_changes_all if r["change_date"] <= current][-10:]

        risk_record = _fetch_risk(fuel_type, current, dsn=dsn)
        cost_record = _fetch_cost(fuel_type, current, dsn=dsn)

        features = _compute_features_from_data(
            target_date=current,
            brent_trading_days=brent_filtered[-100:],
            fx_trading_days=fx_filtered[-100:],
            mbe_records=mbe_recent,
            risk_record=risk_record,
            cost_record=cost_record,
            cost_history=cost_hist_filtered,
            price_changes=price_chg_filtered,
        )

        row = {"trade_date": current, "fuel_type": fuel_type}
        for name in FEATURE_NAMES:
            row[name] = features.get(name, 0.0)
        rows.append(row)

        current += timedelta(days=1)

    if not rows:
        cols = ["trade_date", "fuel_type"] + list(FEATURE_NAMES)
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows)
    col_order = ["trade_date", "fuel_type"] + list(FEATURE_NAMES)
    df = df[col_order]

    logger.info("Bulk feature hesaplama tamamlandı: %d satır × %d feature", len(df), len(FEATURE_NAMES))
    return df


# ---------------------------------------------------------------------------
# price_changed_today
# ---------------------------------------------------------------------------

def get_price_changed_today(
    fuel_type: str,
    target_date: date,
    dsn: str = DB_DSN,
) -> bool:
    if fuel_type not in VALID_FUEL_TYPES:
        raise ValueError(f"Geçersiz yakıt tipi: {fuel_type}. Geçerli: {VALID_FUEL_TYPES}")

    history = _fetch_pump_price_history(fuel_type, target_date, dsn=dsn, limit=5)

    if len(history) < 2:
        return False

    relevant = [(d, v) for d, v in history if d <= target_date]
    if len(relevant) < 2:
        return False

    last_price = relevant[-1][1]
    prev_price = relevant[-2][1]

    return abs(last_price - prev_price) > 0.001
