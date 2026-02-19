#!/usr/bin/env python3
"""
TASK-031: MBE + Risk Backfill + ML Eğitim + E2E Test Pipeline

Bölüm 1: cost_base_snapshots → mbe_calculations → risk_scores → price_changes
Bölüm 2: ML model eğitimi (LightGBM sınıflandırma + regresyon)
Bölüm 3: E2E doğrulama

Yazar: Claude Code (TASK-031)
Tarih: 2026-02-16
"""

import logging
import math
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path

import psycopg2
import psycopg2.extras

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_URL = "postgresql://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi"
FUEL_TYPES = ["benzin", "motorin", "lpg"]
RHO = {"benzin": Decimal("1180"), "motorin": Decimal("1190"), "lpg": Decimal("1750")}
PRECISION = Decimal("0.00000001")
M_TOTAL = Decimal("1.20")

ELECTION_DATES = [date(2023, 5, 14), date(2023, 5, 28), date(2024, 3, 31)]
HOLIDAY_PERIODS = [
    (date(2022, 4, 29), date(2022, 5, 3)), (date(2022, 7, 8), date(2022, 7, 12)),
    (date(2023, 4, 20), date(2023, 4, 24)), (date(2023, 6, 27), date(2023, 7, 1)),
    (date(2024, 4, 9), date(2024, 4, 13)), (date(2024, 6, 16), date(2024, 6, 20)),
    (date(2025, 3, 29), date(2025, 4, 2)), (date(2025, 6, 5), date(2025, 6, 9)),
    (date(2026, 3, 19), date(2026, 3, 23)),
]
OTV_CHANGE_DATES = [
    date(2022, 1, 1), date(2022, 6, 1), date(2023, 1, 1), date(2023, 7, 1),
    date(2024, 1, 1), date(2024, 7, 1), date(2025, 1, 1), date(2025, 7, 1), date(2026, 1, 1),
]


def _safe_decimal(value) -> Decimal:
    if value is None:
        raise ValueError("None")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def get_days_to_election(td: date) -> int:
    future = [e for e in ELECTION_DATES if e > td]
    return (future[0] - td).days if future else 365


def is_holiday(td: date) -> tuple[bool, int]:
    for s, e in HOLIDAY_PERIODS:
        if s <= td <= e:
            return True, 0
    return False, min((min(abs((s - td).days), abs((e - td).days)) for s, e in HOLIDAY_PERIODS), default=365)


def get_otv_change_proximity(td: date) -> int:
    past = [d for d in OTV_CHANGE_DATES if d <= td]
    return (td - past[-1]).days if past else 180


def load_tax_params(conn):
    cur = conn.cursor()
    cur.execute("SELECT id, fuel_type, otv_fixed_tl, kdv_rate, valid_from, valid_to FROM tax_parameters ORDER BY valid_from")
    result = defaultdict(list)
    for r in cur.fetchall():
        result[r[1]].append({"id": r[0], "otv": r[2], "kdv": r[3], "valid_from": r[4], "valid_to": r[5]})
    cur.close()
    return result


def find_tax_param(tax_params, fuel_type, td):
    for p in reversed(tax_params.get(fuel_type, [])):
        if td >= p["valid_from"]:
            if p["valid_to"] is None or td <= p["valid_to"]:
                return p["id"], _safe_decimal(p["otv"]), _safe_decimal(p["kdv"])
    lst = tax_params.get(fuel_type, [])
    if lst:
        p = lst[-1]
        return p["id"], _safe_decimal(p["otv"]), _safe_decimal(p["kdv"])
    return None, Decimal("3.0"), Decimal("0.20")


# ============================================================================
#  BÖLÜM 1
# ============================================================================

