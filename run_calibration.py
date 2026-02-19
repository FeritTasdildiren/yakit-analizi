#!/usr/bin/env python3
"""
TASK-059: Kalibrasyon Eğitimi
Her yakıt tipi için:
1. Features + Labels hesapla
2. Son fold üzerinde Stage-1 model eğit 
3. Train/Val split yap
4. auto_calibrate ile en iyi kalibratörü bul
5. {fuel}_calibrator.joblib olarak kaydet
"""
import sys
import os
import logging
import numpy as np
import pandas as pd
import lightgbm as lgb
from datetime import date, timedelta
from pathlib import Path

# Proje root
os.chdir("/var/www/yakit_analiz")
sys.path.insert(0, "/var/www/yakit_analiz")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from src.predictor_v5.config import FEATURE_NAMES, FUEL_TYPES, MODEL_DIR
from src.predictor_v5.features import compute_features_bulk
from src.predictor_v5.labels import compute_labels
from src.predictor_v5.trainer import (
    _align_features_labels,
    _extract_dates,
    _compute_scale_pos_weight,
    _get_hyperparams_stage1,
)
from src.predictor_v5.calibration import (
    auto_calibrate,
    save_calibrator,
    apply_calibration,
    evaluate_calibration,
)

DB_DSN = "postgresql://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi"

_PROJECT_ROOT = Path("/var/www/yakit_analiz")
_MODEL_PATH = _PROJECT_ROOT / MODEL_DIR


