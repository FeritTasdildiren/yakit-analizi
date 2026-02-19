"""
Predictor v5 — Trainer Module
==============================
İki aşamalı LightGBM eğitim pipeline'ı:
  Stage-1: Binary classifier (zam olacak mı?) — scale_pos_weight ile class imbalance
  Stage-2: Dual regressor (first_event_amount + net_amount_3d) — sadece pozitif örnekler

Kullanim:
    from src.predictor_v5.trainer import train_stage1, train_stage2, train_all
    model, metrics = train_stage1("benzin", features_df, labels_df, cv)
    (m_first, m_net), metrics = train_stage2("benzin", features_df, labels_df, cv, stage1_model)
    results = train_all()
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Tuple

import joblib
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
    FEATURE_NAMES,
    FUEL_TYPES,
    MODEL_DIR,
)
from src.predictor_v5.cv import PurgedWalkForwardCV

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Proje kök dizini (models/v5/ yolu için)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_MODEL_PATH = _PROJECT_ROOT / MODEL_DIR


# ---------------------------------------------------------------------------
# Hyperparameter Fonksiyonları
# ---------------------------------------------------------------------------

def _get_hyperparams_stage1(scale_pos_weight: float = 1.0) -> dict:
    """Stage-1 binary classifier hiperparametreleri.

    Parameters
    ----------
    scale_pos_weight : float
        Negatif/pozitif örnek oranı. Class imbalance handling için KRİTİK.

    Returns
    -------
    dict
        LightGBM parametreleri.
    """
    return {
        "objective": "binary",
        "metric": "binary_logloss",
        "n_estimators": 200,
        "learning_rate": 0.05,
        "max_depth": 6,
        "num_leaves": 31,
        "min_child_samples": 20,
        "scale_pos_weight": scale_pos_weight,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.1,
        "reg_lambda": 0.1,
        "random_state": 42,
        "verbose": -1,
        "n_jobs": -1,
    }


def _get_hyperparams_stage2() -> dict:
    """Stage-2 regressor hiperparametreleri.

    Returns
    -------
    dict
        LightGBM regression parametreleri.
    """
    return {
        "objective": "regression",
        "metric": "rmse",
        "n_estimators": 200,
        "learning_rate": 0.05,
        "max_depth": 6,
        "num_leaves": 31,
        "min_child_samples": 10,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.1,
        "reg_lambda": 0.1,
        "random_state": 42,
        "verbose": -1,
        "n_jobs": -1,
    }


# ---------------------------------------------------------------------------
# Yardımcı Fonksiyonlar
# ---------------------------------------------------------------------------

def _compute_scale_pos_weight(y: np.ndarray) -> float:
    """Binary label'dan scale_pos_weight hesaplar.

    scale_pos_weight = n_negative / n_positive
    Eğer pozitif örnek yoksa 1.0 döner.
    """
    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))
    if n_pos == 0:
        return 1.0
    return n_neg / n_pos


def _align_features_labels(
    features_df: pd.DataFrame,
    labels_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Feature ve label DataFrame'lerini trade_date/run_date üzerinden hizalar.

    Parameters
    ----------
    features_df : pd.DataFrame
        Kolonlar: trade_date, fuel_type, + FEATURE_NAMES
    labels_df : pd.DataFrame
        Kolonlar: run_date, fuel_type, y_binary, first_event_amount, net_amount_3d, ...

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        Hizalanmış (features, labels) DataFrames.
    """
    feat_date_col = "trade_date" if "trade_date" in features_df.columns else "run_date"
    label_date_col = "run_date" if "run_date" in labels_df.columns else "trade_date"

    # Merge on date
    merged = features_df.merge(
        labels_df,
        left_on=feat_date_col,
        right_on=label_date_col,
        how="inner",
        suffixes=("_feat", "_label"),
    )

    if merged.empty:
        return features_df.iloc[:0], labels_df.iloc[:0]

    # Feature kolonlarını al
    feat_result_cols = [feat_date_col]
    for c in FEATURE_NAMES:
        if c in merged.columns:
            feat_result_cols.append(c)
        elif c + "_feat" in merged.columns:
            feat_result_cols.append(c + "_feat")

    # Label kolonlarını al
    label_result_cols = []
    for c in [label_date_col, "y_binary", "first_event_amount", "net_amount_3d"]:
        if c in merged.columns:
            label_result_cols.append(c)
        elif c + "_label" in merged.columns:
            label_result_cols.append(c + "_label")

    features_aligned = merged[feat_result_cols].copy()
    labels_aligned = merged[label_result_cols].copy()

    # Suffix temizle
    features_aligned.columns = [c.replace("_feat", "") for c in features_aligned.columns]
    labels_aligned.columns = [c.replace("_label", "") for c in labels_aligned.columns]

    # Index'leri sıfırla
    features_aligned = features_aligned.reset_index(drop=True)
    labels_aligned = labels_aligned.reset_index(drop=True)

    return features_aligned, labels_aligned