def run_backfill():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        tax_params = load_tax_params(conn)
        logger.info("Tax params yüklendi: %d yakıt tipi", len(tax_params))

        cur.execute("""
            SELECT id, trade_date, fuel_type, brent_usd_bbl, usd_try_rate,
                   pump_price_tl_lt, cif_med_usd_ton
            FROM daily_market_data ORDER BY fuel_type, trade_date
        """)
        rows = cur.fetchall()
        logger.info("%d satır okundu", len(rows))

        by_fuel = defaultdict(list)
        for r in rows:
            by_fuel[r[2]].append({
                "id": r[0], "trade_date": r[1], "fuel_type": r[2],
                "brent": r[3], "fx": r[4], "pump": r[5], "cif": r[6],
            })

        # Faz 1: cost_base_snapshots + price_changes + hesaplanan veriler (MBE, risk)
        # cost_batch'i önce yazıp commit → sonra cost_snapshot_id'leri al → mbe yazı

        cost_batch = []
        # İşlenen veri: fuel_type → [(trade_date, nc_forward, mbe_value, mbe_pct, sma_5, sma_10, delta_mbe, delta_mbe_3, trend, regime, days_since, window, fx_hist_recent, mbe_abs, fx_vol, delay_norm, breach_norm, momentum)]
        computed_data = defaultdict(list)
        price_change_batch = []

        for fuel_type in FUEL_TYPES:
            records = by_fuel.get(fuel_type, [])
            if not records:
                continue
            logger.info("=== %s: %d kayıt ===", fuel_type, len(records))
            rho = RHO[fuel_type]

            nc_forward_history = []
            mbe_history = []
            fx_history = []
            last_pump = None
            last_change_nc_base = None
            days_since_last_change = 0

            for rec in records:
                td = rec["trade_date"]
                brent, fx, pump, cif = rec["brent"], rec["fx"], rec["pump"], rec["cif"]
                mid = rec["id"]
                tax_id, otv_fixed, kdv_rate = find_tax_param(tax_params, fuel_type, td)

                # Fiyat değişimi tespiti
                if pump is not None and last_pump is not None:
                    pd_ = _safe_decimal(pump)
                    lpd = _safe_decimal(last_pump)
                    if pd_ != lpd:
                        ca = pd_ - lpd
                        direction = "hike" if ca > 0 else "cut"
                        cp = ((ca / lpd) * Decimal("100")).quantize(PRECISION, rounding=ROUND_HALF_UP) if lpd != 0 else Decimal("0")
                        mac = mbe_history[-1] if mbe_history else Decimal("0")
                        price_change_batch.append((fuel_type, td, direction, float(lpd), float(pd_), float(ca), float(cp), float(mac), "backfill"))
                        if nc_forward_history:
                            w = min(5, len(nc_forward_history))
                            last_change_nc_base = sum(nc_forward_history[-w:]) / Decimal(str(w))
                        days_since_last_change = 0
                if pump is not None:
                    last_pump = pump

                if brent is None or fx is None:
                    days_since_last_change += 1
                    continue

                brent_d = _safe_decimal(brent)
                fx_d = _safe_decimal(fx)
                fx_history.append(float(fx_d))
                cif_d = _safe_decimal(cif) if cif is not None else (brent_d * Decimal("7.33")).quantize(PRECISION, rounding=ROUND_HALF_UP)

                nc_forward = (cif_d * fx_d / rho).quantize(PRECISION, rounding=ROUND_HALF_UP)
                nc_forward_history.append(nc_forward)

                cif_component = nc_forward
                kdv_component = ((cif_component + otv_fixed) * kdv_rate).quantize(PRECISION, rounding=ROUND_HALF_UP)
                theoretical_cost = ((cif_component + otv_fixed) * (Decimal("1") + kdv_rate) + M_TOTAL).quantize(PRECISION, rounding=ROUND_HALF_UP)
                actual_pump = _safe_decimal(pump) if pump is not None else theoretical_cost
                cost_gap = (actual_pump - theoretical_cost).quantize(PRECISION, rounding=ROUND_HALF_UP)
                cost_gap_pct = ((cost_gap / theoretical_cost) * Decimal("100")).quantize(PRECISION, rounding=ROUND_HALF_UP) if theoretical_cost != 0 else Decimal("0")

                implied_cif = None
                if pump is not None and fx_d > 0:
                    nb = ((_safe_decimal(pump) - M_TOTAL) / (Decimal("1") + kdv_rate) - otv_fixed)
                    implied_cif = ((nb * rho) / fx_d).quantize(PRECISION, rounding=ROUND_HALF_UP)

                cost_batch.append((
                    td, fuel_type, mid, tax_id,
                    float(cif_component), float(otv_fixed), float(kdv_component),
                    float(M_TOTAL), float(theoretical_cost), float(actual_pump),
                    float(implied_cif) if implied_cif else None,
                    float(cost_gap), float(cost_gap_pct), "backfill"
                ))

                # MBE hesaplama
                window = 5
                if last_change_nc_base is None:
                    if len(nc_forward_history) >= 5:
                        last_change_nc_base = sum(nc_forward_history[:5]) / Decimal("5")
                    else:
                        last_change_nc_base = nc_forward_history[0]

                recent_nc = nc_forward_history[-window:] if len(nc_forward_history) >= window else nc_forward_history[:]
                sma_w = sum(recent_nc) / Decimal(str(len(recent_nc)))
                mbe_value = (sma_w - last_change_nc_base).quantize(PRECISION, rounding=ROUND_HALF_UP)
                mbe_pct = ((mbe_value / last_change_nc_base) * Decimal("100")).quantize(PRECISION, rounding=ROUND_HALF_UP) if last_change_nc_base != 0 else Decimal("0")
                sma_5 = sma_w
                nc_10 = nc_forward_history[-10:] if len(nc_forward_history) >= 10 else nc_forward_history[:]
                sma_10 = sum(nc_10) / Decimal(str(len(nc_10)))
                delta_mbe = float((mbe_value - mbe_history[-1]).quantize(PRECISION, rounding=ROUND_HALF_UP)) if mbe_history else None
                delta_mbe_3 = float((mbe_value - mbe_history[-3]).quantize(PRECISION, rounding=ROUND_HALF_UP)) if len(mbe_history) >= 3 else None

                trend = "no_change"
                if len(nc_forward_history) >= 3:
                    if nc_forward_history[-1] > nc_forward_history[-3]:
                        trend = "increase"
                    elif nc_forward_history[-1] < nc_forward_history[-3]:
                        trend = "decrease"

                mbe_history.append(mbe_value)
                days_since_last_change += 1

                # Risk hesaplama
                mbe_abs = abs(float(mbe_value))
                mbe_norm = min(1.0, mbe_abs / 5.0)
                fx_vol = 0.0
                if len(fx_history) >= 5:
                    rfx = fx_history[-5:]
                    mfx = sum(rfx) / 5
                    fx_vol = math.sqrt(sum((x - mfx) ** 2 for x in rfx) / 4)
                fx_vol_norm = min(1.0, fx_vol / 2.0)
                delay_norm = min(1.0, days_since_last_change / 60.0)
                breach_norm = min(1.0, mbe_abs / 1.0) if mbe_abs > 0.1 else 0.0
                momentum = 0.5
                if len(mbe_history) >= 3:
                    m1, m3 = float(mbe_history[-1]), float(mbe_history[-3])
                    mr = (m1 - m3) / max(abs(m3), 0.01)
                    momentum = min(1.0, max(0.0, (mr + 1) / 2))
                composite = min(1.0, max(0.0, 0.30*mbe_norm + 0.15*fx_vol_norm + 0.20*delay_norm + 0.20*breach_norm + 0.15*momentum))
                sys_mode = "crisis" if composite >= 0.80 else ("high_alert" if composite >= 0.60 else "normal")

                computed_data[fuel_type].append({
                    "td": td, "nc_forward": float(nc_forward), "nc_base": float(last_change_nc_base),
                    "mbe_value": float(mbe_value), "mbe_pct": float(mbe_pct),
                    "sma_5": float(sma_5), "sma_10": float(sma_10),
                    "delta_mbe": delta_mbe, "delta_mbe_3": delta_mbe_3,
                    "trend": trend, "regime": 0, "days_since": days_since_last_change, "window": window,
                    "composite": round(composite, 4), "mbe_norm": round(mbe_norm, 4),
                    "fx_vol_norm": round(fx_vol_norm, 4), "delay_norm": round(delay_norm, 4),
                    "breach_norm": round(breach_norm, 4), "momentum": round(momentum, 4),
                    "sys_mode": sys_mode,
                })

                if len(cost_batch) % 500 == 0:
                    logger.info("  %s @ %s — cost=%d", fuel_type, td, len(cost_batch))

        # === FAZ 1: cost_base_snapshots yaz ve commit ===
        logger.info("Faz 1: cost_base_snapshots %d kayıt yazılacak", len(cost_batch))
        if cost_batch:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO cost_base_snapshots
                    (trade_date, fuel_type, market_data_id, tax_parameter_id,
                     cif_component_tl, otv_component_tl, kdv_component_tl,
                     margin_component_tl, theoretical_cost_tl, actual_pump_price_tl,
                     implied_cif_usd_ton, cost_gap_tl, cost_gap_pct, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (trade_date, fuel_type) DO UPDATE SET
                    cif_component_tl=EXCLUDED.cif_component_tl, otv_component_tl=EXCLUDED.otv_component_tl,
                    kdv_component_tl=EXCLUDED.kdv_component_tl, margin_component_tl=EXCLUDED.margin_component_tl,
                    theoretical_cost_tl=EXCLUDED.theoretical_cost_tl, actual_pump_price_tl=EXCLUDED.actual_pump_price_tl,
                    implied_cif_usd_ton=EXCLUDED.implied_cif_usd_ton, cost_gap_tl=EXCLUDED.cost_gap_tl,
                    cost_gap_pct=EXCLUDED.cost_gap_pct, source=EXCLUDED.source, updated_at=NOW()
            """, cost_batch, page_size=500)
        conn.commit()
        logger.info("✅ cost_base_snapshots: %d kayıt yazıldı & commit edildi", len(cost_batch))

        # === FAZ 2: cost_snapshot_id'leri al ===
        cur.execute("SELECT id, trade_date, fuel_type FROM cost_base_snapshots")
        cs_id_map = {}
        for r in cur.fetchall():
            cs_id_map[(r[2], r[1])] = r[0]  # (fuel_type, trade_date) → id
        logger.info("Cost snapshot ID'leri yüklendi: %d", len(cs_id_map))

        # === FAZ 3: mbe_calculations yaz ===
        mbe_batch = []
        for fuel_type in FUEL_TYPES:
            for d in computed_data.get(fuel_type, []):
                cs_id = cs_id_map.get((fuel_type, d["td"]))
                if cs_id is None:
                    continue
                mbe_batch.append((
                    d["td"], fuel_type, cs_id,
                    d["nc_forward"], d["nc_base"], d["mbe_value"], d["mbe_pct"],
                    d["sma_5"], d["sma_10"], d["delta_mbe"], d["delta_mbe_3"],
                    d["trend"], d["regime"], d["days_since"], d["window"], "backfill"
                ))

        if mbe_batch:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO mbe_calculations
                    (trade_date, fuel_type, cost_snapshot_id,
                     nc_forward, nc_base, mbe_value, mbe_pct,
                     sma_5, sma_10, delta_mbe, delta_mbe_3,
                     trend_direction, regime, since_last_change_days, sma_window, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (trade_date, fuel_type) DO UPDATE SET
                    cost_snapshot_id=EXCLUDED.cost_snapshot_id, nc_forward=EXCLUDED.nc_forward,
                    nc_base=EXCLUDED.nc_base, mbe_value=EXCLUDED.mbe_value, mbe_pct=EXCLUDED.mbe_pct,
                    sma_5=EXCLUDED.sma_5, sma_10=EXCLUDED.sma_10, delta_mbe=EXCLUDED.delta_mbe,
                    delta_mbe_3=EXCLUDED.delta_mbe_3, trend_direction=EXCLUDED.trend_direction,
                    regime=EXCLUDED.regime, since_last_change_days=EXCLUDED.since_last_change_days,
                    sma_window=EXCLUDED.sma_window, source=EXCLUDED.source, updated_at=NOW()
            """, mbe_batch, page_size=500)
        logger.info("✅ mbe_calculations: %d kayıt", len(mbe_batch))

        # === FAZ 4: risk_scores yaz ===
        risk_batch = []
        wj = '{"mbe": "0.30", "fx_volatility": "0.15", "political_delay": "0.20", "threshold_breach": "0.20", "trend_momentum": "0.15"}'
        for fuel_type in FUEL_TYPES:
            for d in computed_data.get(fuel_type, []):
                risk_batch.append((
                    d["td"], fuel_type,
                    d["composite"], d["mbe_norm"], d["fx_vol_norm"],
                    d["delay_norm"], d["breach_norm"], d["momentum"],
                    wj, d["sys_mode"]
                ))

        if risk_batch:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO risk_scores
                    (trade_date, fuel_type, composite_score, mbe_component,
                     fx_volatility_component, political_delay_component,
                     threshold_breach_component, trend_momentum_component,
                     weight_vector, system_mode)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (trade_date, fuel_type) DO UPDATE SET
                    composite_score=EXCLUDED.composite_score, mbe_component=EXCLUDED.mbe_component,
                    fx_volatility_component=EXCLUDED.fx_volatility_component,
                    political_delay_component=EXCLUDED.political_delay_component,
                    threshold_breach_component=EXCLUDED.threshold_breach_component,
                    trend_momentum_component=EXCLUDED.trend_momentum_component,
                    weight_vector=EXCLUDED.weight_vector, system_mode=EXCLUDED.system_mode, updated_at=NOW()
            """, risk_batch, page_size=500)
        logger.info("✅ risk_scores: %d kayıt", len(risk_batch))

        # === FAZ 5: price_changes yaz ===
        if price_change_batch:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO price_changes
                    (fuel_type, change_date, direction, old_price, new_price,
                     change_amount, change_pct, mbe_at_change, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (fuel_type, change_date) DO UPDATE SET
                    direction=EXCLUDED.direction, old_price=EXCLUDED.old_price,
                    new_price=EXCLUDED.new_price, change_amount=EXCLUDED.change_amount,
                    change_pct=EXCLUDED.change_pct, mbe_at_change=EXCLUDED.mbe_at_change,
                    source=EXCLUDED.source, updated_at=NOW()
            """, price_change_batch, page_size=500)
        logger.info("✅ price_changes: %d kayıt", len(price_change_batch))

        conn.commit()
        logger.info("=" * 60)
        logger.info("BÖLÜM 1 TAMAMLANDI!")
        logger.info("  cost_base_snapshots: %d", len(cost_batch))
        logger.info("  mbe_calculations:    %d", len(mbe_batch))
        logger.info("  risk_scores:         %d", len(risk_batch))
        logger.info("  price_changes:       %d", len(price_change_batch))
        return True
    except Exception as e:
        conn.rollback()
        logger.error("BACKFILL HATASI: %s", e, exc_info=True)
        return False
    finally:
        cur.close()
        conn.close()


