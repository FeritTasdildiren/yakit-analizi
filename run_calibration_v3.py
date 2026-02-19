#!/usr/bin/env python3
"""
TASK-059: Kalibrasyon Eğitimi v3 (fixes)
OOF walk-forward probabilities → kalibratör eğitimi
"""
import sys
import os
import logging
import numpy as np
import pandas as pd
import joblib
import lightgbm as lgb
from datetime import date, timedelta
from pathlib import Path

os.chdir("/var/www/yakit_analiz")
sys.path.insert(0, "/var/www/yakit_analiz")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from src.predictor_v5.config import FEATURE_NAMES, FUEL_TYPES, MODEL_DIR
from src.predictor_v5.features import compute_features_bulk
from src.predictor_v5.labels import compute_labels
from src.predictor_v5.trainer import _align_features_labels, _compute_scale_pos_weight, _get_hyperparams_stage1
from src.predictor_v5.cv import PurgedWalkForwardCV
from src.predictor_v5.calibration import (
    auto_calibrate,
    save_calibrator,
    apply_calibration,
    evaluate_calibration,
    PlattCalibrator,
    BetaCalibrator,
    IsotonicCalibrator,
)

DB_DSN = "postgresql://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi"
_PROJECT_ROOT = Path("/var/www/yakit_analiz")
_MODEL_PATH = _PROJECT_ROOT / MODEL_DIR