def _extract_dates(features_df: pd.DataFrame) -> list:
    """DataFrame'den sorted date listesi çıkarır."""
    date_col = "trade_date" if "trade_date" in features_df.columns else "run_date"
    dates = features_df[date_col].tolist()
    result = []
    for d in dates:
        if isinstance(d, date) and type(d) is date:
            result.append(d)
        elif hasattr(d, "date"):
            result.append(d.date())
        else:
            result.append(d)
    return sorted(set(result))


def _make_date_mask(df: pd.DataFrame, date_col: str, date_set: set) -> pd.Series:
    """DataFrame'deki tarih kolonunu date_set ile karşılaştırıp boolean mask döner.
    isin kullanarak apply'dan çok daha hızlı."""
    return df[date_col].isin(date_set)


# ---------------------------------------------------------------------------
# Stage-1: Binary Classifier
# ---------------------------------------------------------------------------

def train_stage1(
    fuel_type: str,
    features_df: pd.DataFrame,
    labels_df: pd.DataFrame,
    cv: Optional[PurgedWalkForwardCV] = None,
) -> Tuple[lgb.LGBMClassifier, dict]:
    """Stage-1 binary classifier eğitimi.

    LightGBM binary classifier — pompa fiyatı değişecek mi (y_binary)?
    scale_pos_weight ile class imbalance otomatik telafi edilir.

    Parameters
    ----------
    fuel_type : str
        Yakıt tipi ("benzin", "motorin", "lpg").
    features_df : pd.DataFrame
        Feature DataFrame (trade_date + 35 feature).
    labels_df : pd.DataFrame
        Label DataFrame (run_date + y_binary + ...).
    cv : PurgedWalkForwardCV, optional
        Cross-validation nesnesi. None ise default oluşturulur.

    Returns
    -------
    tuple[lgb.LGBMClassifier, dict]
        (Tüm veriyle eğitilmiş model, CV metrik sözlüğü)
    """
    logger.info("Stage-1 eğitimi başlatılıyor: fuel=%s", fuel_type)

    # Hizala
    feat_aligned, lbl_aligned = _align_features_labels(features_df, labels_df)
    if feat_aligned.empty:
        raise ValueError(f"Hizalama sonrası veri yok: {fuel_type}")

    X = feat_aligned[list(FEATURE_NAMES)].values.astype(np.float64)
    y = lbl_aligned["y_binary"].values.astype(np.int32)

    logger.info(
        "Stage-1 veri: %d örnek, y=1: %d (%.1f%%)",
        len(y), int(np.sum(y)), (np.sum(y) / len(y) * 100) if len(y) > 0 else 0,
    )

    # scale_pos_weight hesapla
    spw = _compute_scale_pos_weight(y)
    logger.info("scale_pos_weight = %.2f", spw)

    # CV
    if cv is None:
        cv = PurgedWalkForwardCV()

    dates = _extract_dates(feat_aligned)
    folds = cv.split(dates)

    date_col = "trade_date" if "trade_date" in feat_aligned.columns else "run_date"

    fold_metrics = []
    params = _get_hyperparams_stage1(scale_pos_weight=spw)

    for fold_idx, (train_date_indices, test_date_indices) in enumerate(folds):
        train_dates_set = set(dates[i] for i in train_date_indices)
        test_dates_set = set(dates[i] for i in test_date_indices)

        train_mask = _make_date_mask(feat_aligned, date_col, train_dates_set)
        test_mask = _make_date_mask(feat_aligned, date_col, test_dates_set)

        X_train = feat_aligned.loc[train_mask, list(FEATURE_NAMES)].values.astype(np.float64)
        y_train = lbl_aligned.loc[train_mask, "y_binary"].values.astype(np.int32)
        X_test = feat_aligned.loc[test_mask, list(FEATURE_NAMES)].values.astype(np.float64)
        y_test = lbl_aligned.loc[test_mask, "y_binary"].values.astype(np.int32)

        if len(X_train) == 0 or len(X_test) == 0:
            logger.warning("Fold %d: Boş train/test, atlanıyor", fold_idx)
            continue

        # Train
        model_fold = lgb.LGBMClassifier(**params)
        model_fold.fit(X_train, y_train)

        # Predict
        y_pred = model_fold.predict(X_test)
        y_prob = model_fold.predict_proba(X_test)[:, 1]

        # Metrics
        auc = roc_auc_score(y_test, y_prob) if len(np.unique(y_test)) > 1 else 0.0
        f1 = f1_score(y_test, y_pred, zero_division=0.0)
        prec = precision_score(y_test, y_pred, zero_division=0.0)
        rec = recall_score(y_test, y_pred, zero_division=0.0)
        acc = accuracy_score(y_test, y_pred)

        fold_metrics.append({
            "fold": fold_idx + 1,
            "auc": round(auc, 4),
            "f1": round(f1, 4),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "accuracy": round(acc, 4),
            "train_size": len(X_train),
            "test_size": len(X_test),
            "pos_ratio_train": round(float(np.mean(y_train)), 4),
            "pos_ratio_test": round(float(np.mean(y_test)), 4),
        })

        logger.info(
            "Fold %d: AUC=%.4f, F1=%.4f, Prec=%.4f, Rec=%.4f (train=%d, test=%d)",
            fold_idx + 1, auc, f1, prec, rec, len(X_train), len(X_test),
        )

    # Ortalama metrikler
    metrics = _aggregate_metrics(fold_metrics, stage="stage1")
    logger.info(
        "Stage-1 CV tamamlandı: mean_auc=%.4f, mean_f1=%.4f, mean_prec=%.4f",
        metrics.get("mean_auc", 0), metrics.get("mean_f1", 0), metrics.get("mean_precision", 0),
    )

    # Son model: TÜM veriyle eğit (deploy modeli)
    final_model = lgb.LGBMClassifier(**params)
    final_model.fit(X, y)

    return final_model, metrics


