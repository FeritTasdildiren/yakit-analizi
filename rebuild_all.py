#!/usr/bin/env python3
"""
TASK-065: MBE + Risk + cost_base Tüm Dönem Yeniden Hesapla

PO İstanbul/Avcılar pompa fiyatları ve güncellenmiş Brent+FX verileriyle
cost_base_snapshots, mbe_calculations, risk_scores tablolarını sıfırdan yeniden hesaplar.

Hesaplama sırası: cost_base ÖNCE → mbe SONRA → risk EN SON (FK bağımlılıkları)
"""

import sys
import os
import logging
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import date, timedelta
from collections import defaultdict
import json
import time

# Proje path
sys.path.insert(0, '/var/www/yakit_analiz')

import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# --- DB ---
DB_PARAMS = dict(host='localhost', port=5433, dbname='yakit_analizi', user='yakit_analizi', password='yakit2026secure')

# --- Sabitler (mbe_calculator.py'den) ---
RHO = {
    'benzin': Decimal('1180'),
    'motorin': Decimal('1190'),
    'lpg': Decimal('1750'),
}

REGIME_PARAMS = {
    0: (5, Decimal('1.20')),   # Normal
    1: (7, Decimal('1.00')),   # Secim
    2: (3, Decimal('1.50')),   # Kur Soku
    3: (5, Decimal('1.20')),   # Vergi Ayarlama
}

PRECISION = Decimal('0.00000001')
CIF_BRENT_RATIO = Decimal('7.75')  # CIF ≈ Brent × 7.75

# Risk ağırlıkları
RISK_WEIGHTS = {
    'mbe': Decimal('0.30'),
    'fx_volatility': Decimal('0.15'),
    'political_delay': Decimal('0.20'),
    'threshold_breach': Decimal('0.20'),
    'trend_momentum': Decimal('0.15'),
}

FUEL_TYPES = ['benzin', 'motorin', 'lpg']


