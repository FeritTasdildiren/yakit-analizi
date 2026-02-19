#!/usr/bin/env python3
"""Son 30 gun backfill - yeni PO modelleriyle"""
import sys, os, logging
from datetime import date, timedelta

sys.path.insert(0, '/var/www/yakit_analiz')
os.chdir('/var/www/yakit_analiz')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', stream=sys.stdout)
logger = logging.getLogger('backfill_30d')

def main():
    from src.predictor_v5.predictor import predict_all
    
    end_date = date(2026, 2, 18)
    start_date = end_date - timedelta(days=30)
    
    logger.info('Backfill: %s -> %s', start_date, end_date)
    
    current = start_date
    success = 0
    errors = 0
    
    while current <= end_date:
        try:
            results = predict_all(target_date=current)
            fuels_ok = sum(1 for v in results.values() if isinstance(v, dict) and v.get('probability') is not None)
            logger.info('%s: %d yakit OK', current, fuels_ok)
            success += 1
        except Exception as e:
            logger.error('%s: HATA - %s', current, e)
            errors += 1
        current += timedelta(days=1)
    
    logger.info('Backfill tamamlandi: %d basarili, %d hatali', success, errors)
    
    # DB'den sonuclari kontrol et
    import psycopg2
    conn = psycopg2.connect(host='localhost', port=5433, dbname='yakit_analizi', user='yakit_analizi', password='yakit2026secure')
    cur = conn.cursor()
    cur.execute("SELECT fuel_type, COUNT(*), MIN(prediction_date), MAX(prediction_date) FROM predictions_v5 WHERE prediction_date >= %s GROUP BY fuel_type ORDER BY fuel_type", (start_date,))
    rows = cur.fetchall()
    logger.info('DB durumu (son 30 gun):')
    for row in rows:
        logger.info('  %s: %d kayit (%s -> %s)', row[0], row[1], row[2], row[3])
    cur.close()
    conn.close()

if __name__ == '__main__':
    main()