# ---------------------------------------------------------------------------
# Stage-2: Dual Regressor
# ---------------------------------------------------------------------------

def train_stage2(
    fuel_type: str,
    features_df: pd.DataFrame,
    labels_df: pd.DataFrame,
    cv: Optional[PurgedWalkForwardCV] = None,
    stage1_model: Optional[lgb.LGBMClassifier] = None,
) -> Tuple[Tuple[Optional[lgb.LGBMRegressor], Optional[lgb.LGBMRegressor]], dict]:
    """Stage-2 dual regressor eğitimi — sadece pozitif örneklerle.

    İki regressor:
      1. first_event_amount: İlk fiyat değişim miktarı (TL/L)
      2. net_amount_3d: 3 günlük net değişim (TL/L)

    Sadece y_binary=1 olan örneklerle eğitilir.

    Parameters
    ----------
    fuel_type : str
        Yakıt tipi.
    features_df : pd.DataFrame
        Feature DataFrame.
    labels_df : pd.DataFrame
        Label DataFrame.
    cv : PurgedWalkForwardCV, optional
        Cross-validation nesnesi.
    stage1_model : lgb.LGBMClassifier, optional
        Stage-1 model (kullanılmıyor, uyumluluk için).

    Returns
    -------
    tuple[tuple[LGBMRegressor|None, LGBMRegressor|None], dict]
        ((model_first, model_net), metrics)
        Pozitif örnek < 20 ise (None, None) döner.
    """
    logger.info("Stage-2 eğitimi başlatılıyor: fuel=%s", fuel_type)

    # Hizala
    feat_aligned, lbl_aligned = _align_features_labels(features_df, labels_df)
    if feat_aligned.empty:
        logger.warning("Stage-2: Hizalama sonrası veri yok: %s", fuel_type)
        return (None, None), {"stage": "stage2", "skipped": True, "reason": "no_data"}

    # Sadece y_binary=1 örnekler
    pos_mask = lbl_aligned["y_binary"] == 1
    feat_pos = feat_aligned.loc[pos_mask].copy().reset_index(drop=True)
    lbl_pos = lbl_aligned.loc[pos_mask].copy().reset_index(drop=True)

    n_pos = len(feat_pos)
    logger.info("Stage-2 pozitif örnek sayısı: %d", n_pos)

    if n_pos < 20:
        logger.warning(
            "Stage-2 atlanıyor: Pozitif örnek sayısı (%d) < 20 minimum", n_pos
        )
        return (None, None), {
            "stage": "stage2",
            "skipped": True,
            "reason": "insufficient_positive_samples",
            "n_positive": n_pos,
        }

    X = feat_pos[list(FEATURE_NAMES)].values.astype(np.float64)

    def _to_float_safe(v):
        if v is None:
            return 0.0
        return float(v)

    y_first = lbl_pos["first_event_amount"].apply(_to_float_safe).values.astype(np.float64)
    y_net = lbl_pos["net_amount_3d"].apply(_to_float_safe).values.astype(np.float64)

    # CV (pozitif örneklerin tarihlerine göre)
    if cv is None:
        cv = PurgedWalkForwardCV()

    dates = _extract_dates(feat_pos)
    folds = cv.split(dates)

    date_col = "trade_date" if "trade_date" in feat_pos.columns else "run_date"

    params = _get_hyperparams_stage2()
    fold_metrics_first = []
    fold_metrics_net = []

    for fold_idx, (train_date_indices, test_date_indices) in enumerate(folds):
        train_dates_set = set(dates[i] for i in train_date_indices)
        test_dates_set = set(dates[i] for i in test_date_indices)

        train_mask = _make_date_mask(feat_pos, date_col, train_dates_set)
        test_mask = _make_date_mask(feat_pos, date_col, test_dates_set)

        X_train = feat_pos.loc[train_mask, list(FEATURE_NAMES)].values.astype(np.float64)
        X_test = feat_pos.loc[test_mask, list(FEATURE_NAMES)].values.astype(np.float64)

        y_first_train = lbl_pos.loc[train_mask, "first_event_amount"].apply(_to_float_safe).values.astype(np.float64)
        y_first_test = lbl_pos.loc[test_mask, "first_event_amount"].apply(_to_float_safe).values.astype(np.float64)
        y_net_train = lbl_pos.loc[train_mask, "net_amount_3d"].apply(_to_float_safe).values.astype(np.float64)
        y_net_test = lbl_pos.loc[test_mask, "net_amount_3d"].apply(_to_float_safe).values.astype(np.float64)

        if len(X_train) < 5 or len(X_test) == 0:
            logger.warning("Stage-2 Fold %d: Yetersiz veri, atlanıyor", fold_idx)
            continue

        # first_event_amount regressor
        model_first_fold = lgb.LGBMRegressor(**params)
        model_first_fold.fit(X_train, y_first_train)
        pred_first = model_first_fold.predict(X_test)

        rmse_first = float(np.sqrt(np.mean((y_first_test - pred_first) ** 2)))
        mae_first = float(np.mean(np.abs(y_first_test - pred_first)))

        fold_metrics_first.append({
            "fold": fold_idx + 1,
            "rmse": round(rmse_first, 6),
            "mae": round(mae_first, 6),
            "train_size": len(X_train),
            "test_size": len(X_test),
        })

        # net_amount_3d regressor
        model_net_fold = lgb.LGBMRegressor(**params)
        model_net_fold.fit(X_train, y_net_train)
        pred_net = model_net_fold.predict(X_test)

        rmse_net = float(np.sqrt(np.mean((y_net_test - pred_net) ** 2)))
        mae_net = float(np.mean(np.abs(y_net_test - pred_net)))

        fold_metrics_net.append({
            "fold": fold_idx + 1,
            "rmse": round(rmse_net, 6),
            "mae": round(mae_net, 6),
            "train_size": len(X_train),
            "test_size": len(X_test),
        })

        logger.info(
            "Stage-2 Fold %d: first(RMSE=%.4f, MAE=%.4f) net(RMSE=%.4f, MAE=%.4f)",
            fold_idx + 1, rmse_first, mae_first, rmse_net, mae_net,
        )

    # Ortalama metrikler
    metrics = _aggregate_stage2_metrics(fold_metrics_first, fold_metrics_net)

    # Son model: TÜM pozitif örneklerle eğit (deploy modeli)
    final_model_first = lgb.LGBMRegressor(**params)
    final_model_first.fit(X, y_first)

    final_model_net = lgb.LGBMRegressor(**params)
    final_model_net.fit(X, y_net)

    logger.info("Stage-2 eğitimi tamamlandı: fuel=%s", fuel_type)

    return (final_model_first, final_model_net), metrics