def _safe_decimal(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def get_conn():
    return psycopg2.connect(**DB_PARAMS)


# ============================================================
# PHASE 0: CIF Backfill (Brent * 7.75)
# ============================================================
def phase0_fill_cif(conn):
    """CIF NULL olan kayıtları Brent × 7.75 ile doldur."""
    logger.info('=== PHASE 0: CIF Backfill ===')
    cur = conn.cursor()
    
    cur.execute("""
        UPDATE daily_market_data
        SET cif_med_usd_ton = brent_usd_bbl * %s,
            updated_at = NOW()
        WHERE cif_med_usd_ton IS NULL
          AND brent_usd_bbl IS NOT NULL
    """, (float(CIF_BRENT_RATIO),))
    
    updated = cur.rowcount
    conn.commit()
    logger.info(f'CIF backfill: {updated} kayıt güncellendi (Brent × {CIF_BRENT_RATIO})')
    
    # Hala NULL olan var mı?
    cur.execute('SELECT COUNT(*) FROM daily_market_data WHERE cif_med_usd_ton IS NULL')
    remaining = cur.fetchone()[0]
    if remaining > 0:
        logger.warning(f'CIF hala NULL: {remaining} kayıt (Brent de NULL)')
    
    cur.close()
    return updated


# ============================================================
# PHASE 1: TRUNCATE
# ============================================================
def phase1_truncate(conn):
    """Türetilmiş tabloları temizle (FK sırasına göre)."""
    logger.info('=== PHASE 1: TRUNCATE ===')
    cur = conn.cursor()
    
    # FK sırasına göre: risk → mbe → cost_base
    for table in ['risk_scores', 'mbe_calculations', 'cost_base_snapshots']:
        cur.execute(f'DELETE FROM {table}')
        deleted = cur.rowcount
        logger.info(f'  {table}: {deleted} kayıt silindi')
    
    conn.commit()
    cur.close()


# ============================================================
# PHASE 2: cost_base_snapshots
# ============================================================
def phase2_cost_base(conn):
    """cost_base_snapshots hesapla ve yaz."""
    logger.info('=== PHASE 2: cost_base_snapshots ===')
    cur = conn.cursor()
    
    # Tüm daily_market_data çek
    cur.execute("""
        SELECT id, trade_date, fuel_type, cif_med_usd_ton, usd_try_rate,
               pump_price_tl_lt, brent_usd_bbl
        FROM daily_market_data
        ORDER BY trade_date, fuel_type
    """)
    market_data = cur.fetchall()
    logger.info(f'  daily_market_data: {len(market_data)} kayıt çekildi')
    
    # tax_parameters çek (fuel_type → sorted by valid_from)
    cur.execute("""
        SELECT id, fuel_type, otv_fixed_tl, kdv_rate, valid_from, valid_to
        FROM tax_parameters
        ORDER BY fuel_type, valid_from
    """)
    tax_rows = cur.fetchall()
    
    # Tax lookup: fuel_type → [(id, otv, kdv, from, to), ...]
    tax_lookup = defaultdict(list)
    for row in tax_rows:
        tax_lookup[row[1]].append({
            'id': row[0],
            'otv': _safe_decimal(row[2]),
            'kdv': _safe_decimal(row[3]),
            'valid_from': row[4],
            'valid_to': row[5],
        })
    
    def get_tax(fuel_type, trade_date):
        for t in tax_lookup.get(fuel_type, []):
            if t['valid_from'] <= trade_date:
                if t['valid_to'] is None or trade_date <= t['valid_to']:
                    return t
        # Fallback: son tax parametresini döndür
        params = tax_lookup.get(fuel_type, [])
        if params:
            return params[-1]
        return None
    
    # Hesapla
    inserts = []
    skipped = 0
    
    for row in market_data:
        md_id, trade_date, fuel_type, cif, fx, pump_price, brent = row
        
        cif_d = _safe_decimal(cif)
        fx_d = _safe_decimal(fx)
        pump_d = _safe_decimal(pump_price)
        rho = RHO.get(fuel_type)
        
        if rho is None:
            skipped += 1
            continue
        
        tax = get_tax(fuel_type, trade_date)
        if tax is None:
            skipped += 1
            continue
        
        otv = tax['otv']
        kdv = tax['kdv']
        tax_id = tax['id']
        
        # CIF yoksa Brent'ten türet
        if cif_d is None:
            brent_d = _safe_decimal(brent)
            if brent_d is not None:
                cif_d = (brent_d * CIF_BRENT_RATIO).quantize(PRECISION, rounding=ROUND_HALF_UP)
            else:
                skipped += 1
                continue
        
        if fx_d is None or fx_d == Decimal('0'):
            skipped += 1
            continue
        
        # Rejim 0 (Normal) marjı
        m_total = Decimal('1.20')
        
        # CIF bileşeni (TL/lt) = (CIF * FX) / rho
        cif_component = (cif_d * fx_d / rho).quantize(PRECISION, rounding=ROUND_HALF_UP)
        
        # OTV bileşeni
        otv_component = otv
        
        # KDV bileşeni
        kdv_component = ((cif_component + otv) * kdv).quantize(PRECISION, rounding=ROUND_HALF_UP)
        
        # Marj bileşeni
        margin_component = m_total
        
        # Teorik maliyet = (CIF + OTV) * (1 + KDV) + marj
        theoretical = ((cif_component + otv) * (Decimal('1') + kdv) + m_total).quantize(PRECISION, rounding=ROUND_HALF_UP)
        
        # Gerçek pompa fiyatı
        actual_pump = pump_d if pump_d is not None else Decimal('0')
        
        # Ima edilen CIF
        implied_cif = None
        if pump_d is not None and pump_d > Decimal('0'):
            nc_base = (pump_d - m_total) / (Decimal('1') + kdv) - otv
            implied_cif = ((nc_base * rho) / fx_d).quantize(PRECISION, rounding=ROUND_HALF_UP)
        
        # Maliyet farkı
        cost_gap = (actual_pump - theoretical).quantize(PRECISION, rounding=ROUND_HALF_UP) if pump_d else Decimal('0')
        cost_gap_pct = Decimal('0')
        if theoretical != Decimal('0') and pump_d:
            cost_gap_pct = ((cost_gap / theoretical) * Decimal('100')).quantize(PRECISION, rounding=ROUND_HALF_UP)
        
        inserts.append((
            trade_date, fuel_type, md_id, tax_id,
            float(cif_component), float(otv_component), float(kdv_component),
            float(margin_component), float(theoretical), float(actual_pump),
            float(implied_cif) if implied_cif else None,
            float(cost_gap), float(cost_gap_pct),
            'rebuild_task065'
        ))
    
    # Batch INSERT
    logger.info(f'  Hesaplanan: {len(inserts)}, Atlanan: {skipped}')
    
    insert_sql = """
        INSERT INTO cost_base_snapshots
        (trade_date, fuel_type, market_data_id, tax_parameter_id,
         cif_component_tl, otv_component_tl, kdv_component_tl,
         margin_component_tl, theoretical_cost_tl, actual_pump_price_tl,
         implied_cif_usd_ton, cost_gap_tl, cost_gap_pct, source,
         created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
    """
    
    batch_size = 500
    for i in range(0, len(inserts), batch_size):
        batch = inserts[i:i+batch_size]
        psycopg2.extras.execute_batch(cur, insert_sql, batch)
        conn.commit()
    
    logger.info(f'  cost_base_snapshots: {len(inserts)} kayıt yazıldı')
    
    cur.close()
    return len(inserts)


# ============================================================
# PHASE 3: mbe_calculations
# ============================================================
def phase3_mbe(conn):
    """MBE hesapla ve yaz."""
    logger.info('=== PHASE 3: mbe_calculations ===')
    cur = conn.cursor()
    
    # cost_base_snapshots çek
    cur.execute("""
        SELECT cbs.id, cbs.trade_date, cbs.fuel_type, cbs.cif_component_tl,
               cbs.actual_pump_price_tl, cbs.otv_component_tl, cbs.margin_component_tl,
               dmd.usd_try_rate, dmd.cif_med_usd_ton
        FROM cost_base_snapshots cbs
        JOIN daily_market_data dmd ON dmd.id = cbs.market_data_id
        ORDER BY cbs.fuel_type, cbs.trade_date
    """)
    cbs_data = cur.fetchall()
    logger.info(f'  cost_base_snapshots: {len(cbs_data)} kayıt çekildi')
    
    # price_changes çek (her yakıt tipi için son zam tarihleri)
    cur.execute("""
        SELECT fuel_type, change_date, new_price
        FROM price_changes
        ORDER BY fuel_type, change_date
    """)
    pc_rows = cur.fetchall()
    
    # price_changes lookup: fuel_type → [date, ...]
    price_changes = defaultdict(list)
    for row in pc_rows:
        price_changes[row[0]].append({'date': row[1], 'price': _safe_decimal(row[2])})
    
    # tax_parameters çek
    cur.execute("""
        SELECT fuel_type, otv_fixed_tl, kdv_rate, valid_from, valid_to
        FROM tax_parameters ORDER BY fuel_type, valid_from
    """)
    tax_rows = cur.fetchall()
    tax_lookup = defaultdict(list)
    for row in tax_rows:
        tax_lookup[row[0]].append({
            'otv': _safe_decimal(row[1]),
            'kdv': _safe_decimal(row[2]),
            'valid_from': row[3],
            'valid_to': row[4],
        })
    
    def get_tax(fuel_type, trade_date):
        for t in tax_lookup.get(fuel_type, []):
            if t['valid_from'] <= trade_date:
                if t['valid_to'] is None or trade_date <= t['valid_to']:
                    return t
        params = tax_lookup.get(fuel_type, [])
        return params[-1] if params else None
    
    # fuel_type bazlı grupla
    by_fuel = defaultdict(list)
    for row in cbs_data:
        cbs_id, trade_date, fuel_type, cif_comp, actual_pump, otv_comp, margin_comp, fx, cif = row
        by_fuel[fuel_type].append({
            'cbs_id': cbs_id,
            'trade_date': trade_date,
            'cif_component': _safe_decimal(cif_comp),
            'actual_pump': _safe_decimal(actual_pump),
            'otv': _safe_decimal(otv_comp),
            'margin': _safe_decimal(margin_comp),
            'fx': _safe_decimal(fx),
            'cif_usd': _safe_decimal(cif),
        })
    
    inserts = []
    
    for fuel_type in FUEL_TYPES:
        records = by_fuel.get(fuel_type, [])
        if not records:
            continue
        
        rho = RHO[fuel_type]
        changes = price_changes.get(fuel_type, [])
        
        # nc_forward serisi (her gün için) — rebuild_derived_tables.py ile uyumlu
        nc_forward_series = []
        mbe_history = []  # (trade_date, mbe_value)
        last_change_nc_base = None  # Son fiyat değişimindeki SMA5(nc_forward)
        dslc = 0  # days since last change
        
        # price_changes tarihlerini set'e çevir (hızlı arama için)
        pc_dates = set(pc['date'] for pc in changes)
        
        for i, rec in enumerate(records):
            trade_date = rec['trade_date']
            cif_comp = rec['cif_component']
            actual_pump = rec['actual_pump']
            
            if cif_comp is None:
                continue
            
            # Fiyat değişimi tespiti: price_changes tablosundaki tarihlere bak
            if trade_date in pc_dates:
                if nc_forward_series:
                    w = min(5, len(nc_forward_series))
                    last_change_nc_base = sum(nc_forward_series[-w:]) / Decimal(str(w))
                dslc = 0
            else:
                dslc += 1
            
            # NC_forward = CIF bileşeni (zaten TL/lt)
            nc_forward = cif_comp
            nc_forward_series.append(nc_forward)
            
            # since_last_change_days
            last_change_date = None
            for pc in changes:
                if pc['date'] <= trade_date:
                    last_change_date = pc['date']
                else:
                    break
            if last_change_date:
                since_last_change = (trade_date - last_change_date).days
            else:
                since_last_change = 0
            
            # NC_base hesabı: SMA5(nc_forward) @ son fiyat değişimi günü
            # (rebuild_derived_tables.py ile aynı mantık)
            regime = 0  # Normal rejim
            config_window, m_total = REGIME_PARAMS[regime]
            
            tax = get_tax(fuel_type, trade_date)
            otv = tax['otv'] if tax else rec['otv']
            kdv = tax['kdv'] if tax else Decimal('0.18')
            
            if last_change_nc_base is None:
                if len(nc_forward_series) >= 5:
                    last_change_nc_base = sum(nc_forward_series[:5]) / Decimal('5')
                else:
                    last_change_nc_base = nc_forward_series[0]
            
            nc_base = last_change_nc_base
            
            # SMA hesaplama (pencere genişliği kadar geriye git)
            window = config_window
            start_idx = max(0, len(nc_forward_series) - window)
            window_data = nc_forward_series[start_idx:]
            
            current_sma = sum(window_data) / Decimal(str(len(window_data)))
            current_sma = current_sma.quantize(PRECISION, rounding=ROUND_HALF_UP)
            
            # MBE değeri
            mbe_value = (current_sma - nc_base).quantize(PRECISION, rounding=ROUND_HALF_UP)
            
            # MBE yüzdesi
            mbe_pct = Decimal('0')
            if nc_base != Decimal('0'):
                mbe_pct = ((mbe_value / nc_base) * Decimal('100')).quantize(PRECISION, rounding=ROUND_HALF_UP)
            
            # SMA 5 ve 10
            sma5_start = max(0, len(nc_forward_series) - 5)
            sma5_data = nc_forward_series[sma5_start:]
            sma_5 = (sum(sma5_data) / Decimal(str(len(sma5_data)))).quantize(PRECISION, rounding=ROUND_HALF_UP)
            
            sma10_start = max(0, len(nc_forward_series) - 10)
            sma10_data = nc_forward_series[sma10_start:]
            sma_10 = (sum(sma10_data) / Decimal(str(len(sma10_data)))).quantize(PRECISION, rounding=ROUND_HALF_UP)
            
            # Delta MBE
            delta_mbe = None
            if len(mbe_history) >= 1:
                delta_mbe = float((mbe_value - mbe_history[-1][1]).quantize(PRECISION, rounding=ROUND_HALF_UP))
            
            delta_mbe_3 = None
            if len(mbe_history) >= 3:
                delta_mbe_3 = float((mbe_value - mbe_history[-3][1]).quantize(PRECISION, rounding=ROUND_HALF_UP))
            
            # Trend
            if len(mbe_history) >= 3:
                old_mbe = mbe_history[-3][1]
                if mbe_value > old_mbe:
                    trend = 'increase'
                elif mbe_value < old_mbe:
                    trend = 'decrease'
                else:
                    trend = 'no_change'
            else:
                trend = 'no_change'
            
            mbe_history.append((trade_date, mbe_value))
            
            inserts.append((
                trade_date, fuel_type, rec['cbs_id'],
                float(nc_forward), float(nc_base), float(mbe_value), float(mbe_pct),
                float(sma_5), float(sma_10),
                delta_mbe, delta_mbe_3,
                trend, regime, since_last_change, window,
                'rebuild_task065'
            ))
    
    logger.info(f'  Hesaplanan: {len(inserts)} MBE kaydı')
    
    insert_sql = """
        INSERT INTO mbe_calculations
        (trade_date, fuel_type, cost_snapshot_id,
         nc_forward, nc_base, mbe_value, mbe_pct,
         sma_5, sma_10, delta_mbe, delta_mbe_3,
         trend_direction, regime, since_last_change_days, sma_window,
         source, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
    """
    
    batch_size = 500
    for i in range(0, len(inserts), batch_size):
        batch = inserts[i:i+batch_size]
        psycopg2.extras.execute_batch(cur, insert_sql, batch)
        conn.commit()
    
    logger.info(f'  mbe_calculations: {len(inserts)} kayıt yazıldı')
    cur.close()
    return len(inserts)


# ============================================================
# PHASE 4: risk_scores
# ============================================================
def phase4_risk(conn):
    """Risk skorları hesapla ve yaz."""
    logger.info('=== PHASE 4: risk_scores ===')
    cur = conn.cursor()
    
    # MBE verilerini çek
    cur.execute("""
        SELECT trade_date, fuel_type, mbe_value, mbe_pct, delta_mbe, trend_direction
        FROM mbe_calculations
        ORDER BY fuel_type, trade_date
    """)
    mbe_data = cur.fetchall()
    
    # FX verilerini çek (volatilite hesabı için)
    cur.execute("""
        SELECT DISTINCT trade_date, usd_try_rate
        FROM daily_market_data
        WHERE fuel_type = 'benzin'
        ORDER BY trade_date
    """)
    fx_data = cur.fetchall()
    fx_by_date = {}
    for row in fx_data:
        fx_by_date[row[0]] = _safe_decimal(row[1])
    
    # FX volatilite hesabı (20 günlük pencere)
    fx_dates = sorted(fx_by_date.keys())
    fx_volatility_by_date = {}
    for i, d in enumerate(fx_dates):
        start_idx = max(0, i - 19)
        window = [fx_by_date[fx_dates[j]] for j in range(start_idx, i+1) if fx_by_date[fx_dates[j]] is not None]
        if len(window) >= 2:
            # Basit volatilite: (max-min)/mean
            mean_fx = sum(window) / Decimal(str(len(window)))
            if mean_fx > 0:
                vol = (max(window) - min(window)) / mean_fx
                fx_volatility_by_date[d] = vol.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
            else:
                fx_volatility_by_date[d] = Decimal('0')
        else:
            fx_volatility_by_date[d] = Decimal('0')
    
    # price_changes (political delay için)
    cur.execute('SELECT fuel_type, change_date FROM price_changes ORDER BY fuel_type, change_date')
    pc_rows = cur.fetchall()
    pc_lookup = defaultdict(list)
    for row in pc_rows:
        pc_lookup[row[0]].append(row[1])
    
    # MBE bazlı grupla
    by_fuel = defaultdict(list)
    for row in mbe_data:
        by_fuel[row[1]].append({
            'trade_date': row[0],
            'mbe_value': _safe_decimal(row[2]),
            'mbe_pct': _safe_decimal(row[3]),
            'delta_mbe': _safe_decimal(row[4]),
            'trend': row[5],
        })
    
    inserts = []
    
    for fuel_type in FUEL_TYPES:
        records = by_fuel.get(fuel_type, [])
        changes = pc_lookup.get(fuel_type, [])
        
        for rec in records:
            td = rec['trade_date']
            mbe_val = rec['mbe_value'] or Decimal('0')
            mbe_pct = rec['mbe_pct'] or Decimal('0')
            delta_mbe = rec['delta_mbe'] or Decimal('0')
            trend = rec['trend'] or 'no_change'
            
            # 1. MBE bileşeni: abs(mbe_value) normalize [0, 1]
            abs_mbe = abs(mbe_val)
            mbe_norm_range = (Decimal('0'), Decimal('1'))
            mbe_comp = min(max((abs_mbe - mbe_norm_range[0]) / (mbe_norm_range[1] - mbe_norm_range[0]) if mbe_norm_range[1] > mbe_norm_range[0] else Decimal('0'), Decimal('0')), Decimal('1'))
            
            # 2. FX volatilite bileşeni
            fx_vol = fx_volatility_by_date.get(td, Decimal('0'))
            fx_norm_range = (Decimal('0'), Decimal('0.10'))
            fx_comp = min(max((fx_vol - fx_norm_range[0]) / (fx_norm_range[1] - fx_norm_range[0]) if fx_norm_range[1] > fx_norm_range[0] else Decimal('0'), Decimal('0')), Decimal('1'))
            
            # 3. Politik gecikme bileşeni (son zamdan bu yana gün)
            last_change = None
            for c in changes:
                if c <= td:
                    last_change = c
                else:
                    break
            pol_delay = Decimal(str((td - last_change).days)) if last_change else Decimal('0')
            pol_norm_range = (Decimal('0'), Decimal('60'))
            pol_comp = min(max((pol_delay - pol_norm_range[0]) / (pol_norm_range[1] - pol_norm_range[0]) if pol_norm_range[1] > pol_norm_range[0] else Decimal('0'), Decimal('0')), Decimal('1'))
            
            # 4. Eşik ihlali bileşeni (MBE > 0.5 TL ise breach)
            threshold_breach = Decimal('1') if abs_mbe > Decimal('0.5') else (abs_mbe / Decimal('0.5')).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
            
            # 5. Trend momentum bileşeni
            if trend == 'increase':
                trend_raw = Decimal('0.5') + min(abs(delta_mbe), Decimal('0.5'))
            elif trend == 'decrease':
                trend_raw = Decimal('0.5') - min(abs(delta_mbe), Decimal('0.5'))
            else:
                trend_raw = Decimal('0.5')
            trend_comp = min(max(trend_raw, Decimal('0')), Decimal('1'))
            
            # Bileşik skor
            composite = (
                RISK_WEIGHTS['mbe'] * mbe_comp +
                RISK_WEIGHTS['fx_volatility'] * fx_comp +
                RISK_WEIGHTS['political_delay'] * pol_comp +
                RISK_WEIGHTS['threshold_breach'] * threshold_breach +
                RISK_WEIGHTS['trend_momentum'] * trend_comp
            ).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
            composite = min(max(composite, Decimal('0')), Decimal('1'))
            
            # Sistem modu
            if composite >= Decimal('0.80'):
                mode = 'crisis'
            elif composite >= Decimal('0.60'):
                mode = 'high_alert'
            else:
                mode = 'normal'
            
            weight_json = json.dumps({k: str(v) for k, v in RISK_WEIGHTS.items()})
            
            inserts.append((
                td, fuel_type,
                float(composite),
                float(mbe_comp.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)),
                float(fx_comp.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)),
                float(pol_comp.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)),
                float(threshold_breach.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)),
                float(trend_comp.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)),
                weight_json,
                '{}',  # triggered_alerts
                mode
            ))
    
    logger.info(f'  Hesaplanan: {len(inserts)} risk kaydı')
    
    insert_sql = """
        INSERT INTO risk_scores
        (trade_date, fuel_type, composite_score,
         mbe_component, fx_volatility_component, political_delay_component,
         threshold_breach_component, trend_momentum_component,
         weight_vector, triggered_alerts, system_mode,
         created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
    """
    
    batch_size = 500
    for i in range(0, len(inserts), batch_size):
        batch = inserts[i:i+batch_size]
        psycopg2.extras.execute_batch(cur, insert_sql, batch)
        conn.commit()
    
    logger.info(f'  risk_scores: {len(inserts)} kayıt yazıldı')
    cur.close()
    return len(inserts)