def run_calibration_for_fuel(fuel_type: str) -> dict:
    """Tek yakıt tipi için kalibrasyon eğitimi."""
    logger.info("=" * 60)
    logger.info("Kalibrasyon başlıyor: %s", fuel_type.upper())
    logger.info("=" * 60)

    # 1. Veri çek
    start_date = date(2022, 1, 1)
    end_date = date.today()

    logger.info("Features hesaplanıyor: %s .. %s", start_date, end_date)
    features_df = compute_features_bulk(fuel_type, start_date, end_date, dsn=DB_DSN)
    logger.info("Features: %d satır", len(features_df))

    logger.info("Labels hesaplanıyor...")
    labels_df = compute_labels(fuel_type, start_date, end_date, dsn=DB_DSN)
    logger.info("Labels: %d satır", len(labels_df))

    if features_df.empty or labels_df.empty:
        logger.error("Veri yok: %s", fuel_type)
        return {"fuel_type": fuel_type, "status": "no_data"}

    # 2. Hizalama
    feat_aligned, lbl_aligned = _align_features_labels(features_df, labels_df)
    logger.info("Hizalanmış: %d satır", len(feat_aligned))

    if feat_aligned.empty:
        logger.error("Hizalama başarısız: %s", fuel_type)
        return {"fuel_type": fuel_type, "status": "alignment_failed"}

    # 3. Feature matrix + labels
    X = feat_aligned[list(FEATURE_NAMES)].values.astype(np.float64)
    y = lbl_aligned["y_binary"].values.astype(np.int32)

    total = len(y)
    n_pos = int(np.sum(y))
    n_neg = total - n_pos
    logger.info("Toplam: %d, Pozitif: %d (%.1f%%), Negatif: %d", total, n_pos, 100*n_pos/total, n_neg)

    # 4. Train/Val split (son %25 validation)
    val_size = max(int(total * 0.25), 30)
    train_size = total - val_size

    X_train, X_val = X[:train_size], X[train_size:]
    y_train, y_val = y[:train_size], y[train_size:]

    logger.info("Train: %d, Val: %d", train_size, val_size)
    logger.info("Train pozitif: %d (%.1f%%), Val pozitif: %d (%.1f%%)", 
                int(np.sum(y_train)), 100*np.mean(y_train),
                int(np.sum(y_val)), 100*np.mean(y_val))

    # 5. Stage-1 model eğit (kalibrasyon için)
    spw = _compute_scale_pos_weight(y_train)
    params = _get_hyperparams_stage1(scale_pos_weight=spw)
    logger.info("Stage-1 eğitiliyor (scale_pos_weight=%.2f)...", spw)

    model = lgb.LGBMClassifier(**params)
    model.fit(X_train, y_train)

    # 6. Raw probability al
    y_prob_train = model.predict_proba(X_train)[:, 1]
    y_prob_val = model.predict_proba(X_val)[:, 1]

    logger.info("Train prob range: [%.4f, %.4f], mean=%.4f", 
                y_prob_train.min(), y_prob_train.max(), y_prob_train.mean())
    logger.info("Val prob range: [%.4f, %.4f], mean=%.4f", 
                y_prob_val.min(), y_prob_val.max(), y_prob_val.mean())

    # 7. Raw kalibrasyon metrikleri
    raw_eval = evaluate_calibration(y_prob_val, y_val)
    logger.info("RAW kalibrasyon: ECE=%.6f, MCE=%.6f, Brier=%.6f", 
                raw_eval["ece"], raw_eval["mce"], raw_eval["brier_score"])

    # 8. auto_calibrate çalıştır
    logger.info("auto_calibrate çalıştırılıyor (Platt → Beta → Isotonic)...")
    try:
        calibrator, cal_metrics = auto_calibrate(y_prob_train, y_train, y_prob_val, y_val)
        logger.info("Seçilen metod: %s", cal_metrics["selected_method"])
        logger.info("Kalibrasyon ECE: %.6f (raw: %.6f)", cal_metrics["ece"], raw_eval["ece"])
        logger.info("Kalibrasyon MCE: %.6f", cal_metrics["mce"])
        logger.info("Brier Score: %.6f", cal_metrics["brier_score"])
        
        if cal_metrics.get("all_candidates"):
            logger.info("Tüm adaylar:")
            for c in cal_metrics["all_candidates"]:
                logger.info("  %s: ECE=%.6f", c["method"], c["ece"])

        # 9. Kaydet
        saved_path = save_calibrator(calibrator, fuel_type, _MODEL_PATH)
        logger.info("Kalibratör kaydedildi: %s", saved_path)

        # 10. Doğrulama: yükle ve test et
        import joblib
        loaded = joblib.load(saved_path)
        test_probs = apply_calibration(loaded, y_prob_val[:5])
        logger.info("Doğrulama (ilk 5): raw=%s → cal=%s", 
                    np.round(y_prob_val[:5], 4), np.round(test_probs, 4))

        return {
            "fuel_type": fuel_type,
            "status": "success",
            "method": cal_metrics["selected_method"],
            "ece_raw": raw_eval["ece"],
            "ece_calibrated": cal_metrics["ece"],
            "mce": cal_metrics["mce"],
            "brier": cal_metrics["brier_score"],
            "train_size": train_size,
            "val_size": val_size,
            "saved_path": str(saved_path),
        }
    except Exception as e:
        logger.error("Kalibrasyon hatası: %s — %s", fuel_type, str(e), exc_info=True)
        return {"fuel_type": fuel_type, "status": "error", "error": str(e)}


def main():
    results = {}
    for fuel in FUEL_TYPES:
        try:
            results[fuel] = run_calibration_for_fuel(fuel)
        except Exception as e:
            logger.error("%s GENEL HATA: %s", fuel, str(e), exc_info=True)
            results[fuel] = {"fuel_type": fuel, "status": "error", "error": str(e)}
    
    # Özet
    logger.info("\n" + "=" * 60)
    logger.info("KALIBRASYON ÖZET")
    logger.info("=" * 60)
    for fuel, r in results.items():
        if r["status"] == "success":
            logger.info("✅ %s: %s — ECE %.6f → %.6f (iyileşme: %.1f%%)",
                        fuel.upper(), r["method"], 
                        r["ece_raw"], r["ece_calibrated"],
                        100*(1 - r["ece_calibrated"]/max(r["ece_raw"], 1e-9)))
        else:
            logger.info("❌ %s: %s", fuel.upper(), r.get("error", r["status"]))
    
    return results


if __name__ == "__main__":
    results = main()
    print("\n=== SONUÇ ===")
    for fuel, r in results.items():
        print(f"{fuel}: {r}")