# ============================================================================
#  BÖLÜM 2: ML
# ============================================================================

def run_ml_training():
    import numpy as np
    try:
        import lightgbm as lgb
    except ImportError:
        logger.error("LightGBM yüklü değil!")
        return False

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT d.trade_date, d.fuel_type,
                d.brent_usd_bbl, d.usd_try_rate, d.pump_price_tl_lt, d.cif_med_usd_ton,
                m.mbe_value, m.mbe_pct, m.nc_forward, m.nc_base,
                m.sma_5, m.sma_10, m.delta_mbe, m.delta_mbe_3,
                m.trend_direction, m.since_last_change_days, m.regime,
                r.composite_score, r.mbe_component, r.fx_volatility_component,
                r.political_delay_component, r.threshold_breach_component,
                r.trend_momentum_component,
                c.cif_component_tl, c.otv_component_tl, c.kdv_component_tl,
                c.theoretical_cost_tl, c.actual_pump_price_tl,
                c.implied_cif_usd_ton, c.cost_gap_tl, c.cost_gap_pct
            FROM daily_market_data d
            JOIN mbe_calculations m ON d.trade_date=m.trade_date AND d.fuel_type=m.fuel_type
            JOIN risk_scores r ON d.trade_date=r.trade_date AND d.fuel_type=r.fuel_type
            JOIN cost_base_snapshots c ON d.trade_date=c.trade_date AND d.fuel_type=c.fuel_type
            WHERE d.pump_price_tl_lt IS NOT NULL
            ORDER BY d.fuel_type, d.trade_date
        """)
        rows = cur.fetchall()
        logger.info("ML veri: %d satır", len(rows))
        if len(rows) < 100:
            logger.error("Yetersiz: %d", len(rows))
            return False

        cur.execute("SELECT fuel_type, change_date, change_amount FROM price_changes")
        change_map = {(r[0], r[1]): float(r[2]) for r in cur.fetchall()}
        logger.info("Fiyat değişim: %d", len(change_map))

        tax_params = load_tax_params(conn)

        feature_names = [
            "mbe_value", "mbe_pct", "mbe_sma_5", "mbe_sma_10", "delta_mbe", "delta_mbe_3d",
            "nc_forward", "nc_sma_5", "nc_sma_10", "nc_trend_increase", "nc_trend_decrease",
            "brent_usd_bbl", "fx_rate", "fx_volatility_5d", "cif_usd_ton",
            "composite_risk", "risk_mbe", "risk_fx_vol", "risk_delay", "risk_breach", "risk_momentum",
            "days_since_last_hike", "days_to_election", "is_holiday", "holiday_proximity",
            "regime_normal", "regime_election", "otv_change_proximity",
            "otv_rate", "kdv_rate", "margin_total", "cost_base", "implied_cif",
            "cost_gap_tl", "cost_gap_pct", "effective_tax_rate",
        ]

        X_list, y_clf_list, y_reg_list = [], [], []
        fx_hist_map = defaultdict(list)

        def fv(v, d=0.0):
            return float(v) if v is not None else d

        for row in rows:
            td, ft = row[0], row[1]
            brent = fv(row[2]); fx = fv(row[3]); pump = fv(row[4])
            cif = fv(row[5], brent * 7.33)
            mbe_val = fv(row[6]); mbe_pct = fv(row[7]); nc_fwd = fv(row[8])
            sma5 = fv(row[10]); sma10 = fv(row[11])
            dm = fv(row[12]); dm3 = fv(row[13])
            trend_dir = row[14] or "no_change"
            days_since = int(row[15] or 0); regime = int(row[16] or 0)
            cr = fv(row[17]); rm = fv(row[18]); rfx = fv(row[19])
            rd = fv(row[20]); rb = fv(row[21]); rmo = fv(row[22])
            cc = fv(row[23]); oc = fv(row[24])
            ic = fv(row[28]); cg = fv(row[29]); cgp = fv(row[30])

            fx_hist_map[ft].append(fx)
            fxv5 = 0.0
            if len(fx_hist_map[ft]) >= 5:
                r5 = fx_hist_map[ft][-5:]
                m5 = sum(r5)/5
                fxv5 = math.sqrt(sum((x-m5)**2 for x in r5)/4)

            dte = get_days_to_election(td)
            ih, hp = is_holiday(td)
            ocp = get_otv_change_proximity(td)
            _, otv_f, kdv_r = find_tax_param(tax_params, ft, td)

            etx = 0.0
            if pump > 0:
                etx = (float(otv_f) + (cc + float(otv_f)) * float(kdv_r)) / pump

            features = [
                mbe_val, mbe_pct, sma5, sma10, dm, dm3,
                nc_fwd, sma5, sma10,
                1.0 if trend_dir=="increase" else 0.0, 1.0 if trend_dir=="decrease" else 0.0,
                brent, fx, fxv5, cif,
                cr, rm, rfx, rd, rb, rmo,
                float(days_since), float(dte),
                1.0 if ih else 0.0, float(hp),
                1.0 if regime==0 else 0.0, 1.0 if regime==1 else 0.0,
                float(ocp),
                float(otv_f), float(kdv_r), 1.20,
                cc, ic, cg, cgp, etx,
            ]

            label_amt = 0.0
            for dd in range(1, 8):
                k = (ft, td + timedelta(days=dd))
                if k in change_map:
                    label_amt = change_map[k]
                    break
            
            y_clf = 2 if label_amt > 0.25 else (0 if label_amt < -0.25 else 1)
            X_list.append(features)
            y_clf_list.append(y_clf)
            y_reg_list.append(label_amt)

        X = np.array(X_list, dtype=np.float64)
        y_clf = np.array(y_clf_list, dtype=np.int32)
        y_reg = np.array(y_reg_list, dtype=np.float64)

        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        logger.info("X: %s, hike=%d, stable=%d, cut=%d",
                     X.shape, (y_clf==2).sum(), (y_clf==1).sum(), (y_clf==0).sum())

        from src.ml.trainer import train_models
        model_dir = Path("/var/www/yakit_analiz/models")
        model_dir.mkdir(parents=True, exist_ok=True)

        result = train_models(X=X, y_clf=y_clf, y_reg=y_reg,
                              feature_names=feature_names, model_dir=model_dir, version=1)

        logger.info("=" * 60)
        logger.info("ML SONUÇ: %s — %s", result.status, result.message)
        if result.status == "success":
            logger.info("  CLF: %s", result.clf_metrics)
            logger.info("  REG: %s", result.reg_metrics)
            logger.info("  Dosyalar: %s, %s", result.clf_path, result.reg_path)
        return result.status == "success"
    except Exception as e:
        logger.error("ML HATA: %s", e, exc_info=True)
        return False
    finally:
        cur.close()
        conn.close()


# ============================================================================
#  BÖLÜM 3: E2E
# ============================================================================

def run_e2e_checks():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
        logger.info("=" * 60)
        logger.info("E2E DOĞRULAMA")
        for tbl in ["daily_market_data", "cost_base_snapshots", "mbe_calculations",
                     "risk_scores", "price_changes", "ml_predictions", "tax_parameters"]:
            cur.execute(f"SELECT count(*) FROM {tbl}")
            v = cur.fetchone()[0]
            logger.info("  %s %s: %d", "✅" if v > 0 else "⚠️", tbl, v)

        for tbl in ["cost_base_snapshots", "mbe_calculations", "risk_scores"]:
            cur.execute(f"SELECT fuel_type, count(*) FROM {tbl} GROUP BY fuel_type ORDER BY fuel_type")
            logger.info("  %s dağılım: %s", tbl, {r[0]: r[1] for r in cur.fetchall()})

        cur.execute("SELECT fuel_type, direction, count(*) FROM price_changes GROUP BY fuel_type, direction ORDER BY fuel_type, direction")
        logger.info("  Fiyat değişimleri: %s", [(r[0], r[1], r[2]) for r in cur.fetchall()])

        cur.execute("SELECT fuel_type, round(min(mbe_value)::numeric,4), round(avg(mbe_value)::numeric,4), round(max(mbe_value)::numeric,4) FROM mbe_calculations GROUP BY fuel_type ORDER BY fuel_type")
        logger.info("  MBE stats: %s", [(r[0], f"min={r[1]} avg={r[2]} max={r[3]}") for r in cur.fetchall()])

        cur.execute("SELECT fuel_type, round(min(composite_score)::numeric,4), round(avg(composite_score)::numeric,4), round(max(composite_score)::numeric,4) FROM risk_scores GROUP BY fuel_type ORDER BY fuel_type")
        logger.info("  Risk stats: %s", [(r[0], f"min={r[1]} avg={r[2]} max={r[3]}") for r in cur.fetchall()])

        model_dir = Path("/var/www/yakit_analiz/models")
        if model_dir.exists():
            for f in sorted(model_dir.glob("*.joblib")):
                logger.info("  ✅ Model: %s (%.1f KB)", f.name, f.stat().st_size/1024)
        return True
    except Exception as e:
        logger.error("E2E HATA: %s", e, exc_info=True)
        return False
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    logger.info("🚀 TASK-031 Pipeline")
    
    ok1 = run_backfill()
    if not ok1:
        logger.error("❌ Bölüm 1 FAIL")
        sys.exit(1)

    ok2 = run_ml_training()
    if not ok2:
        logger.warning("⚠️ Bölüm 2 FAIL, devam")

    ok3 = run_e2e_checks()

    logger.info("SONUÇ: B1=%s B2=%s B3=%s",
                "✅" if ok1 else "❌", "✅" if ok2 else "❌", "✅" if ok3 else "❌")
    sys.exit(0 if (ok1 and ok3) else 1)
