#!/usr/bin/env python3
"""
TASK-031 Phase 2: MBE + Risk + Price Changes yazımı.
cost_base_snapshots zaten 3108 kayıt yazılmış durumda.
Bu script kalan tabloları yazar + ML eğitimi + E2E doğrulama.
"""

import logging
import math
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
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


def _sd(v):
    if v is None: raise ValueError("None")
    return Decimal(str(v)) if not isinstance(v, Decimal) else v

def dte(td):
    f = [e for e in ELECTION_DATES if e > td]
    return (f[0] - td).days if f else 365

def ihol(td):
    for s, e in HOLIDAY_PERIODS:
        if s <= td <= e: return True, 0
    return False, min((min(abs((s-td).days), abs((e-td).days)) for s, e in HOLIDAY_PERIODS), default=365)

def otv_prox(td):
    p = [d for d in OTV_CHANGE_DATES if d <= td]
    return (td - p[-1]).days if p else 180

def load_tax(conn):
    c = conn.cursor()
    c.execute("SELECT id, fuel_type, otv_fixed_tl, kdv_rate, valid_from, valid_to FROM tax_parameters ORDER BY valid_from")
    r = defaultdict(list)
    for row in c.fetchall():
        r[row[1]].append({"id": row[0], "otv": row[2], "kdv": row[3], "vf": row[4], "vt": row[5]})
    c.close()
    return r

def find_tax(tp, ft, td):
    for p in reversed(tp.get(ft, [])):
        if td >= p["vf"] and (p["vt"] is None or td <= p["vt"]):
            return p["id"], _sd(p["otv"]), _sd(p["kdv"])
    lst = tp.get(ft, [])
    if lst: return lst[-1]["id"], _sd(lst[-1]["otv"]), _sd(lst[-1]["kdv"])
    return None, Decimal("3"), Decimal("0.20")


