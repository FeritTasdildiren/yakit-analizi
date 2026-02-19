#!/usr/bin/env python3
"""
TASK-065: MBE + Risk + cost_base Tüm Dönem Yeniden Hesapla

PO İstanbul/Avcılar pompa fiyatları ve güncellenmiş Brent+FX verileriyle
cost_base_snapshots, mbe_calculations, risk_scores tablolarını sıfırdan yeniden hesaplar.

Sıra: TRUNCATE → cost_base_snapshots → mbe_calculations → risk_scores
price_changes DOKUNULMAZ (TASK-064'te zaten PO verisiyle yeniden oluşturuldu).

Tarih: 2026-02-19
"""

import logging
import math
import os
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

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


def _sd(v):
    """Safe Decimal conversion: float→str→Decimal"""
    if v is None:
        raise ValueError("None")
    return Decimal(str(v)) if not isinstance(v, Decimal) else v


def load_tax_params(conn):
    cur = conn.cursor()
    cur.execute("SELECT id, fuel_type, otv_fixed_tl, kdv_rate, valid_from, valid_to FROM tax_parameters ORDER BY valid_from")
    result = defaultdict(list)
    for r in cur.fetchall():
        result[r[1]].append({"id": r[0], "otv": r[2], "kdv": r[3], "valid_from": r[4], "valid_to": r[5]})
    cur.close()
    return result


def find_tax(tp, ft, td):
    for p in reversed(tp.get(ft, [])):
        if td >= p["valid_from"]:
            if p["valid_to"] is None or td <= p["valid_to"]:
                return p["id"], _sd(p["otv"]), _sd(p["kdv"])
    lst = tp.get(ft, [])
    if lst:
        return lst[0]["id"], _sd(lst[0]["otv"]), _sd(lst[0]["kdv"])
    return None, Decimal("3"), Decimal("0.20")


def load_price_changes(conn):
    """price_changes tablosundan fiyat değişim tarihlerini yükle."""
    cur = conn.cursor()
    cur.execute("SELECT fuel_type, change_date, new_price FROM price_changes ORDER BY fuel_type, change_date")
    result = defaultdict(list)
    for r in cur.fetchall():
        result[r[0]].append({"date": r[1], "price": r[2]})
    cur.close()
    return result


