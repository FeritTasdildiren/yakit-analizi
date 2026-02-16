"""
ML Model Egitim Pipeline (Katman 4).

LightGBM siniflandirma (3-class: Zam/Sabit/Indirim) ve regresyon
(TL/L degisim buyuklugu) modellerini egitir.

Egitim Stratejisi:
  - TimeSeriesSplit: n_splits=5, test_size=30, gap=7
  - ASLA random shuffle kullanilmaz (data leakage riski).
  - Class weights: Zam sinifi 8-12x agirlik (dengesiz veri).
  - Hedef metrik: Precision(Zam) >= 0.75
  - Model kayit: joblib.dump ile pickle
  - Versiyon: ml_classifier_v{N}.joblib, ml_regressor_v{N}.joblib
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    f1_score,
    mean_absolute_error,
    precision_score,
    recall_score,
)

logger = logging.getLogger(__name__)

# --- Sabitler ---

# Sinif etiketleri
CLASS_LABELS = {0: "cut", 1: "stable", 2: "hike"}
LABEL_TO_INT = {"cut": 0, "stable": 1, "hike": 2}

# Degisim esigi: ±0.25 TRY/L
CHANGE_THRESHOLD = 0.25

# Model kayit dizini
DEFAULT_MODEL_DIR = Path("models")


# --- Hiperparametre Konfigurasyonlari ---

PARAMS_CLF: dict = {
    "objective": "multiclass",
    "num_class": 3,
    "metric": "multi_logloss",
    "num_leaves": 64,
    "max_depth": 8,
    "learning_rate": 0.05,
    "n_estimators": 500,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "reg_alpha": 0.5,
    "reg_lambda": 0.5,
    "min_child_samples": 20,
    "verbose": -1,
    "force_col_wise": True,
}

PARAMS_REG: dict = {
    "objective": "regression",
    "metric": "mae",
    "num_leaves": 64,
    "max_depth": 8,
    "learning_rate": 0.03,
    "n_estimators": 500,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "reg_alpha": 0.3,
    "reg_lambda": 0.3,
    "min_child_samples": 20,
    "verbose": -1,
    "force_col_wise": True,
}


@dataclass
class TrainResult:
    """Model egitim sonucu."""

    status: str  # success, failed
    model_version: str | None = None
    clf_metrics: dict = field(default_factory=dict)
    reg_metrics: dict = field(default_factory=dict)
    message: str = ""
    clf_path: str | None = None
    reg_path: str | None = None


# ────────────────────────────────────────────────────────────────────────────
#  Label Olusturma
# ────────────────────────────────────────────────────────────────────────────


def create_labels(
    price_changes: list[float],
    threshold: float = CHANGE_THRESHOLD,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Fiyat degisimlerinden siniflandirma ve regresyon etiketleri olusturur.

    Args:
        price_changes: Fiyat degisimleri (TL/L).
        threshold: Siniflandirma esigi (±TL/L).

    Returns:
        (y_clf, y_reg): Siniflandirma (0,1,2) ve regresyon (float) etiketleri.
    """
    y_clf = []
    y_reg = np.array(price_changes, dtype=np.float64)

    for change in price_changes:
        if change > threshold:
            y_clf.append(2)  # hike
        elif change < -threshold:
            y_clf.append(0)  # cut
        else:
            y_clf.append(1)  # stable

    return np.array(y_clf, dtype=np.int32), y_reg


def compute_class_weights(y: np.ndarray) -> dict[int, float]:
    """
    Sinif dagilimina gore agirlik hesaplar.

    Zam sinifi icin 8-12x agirlik, Indirim icin 4-6x.

    Args:
        y: Sinif etiketleri (0, 1, 2).

    Returns:
        {sinif: agirlik} dict'i.
    """
    unique, counts = np.unique(y, return_counts=True)
    total = len(y)
    n_classes = len(unique)

    weights = {}
    for cls, count in zip(unique, counts):
        # Balanced: total / (n_classes * count)
        w = total / (n_classes * count)
        weights[int(cls)] = round(w, 2)

    # Zam agirligi 8-12x arasinda sinirla
    if 2 in weights:
        weights[2] = max(8.0, min(12.0, weights[2]))

    # Indirim agirligi 4-6x arasinda sinirla
    if 0 in weights:
        weights[0] = max(4.0, min(6.0, weights[0]))

    # Sabit agirligi 1x civarinda tut
    if 1 in weights:
        weights[1] = max(0.5, min(1.5, weights[1]))

    logger.info("Sinif agirliklari: %s", weights)
    return weights


# ────────────────────────────────────────────────────────────────────────────
#  Model Egitimi
# ────────────────────────────────────────────────────────────────────────────


def _apply_sample_weights(
    y_train: np.ndarray, class_weights: dict[int, float]
) -> np.ndarray:
    """Sinif agirliklarini ornek agirliklarına donusturur."""
    return np.array([class_weights.get(int(label), 1.0) for label in y_train])