def run_calibration_for_fuel(fuel_type: str) -> dict:
    logger.info("=" * 60)
    logger.info("Kalibrasyon v3 başlıyor: %s", fuel_type.upper())
    logger.info("=" * 60)

    start_date = date(2022, 1, 1)
    end_date = date.today()

    logger.info("Features hesaplanıyor...")
    features_df = compute_features_bulk(fuel_type, start_date, end_date, dsn=DB_DSN)
    logger.info("Features: %d satır", len(features_df))

    logger.info("Labels hesaplanıyor...")
    labels_df = compute_labels(fuel_type, start_date, end_date, dsn=DB_DSN)
    logger.info("Labels: %d satır", len(labels_df))

    feat_aligned, lbl_aligned = _align_features_labels(features_df, labels_df)
    logger.info("Hizalanmış: %d satır", len(feat_aligned))

    if feat_aligned.empty:
        return {"fuel_type": fuel_type, "status": "no_data"}

    date_col = "trade_date" if "trade_date" in feat_aligned.columns else "run_date"
    dates_series = feat_aligned[date_col]

    X_all = feat_aligned[list(FEATURE_NAMES)].values.astype(np.float64)
    y_all = lbl_aligned["y_binary"].values.astype(np.int32)

    total = len(y_all)
    n_pos = int(np.sum(y_all))
    logger.info("Toplam: %d, Pozitif: %d (%.1f%%)", total, n_pos, 100*n_pos/total)

    # unique_dates → Python list[date] olarak (cv.split bunu istiyor)
    unique_dates_raw = sorted(dates_series.unique())
    # pandas Timestamp → datetime.date dönüşümü
    unique_dates = []
    for d in unique_dates_raw:
        if hasattr(d, 'date'):
            unique_dates.append(d.date())
        elif hasattr(d, 'item'):
            unique_dates.append(d.item())  # numpy datetime64
        else:
            unique_dates.append(d)
    
    logger.info("Unique dates: %d (tip: %s)", len(unique_dates), type(unique_dates[0]))

    cv = PurgedWalkForwardCV()
    folds = cv.split(unique_dates)
    logger.info("CV fold sayısı: %d", len(folds))

    if not folds:
        return {"fuel_type": fuel_type, "status": "no_folds"}

    oof_probs = np.full(total, np.nan)

    for fold_idx, (train_idx, test_idx) in enumerate(folds):
        train_dates_set = set(unique_dates[i] for i in train_idx)
        test_dates_set = set(unique_dates[i] for i in test_idx)

        # dates_series değerleri de aynı tipte olmalı
        if hasattr(dates_series.iloc[0], 'date'):
            train_mask = dates_series.apply(lambda x: x.date() if hasattr(x, 'date') else x).isin(train_dates_set).values
            test_mask = dates_series.apply(lambda x: x.date() if hasattr(x, 'date') else x).isin(test_dates_set).values
        else:
            train_mask = dates_series.isin(train_dates_set).values
            test_mask = dates_series.isin(test_dates_set).values

        X_train = X_all[train_mask]
        y_train = y_all[train_mask]
        X_test = X_all[test_mask]

        if len(X_train) < 50 or len(X_test) == 0:
            continue

        spw = _compute_scale_pos_weight(y_train)
        params = _get_hyperparams_stage1(scale_pos_weight=spw)
        model = lgb.LGBMClassifier(**params)
        model.fit(X_train, y_train)

        probs = model.predict_proba(X_test)[:, 1]
        oof_probs[test_mask] = probs

        logger.info("Fold %d: train=%d, test=%d, prob=[%.4f, %.4f] mean=%.4f",
                    fold_idx + 1, int(train_mask.sum()), int(test_mask.sum()),
                    probs.min(), probs.max(), probs.mean())

    # NaN'ları at
    valid_mask = ~np.isnan(oof_probs)
    oof_probs_valid = oof_probs[valid_mask]
    oof_labels_valid = y_all[valid_mask]
    logger.info("OOF: %d / %d geçerli (%.1f%%)",
                len(oof_probs_valid), total, 100*len(oof_probs_valid)/total)

    if len(oof_probs_valid) < 50:
        return {"fuel_type": fuel_type, "status": "insufficient_oof"}

    # Raw ECE
    raw_eval = evaluate_calibration(oof_probs_valid, oof_labels_valid)
    logger.info("RAW OOF: ECE=%.6f, MCE=%.6f, Brier=%.6f",
                raw_eval["ece"], raw_eval["mce"], raw_eval["brier_score"])

    # Train/Val split for auto_calibrate (son %30 val)
    n_valid = len(oof_probs_valid)
    val_size = max(int(n_valid * 0.30), 30)
    train_size = n_valid - val_size

    prob_train = oof_probs_valid[:train_size]
    label_train = oof_labels_valid[:train_size]
    prob_val = oof_probs_valid[train_size:]
    label_val = oof_labels_valid[train_size:]

    logger.info("Kalibrasyon train=%d, val=%d", train_size, val_size)

    # auto_calibrate
    calibrator, cal_metrics = auto_calibrate(prob_train, label_train, prob_val, label_val)
    method = cal_metrics["selected_method"]
    logger.info("Seçilen: %s (val ECE=%.6f)", method, cal_metrics["ece"])

    if cal_metrics.get("all_candidates"):
        for c in cal_metrics["all_candidates"]:
            logger.info("  %s: ECE=%.6f", c["method"], c["ece"])

    # Full refit — tüm OOF veri ile
    if method == "platt":
        final_cal = PlattCalibrator()
    elif method == "beta":
        final_cal = BetaCalibrator()
    else:
        final_cal = IsotonicCalibrator()

    final_cal.fit(oof_probs_valid, oof_labels_valid)

    # Final değerlendirme
    cal_probs = final_cal.transform(oof_probs_valid)
    final_eval = evaluate_calibration(cal_probs, oof_labels_valid)
    logger.info("FINAL (full refit): ECE=%.6f, MCE=%.6f, Brier=%.6f",
                final_eval["ece"], final_eval["mce"], final_eval["brier_score"])

    # Kaydet
    saved_path = save_calibrator(final_cal, fuel_type, _MODEL_PATH)
    logger.info("Kaydedildi: %s", saved_path)

    # Doğrulama
    test_sample = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
    cal_sample = apply_calibration(joblib.load(saved_path), test_sample)
    logger.info("Doğrulama: [0.1, 0.3, 0.5, 0.7, 0.9] → %s", np.round(cal_sample, 4))

    return {
        "fuel_type": fuel_type, "status": "success", "method": method,
        "ece_raw": raw_eval["ece"], "ece_calibrated": final_eval["ece"],
        "ece_improvement": round(raw_eval["ece"] - final_eval["ece"], 6),
        "mce_raw": raw_eval["mce"], "mce_calibrated": final_eval["mce"],
        "brier_raw": raw_eval["brier_score"], "brier_calibrated": final_eval["brier_score"],
        "n_oof": len(oof_probs_valid), "n_folds": len(folds),
        "saved_path": str(saved_path),
    }


def main():
    results = {}
    for fuel in FUEL_TYPES:
        try:
            results[fuel] = run_calibration_for_fuel(fuel)
        except Exception as e:
            logger.error("%s HATA: %s", fuel, str(e), exc_info=True)
            results[fuel] = {"fuel_type": fuel, "status": "error", "error": str(e)}

    logger.info("\n" + "=" * 60)
    logger.info("KALIBRASYON v3 ÖZET")
    logger.info("=" * 60)
    for fuel, r in results.items():
        if r["status"] == "success":
            logger.info("✅ %s: %s — ECE %.6f → %.6f (iyileşme: %+.6f), Brier %.6f → %.6f",
                        fuel.upper(), r["method"],
                        r["ece_raw"], r["ece_calibrated"], -r.get("ece_improvement", 0),
                        r["brier_raw"], r["brier_calibrated"])
        else:
            logger.info("❌ %s: %s", fuel.upper(), r.get("error", r["status"]))

    return results


if __name__ == "__main__":
    results = main()
    print("\n=== SONUÇ ===")
    for fuel, r in results.items():
        print(f"{fuel}: {r}")