def run_rebuild():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # === ADIM 0: TRUNCATE ===
        logger.info("=" * 60)
        logger.info("ADIM 0: Mevcut türetilmiş tabloları temizle")
        # FK bağımlılığı: mbe_calculations.cost_snapshot_id → cost_base_snapshots.id
        # Sıra: risk_scores → mbe_calculations → cost_base_snapshots
        cur.execute("TRUNCATE risk_scores CASCADE")
        cur.execute("TRUNCATE mbe_calculations CASCADE")
        cur.execute("TRUNCATE cost_base_snapshots CASCADE")
        conn.commit()
        logger.info("✅ risk_scores, mbe_calculations, cost_base_snapshots TRUNCATE edildi")

        # === ADIM 1: Veri yükle ===
        tax_params = load_tax_params(conn)
        logger.info("Tax params: %d yakıt tipi, toplam %d kayıt",
                     len(tax_params), sum(len(v) for v in tax_params.values()))

        # price_changes tablosundan değişim tarihlerini al
        price_changes = load_price_changes(conn)
        logger.info("Price changes: %s", {ft: len(v) for ft, v in price_changes.items()})

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

        cost_batch = []
        mbe_data = defaultdict(list)  # fuel_type → [{td, nc_forward, mbe vals, risk vals}]

        for ft in FUEL_TYPES:
            recs = by_fuel.get(ft, [])
            if not recs:
                continue
            logger.info("=== %s: %d kayıt ===", ft, len(recs))
            rho = RHO[ft]

            # price_changes'dan bu yakıtın değişim tarihlerini al
            pc_dates = set(pc["date"] for pc in price_changes.get(ft, []))

            nc_hist = []
            mbe_hist = []
            fx_hist = []
            last_change_nc_base = None
            dslc = 0  # days since last change

            for rec in recs:
                td = rec["td"]
                brent, fx, pump, cif = rec["brent"], rec["fx"], rec["pump"], rec["cif"]
                mid = rec["id"]
                tax_id, otv_fixed, kdv_rate = find_tax(tax_params, ft, td)

                # Fiyat değişimi tespiti: price_changes tablosundaki tarihlere bak
                if td in pc_dates:
                    if nc_hist:
                        w = min(5, len(nc_hist))
                        last_change_nc_base = sum(nc_hist[-w:]) / Decimal(str(w))
                    dslc = 0

                if brent is None or fx is None:
                    # Brent/FX olmadan cost_base hesaplanamaz — ama pump varsa sadece pump yazabiliriz
                    # Burada skip ediyoruz çünkü nc_forward hesaplanamaz
                    dslc += 1
                    continue

                brent_d = _sd(brent)
                fx_d = _sd(fx)
                fx_hist.append(float(fx_d))
                cif_d = _sd(cif) if cif is not None else (brent_d * Decimal("7.33")).quantize(PRECISION, rounding=ROUND_HALF_UP)

                # NC_forward = (CIF * FX) / rho
                nc_forward = (cif_d * fx_d / rho).quantize(PRECISION, rounding=ROUND_HALF_UP)
                nc_hist.append(nc_forward)

                # === COST BASE SNAPSHOT ===
                cif_component = nc_forward
                kdv_component = ((cif_component + otv_fixed) * kdv_rate).quantize(PRECISION, rounding=ROUND_HALF_UP)
                theoretical_cost = ((cif_component + otv_fixed) * (Decimal("1") + kdv_rate) + M_TOTAL).quantize(PRECISION, rounding=ROUND_HALF_UP)
                actual_pump = _sd(pump) if pump is not None else theoretical_cost
                cost_gap = (actual_pump - theoretical_cost).quantize(PRECISION, rounding=ROUND_HALF_UP)
                cost_gap_pct = ((cost_gap / theoretical_cost) * Decimal("100")).quantize(PRECISION, rounding=ROUND_HALF_UP) if theoretical_cost != 0 else Decimal("0")

                implied_cif = None
                if pump is not None and fx_d > 0:
                    nb = ((_sd(pump) - M_TOTAL) / (Decimal("1") + kdv_rate) - otv_fixed)
                    implied_cif = ((nb * rho) / fx_d).quantize(PRECISION, rounding=ROUND_HALF_UP)

                cost_batch.append((
                    td, ft, mid, tax_id,
                    float(cif_component), float(otv_fixed), float(kdv_component),
                    float(M_TOTAL), float(theoretical_cost), float(actual_pump),
                    float(implied_cif) if implied_cif else None,
                    float(cost_gap), float(cost_gap_pct), "po_rebuild"
                ))

                # === MBE HESAPLAMA ===
                window = 5
                if last_change_nc_base is None:
                    if len(nc_hist) >= 5:
                        last_change_nc_base = sum(nc_hist[:5]) / Decimal("5")
                    else:
                        last_change_nc_base = nc_hist[0]

                recent_nc = nc_hist[-window:] if len(nc_hist) >= window else nc_hist[:]
                sma_w = sum(recent_nc) / Decimal(str(len(recent_nc)))
                mbe_value = (sma_w - last_change_nc_base).quantize(PRECISION, rounding=ROUND_HALF_UP)
                mbe_pct = ((mbe_value / last_change_nc_base) * Decimal("100")).quantize(PRECISION, rounding=ROUND_HALF_UP) if last_change_nc_base != 0 else Decimal("0")
                sma_5 = sma_w
                nc_10 = nc_hist[-10:] if len(nc_hist) >= 10 else nc_hist[:]
                sma_10 = sum(nc_10) / Decimal(str(len(nc_10)))
                dm = float((mbe_value - mbe_hist[-1]).quantize(PRECISION, rounding=ROUND_HALF_UP)) if mbe_hist else None
                dm3 = float((mbe_value - mbe_hist[-3]).quantize(PRECISION, rounding=ROUND_HALF_UP)) if len(mbe_hist) >= 3 else None

                trend = "no_change"
                if len(nc_hist) >= 3:
                    if nc_hist[-1] > nc_hist[-3]:
                        trend = "increase"
                    elif nc_hist[-1] < nc_hist[-3]:
                        trend = "decrease"

                mbe_hist.append(mbe_value)
                dslc += 1

                # === RISK HESAPLAMA ===
                mbe_abs = abs(float(mbe_value))
                mbe_norm = min(1.0, mbe_abs / 5.0)
                fx_vol = 0.0
                if len(fx_hist) >= 5:
                    rfx = fx_hist[-5:]
                    mfx = sum(rfx) / 5
                    fx_vol = math.sqrt(sum((x - mfx) ** 2 for x in rfx) / 4)
                fx_vol_norm = min(1.0, fx_vol / 2.0)
                delay_norm = min(1.0, dslc / 60.0)
                breach_norm = min(1.0, mbe_abs / 1.0) if mbe_abs > 0.1 else 0.0
                momentum = 0.5
                if len(mbe_hist) >= 3:
                    m1, m3 = float(mbe_hist[-1]), float(mbe_hist[-3])
                    mr = (m1 - m3) / max(abs(m3), 0.01)
                    momentum = min(1.0, max(0.0, (mr + 1) / 2))
                composite = min(1.0, max(0.0, 0.30 * mbe_norm + 0.15 * fx_vol_norm + 0.20 * delay_norm + 0.20 * breach_norm + 0.15 * momentum))
                sys_mode = "crisis" if composite >= 0.80 else ("high_alert" if composite >= 0.60 else "normal")

                mbe_data[ft].append({
                    "td": td, "nc_fwd": float(nc_forward), "nc_base": float(last_change_nc_base),
                    "mbe": float(mbe_value), "mbe_pct": float(mbe_pct),
                    "sma5": float(sma_5), "sma10": float(sma_10),
                    "dm": dm, "dm3": dm3,
                    "trend": trend, "regime": 0, "dslc": dslc, "window": window,
                    "comp": round(composite, 4), "mn": round(mbe_norm, 4),
                    "fvn": round(fx_vol_norm, 4), "dn": round(delay_norm, 4),
                    "bn": round(breach_norm, 4), "mom": round(momentum, 4),
                    "sm": sys_mode,
                })

                if len(cost_batch) % 500 == 0 and len(cost_batch) > 0:
                    logger.info("  %s @ %s — cost=%d", ft, td, len(cost_batch))

        # === FAZ 1: cost_base_snapshots yaz ===
        logger.info("FAZ 1: cost_base_snapshots %d kayıt yazılacak", len(cost_batch))
        if cost_batch:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO cost_base_snapshots
                    (trade_date, fuel_type, market_data_id, tax_parameter_id,
                     cif_component_tl, otv_component_tl, kdv_component_tl,
                     margin_component_tl, theoretical_cost_tl, actual_pump_price_tl,
                     implied_cif_usd_ton, cost_gap_tl, cost_gap_pct, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, cost_batch, page_size=500)
        conn.commit()
        logger.info("✅ cost_base_snapshots: %d kayıt yazıldı", len(cost_batch))

        # === FAZ 2: cost_snapshot_id haritası al ===
        cur.execute("SELECT id, trade_date, fuel_type FROM cost_base_snapshots")
        cs_map = {(r[2], r[1]): r[0] for r in cur.fetchall()}
        logger.info("Cost snapshot ID haritası: %d kayıt", len(cs_map))

        # === FAZ 3: mbe_calculations yaz ===
        mbe_batch = []
        for ft in FUEL_TYPES:
            for d in mbe_data.get(ft, []):
                cs_id = cs_map.get((ft, d["td"]))
                if cs_id is None:
                    continue
                mbe_batch.append((
                    d["td"], ft, cs_id,
                    d["nc_fwd"], d["nc_base"], d["mbe"], d["mbe_pct"],
                    d["sma5"], d["sma10"], d["dm"], d["dm3"],
                    d["trend"], d["regime"], d["dslc"], d["window"], "po_rebuild"
                ))

        if mbe_batch:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO mbe_calculations
                    (trade_date, fuel_type, cost_snapshot_id,
                     nc_forward, nc_base, mbe_value, mbe_pct,
                     sma_5, sma_10, delta_mbe, delta_mbe_3,
                     trend_direction, regime, since_last_change_days, sma_window, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, mbe_batch, page_size=500)
        conn.commit()
        logger.info("✅ mbe_calculations: %d kayıt yazıldı", len(mbe_batch))

        # === FAZ 4: risk_scores yaz ===
        wj = '{"mbe": "0.30", "fx_volatility": "0.15", "political_delay": "0.20", "threshold_breach": "0.20", "trend_momentum": "0.15"}'
        risk_batch = []
        for ft in FUEL_TYPES:
            for d in mbe_data.get(ft, []):
                risk_batch.append((
                    d["td"], ft,
                    d["comp"], d["mn"], d["fvn"],
                    d["dn"], d["bn"], d["mom"],
                    wj, d["sm"]
                ))

        if risk_batch:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO risk_scores
                    (trade_date, fuel_type, composite_score, mbe_component,
                     fx_volatility_component, political_delay_component,
                     threshold_breach_component, trend_momentum_component,
                     weight_vector, system_mode)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            """, risk_batch, page_size=500)
        conn.commit()
        logger.info("✅ risk_scores: %d kayıt yazıldı", len(risk_batch))

        # === DOĞRULAMA ===
        logger.info("=" * 60)
        logger.info("DOĞRULAMA RAPORU")
        logger.info("=" * 60)

        for tbl in ["cost_base_snapshots", "mbe_calculations", "risk_scores"]:
            cur.execute(f"SELECT fuel_type, count(*) FROM {tbl} GROUP BY fuel_type ORDER BY fuel_type")
            counts = dict(cur.fetchall())
            cur.execute(f"SELECT count(*) FROM {tbl}")
            total = cur.fetchone()[0]
            logger.info("  %s: %d toplam — %s", tbl, total, counts)

        # MBE istatistikleri
        cur.execute("""
            SELECT fuel_type,
                   round(min(mbe_value)::numeric, 4) as min_mbe,
                   round(avg(mbe_value)::numeric, 4) as avg_mbe,
                   round(max(mbe_value)::numeric, 4) as max_mbe,
                   count(CASE WHEN mbe_value IS NULL THEN 1 END) as null_count
            FROM mbe_calculations GROUP BY fuel_type ORDER BY fuel_type
        """)
        logger.info("  MBE İstatistikleri:")
        for r in cur.fetchall():
            logger.info("    %s: min=%s avg=%s max=%s null=%s", r[0], r[1], r[2], r[3], r[4])

        # Risk istatistikleri
        cur.execute("""
            SELECT fuel_type,
                   round(min(composite_score)::numeric, 4) as min_r,
                   round(avg(composite_score)::numeric, 4) as avg_r,
                   round(max(composite_score)::numeric, 4) as max_r,
                   system_mode, count(*)
            FROM risk_scores GROUP BY fuel_type, system_mode ORDER BY fuel_type, system_mode
        """)
        logger.info("  Risk İstatistikleri:")
        for r in cur.fetchall():
            logger.info("    %s [%s]: min=%s avg=%s max=%s count=%s", r[0], r[4], r[1], r[2], r[3], r[5])

        # Cost base istatistikleri
        cur.execute("""
            SELECT fuel_type,
                   round(min(cost_gap_tl)::numeric, 4) as min_gap,
                   round(avg(cost_gap_tl)::numeric, 4) as avg_gap,
                   round(max(cost_gap_tl)::numeric, 4) as max_gap,
                   count(CASE WHEN implied_cif_usd_ton IS NULL THEN 1 END) as null_cif
            FROM cost_base_snapshots GROUP BY fuel_type ORDER BY fuel_type
        """)
        logger.info("  Cost Base İstatistikleri:")
        for r in cur.fetchall():
            logger.info("    %s: gap min=%s avg=%s max=%s null_implied_cif=%s", r[0], r[1], r[2], r[3], r[4])

        # Tarih aralığı
        cur.execute("SELECT min(trade_date), max(trade_date) FROM cost_base_snapshots")
        mn, mx = cur.fetchone()
        logger.info("  Tarih aralığı: %s → %s", mn, mx)

        logger.info("=" * 60)
        logger.info("REBUILD TAMAMLANDI!")
        logger.info("  cost_base_snapshots: %d", len(cost_batch))
        logger.info("  mbe_calculations:    %d", len(mbe_batch))
        logger.info("  risk_scores:         %d", len(risk_batch))
        return True

    except Exception as e:
        conn.rollback()
        logger.error("HATA: %s", e, exc_info=True)
        return False
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    logger.info("🚀 TASK-065: Rebuild Derived Tables")
    ok = run_rebuild()
    if not ok:
        logger.error("❌ Rebuild FAILED")
        sys.exit(1)
    sys.exit(0)
