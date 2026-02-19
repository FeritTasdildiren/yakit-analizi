"""
Predictor v5 — End-to-End Backtest Runner
==========================================
Purged walk-forward CV ile gerçek backtest:
  eğit → kalibre → tahmin → karşılaştır → metrik raporla.

Kullanım:
    from src.predictor_v5.backtest import run_backtest, run_full_backtest
    result = run_backtest("benzin")
    all_results = run_full_backtest()
    report = generate_backtest_report(all_results)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional, List

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from src.predictor_v5.config import (
    EMBARGO_DAYS,
    FEATURE_NAMES,
    FUEL_TYPES,
    MIN_TRAIN_DAYS,
    STEP_DAYS,
    TEST_DAYS,
)
from src.predictor_v5.cv import PurgedWalkForwardCV
from src.predictor_v5.calibration import (
    auto_calibrate,
    apply_calibration,
    evaluate_calibration,
)
from src.predictor_v5.trainer import (
    _align_features_labels,
    _compute_scale_pos_weight,
    _extract_dates,
    _get_hyperparams_stage1,
    _get_hyperparams_stage2,
    _make_date_mask,
)

logger = logging.getLogger(__name__)

DB_DSN = "postgresql://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi"

# Stage-2 minimum pozitif örnek eşiği
_MIN_POSITIVE_STAGE2 = 10


# ---------------------------------------------------------------------------
# Stage-1 Metrik Hesaplama
# ---------------------------------------------------------------------------

def _compute_stage1_metrics(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    y_pred: np.ndarray,
) -> dict:
    """Stage-1 binary classification metrikleri.

    Parameters
    ----------
    y_true : array-like
        Gerçek binary label (0/1).
    y_prob : array-like
        Kalibre edilmiş olasılıklar [0, 1].
    y_pred : array-like
        Binary tahminler (0/1).

    Returns
    -------
    dict
        auc, f1, precision, recall, accuracy, ece
    """
    y_true = np.asarray(y_true, dtype=np.int32).ravel()
    y_prob = np.asarray(y_prob, dtype=np.float64).ravel()
    y_pred = np.asarray(y_pred, dtype=np.int32).ravel()

    # AUC: tek sınıf varsa hesaplanamaz
    try:
        if len(np.unique(y_true)) > 1:
            auc = roc_auc_score(y_true, y_prob)
        else:
            auc = 0.0
    except Exception:
        auc = 0.0

    f1 = f1_score(y_true, y_pred, zero_division=0.0)
    prec = precision_score(y_true, y_pred, zero_division=0.0)
    rec = recall_score(y_true, y_pred, zero_division=0.0)
    acc = accuracy_score(y_true, y_pred)

    # ECE
    cal_eval = evaluate_calibration(y_prob, y_true)
    ece = cal_eval["ece"]

    return {
        "auc": round(float(auc), 4),
        "f1": round(float(f1), 4),
        "precision": round(float(prec), 4),
        "recall": round(float(rec), 4),
        "accuracy": round(float(acc), 4),
        "ece": round(float(ece), 6),
    }


# ---------------------------------------------------------------------------
# Stage-2 Metrik Hesaplama
# ---------------------------------------------------------------------------

def _compute_stage2_metrics(
    y_true_first: np.ndarray,
    y_pred_first: np.ndarray,
    y_true_net: np.ndarray,
    y_pred_net: np.ndarray,
) -> dict:
    """Stage-2 regresyon metrikleri.

    Parameters
    ----------
    y_true_first : array-like
        Gerçek first_event_amount değerleri.
    y_pred_first : array-like
        Tahmin edilen first_event_amount değerleri.
    y_true_net : array-like
        Gerçek net_amount_3d değerleri.
    y_pred_net : array-like
        Tahmin edilen net_amount_3d değerleri.

    Returns
    -------
    dict
        mae_first_event, rmse_first_event, mae_net_amount, rmse_net_amount,
        directional_accuracy
    """
    y_true_first = np.asarray(y_true_first, dtype=np.float64).ravel()
    y_pred_first = np.asarray(y_pred_first, dtype=np.float64).ravel()
    y_true_net = np.asarray(y_true_net, dtype=np.float64).ravel()
    y_pred_net = np.asarray(y_pred_net, dtype=np.float64).ravel()

    # First event amount
    mae_first = float(np.mean(np.abs(y_true_first - y_pred_first)))
    rmse_first = float(np.sqrt(np.mean((y_true_first - y_pred_first) ** 2)))

    # Net amount 3d
    mae_net = float(np.mean(np.abs(y_true_net - y_pred_net)))
    rmse_net = float(np.sqrt(np.mean((y_true_net - y_pred_net) ** 2)))

    # Directional accuracy: tahmin ve gerçek aynı yönde mi?
    if len(y_true_net) > 0:
        correct_dir = np.sum(np.sign(y_true_net) == np.sign(y_pred_net))
        dir_acc = float(correct_dir / len(y_true_net))
    else:
        dir_acc = 0.0

    return {
        "mae_first_event": round(mae_first, 6),
        "rmse_first_event": round(rmse_first, 6),
        "mae_net_amount": round(mae_net, 6),
        "rmse_net_amount": round(rmse_net, 6),
        "directional_accuracy": round(dir_acc, 4),
    }


# ---------------------------------------------------------------------------
# _to_float_safe — None → 0.0 güvenli dönüşüm
# ---------------------------------------------------------------------------

def _to_float_safe(v) -> float:
    """None/Decimal/str → float güvenli dönüşüm."""
    if v is None:
        return 0.0
    return float(v)


# ---------------------------------------------------------------------------
# Tek Yakıt Tipi Backtest
# ---------------------------------------------------------------------------

def run_backtest(
    fuel_type: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db_url: Optional[str] = None,
    features_df: Optional[pd.DataFrame] = None,
    labels_df: Optional[pd.DataFrame] = None,
) -> dict:
    """Tek yakıt tipi için tam walk-forward backtest.

    Akış (her fold):
    1. Train/test split (PurgedWalkForwardCV)
    2. Stage-1 binary classifier eğit
    3. Train set'in son %25'ini validation olarak ayır → kalibrasyon
    4. Test set üzerinde tahmin + kalibrasyon uygula
    5. Stage-1 metrikleri hesapla
    6. Pozitif örneklerde Stage-2 regressor eğit + tahmin
    7. Stage-2 metrikleri hesapla

    Parameters
    ----------
    fuel_type : str
        Yakıt tipi ("benzin", "motorin", "lpg").
    start_date : date, optional
        Veri başlangıç tarihi. None ise 2 yıl öncesi.
    end_date : date, optional
        Veri bitiş tarihi. None ise bugün.
    db_url : str, optional
        DB bağlantı URL'i. None ise default.
    features_df : DataFrame, optional
        Önceden hesaplanmış feature'lar. None ise DB'den çekilir.
    labels_df : DataFrame, optional
        Önceden hesaplanmış label'lar. None ise DB'den çekilir.

    Returns
    -------
    dict
        Backtest sonuçları (stage1, stage2 metrikleri, fold detayları, vs.)
    """
    dsn = db_url or DB_DSN

    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=730)

    logger.info(
        "Backtest başlatılıyor: fuel=%s, range=%s..%s",
        fuel_type, start_date, end_date,
    )

    # --- Veri hazırlığı ---
    if features_df is None:
        from src.predictor_v5.features import compute_features_bulk
        features_df = compute_features_bulk(fuel_type, start_date, end_date, dsn=dsn)
    if labels_df is None:
        from src.predictor_v5.labels import compute_labels
        labels_df = compute_labels(fuel_type, start_date, end_date, dsn=dsn)

    if features_df.empty or labels_df.empty:
        logger.warning("Backtest: Veri yok, fuel=%s", fuel_type)
        return _empty_backtest_result(fuel_type, "no_data")

    # Hizala
    feat_aligned, lbl_aligned = _align_features_labels(features_df, labels_df)
    if feat_aligned.empty:
        return _empty_backtest_result(fuel_type, "alignment_failed")

    date_col = "trade_date" if "trade_date" in feat_aligned.columns else "run_date"
    dates = _extract_dates(feat_aligned)

    logger.info("Backtest veri: %d örnek, %d benzersiz tarih", len(feat_aligned), len(dates))

    # --- CV fold'ları ---
    cv = PurgedWalkForwardCV()
    folds = cv.split(dates)

    if not folds:
        logger.warning("Backtest: Yeterli veri yok, fold oluşturulamadı")
        return _empty_backtest_result(fuel_type, "insufficient_data_for_folds")

    logger.info("Backtest: %d fold oluşturuldu", len(folds))

    # --- Fold döngüsü ---
    fold_details: List[dict] = []
    all_predictions: List[dict] = []

    for fold_idx, (train_date_indices, test_date_indices) in enumerate(folds):
        train_dates_set = set(dates[i] for i in train_date_indices)
        test_dates_set = set(dates[i] for i in test_date_indices)

        train_mask = _make_date_mask(feat_aligned, date_col, train_dates_set)
        test_mask = _make_date_mask(feat_aligned, date_col, test_dates_set)

        X_train_df = feat_aligned.loc[train_mask].copy()
        y_train_df = lbl_aligned.loc[train_mask].copy()
        X_test_df = feat_aligned.loc[test_mask].copy()
        y_test_df = lbl_aligned.loc[test_mask].copy()

        if X_train_df.empty or X_test_df.empty:
            logger.warning("Fold %d: Boş train/test, atlanıyor", fold_idx)
            continue

        X_train = X_train_df[list(FEATURE_NAMES)].values.astype(np.float64)
        y_train = y_train_df["y_binary"].values.astype(np.int32)
        X_test = X_test_df[list(FEATURE_NAMES)].values.astype(np.float64)
        y_test = y_test_df["y_binary"].values.astype(np.int32)

        test_dates_list = X_test_df[date_col].tolist()

        # --- Stage-1: Binary Classifier ---
        spw = _compute_scale_pos_weight(y_train)
        params_s1 = _get_hyperparams_stage1(scale_pos_weight=spw)

        model_s1 = lgb.LGBMClassifier(**params_s1)
        model_s1.fit(X_train, y_train)

        y_prob_raw = model_s1.predict_proba(X_test)[:, 1]

        # --- Kalibrasyon ---
        # Train set'in son %25'ini validation olarak ayır
        n_train = len(X_train)
        val_size = max(int(n_train * 0.25), 10)
        val_start = n_train - val_size

        X_val = X_train[val_start:]
        y_val = y_train[val_start:]
        y_prob_val_raw = model_s1.predict_proba(X_val)[:, 1]

        try:
            calibrator, cal_metrics = auto_calibrate(
                y_prob_val_raw, y_val, y_prob_raw, y_test
            )
            y_prob_cal = apply_calibration(calibrator, y_prob_raw)
            cal_method = cal_metrics.get("selected_method", "unknown")
        except Exception as e:
            logger.warning("Fold %d: Kalibrasyon başarısız (%s), ham olasılık kullanılıyor", fold_idx, str(e))
            y_prob_cal = y_prob_raw
            cal_method = "none"

        y_pred = (y_prob_cal >= 0.5).astype(np.int32)

        # Stage-1 metrikleri
        s1_metrics = _compute_stage1_metrics(y_test, y_prob_cal, y_pred)

        # --- Stage-2: Dual Regressor (sadece pozitifler) ---
        s2_metrics = None
        pos_mask_test = y_test_df["y_binary"].values == 1
        pos_mask_train = y_train_df["y_binary"].values == 1

        n_pos_train = int(np.sum(pos_mask_train))
        n_pos_test = int(np.sum(pos_mask_test))

        if n_pos_train >= _MIN_POSITIVE_STAGE2 and n_pos_test >= 1:
            try:
                X_train_pos = X_train[pos_mask_train]
                X_test_pos = X_test[pos_mask_test]

                y_first_train = y_train_df.loc[pos_mask_train, "first_event_amount"].apply(_to_float_safe).values
                y_first_test = y_test_df.loc[pos_mask_test, "first_event_amount"].apply(_to_float_safe).values
                y_net_train = y_train_df.loc[pos_mask_train, "net_amount_3d"].apply(_to_float_safe).values
                y_net_test = y_test_df.loc[pos_mask_test, "net_amount_3d"].apply(_to_float_safe).values

                params_s2 = _get_hyperparams_stage2()

                # First event amount regressor
                model_first = lgb.LGBMRegressor(**params_s2)
                model_first.fit(X_train_pos, y_first_train)
                pred_first = model_first.predict(X_test_pos)

                # Net amount 3d regressor
                model_net = lgb.LGBMRegressor(**params_s2)
                model_net.fit(X_train_pos, y_net_train)
                pred_net = model_net.predict(X_test_pos)

                s2_metrics = _compute_stage2_metrics(
                    y_first_test, pred_first, y_net_test, pred_net
                )
                s2_metrics["n_positive_train"] = n_pos_train
                s2_metrics["n_positive_test"] = n_pos_test

            except Exception as e:
                logger.warning("Fold %d: Stage-2 başarısız: %s", fold_idx, str(e))
                s2_metrics = None

        # --- Fold detayları ---
        fold_detail = {
            "fold": fold_idx + 1,
            "train_size": len(X_train),
            "test_size": len(X_test),
            "train_dates": f"{dates[train_date_indices[0]]}..{dates[train_date_indices[-1]]}",
            "test_dates": f"{dates[test_date_indices[0]]}..{dates[test_date_indices[-1]]}",
            "pos_ratio_train": round(float(np.mean(y_train)), 4),
            "pos_ratio_test": round(float(np.mean(y_test)), 4),
            "calibration_method": cal_method,
            "stage1": s1_metrics,
            "stage2": s2_metrics,
        }
        fold_details.append(fold_detail)

        # --- Predictions vs Actuals ---
        for i, td in enumerate(test_dates_list):
            entry = {
                "date": str(td),
                "fold": fold_idx + 1,
                "y_true": int(y_test[i]),
                "y_prob": round(float(y_prob_cal[i]), 4),
                "y_pred": int(y_pred[i]),
            }
            all_predictions.append(entry)

        logger.info(
            "Fold %d: AUC=%.4f F1=%.4f Prec=%.4f Rec=%.4f ECE=%.4f | S2=%s",
            fold_idx + 1,
            s1_metrics["auc"], s1_metrics["f1"],
            s1_metrics["precision"], s1_metrics["recall"],
            s1_metrics["ece"],
            "OK" if s2_metrics else "SKIP",
        )

    # --- Sonuçları birleştir ---
    return _aggregate_backtest_results(fuel_type, fold_details, all_predictions)


# ---------------------------------------------------------------------------
# Sonuç Aggregation
# ---------------------------------------------------------------------------

def _aggregate_backtest_results(
    fuel_type: str,
    fold_details: List[dict],
    predictions: List[dict],
) -> dict:
    """Fold sonuçlarını mean ± std olarak birleştirir."""
    if not fold_details:
        return _empty_backtest_result(fuel_type, "no_valid_folds")

    n_folds = len(fold_details)

    # Stage-1 aggregation
    s1_keys = ["auc", "f1", "precision", "recall", "accuracy", "ece"]
    s1_agg = {}
    for key in s1_keys:
        vals = [f["stage1"][key] for f in fold_details if f["stage1"]]
        if vals:
            s1_agg[f"{key}_mean"] = round(float(np.mean(vals)), 4)
            s1_agg[f"{key}_std"] = round(float(np.std(vals)), 4)
        else:
            s1_agg[f"{key}_mean"] = 0.0
            s1_agg[f"{key}_std"] = 0.0

    # Stage-2 aggregation (fold'lar arası)
    s2_folds = [f for f in fold_details if f.get("stage2") is not None]
    s2_agg = {}
    if s2_folds:
        s2_keys = ["mae_first_event", "rmse_first_event", "mae_net_amount",
                    "rmse_net_amount", "directional_accuracy"]
        for key in s2_keys:
            vals = [f["stage2"][key] for f in s2_folds if key in f["stage2"]]
            if vals:
                s2_agg[f"{key}_mean" if "mean" not in key else key] = round(float(np.mean(vals)), 6)
                s2_agg[f"{key}_std" if "std" not in key else f"{key}_s"] = round(float(np.std(vals)), 6)
            else:
                s2_agg[f"{key}_mean" if "mean" not in key else key] = 0.0
                s2_agg[f"{key}_std" if "std" not in key else f"{key}_s"] = 0.0

        total_pos = sum(f["stage2"].get("n_positive_test", 0) for f in s2_folds)
        s2_agg["n_positive_samples"] = total_pos
        s2_agg["n_folds_with_stage2"] = len(s2_folds)
    else:
        s2_agg = {
            "skipped": True,
            "reason": "insufficient_positive_samples",
            "n_positive_samples": 0,
        }

    return {
        "fuel_type": fuel_type,
        "n_folds": n_folds,
        "stage1": s1_agg,
        "stage2": s2_agg,
        "fold_details": fold_details,
        "predictions_vs_actuals": predictions,
    }


def _empty_backtest_result(fuel_type: str, reason: str) -> dict:
    """Boş backtest sonucu."""
    return {
        "fuel_type": fuel_type,
        "n_folds": 0,
        "stage1": {
            "auc_mean": 0.0, "auc_std": 0.0,
            "f1_mean": 0.0, "f1_std": 0.0,
            "precision_mean": 0.0, "precision_std": 0.0,
            "recall_mean": 0.0, "recall_std": 0.0,
            "accuracy_mean": 0.0, "accuracy_std": 0.0,
            "ece_mean": 0.0, "ece_std": 0.0,
        },
        "stage2": {"skipped": True, "reason": reason, "n_positive_samples": 0},
        "fold_details": [],
        "predictions_vs_actuals": [],
        "error": reason,
    }


# ---------------------------------------------------------------------------
# Tüm Yakıt Tipleri Backtest
# ---------------------------------------------------------------------------

def run_full_backtest(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db_url: Optional[str] = None,
) -> dict:
    """3 yakıt tipi için tam backtest.

    Parameters
    ----------
    start_date : date, optional
        Başlangıç tarihi. None ise 2 yıl öncesi.
    end_date : date, optional
        Bitiş tarihi. None ise bugün.
    db_url : str, optional
        DB bağlantı URL'i.

    Returns
    -------
    dict
        {fuel_type: backtest_result} mapping.
    """
    results = {}
    for fuel_type in FUEL_TYPES:
        logger.info("=== %s backtest başlıyor ===", fuel_type.upper())
        try:
            results[fuel_type] = run_backtest(
                fuel_type,
                start_date=start_date,
                end_date=end_date,
                db_url=db_url,
            )
        except Exception as e:
            logger.error("%s backtest hatası: %s", fuel_type, str(e), exc_info=True)
            results[fuel_type] = _empty_backtest_result(fuel_type, str(e))

    return results


# ---------------------------------------------------------------------------
# Markdown Rapor
# ---------------------------------------------------------------------------

def generate_backtest_report(results: dict) -> str:
    """Backtest sonuçlarını Markdown formatında rapor.

    Parameters
    ----------
    results : dict
        run_full_backtest() veya {fuel_type: run_backtest()} çıktısı.

    Returns
    -------
    str
        Markdown formatında detaylı backtest raporu.
    """
    lines = [
        "# Predictor v5 — Backtest Raporu",
        "",
        f"**Tarih:** {date.today()}",
        f"**Yakıt Tipleri:** {', '.join(results.keys())}",
        "",
    ]

    for fuel_type, result in results.items():
        lines.append(f"## {fuel_type.upper()}")
        lines.append("")

        if result.get("error"):
            lines.append(f"**Hata:** {result['error']}")
            lines.append("")
            continue

        n_folds = result.get("n_folds", 0)
        lines.append(f"**Fold Sayısı:** {n_folds}")
        lines.append("")

        # Stage-1 Metrikleri
        s1 = result.get("stage1", {})
        lines.append("### Stage-1: Binary Classifier")
        lines.append("")
        lines.append("| Metrik | Ortalama | Std |")
        lines.append("|--------|----------|-----|")

        for key in ["auc", "f1", "precision", "recall", "accuracy", "ece"]:
            mean_val = s1.get(f"{key}_mean", 0.0)
            std_val = s1.get(f"{key}_std", 0.0)
            lines.append(f"| {key.upper()} | {mean_val:.4f} | ±{std_val:.4f} |")

        lines.append("")

        # Stage-2 Metrikleri
        s2 = result.get("stage2", {})
        if s2.get("skipped"):
            lines.append(f"### Stage-2: Regressor — ATLANMIŞ ({s2.get('reason', 'N/A')})")
        else:
            lines.append("### Stage-2: Dual Regressor")
            lines.append("")
            lines.append(f"**Pozitif Örnek Sayısı:** {s2.get('n_positive_samples', 0)}")
            lines.append(f"**Stage-2 Fold Sayısı:** {s2.get('n_folds_with_stage2', 0)}")
            lines.append("")
            lines.append("| Metrik | Değer |")
            lines.append("|--------|-------|")

            for key in ["mae_first_event", "rmse_first_event", "mae_net_amount",
                         "rmse_net_amount", "directional_accuracy"]:
                mean_key = f"{key}_mean" if f"{key}_mean" in s2 else key
                val = s2.get(mean_key, 0.0)
                lines.append(f"| {key} | {val:.6f} |")

        lines.append("")

        # Fold Detayları
        lines.append("### Fold Detayları")
        lines.append("")
        lines.append("| Fold | Train | Test | AUC | F1 | Prec | Rec | ECE | Cal | S2 |")
        lines.append("|------|-------|------|-----|----|----- |-----|-----|-----|------|")

        for fd in result.get("fold_details", []):
            s1_f = fd.get("stage1", {})
            s2_f = fd.get("stage2")
            s2_str = "OK" if s2_f else "SKIP"
            lines.append(
                f"| {fd['fold']} "
                f"| {fd['train_size']} "
                f"| {fd['test_size']} "
                f"| {s1_f.get('auc', 0):.4f} "
                f"| {s1_f.get('f1', 0):.4f} "
                f"| {s1_f.get('precision', 0):.4f} "
                f"| {s1_f.get('recall', 0):.4f} "
                f"| {s1_f.get('ece', 0):.4f} "
                f"| {fd.get('calibration_method', 'N/A')} "
                f"| {s2_str} |"
            )

        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)
