#!/usr/bin/env python3
"""
v5 Model Eğitimi — PO İstanbul/Avcılar Verisiyle (2021-2023)
=============================================================
Eğitim seti: 2021-06-05 → 2023-12-31 (look-ahead bias yok)
9 model (3 yakıt × {stage1, stage2_first, stage2_net}) + 3 kalibratör

Kullanım:
    /var/www/yakit_analiz/.venv/bin/python3 /var/www/yakit_analiz/train_v5_po.py
"""

import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# Proje kökünü sys.path'e ekle
PROJECT_ROOT = Path("/var/www/yakit_analiz")
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(str(PROJECT_ROOT))

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(PROJECT_ROOT / "train_v5_po.log", mode="w"),
    ],
)
logger = logging.getLogger("train_v5_po")

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import numpy as np
import pandas as pd
import joblib

from src.predictor_v5.config import FEATURE_NAMES, FUEL_TYPES, MODEL_DIR
from src.predictor_v5.features import compute_features_bulk
from src.predictor_v5.labels import compute_labels
from src.predictor_v5.trainer import (
    train_stage1,
    train_stage2,
    _save_models,
    _compute_scale_pos_weight,
    _align_features_labels,
    _get_hyperparams_stage1,
    _get_hyperparams_stage2,
)
from src.predictor_v5.calibration import auto_calibrate, apply_calibration
from src.predictor_v5.cv import PurgedWalkForwardCV

import lightgbm as lgb

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------
TRAIN_START = date(2021, 6, 5)
TRAIN_END = date(2023, 12, 31)
MODEL_PATH = PROJECT_ROOT / MODEL_DIR

# n_estimators override (hızlı eğitim)
N_ESTIMATORS = 100


def quick_train_stage1(fuel_type, features_df, labels_df):
    """Stage-1 eğitimi — CV atlanır, tüm veriyle eğit (hızlı)."""
    from src.predictor_v5.trainer import _align_features_labels, _compute_scale_pos_weight

    feat_aligned, lbl_aligned = _align_features_labels(features_df, labels_df)
    if feat_aligned.empty:
        raise ValueError(f"Hizalama sonrası veri yok: {fuel_type}")

    X = feat_aligned[list(FEATURE_NAMES)].values.astype(np.float64)
    y = lbl_aligned["y_binary"].values.astype(np.int32)

    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))
    spw = _compute_scale_pos_weight(y)

    logger.info(
        "Stage-1 %s: %d örnek, pos=%d (%.1f%%), neg=%d, scale_pos_weight=%.2f",
        fuel_type, len(y), n_pos, (n_pos / len(y) * 100) if len(y) > 0 else 0, n_neg, spw,
    )

    params = _get_hyperparams_stage1(scale_pos_weight=spw)
    params["n_estimators"] = N_ESTIMATORS  # Hızlı eğitim

    model = lgb.LGBMClassifier(**params)
    model.fit(X, y)

    # Eğitim metrikleri (in-sample)
    y_prob = model.predict_proba(X)[:, 1]
    y_pred = model.predict(X)

    from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score, accuracy_score

    try:
        auc = roc_auc_score(y, y_prob) if len(np.unique(y)) > 1 else 0.0
    except Exception:
        auc = 0.0

    metrics = {
        "stage": "stage1",
        "n_samples": len(y),
        "n_positive": n_pos,
        "n_negative": n_neg,
        "scale_pos_weight": round(spw, 2),
        "train_auc": round(auc, 4),
        "train_f1": round(f1_score(y, y_pred, zero_division=0.0), 4),
        "train_precision": round(precision_score(y, y_pred, zero_division=0.0), 4),
        "train_recall": round(recall_score(y, y_pred, zero_division=0.0), 4),
        "train_accuracy": round(accuracy_score(y, y_pred), 4),
    }

    return model, metrics, feat_aligned, lbl_aligned