# ---------------------------------------------------------------------------
# Metrik Aggregation
# ---------------------------------------------------------------------------

def _aggregate_metrics(fold_metrics: list, stage: str = "stage1") -> dict:
    """Fold metriklerini toplar."""
    if not fold_metrics:
        return {
            "stage": stage,
            "n_folds": 0,
            "folds": [],
            "mean_auc": 0.0,
            "mean_f1": 0.0,
            "mean_precision": 0.0,
            "mean_recall": 0.0,
            "mean_accuracy": 0.0,
        }

    n = len(fold_metrics)
    return {
        "stage": stage,
        "n_folds": n,
        "folds": fold_metrics,
        "mean_auc": round(sum(f["auc"] for f in fold_metrics) / n, 4),
        "mean_f1": round(sum(f["f1"] for f in fold_metrics) / n, 4),
        "mean_precision": round(sum(f["precision"] for f in fold_metrics) / n, 4),
        "mean_recall": round(sum(f["recall"] for f in fold_metrics) / n, 4),
        "mean_accuracy": round(sum(f["accuracy"] for f in fold_metrics) / n, 4),
    }


def _aggregate_stage2_metrics(
    fold_metrics_first: list,
    fold_metrics_net: list,
) -> dict:
    """Stage-2 dual regressor metriklerini toplar."""
    result = {"stage": "stage2", "skipped": False}

    if fold_metrics_first:
        n = len(fold_metrics_first)
        result["first_event"] = {
            "n_folds": n,
            "folds": fold_metrics_first,
            "mean_rmse": round(sum(f["rmse"] for f in fold_metrics_first) / n, 6),
            "mean_mae": round(sum(f["mae"] for f in fold_metrics_first) / n, 6),
        }
    else:
        result["first_event"] = {"n_folds": 0, "folds": [], "mean_rmse": 0.0, "mean_mae": 0.0}

    if fold_metrics_net:
        n = len(fold_metrics_net)
        result["net_amount"] = {
            "n_folds": n,
            "folds": fold_metrics_net,
            "mean_rmse": round(sum(f["rmse"] for f in fold_metrics_net) / n, 6),
            "mean_mae": round(sum(f["mae"] for f in fold_metrics_net) / n, 6),
        }
    else:
        result["net_amount"] = {"n_folds": 0, "folds": [], "mean_rmse": 0.0, "mean_mae": 0.0}

    return result