def run_phase2():
    """MBE + Risk + Price Changes hesapla ve yaz."""
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        tax_params = load_tax(conn)
        
        # cost_snapshot_id haritası
        cur.execute("SELECT id, trade_date, fuel_type FROM cost_base_snapshots")
        cs_map = {(r[2], r[1]): r[0] for r in cur.fetchall()}
        logger.info("Cost snapshot ID: %d", len(cs_map))

        # Tüm market data
        cur.execute("""
            SELECT id, trade_date, fuel_type, brent_usd_bbl, usd_try_rate,
                   pump_price_tl_lt, cif_med_usd_ton
            FROM daily_market_data ORDER BY fuel_type, trade_date
        """)
        by_fuel = defaultdict(list)
        for r in cur.fetchall():
            by_fuel[r[2]].append({
                "id": r[0], "td": r[1], "ft": r[2],
                "brent": r[3], "fx": r[4], "pump": r[5], "cif": r[6],
            })

        mbe_batch = []
        risk_batch = []
        pc_batch = []
        wj = '{"mbe": "0.30", "fx_volatility": "0.15", "political_delay": "0.20", "threshold_breach": "0.20", "trend_momentum": "0.15"}'

        for ft in FUEL_TYPES:
            recs = by_fuel.get(ft, [])
            if not recs: continue
            logger.info("=== %s: %d kayıt ===", ft, len(recs))
            rho = RHO[ft]

            nc_hist = []
            mbe_hist = []
            fx_hist = []
            last_pump = None
            last_change_nc_base = None
            dslc = 0  # days since last change

            for rec in recs:
                td = rec["td"]
                brent, fx, pump, cif = rec["brent"], rec["fx"], rec["pump"], rec["cif"]

                # Fiyat değişimi — enum: "increase" / "decrease"
                if pump is not None and last_pump is not None:
                    pd_ = _sd(pump)
                    lpd = _sd(last_pump)
                    if pd_ != lpd:
                        ca = pd_ - lpd
                        # direction enum: increase veya decrease (NOT hike/cut)
                        direction = "increase" if ca > 0 else "decrease"
                        cp = ((ca / lpd) * Decimal("100")).quantize(PRECISION, rounding=ROUND_HALF_UP) if lpd != 0 else Decimal("0")
                        mac = mbe_hist[-1] if mbe_hist else Decimal("0")
                        pc_batch.append((ft, td, direction, float(lpd), float(pd_), float(ca), float(cp), float(mac), "backfill"))
                        if nc_hist:
                            w = min(5, len(nc_hist))
                            last_change_nc_base = sum(nc_hist[-w:]) / Decimal(str(w))
                        dslc = 0
                if pump is not None:
                    last_pump = pump

                if brent is None or fx is None:
                    dslc += 1
                    continue

                brent_d = _sd(brent)
                fx_d = _sd(fx)
                fx_hist.append(float(fx_d))
                cif_d = _sd(cif) if cif is not None else (brent_d * Decimal("7.33")).quantize(PRECISION, rounding=ROUND_HALF_UP)

                nc_fwd = (cif_d * fx_d / rho).quantize(PRECISION, rounding=ROUND_HALF_UP)
                nc_hist.append(nc_fwd)

                # MBE
                window = 5
                if last_change_nc_base is None:
                    last_change_nc_base = sum(nc_hist[:min(5, len(nc_hist))]) / Decimal(str(min(5, len(nc_hist))))

                rnc = nc_hist[-window:] if len(nc_hist) >= window else nc_hist[:]
                sma_w = sum(rnc) / Decimal(str(len(rnc)))
                mbe_val = (sma_w - last_change_nc_base).quantize(PRECISION, rounding=ROUND_HALF_UP)
                mbe_pct = ((mbe_val / last_change_nc_base) * Decimal("100")).quantize(PRECISION, rounding=ROUND_HALF_UP) if last_change_nc_base != 0 else Decimal("0")
                sma5 = sma_w
                nc10 = nc_hist[-10:] if len(nc_hist) >= 10 else nc_hist[:]
                sma10 = sum(nc10) / Decimal(str(len(nc10)))
                dm = float((mbe_val - mbe_hist[-1]).quantize(PRECISION, rounding=ROUND_HALF_UP)) if mbe_hist else None
                dm3 = float((mbe_val - mbe_hist[-3]).quantize(PRECISION, rounding=ROUND_HALF_UP)) if len(mbe_hist) >= 3 else None

                trend = "no_change"
                if len(nc_hist) >= 3:
                    if nc_hist[-1] > nc_hist[-3]: trend = "increase"
                    elif nc_hist[-1] < nc_hist[-3]: trend = "decrease"

                mbe_hist.append(mbe_val)
                dslc += 1

                cs_id = cs_map.get((ft, td))
                if cs_id is None:
                    continue

                mbe_batch.append((
                    td, ft, cs_id, float(nc_fwd), float(last_change_nc_base),
                    float(mbe_val), float(mbe_pct), float(sma5), float(sma10),
                    dm, dm3, trend, 0, dslc, window, "backfill"
                ))

                # Risk
                ma = abs(float(mbe_val))
                mn = min(1.0, ma / 5.0)
                fxv = 0.0
                if len(fx_hist) >= 5:
                    r5 = fx_hist[-5:]
                    m5 = sum(r5)/5
                    fxv = math.sqrt(sum((x-m5)**2 for x in r5)/4)
                fvn = min(1.0, fxv / 2.0)
                dn = min(1.0, dslc / 60.0)
                bn = min(1.0, ma / 1.0) if ma > 0.1 else 0.0
                mom = 0.5
                if len(mbe_hist) >= 3:
                    m1, m3 = float(mbe_hist[-1]), float(mbe_hist[-3])
                    mr = (m1 - m3) / max(abs(m3), 0.01)
                    mom = min(1.0, max(0.0, (mr + 1) / 2))
                comp = min(1.0, max(0.0, 0.30*mn + 0.15*fvn + 0.20*dn + 0.20*bn + 0.15*mom))
                sm = "crisis" if comp >= 0.80 else ("high_alert" if comp >= 0.60 else "normal")

                risk_batch.append((td, ft, round(comp, 4), round(mn, 4), round(fvn, 4),
                                   round(dn, 4), round(bn, 4), round(mom, 4), wj, sm))

                if len(mbe_batch) % 500 == 0:
                    logger.info("  %s @ %s — mbe=%d risk=%d", ft, td, len(mbe_batch), len(risk_batch))

        # MBE yazımı
        logger.info("MBE: %d kayıt yazılacak", len(mbe_batch))
        if mbe_batch:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO mbe_calculations
                    (trade_date, fuel_type, cost_snapshot_id, nc_forward, nc_base,
                     mbe_value, mbe_pct, sma_5, sma_10, delta_mbe, delta_mbe_3,
                     trend_direction, regime, since_last_change_days, sma_window, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (trade_date, fuel_type) DO UPDATE SET
                    cost_snapshot_id=EXCLUDED.cost_snapshot_id, nc_forward=EXCLUDED.nc_forward,
                    nc_base=EXCLUDED.nc_base, mbe_value=EXCLUDED.mbe_value, mbe_pct=EXCLUDED.mbe_pct,
                    sma_5=EXCLUDED.sma_5, sma_10=EXCLUDED.sma_10, delta_mbe=EXCLUDED.delta_mbe,
                    delta_mbe_3=EXCLUDED.delta_mbe_3, trend_direction=EXCLUDED.trend_direction,
                    regime=EXCLUDED.regime, since_last_change_days=EXCLUDED.since_last_change_days,
                    sma_window=EXCLUDED.sma_window, source=EXCLUDED.source, updated_at=NOW()
            """, mbe_batch, page_size=500)
        conn.commit()
        logger.info("✅ mbe_calculations: %d", len(mbe_batch))

        # Risk yazımı
        if risk_batch:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO risk_scores
                    (trade_date, fuel_type, composite_score, mbe_component,
                     fx_volatility_component, political_delay_component,
                     threshold_breach_component, trend_momentum_component,
                     weight_vector, system_mode)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                ON CONFLICT (trade_date, fuel_type) DO UPDATE SET
                    composite_score=EXCLUDED.composite_score, mbe_component=EXCLUDED.mbe_component,
                    fx_volatility_component=EXCLUDED.fx_volatility_component,
                    political_delay_component=EXCLUDED.political_delay_component,
                    threshold_breach_component=EXCLUDED.threshold_breach_component,
                    trend_momentum_component=EXCLUDED.trend_momentum_component,
                    weight_vector=EXCLUDED.weight_vector, system_mode=EXCLUDED.system_mode, updated_at=NOW()
            """, risk_batch, page_size=500)
        conn.commit()
        logger.info("✅ risk_scores: %d", len(risk_batch))

        # Price changes
        if pc_batch:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO price_changes
                    (fuel_type, change_date, direction, old_price, new_price,
                     change_amount, change_pct, mbe_at_change, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (fuel_type, change_date) DO UPDATE SET
                    direction=EXCLUDED.direction, old_price=EXCLUDED.old_price,
                    new_price=EXCLUDED.new_price, change_amount=EXCLUDED.change_amount,
                    change_pct=EXCLUDED.change_pct, mbe_at_change=EXCLUDED.mbe_at_change,
                    source=EXCLUDED.source, updated_at=NOW()
            """, pc_batch, page_size=500)
        conn.commit()
        logger.info("✅ price_changes: %d", len(pc_batch))

        logger.info("=" * 60)
        logger.info("BÖLÜM 1 TAMAMLANDI!")
        return True
    except Exception as e:
        conn.rollback()
        logger.error("HATA: %s", e, exc_info=True)
        return False
    finally:
        cur.close()
        conn.close()


# ============================================================================
#  BÖLÜM 2: ML Eğitim
# ============================================================================

def run_ml():
    import numpy as np
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
                c.cif_component_tl, c.otv_component_tl,
                c.implied_cif_usd_ton, c.cost_gap_tl, c.cost_gap_pct
            FROM daily_market_data d
            JOIN mbe_calculations m ON d.trade_date=m.trade_date AND d.fuel_type=m.fuel_type
            JOIN risk_scores r ON d.trade_date=r.trade_date AND d.fuel_type=r.fuel_type
            JOIN cost_base_snapshots c ON d.trade_date=c.trade_date AND d.fuel_type=c.fuel_type
            WHERE d.pump_price_tl_lt IS NOT NULL
            ORDER BY d.fuel_type, d.trade_date
        """)
        rows = cur.fetchall()
        logger.info("ML veri: %d", len(rows))
        if len(rows) < 100:
            logger.error("Yetersiz: %d", len(rows))
            return False

        cur.execute("SELECT fuel_type, change_date, change_amount FROM price_changes")
        cm = {(r[0], r[1]): float(r[2]) for r in cur.fetchall()}
        logger.info("Değişim: %d", len(cm))

        tax_params = load_tax(conn)

        fn = [
            "mbe_value", "mbe_pct", "mbe_sma_5", "mbe_sma_10", "delta_mbe", "delta_mbe_3d",
            "nc_forward", "nc_sma_5", "nc_sma_10", "nc_trend_inc", "nc_trend_dec",
            "brent", "fx", "fx_vol_5d", "cif",
            "comp_risk", "risk_mbe", "risk_fx", "risk_delay", "risk_breach", "risk_mom",
            "days_since", "days_to_elec", "is_hol", "hol_prox",
            "regime_normal", "regime_elec", "otv_prox",
            "otv_rate", "kdv_rate", "margin", "cost_base", "implied_cif",
            "cost_gap", "cost_gap_pct", "eff_tax",
        ]

        X, yc, yr = [], [], []
        fxhm = defaultdict(list)

        def fv(v, d=0.0): return float(v) if v is not None else d

        for row in rows:
            td, ft = row[0], row[1]
            b = fv(row[2]); f = fv(row[3]); p = fv(row[4]); ci = fv(row[5], b*7.33)
            mv = fv(row[6]); mp = fv(row[7]); nf = fv(row[8])
            s5 = fv(row[10]); s10 = fv(row[11]); dm = fv(row[12]); dm3 = fv(row[13])
            tr = row[14] or "no_change"
            ds = int(row[15] or 0); rg = int(row[16] or 0)
            cr = fv(row[17]); rm = fv(row[18]); rf = fv(row[19])
            rd = fv(row[20]); rb = fv(row[21]); rmo = fv(row[22])
            cc = fv(row[23]); oc = fv(row[24])
            ic = fv(row[25]); cg = fv(row[26]); cgp = fv(row[27])

            fxhm[ft].append(f)
            fv5 = 0.0
            if len(fxhm[ft]) >= 5:
                r5 = fxhm[ft][-5:]
                m5 = sum(r5)/5
                fv5 = math.sqrt(sum((x-m5)**2 for x in r5)/4)

            d2e = dte(td); ih, hp = ihol(td); op = otv_prox(td)
            _, of, kr = find_tax(tax_params, ft, td)
            et = (float(of) + (cc + float(of)) * float(kr)) / p if p > 0 else 0.0

            feat = [
                mv, mp, s5, s10, dm, dm3,
                nf, s5, s10,
                1.0 if tr=="increase" else 0.0, 1.0 if tr=="decrease" else 0.0,
                b, f, fv5, ci,
                cr, rm, rf, rd, rb, rmo,
                float(ds), float(d2e), 1.0 if ih else 0.0, float(hp),
                1.0 if rg==0 else 0.0, 1.0 if rg==1 else 0.0, float(op),
                float(of), float(kr), 1.20, cc, ic, cg, cgp, et,
            ]

            la = 0.0
            for dd in range(1, 8):
                k = (ft, td + timedelta(days=dd))
                if k in cm: la = cm[k]; break
            
            X.append(feat)
            yc.append(2 if la > 0.25 else (0 if la < -0.25 else 1))
            yr.append(la)

        X = np.nan_to_num(np.array(X, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
        yc = np.array(yc, dtype=np.int32)
        yr = np.array(yr, dtype=np.float64)

        logger.info("X=%s hike=%d stable=%d cut=%d", X.shape, (yc==2).sum(), (yc==1).sum(), (yc==0).sum())

        from src.ml.trainer import train_models
        md = Path("/var/www/yakit_analiz/models")
        md.mkdir(parents=True, exist_ok=True)

        res = train_models(X=X, y_clf=yc, y_reg=yr, feature_names=fn, model_dir=md, version=1)
        logger.info("ML: %s — %s", res.status, res.message)
        if res.status == "success":
            logger.info("  CLF: %s", res.clf_metrics)
            logger.info("  REG: %s", res.reg_metrics)
        return res.status == "success"
    except Exception as e:
        logger.error("ML HATA: %s", e, exc_info=True)
        return False
    finally:
        cur.close()
        conn.close()


# ============================================================================
#  BÖLÜM 3: E2E
# ============================================================================

def run_e2e():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
        logger.info("=" * 60)
        logger.info("E2E DOĞRULAMA")
        for t in ["daily_market_data", "cost_base_snapshots", "mbe_calculations",
                   "risk_scores", "price_changes", "ml_predictions", "tax_parameters"]:
            cur.execute(f"SELECT count(*) FROM {t}")
            v = cur.fetchone()[0]
            logger.info("  %s %s: %d", "✅" if v > 0 else "⚠️", t, v)

        for t in ["cost_base_snapshots", "mbe_calculations", "risk_scores"]:
            cur.execute(f"SELECT fuel_type, count(*) FROM {t} GROUP BY fuel_type ORDER BY fuel_type")
            logger.info("  %s: %s", t, dict(cur.fetchall()))

        cur.execute("SELECT fuel_type, direction, count(*) FROM price_changes GROUP BY fuel_type, direction ORDER BY 1,2")
        logger.info("  Price changes: %s", [(r[0], r[1], r[2]) for r in cur.fetchall()])

        cur.execute("SELECT fuel_type, round(min(mbe_value)::numeric,4), round(avg(mbe_value)::numeric,4), round(max(mbe_value)::numeric,4) FROM mbe_calculations GROUP BY fuel_type ORDER BY 1")
        logger.info("  MBE: %s", [(r[0], f"min={r[1]} avg={r[2]} max={r[3]}") for r in cur.fetchall()])

        cur.execute("SELECT fuel_type, round(min(composite_score)::numeric,4), round(avg(composite_score)::numeric,4), round(max(composite_score)::numeric,4) FROM risk_scores GROUP BY fuel_type ORDER BY 1")
        logger.info("  Risk: %s", [(r[0], f"min={r[1]} avg={r[2]} max={r[3]}") for r in cur.fetchall()])

        md = Path("/var/www/yakit_analiz/models")
        if md.exists():
            for f in sorted(md.glob("*.joblib")):
                logger.info("  ✅ %s (%.1f KB)", f.name, f.stat().st_size/1024)
        return True
    except Exception as e:
        logger.error("E2E HATA: %s", e, exc_info=True)
        return False
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    logger.info("🚀 TASK-031 Phase 2")

    ok1 = run_phase2()
    if not ok1:
        logger.error("❌ Phase 2 FAIL")
        sys.exit(1)

    ok2 = run_ml()
    ok3 = run_e2e()

    logger.info("SONUÇ: B1=%s B2=%s B3=%s",
                "✅" if ok1 else "❌", "✅" if ok2 else "❌", "✅" if ok3 else "❌")
    sys.exit(0 if ok1 else 1)