def quick_train_stage2(fuel_type, features_df, labels_df):
    """Stage-2 dual regressor — sadece pozitif örneklerle, CV atlanır."""
    feat_aligned, lbl_aligned = _align_features_labels(features_df, labels_df)
    if feat_aligned.empty:
        return (None, None), {"stage": "stage2", "skipped": True, "reason": "no_data"}

    pos_mask = lbl_aligned["y_binary"] == 1
    feat_pos = feat_aligned.loc[pos_mask].copy().reset_index(drop=True)
    lbl_pos = lbl_aligned.loc[pos_mask].copy().reset_index(drop=True)
    n_pos = len(feat_pos)

    logger.info("Stage-2 %s: %d pozitif örnek", fuel_type, n_pos)

    if n_pos < 20:
        logger.warning("Stage-2 atlanıyor: pozitif örnek (%d) < 20", n_pos)
        return (None, None), {
            "stage": "stage2",
            "skipped": True,
            "reason": "insufficient_positive_samples",
            "n_positive": n_pos,
        }

    X = feat_pos[list(FEATURE_NAMES)].values.astype(np.float64)

    def _to_float_safe(v):
        return float(v) if v is not None else 0.0

    y_first = lbl_pos["first_event_amount"].apply(_to_float_safe).values.astype(np.float64)
    y_net = lbl_pos["net_amount_3d"].apply(_to_float_safe).values.astype(np.float64)

    params = _get_hyperparams_stage2()
    params["n_estimators"] = N_ESTIMATORS

    model_first = lgb.LGBMRegressor(**params)
    model_first.fit(X, y_first)

    model_net = lgb.LGBMRegressor(**params)
    model_net.fit(X, y_net)

    pred_first = model_first.predict(X)
    pred_net = model_net.predict(X)

    metrics = {
        "stage": "stage2",
        "skipped": False,
        "n_positive": n_pos,
        "first_event": {
            "train_rmse": round(float(np.sqrt(np.mean((y_first - pred_first) ** 2))), 6),
            "train_mae": round(float(np.mean(np.abs(y_first - pred_first))), 6),
            "mean_actual": round(float(np.mean(y_first)), 4),
            "std_actual": round(float(np.std(y_first)), 4),
        },
        "net_amount": {
            "train_rmse": round(float(np.sqrt(np.mean((y_net - pred_net) ** 2))), 6),
            "train_mae": round(float(np.mean(np.abs(y_net - pred_net))), 6),
            "mean_actual": round(float(np.mean(y_net)), 4),
            "std_actual": round(float(np.std(y_net)), 4),
        },
    }

    return (model_first, model_net), metrics


def train_calibrator(fuel_type, stage1_model, feat_aligned, lbl_aligned):
    """Kalibratör eğitimi — %80 train, %20 val split."""
    X = feat_aligned[list(FEATURE_NAMES)].values.astype(np.float64)
    y = lbl_aligned["y_binary"].values.astype(np.int32)
    y_prob = stage1_model.predict_proba(X)[:, 1]

    # Kronolojik split: %80 train, %20 val
    n = len(y)
    split_idx = int(n * 0.8)

    y_prob_train = y_prob[:split_idx]
    y_true_train = y[:split_idx]
    y_prob_val = y_prob[split_idx:]
    y_true_val = y[split_idx:]

    if len(np.unique(y_true_val)) < 2:
        logger.warning("Kalibrasyon %s: Validation set tek sınıf, atlanıyor", fuel_type)
        return None, {"skipped": True, "reason": "single_class_val"}

    try:
        calibrator, cal_metrics = auto_calibrate(
            y_prob_train, y_true_train, y_prob_val, y_true_val
        )
        logger.info(
            "Kalibrasyon %s: method=%s, ECE=%.6f",
            fuel_type, cal_metrics.get("selected_method", "?"), cal_metrics.get("ece", 0),
        )
        return calibrator, cal_metrics
    except Exception as e:
        logger.warning("Kalibrasyon %s hatası: %s", fuel_type, str(e))
        return None, {"skipped": True, "reason": str(e)}


def smoke_test():
    """Eğitilmiş modellerle bugünün verisiyle tek tahmin yap."""
    from src.predictor_v5.predictor import predict_all

    logger.info("=" * 60)
    logger.info("SMOKE TEST — Bugünün verisiyle tahmin")
    logger.info("=" * 60)

    try:
        results = predict_all()
        for fuel_type, result in results.items():
            if "error" in result:
                logger.warning("Smoke %s: HATA — %s", fuel_type, result["error"])
            else:
                prob = result.get("probability", result.get("calibrated_probability", "?"))
                direction = result.get("direction", "?")
                logger.info(
                    "Smoke %s: prob=%.4f, direction=%s ✅",
                    fuel_type, float(prob) if prob != "?" else 0, direction,
                )
        return results
    except Exception as e:
        logger.error("Smoke test hatası: %s", str(e), exc_info=True)
        return {"error": str(e)}