# ---------------------------------------------------------------------------
# train_all — Full Pipeline
# ---------------------------------------------------------------------------

def train_all(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict:
    """3 yakıt tipi x 3 model = 9 model dosyası üretir.

    Her yakıt tipi için:
      1. {fuel}_stage1.joblib     — Binary classifier
      2. {fuel}_stage2_first.joblib — first_event_amount regressor
      3. {fuel}_stage2_net.joblib   — net_amount_3d regressor

    Modeller models/v5/ altına kaydedilir.
    CV metrikleri sadece değerlendirme amaçlıdır — son model TÜM veriyle eğitilir.

    Parameters
    ----------
    start_date : date, optional
        Veri başlangıç tarihi. None ise 2 yıl öncesi.
    end_date : date, optional
        Veri bitiş tarihi. None ise bugün.

    Returns
    -------
    dict
        Her yakıt için model dosya yolları ve metrikler.
    """
    from src.predictor_v5.features import compute_features_bulk
    from src.predictor_v5.labels import compute_labels

    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=730)

    # Model dizini oluştur
    _MODEL_PATH.mkdir(parents=True, exist_ok=True)

    cv = PurgedWalkForwardCV()
    results = {}

    for fuel_type in FUEL_TYPES:
        logger.info("=== %s eğitimi başlıyor ===", fuel_type.upper())

        try:
            # Veri çek
            features_df = compute_features_bulk(fuel_type, start_date, end_date)
            labels_df = compute_labels(fuel_type, start_date, end_date)

            if features_df.empty or labels_df.empty:
                logger.warning("%s: Veri yok, atlanıyor", fuel_type)
                results[fuel_type] = {"status": "skipped", "reason": "no_data"}
                continue

            # Stage-1: Binary Classifier
            stage1_model, stage1_metrics = train_stage1(
                fuel_type, features_df, labels_df, cv
            )

            # Stage-2: Dual Regressor
            (model_first, model_net), stage2_metrics = train_stage2(
                fuel_type, features_df, labels_df, cv, stage1_model
            )

            # Model dosyalarını kaydet
            paths = _save_models(
                fuel_type, stage1_model, model_first, model_net
            )

            results[fuel_type] = {
                "status": "success",
                "paths": paths,
                "stage1_metrics": stage1_metrics,
                "stage2_metrics": stage2_metrics,
                "data_range": {
                    "start": str(start_date),
                    "end": str(end_date),
                    "n_features": len(features_df),
                    "n_labels": len(labels_df),
                },
            }

            logger.info("%s eğitimi tamamlandı: %s", fuel_type, paths)

        except Exception as e:
            logger.error("%s eğitiminde hata: %s", fuel_type, str(e), exc_info=True)
            results[fuel_type] = {"status": "error", "error": str(e)}

    _log_summary(results)
    return results