# ============================================================
# PHASE 5: Doğrulama
# ============================================================
def phase5_validate(conn):
    """Doğrulama raporu oluştur."""
    logger.info('=== PHASE 5: DOĞRULAMA ===')
    cur = conn.cursor()
    
    report = []
    
    for table in ['cost_base_snapshots', 'mbe_calculations', 'risk_scores']:
        cur.execute(f'SELECT fuel_type, COUNT(*), MIN(trade_date), MAX(trade_date) FROM {table} GROUP BY fuel_type ORDER BY fuel_type')
        for row in cur.fetchall():
            line = f'{table} | {row[0]}: {row[1]} kayıt ({row[2]} → {row[3]})'
            report.append(line)
            logger.info(f'  {line}')
    
    # NULL kontrolleri
    cur.execute('SELECT fuel_type, COUNT(*) FROM cost_base_snapshots WHERE theoretical_cost_tl IS NULL GROUP BY fuel_type')
    for row in cur.fetchall():
        report.append(f'CBS NULL theoretical: {row[0]} → {row[1]}')
    
    cur.execute('SELECT fuel_type, COUNT(*) FROM mbe_calculations WHERE mbe_value IS NULL GROUP BY fuel_type')
    for row in cur.fetchall():
        report.append(f'MBE NULL mbe_value: {row[0]} → {row[1]}')
    
    cur.execute('SELECT fuel_type, COUNT(*) FROM risk_scores WHERE composite_score IS NULL GROUP BY fuel_type')
    for row in cur.fetchall():
        report.append(f'RISK NULL composite: {row[0]} → {row[1]}')
    
    # Min/Max değerler
    cur.execute("""
        SELECT fuel_type, 
               MIN(theoretical_cost_tl), MAX(theoretical_cost_tl),
               MIN(cost_gap_tl), MAX(cost_gap_tl)
        FROM cost_base_snapshots GROUP BY fuel_type ORDER BY fuel_type
    """)
    for row in cur.fetchall():
        report.append(f'CBS {row[0]}: theo [{row[1]} → {row[2]}], gap [{row[3]} → {row[4]}]')
    
    cur.execute("""
        SELECT fuel_type,
               MIN(mbe_value), MAX(mbe_value),
               MIN(mbe_pct), MAX(mbe_pct)
        FROM mbe_calculations GROUP BY fuel_type ORDER BY fuel_type
    """)
    for row in cur.fetchall():
        report.append(f'MBE {row[0]}: value [{row[1]} → {row[2]}], pct [{row[3]} → {row[4]}]')
    
    cur.execute("""
        SELECT fuel_type,
               MIN(composite_score), MAX(composite_score),
               COUNT(CASE WHEN system_mode='crisis' THEN 1 END),
               COUNT(CASE WHEN system_mode='high_alert' THEN 1 END),
               COUNT(CASE WHEN system_mode='normal' THEN 1 END)
        FROM risk_scores GROUP BY fuel_type ORDER BY fuel_type
    """)
    for row in cur.fetchall():
        report.append(f'RISK {row[0]}: score [{row[1]} → {row[2]}], crisis={row[3]}, high_alert={row[4]}, normal={row[5]}')
    
    # Son 3 gün MBE
    cur.execute("""
        SELECT trade_date, fuel_type, mbe_value, mbe_pct, trend_direction
        FROM mbe_calculations
        WHERE trade_date >= '2026-02-15'
        ORDER BY trade_date DESC, fuel_type
        LIMIT 15
    """)
    report.append('--- Son 3 gün MBE ---')
    for row in cur.fetchall():
        report.append(f'  {row[0]} {row[1]}: mbe={row[2]}, pct={row[3]}, trend={row[4]}')
    
    cur.close()
    
    for line in report:
        print(line)
    
    return report


# ============================================================
# MAIN
# ============================================================
def main():
    start = time.time()
    logger.info('Rebuild başlıyor...')
    
    conn = get_conn()
    
    try:
        phase0_fill_cif(conn)
        phase1_truncate(conn)
        cbs_count = phase2_cost_base(conn)
        mbe_count = phase3_mbe(conn)
        risk_count = phase4_risk(conn)
        phase5_validate(conn)
        
        elapsed = time.time() - start
        logger.info(f'=== REBUILD TAMAMLANDI === ({elapsed:.1f}s)')
        logger.info(f'  cost_base: {cbs_count}, mbe: {mbe_count}, risk: {risk_count}')
        
    except Exception as e:
        conn.rollback()
        logger.error(f'HATA: {e}', exc_info=True)
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