def main():
    """Ana eğitim pipeline'ı."""
    start_time = time.time()

    logger.info("=" * 60)
    logger.info("v5 MODEL EĞİTİMİ — PO İstanbul/Avcılar")
    logger.info("Eğitim dönemi: %s → %s", TRAIN_START, TRAIN_END)
    logger.info("n_estimators: %d (hızlı eğitim)", N_ESTIMATORS)
    logger.info("=" * 60)

    # Model dizini oluştur
    MODEL_PATH.mkdir(parents=True, exist_ok=True)

    all_results = {}

    for fuel_type in FUEL_TYPES:
        fuel_start = time.time()
        logger.info("\n" + "=" * 60)
        logger.info("=== %s EĞİTİMİ BAŞLIYOR ===", fuel_type.upper())
        logger.info("=" * 60)

        try:
            # 1. Feature hesaplama
            logger.info("[1/4] Feature hesaplama: %s → %s", TRAIN_START, TRAIN_END)
            features_df = compute_features_bulk(fuel_type, TRAIN_START, TRAIN_END)
            logger.info("Feature: %d satır, %d kolon", len(features_df), len(features_df.columns))

            # 2. Label hesaplama
            logger.info("[2/4] Label hesaplama: %s → %s", TRAIN_START, TRAIN_END)
            labels_df = compute_labels(fuel_type, TRAIN_START, TRAIN_END)
            logger.info("Label: %d satır", len(labels_df))

            if features_df.empty or labels_df.empty:
                logger.warning("%s: Veri yok, atlanıyor!", fuel_type)
                all_results[fuel_type] = {"status": "skipped", "reason": "no_data"}
                continue

            # y_binary dağılımı
            if "y_binary" in labels_df.columns:
                pos = int(labels_df["y_binary"].sum())
                neg = len(labels_df) - pos
                logger.info("Label dağılımı: pos=%d (%.1f%%), neg=%d", pos, (pos/len(labels_df)*100), neg)

            # 3. Stage-1 eğitimi
            logger.info("[3/4] Stage-1 Binary Classifier eğitimi...")
            stage1_model, stage1_metrics, feat_aligned, lbl_aligned = quick_train_stage1(
                fuel_type, features_df, labels_df
            )
            logger.info(
                "Stage-1 %s: AUC=%.4f, F1=%.4f, Precision=%.4f, Recall=%.4f",
                fuel_type,
                stage1_metrics["train_auc"],
                stage1_metrics["train_f1"],
                stage1_metrics["train_precision"],
                stage1_metrics["train_recall"],
            )

            # 4. Stage-2 eğitimi
            logger.info("[4/4] Stage-2 Dual Regressor eğitimi...")
            (model_first, model_net), stage2_metrics = quick_train_stage2(
                fuel_type, features_df, labels_df
            )

            if not stage2_metrics.get("skipped"):
                logger.info(
                    "Stage-2 %s: first(RMSE=%.4f, MAE=%.4f), net(RMSE=%.4f, MAE=%.4f)",
                    fuel_type,
                    stage2_metrics["first_event"]["train_rmse"],
                    stage2_metrics["first_event"]["train_mae"],
                    stage2_metrics["net_amount"]["train_rmse"],
                    stage2_metrics["net_amount"]["train_mae"],
                )

            # Model dosyalarını kaydet
            paths = _save_models(fuel_type, stage1_model, model_first, model_net)
            logger.info("Model dosyaları kaydedildi: %s", list(paths.values()))

            # Kalibratör eğitimi
            logger.info("Kalibratör eğitimi...")
            calibrator, cal_metrics = train_calibrator(
                fuel_type, stage1_model, feat_aligned, lbl_aligned
            )

            if calibrator is not None:
                cal_path = MODEL_PATH / f"{fuel_type}_calibrator.joblib"
                joblib.dump(calibrator, cal_path)
                logger.info("Kalibratör kaydedildi: %s (method=%s)", cal_path, cal_metrics.get("selected_method"))
                paths["calibrator"] = str(cal_path)

            fuel_elapsed = time.time() - fuel_start
            all_results[fuel_type] = {
                "status": "success",
                "paths": paths,
                "stage1_metrics": stage1_metrics,
                "stage2_metrics": stage2_metrics,
                "calibration_metrics": cal_metrics if calibrator else {"skipped": True},
                "elapsed_seconds": round(fuel_elapsed, 1),
            }

            logger.info("%s tamamlandı: %.1f saniye", fuel_type.upper(), fuel_elapsed)

        except Exception as e:
            logger.error("%s eğitiminde hata: %s", fuel_type, str(e), exc_info=True)
            all_results[fuel_type] = {"status": "error", "error": str(e)}

    # Sonuç özeti
    total_elapsed = time.time() - start_time
    logger.info("\n" + "=" * 60)
    logger.info("EĞİTİM ÖZETİ")
    logger.info("=" * 60)
    logger.info("Toplam süre: %.1f saniye (%.1f dakika)", total_elapsed, total_elapsed / 60)

    for fuel_type, result in all_results.items():
        if result["status"] == "success":
            s1 = result["stage1_metrics"]
            s2 = result["stage2_metrics"]
            logger.info(
                "%s: Stage-1 AUC=%.4f F1=%.4f | Stage-2 %s | %.1f sn",
                fuel_type.upper(),
                s1["train_auc"],
                s1["train_f1"],
                "SKIPPED" if s2.get("skipped") else f"RMSE={s2['first_event']['train_rmse']:.4f}",
                result["elapsed_seconds"],
            )
        else:
            logger.info("%s: %s — %s", fuel_type.upper(), result["status"], result.get("error", result.get("reason")))

    # Model dosyalarını listele
    logger.info("\nModel dosyaları:")
    for f in sorted(MODEL_PATH.glob("*.joblib")):
        logger.info("  %s (%d bytes)", f.name, f.stat().st_size)

    # Sonuçları JSON olarak kaydet
    report_path = PROJECT_ROOT / "train_v5_po_report.json"
    with open(report_path, "w") as f:
        # Convert non-serializable types
        def default_serializer(obj):
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            return str(obj)
        json.dump(all_results, f, indent=2, default=default_serializer)
    logger.info("Rapor kaydedildi: %s", report_path)

    # Smoke test
    logger.info("\n")
    smoke_results = smoke_test()

    logger.info("\n" + "=" * 60)
    logger.info("✅ EĞİTİM TAMAMLANDI")
    logger.info("=" * 60)

    return all_results


if __name__ == "__main__":
    main()