def _save_models(
    fuel_type: str,
    stage1_model: lgb.LGBMClassifier,
    model_first: Optional[lgb.LGBMRegressor],
    model_net: Optional[lgb.LGBMRegressor],
) -> dict:
    """Modelleri joblib ile kaydet."""
    _MODEL_PATH.mkdir(parents=True, exist_ok=True)
    paths = {}

    s1_path = _MODEL_PATH / f"{fuel_type}_stage1.joblib"
    joblib.dump(stage1_model, s1_path)
    paths["stage1"] = str(s1_path)
    logger.info("Kaydedildi: %s", s1_path)

    if model_first is not None:
        s2f_path = _MODEL_PATH / f"{fuel_type}_stage2_first.joblib"
        joblib.dump(model_first, s2f_path)
        paths["stage2_first"] = str(s2f_path)
        logger.info("Kaydedildi: %s", s2f_path)

    if model_net is not None:
        s2n_path = _MODEL_PATH / f"{fuel_type}_stage2_net.joblib"
        joblib.dump(model_net, s2n_path)
        paths["stage2_net"] = str(s2n_path)
        logger.info("Kaydedildi: %s", s2n_path)

    return paths


def _log_summary(results: dict) -> None:
    """Eğitim sonuç özeti loglar."""
    logger.info("=" * 60)
    logger.info("EĞİTİM ÖZETİ")
    logger.info("=" * 60)

    for fuel_type, result in results.items():
        status = result.get("status", "unknown")
        if status == "success":
            s1 = result.get("stage1_metrics", {})
            s2 = result.get("stage2_metrics", {})
            s2_str = "SKIPPED" if s2.get("skipped") else "RMSE={:.4f}".format(
                s2.get("first_event", {}).get("mean_rmse", 0)
            )
            logger.info(
                "%s: Stage-1 AUC=%.4f F1=%.4f | Stage-2 %s",
                fuel_type.upper(),
                s1.get("mean_auc", 0),
                s1.get("mean_f1", 0),
                s2_str,
            )
        elif status == "skipped":
            logger.info("%s: Atlandı — %s", fuel_type.upper(), result.get("reason"))
        else:
            logger.info("%s: Hata — %s", fuel_type.upper(), result.get("error"))

    logger.info("=" * 60)
