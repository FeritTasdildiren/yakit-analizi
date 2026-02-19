#!/usr/bin/env python3
"""v5 Model Out-of-Sample Test — 2024-2025 verisi"""

import sys
import os
import logging
import json
import numpy as np
from datetime import date

sys.path.insert(0, '/var/www/yakit_analiz')
os.chdir('/var/www/yakit_analiz')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger('test_v5_oos')

def main():
    import joblib
    from pathlib import Path
    from sklearn.metrics import (
        roc_auc_score, accuracy_score, precision_score, recall_score,
        f1_score, confusion_matrix, brier_score_loss, mean_squared_error,
        mean_absolute_error, r2_score
    )
    from src.predictor_v5.features import compute_features_bulk
    from src.predictor_v5.labels import compute_labels
    from src.predictor_v5.trainer import _align_features_labels, _extract_dates
    from src.predictor_v5.config import FEATURE_NAMES, FUEL_TYPES, MODEL_DIR

    MODEL_PATH = Path('/var/www/yakit_analiz') / MODEL_DIR

    test_start = date(2024, 1, 1)
    test_end = date(2025, 12, 31)

    logger.info("=" * 60)
    logger.info("v5 Out-of-Sample Test: %s -> %s", test_start, test_end)
    logger.info("=" * 60)

    results = {}
    
    for fuel_type in FUEL_TYPES:
        logger.info("=== %s test basliyor ===", fuel_type.upper())
        
        try:
            features_df = compute_features_bulk(fuel_type, test_start, test_end)
            labels_df = compute_labels(fuel_type, test_start, test_end)
            
            logger.info("%s: features=%d, labels=%d", fuel_type, len(features_df), len(labels_df))
            
            if features_df.empty or labels_df.empty:
                logger.warning("%s: Veri yok, atlaniyor", fuel_type)
                results[fuel_type] = {"status": "skipped", "reason": "no_data"}
                continue
            
            features_aligned, labels_aligned = _align_features_labels(features_df, labels_df)
            logger.info("%s: hizalanmis=%d", fuel_type, len(features_aligned))
            
            if features_aligned.empty:
                results[fuel_type] = {"status": "skipped", "reason": "no_aligned_data"}
                continue
            
            feat_cols = [c for c in FEATURE_NAMES if c in features_aligned.columns]
            X_test = features_aligned[feat_cols].values
            y_true = labels_aligned["y_binary"].values.astype(int)
            
            n_pos = int(np.sum(y_true == 1))
            n_neg = int(np.sum(y_true == 0))
            pct = 100.0 * n_pos / len(y_true)
            logger.info("%s: test ornekleri=%d, pozitif=%d, oran=%.1f%%, negatif=%d", 
                        fuel_type, len(y_true), n_pos, pct, n_neg)
            
            stage1_path = MODEL_PATH / f"{fuel_type}_stage1.joblib"
            stage1_model = joblib.load(stage1_path)
            
            y_prob = stage1_model.predict_proba(X_test)[:, 1]
            y_pred = (y_prob >= 0.5).astype(int)
            
            cal_path = MODEL_PATH / f"{fuel_type}_calibrator.joblib"
            y_prob_cal = y_prob.copy()
            if cal_path.exists():
                try:
                    calibrator = joblib.load(cal_path)
                    y_prob_cal = calibrator.predict_proba(y_prob.reshape(-1, 1))[:, 1]
                    logger.info("%s: Kalibrasyon uygulandi", fuel_type)
                except Exception as e:
                    logger.warning("%s: Kalibrasyon hatasi: %s", fuel_type, e)
            
            try:
                auc = roc_auc_score(y_true, y_prob)
            except Exception:
                auc = None
            
            try:
                auc_cal = roc_auc_score(y_true, y_prob_cal)
            except Exception:
                auc_cal = None
                
            acc = accuracy_score(y_true, y_pred)
            prec = precision_score(y_true, y_pred, zero_division=0)
            rec = recall_score(y_true, y_pred, zero_division=0)
            f1 = f1_score(y_true, y_pred, zero_division=0)
            brier = brier_score_loss(y_true, y_prob)
            brier_cal = brier_score_loss(y_true, y_prob_cal)
            
            cm = confusion_matrix(y_true, y_pred)
            if cm.shape == (2, 2):
                tn, fp, fn, tp = cm.ravel()
            else:
                tn, fp, fn, tp = 0, 0, 0, 0
            
            stage2_metrics = {"skipped": True}
            if n_pos >= 5:
                try:
                    s2f_path = MODEL_PATH / f"{fuel_type}_stage2_first.joblib"
                    s2n_path = MODEL_PATH / f"{fuel_type}_stage2_net.joblib"
                    if s2f_path.exists() and s2n_path.exists():
                        model_first = joblib.load(s2f_path)
                        model_net = joblib.load(s2n_path)
                        
                        pos_mask = y_true == 1
                        X_pos = X_test[pos_mask]
                        
                        if "first_event_amount" in labels_aligned.columns:
                            y_first_true = labels_aligned["first_event_amount"].values[pos_mask]
                            y_first_pred = model_first.predict(X_pos)
                            
                            y_net_true = labels_aligned["net_amount_3d"].values[pos_mask]
                            y_net_pred = model_net.predict(X_pos)
                            
                            stage2_metrics = {
                                "skipped": False,
                                "n_positive": int(n_pos),
                                "first_event": {
                                    "rmse": float(np.sqrt(mean_squared_error(y_first_true, y_first_pred))),
                                    "mae": float(mean_absolute_error(y_first_true, y_first_pred)),
                                    "r2": float(r2_score(y_first_true, y_first_pred)) if n_pos > 1 else None,
                                },
                                "net_amount": {
                                    "rmse": float(np.sqrt(mean_squared_error(y_net_true, y_net_pred))),
                                    "mae": float(mean_absolute_error(y_net_true, y_net_pred)),
                                    "r2": float(r2_score(y_net_true, y_net_pred)) if n_pos > 1 else None,
                                }
                            }
                except Exception as e:
                    logger.error("%s Stage-2 test hatasi: %s", fuel_type, e)
            
            fuel_result = {
                "status": "success",
                "n_samples": len(y_true),
                "n_positive": n_pos,
                "n_negative": n_neg,
                "pos_ratio": round(n_pos/len(y_true), 4),
                "stage1": {
                    "auc_raw": round(auc, 4) if auc else None,
                    "auc_calibrated": round(auc_cal, 4) if auc_cal else None,
                    "accuracy": round(acc, 4),
                    "precision": round(prec, 4),
                    "recall": round(rec, 4),
                    "f1": round(f1, 4),
                    "brier_raw": round(brier, 4),
                    "brier_calibrated": round(brier_cal, 4),
                    "confusion_matrix": {
                        "TP": int(tp), "FP": int(fp),
                        "TN": int(tn), "FN": int(fn),
                    },
                    "miss_rate": round(fn / max(fn + tp, 1), 4),
                    "false_alarm_rate": round(fp / max(fp + tn, 1), 4),
                },
                "stage2": stage2_metrics,
            }
            
            results[fuel_type] = fuel_result
            
            logger.info("%s: AUC=%.4f, Acc=%.4f, Prec=%.4f, Rec=%.4f, F1=%.4f",
                        fuel_type, auc or 0, acc, prec, rec, f1)
            logger.info("%s: TP=%d, FP=%d, TN=%d, FN=%d", fuel_type, tp, fp, tn, fn)
            
        except Exception as e:
            logger.error("%s test hatasi: %s", fuel_type, str(e), exc_info=True)
            results[fuel_type] = {"status": "error", "error": str(e)}
    
    train_metrics = {
        "benzin": {"auc": 0.5494, "f1": 0.2795},
        "motorin": {"auc": 0.5280, "f1": 0.3768},
        "lpg": {"auc": 0.6263, "f1": 0.1456},
    }
    
    logger.info("=" * 60)
    logger.info("KARSILASTIRMA: Egitim CV vs Test OOS")
    logger.info("=" * 60)
    for fuel in FUEL_TYPES:
        if results.get(fuel, {}).get("status") == "success":
            train_auc = train_metrics.get(fuel, {}).get("auc", 0)
            test_auc = results[fuel]["stage1"]["auc_raw"] or 0
            train_f1 = train_metrics.get(fuel, {}).get("f1", 0)
            test_f1 = results[fuel]["stage1"]["f1"]
            logger.info("%s: Train AUC=%.4f -> Test AUC=%.4f diff=%.4f | Train F1=%.4f -> Test F1=%.4f",
                        fuel.upper(), train_auc, test_auc, test_auc - train_auc, train_f1, test_f1)
    
    logger.info("=" * 60)
    logger.info("SONUCLAR JSON")
    logger.info("=" * 60)
    
    def make_serializable(obj):
        if hasattr(obj, 'item'):
            return obj.item()
        if isinstance(obj, dict):
            return {k: make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [make_serializable(v) for v in obj]
        return obj
    
    print(json.dumps(make_serializable(results), indent=2, ensure_ascii=False))
    
    logger.info("=" * 60)
    logger.info("TEST TAMAMLANDI")
    logger.info("=" * 60)

if __name__ == '__main__':
    main()