def train_models(
    X: np.ndarray,
    y_clf: np.ndarray,
    y_reg: np.ndarray,
    feature_names: list[str] | None = None,
    model_dir: Path | None = None,
    version: int = 1,
) -> TrainResult:
    """
    LightGBM siniflandirma ve regresyon modellerini egitir.

    TimeSeriesSplit ile cross-validation yapar.
    ASLA random shuffle kullanmaz!

    Args:
        X: Feature matrisi (n_samples, n_features).
        y_clf: Siniflandirma etiketleri (0, 1, 2).
        y_reg: Regresyon etiketleri (TL/L).
        feature_names: Feature isimleri.
        model_dir: Model kayit dizini.
        version: Model versiyon numarasi.

    Returns:
        TrainResult nesnesi.
    """
    try:
        import lightgbm as lgb
    except ImportError as e:
        return TrainResult(
            status="failed",
            message=f"LightGBM yuklu degil: {e}",
        )

    if model_dir is None:
        model_dir = DEFAULT_MODEL_DIR
    model_dir.mkdir(parents=True, exist_ok=True)

    n_samples = X.shape[0]
    if n_samples < 50:
        return TrainResult(
            status="failed",
            message=f"Yetersiz veri: {n_samples} ornek (min 50 gerekli)",
        )

    # --- TimeSeriesSplit ---
    n_splits = min(5, n_samples // 37)  # test_size=30 + gap=7 = 37
    if n_splits < 2:
        n_splits = 2

    tscv = TimeSeriesSplit(n_splits=n_splits, test_size=30, gap=7)

    # --- Sinif Agirliklari ---
    class_weights = compute_class_weights(y_clf)

    # --- Cross-Validation Metrikleri ---
    cv_accuracy = []
    cv_precision_hike = []
    cv_recall_hike = []
    cv_f1_hike = []
    cv_mae = []

    best_clf = None
    best_reg = None
    best_precision = 0.0

    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        X_train, X_test = X[train_idx], X[test_idx]
        y_clf_train, y_clf_test = y_clf[train_idx], y_clf[test_idx]
        y_reg_train, y_reg_test = y_reg[train_idx], y_reg[test_idx]

        # Sample weights
        sample_weights = _apply_sample_weights(y_clf_train, class_weights)

        # --- Siniflandirma ---
        clf = lgb.LGBMClassifier(**PARAMS_CLF)
        clf.fit(
            X_train,
            y_clf_train,
            sample_weight=sample_weights,
            eval_set=[(X_test, y_clf_test)],
            callbacks=[lgb.log_evaluation(period=0)],
        )

        y_clf_pred = clf.predict(X_test)
        acc = accuracy_score(y_clf_test, y_clf_pred)
        prec_hike = precision_score(
            y_clf_test, y_clf_pred, labels=[2], average="macro", zero_division=0
        )
        rec_hike = recall_score(
            y_clf_test, y_clf_pred, labels=[2], average="macro", zero_division=0
        )
        f1_hike = f1_score(
            y_clf_test, y_clf_pred, labels=[2], average="macro", zero_division=0
        )

        cv_accuracy.append(acc)
        cv_precision_hike.append(prec_hike)
        cv_recall_hike.append(rec_hike)
        cv_f1_hike.append(f1_hike)

        # --- Regresyon ---
        reg = lgb.LGBMRegressor(**PARAMS_REG)
        reg.fit(
            X_train,
            y_reg_train,
            eval_set=[(X_test, y_reg_test)],
            callbacks=[lgb.log_evaluation(period=0)],
        )

        y_reg_pred = reg.predict(X_test)
        mae = mean_absolute_error(y_reg_test, y_reg_pred)
        cv_mae.append(mae)

        # En iyi modeli sec (precision_hike bazinda)
        if prec_hike >= best_precision:
            best_precision = prec_hike
            best_clf = clf
            best_reg = reg

        logger.info(
            "Fold %d: acc=%.3f, prec_hike=%.3f, rec_hike=%.3f, mae=%.4f",
            fold + 1, acc, prec_hike, rec_hike, mae,
        )

    if best_clf is None or best_reg is None:
        return TrainResult(
            status="failed",
            message="Hicbir fold'da model egitelemedi",
        )

    # --- Model Kayit ---
    version_str = f"v{version}"
    clf_filename = f"ml_classifier_{version_str}.joblib"
    reg_filename = f"ml_regressor_{version_str}.joblib"
    clf_path = model_dir / clf_filename
    reg_path = model_dir / reg_filename

    # Feature isimleri ile birlikte kaydet
    clf_payload = {"model": best_clf, "feature_names": feature_names, "version": version_str}
    reg_payload = {"model": best_reg, "feature_names": feature_names, "version": version_str}

    joblib.dump(clf_payload, clf_path)
    joblib.dump(reg_payload, reg_path)

    logger.info("Model kaydedildi: %s, %s", clf_path, reg_path)

    # --- Metrikler ---
    clf_metrics = {
        "accuracy": round(float(np.mean(cv_accuracy)), 4),
        "precision_hike": round(float(np.mean(cv_precision_hike)), 4),
        "recall_hike": round(float(np.mean(cv_recall_hike)), 4),
        "f1_hike": round(float(np.mean(cv_f1_hike)), 4),
        "class_weights": {str(k): v for k, v in class_weights.items()},
        "n_folds": n_splits,
    }

    reg_metrics = {
        "mae": round(float(np.mean(cv_mae)), 4),
        "n_folds": n_splits,
    }

    return TrainResult(
        status="success",
        model_version=version_str,
        clf_metrics=clf_metrics,
        reg_metrics=reg_metrics,
        message=f"Model basariyla egitildi: {version_str}",
        clf_path=str(clf_path),
        reg_path=str(reg_path),
    )


def get_next_version(model_dir: Path | None = None) -> int:
    """
    Mevcut model dosyalarindan bir sonraki versiyon numarasini belirler.

    Args:
        model_dir: Model dizini.

    Returns:
        Bir sonraki versiyon numarasi.
    """
    if model_dir is None:
        model_dir = DEFAULT_MODEL_DIR

    if not model_dir.exists():
        return 1

    versions = []
    for f in model_dir.glob("ml_classifier_v*.joblib"):
        try:
            v = int(f.stem.split("_v")[-1])
            versions.append(v)
        except (ValueError, IndexError):
            continue

    return max(versions, default=0) + 1
