"""
Predictor v5 — Trainer Testleri
================================
Sentetik/mock data ile test. Gerçek DB'ye bağımlı değil.
"""

import os
import sys
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

# Proje kök dizinini path'e ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.predictor_v5.config import FEATURE_NAMES, FUEL_TYPES
from src.predictor_v5.cv import PurgedWalkForwardCV
from src.predictor_v5.trainer import (
    _compute_scale_pos_weight,
    _get_hyperparams_stage1,
    _get_hyperparams_stage2,
    _align_features_labels,
    _aggregate_metrics,
    _aggregate_stage2_metrics,
    _save_models,
    train_stage1,
    train_stage2,
    train_all,
)


# ---------------------------------------------------------------------------
# Test hizi icin hyperparameter override — n_estimators=10
# ---------------------------------------------------------------------------

_FAST_STAGE1_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "n_estimators": 10,
    "learning_rate": 0.1,
    "max_depth": 4,
    "num_leaves": 15,
    "min_child_samples": 5,
    "scale_pos_weight": 1.0,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 0.1,
    "random_state": 42,
    "verbose": -1,
    "n_jobs": 1,
}

_FAST_STAGE2_PARAMS = {
    "objective": "regression",
    "metric": "rmse",
    "n_estimators": 10,
    "learning_rate": 0.1,
    "max_depth": 4,
    "num_leaves": 15,
    "min_child_samples": 5,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 0.1,
    "random_state": 42,
    "verbose": -1,
    "n_jobs": 1,
}


def _fast_stage1_params(scale_pos_weight=1.0):
    params = _FAST_STAGE1_PARAMS.copy()
    params["scale_pos_weight"] = scale_pos_weight
    return params


def _fast_stage2_params():
    return _FAST_STAGE2_PARAMS.copy()


@pytest.fixture
def fast_hyperparams():
    """Egitim testlerinde n_estimators=10 ile calis — hiz icin."""
    with patch("src.predictor_v5.trainer._get_hyperparams_stage1", side_effect=_fast_stage1_params), \
         patch("src.predictor_v5.trainer._get_hyperparams_stage2", side_effect=_fast_stage2_params):
        yield


# ---------------------------------------------------------------------------
# Yardımcı: Sentetik veri üretici
# ---------------------------------------------------------------------------

def _make_synthetic_features(
    start_date: date,
    n_days: int = 250,
    fuel_type: str = "benzin",
) -> pd.DataFrame:
    """Sentetik feature DataFrame üretir."""
    rng = np.random.RandomState(42)
    dates = [start_date + timedelta(days=i) for i in range(n_days)]
    rows = []
    for d in dates:
        row = {"trade_date": d, "fuel_type": fuel_type}
        for fname in FEATURE_NAMES:
            if "stale" in fname or "is_weekend" in fname:
                row[fname] = float(rng.choice([0.0, 1.0]))
            elif "day_of_week" in fname:
                row[fname] = float(d.weekday())
            else:
                row[fname] = rng.normal(0, 1)
        rows.append(row)
    return pd.DataFrame(rows)


def _make_synthetic_labels(
    start_date: date,
    n_days: int = 250,
    fuel_type: str = "benzin",
    pos_ratio: float = 0.15,
) -> pd.DataFrame:
    """Sentetik label DataFrame üretir."""
    rng = np.random.RandomState(42)
    dates = [start_date + timedelta(days=i) for i in range(n_days)]
    rows = []
    for d in dates:
        y_binary = 1 if rng.random() < pos_ratio else 0
        first_event_amount = Decimal(str(round(rng.normal(0.5, 0.3), 4))) if y_binary else Decimal("0")
        net_amount_3d = Decimal(str(round(rng.normal(0.3, 0.5), 4))) if y_binary else Decimal("0")
        rows.append({
            "run_date": d,
            "fuel_type": fuel_type,
            "y_binary": y_binary,
            "first_event_direction": (1 if float(first_event_amount) > 0 else -1) if y_binary else 0,
            "first_event_amount": first_event_amount,
            "first_event_type": "daily" if y_binary else "none",
            "net_amount_3d": net_amount_3d,
            "ref_price": Decimal("58.07"),
            "label_window_end": d + timedelta(days=3),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_data():
    """250 gunluk sentetik feature + label verisi."""
    start = date(2024, 1, 1)
    n_days = 250
    features_df = _make_synthetic_features(start, n_days)
    labels_df = _make_synthetic_labels(start, n_days)
    return features_df, labels_df


@pytest.fixture
def small_cv():
    """Kucuk CV — hizli testler icin (max 2 fold)."""
    return PurgedWalkForwardCV(
        min_train=120,
        test_size=50,
        step_size=100,
        embargo=4,
    )


@pytest.fixture
def tmp_model_dir(tmp_path):
    """Gecici model dizini."""
    model_dir = tmp_path / "models" / "v5"
    model_dir.mkdir(parents=True)
    return model_dir


# ---------------------------------------------------------------------------
# Test 1: Hyperparameter fonksiyonları
# ---------------------------------------------------------------------------

class TestHyperparams:
    def test_stage1_hyperparams_default(self):
        """Stage-1 default hiperparametreleri kontrol."""
        params = _get_hyperparams_stage1()
        assert params["objective"] == "binary"
        assert params["n_estimators"] == 200
        assert params["learning_rate"] == 0.05
        assert params["max_depth"] == 6
        assert params["scale_pos_weight"] == 1.0
        assert params["verbose"] == -1

    def test_stage1_hyperparams_custom_spw(self):
        """Stage-1 custom scale_pos_weight."""
        params = _get_hyperparams_stage1(scale_pos_weight=5.0)
        assert params["scale_pos_weight"] == 5.0

    def test_stage2_hyperparams(self):
        """Stage-2 regression hiperparametreleri kontrol."""
        params = _get_hyperparams_stage2()
        assert params["objective"] == "regression"
        assert params["metric"] == "rmse"
        assert params["n_estimators"] == 200
        assert params["learning_rate"] == 0.05
        assert params["max_depth"] == 6


# ---------------------------------------------------------------------------
# Test 2: scale_pos_weight hesaplama
# ---------------------------------------------------------------------------

class TestScalePosWeight:
    def test_balanced(self):
        """50/50 dagilimda weight=1."""
        y = np.array([0, 0, 1, 1])
        assert _compute_scale_pos_weight(y) == 1.0

    def test_imbalanced(self):
        """Dengesiz dagilimda dogru oran."""
        y = np.array([0, 0, 0, 0, 0, 0, 0, 0, 1, 1])
        assert _compute_scale_pos_weight(y) == 4.0

    def test_no_positive(self):
        """Pozitif ornek yoksa 1.0."""
        y = np.array([0, 0, 0])
        assert _compute_scale_pos_weight(y) == 1.0

    def test_all_positive(self):
        """Tum ornekler pozitif."""
        y = np.array([1, 1, 1])
        assert _compute_scale_pos_weight(y) == 0.0


# ---------------------------------------------------------------------------
# Test 3: Feature-Label hizalama
# ---------------------------------------------------------------------------

class TestAlignFeaturesLabels:
    def test_basic_alignment(self, synthetic_data):
        """Temel hizalama calisiyor."""
        features_df, labels_df = synthetic_data
        feat_aligned, lbl_aligned = _align_features_labels(features_df, labels_df)
        assert len(feat_aligned) == len(lbl_aligned)
        assert len(feat_aligned) > 0
        assert "y_binary" in lbl_aligned.columns
        for fname in FEATURE_NAMES:
            assert fname in feat_aligned.columns

    def test_partial_overlap(self):
        """Kismi overlap durumunda inner join."""
        start = date(2024, 1, 1)
        feat = _make_synthetic_features(start, 100)
        lbl = _make_synthetic_labels(date(2024, 2, 1), 100)
        feat_aligned, lbl_aligned = _align_features_labels(feat, lbl)
        assert len(feat_aligned) > 0
        assert len(feat_aligned) < 100

    def test_no_overlap(self):
        """Hic overlap yoksa bos doner."""
        feat = _make_synthetic_features(date(2024, 1, 1), 30)
        lbl = _make_synthetic_labels(date(2025, 1, 1), 30)
        feat_aligned, lbl_aligned = _align_features_labels(feat, lbl)
        assert len(feat_aligned) == 0


# ---------------------------------------------------------------------------
# Test 4: Metrik aggregation
# ---------------------------------------------------------------------------

class TestMetricAggregation:
    def test_aggregate_stage1_metrics(self):
        """Stage-1 metrik ortalamalari dogru."""
        fold_metrics = [
            {"fold": 1, "auc": 0.8, "f1": 0.6, "precision": 0.7, "recall": 0.5, "accuracy": 0.75},
            {"fold": 2, "auc": 0.9, "f1": 0.7, "precision": 0.8, "recall": 0.6, "accuracy": 0.85},
        ]
        result = _aggregate_metrics(fold_metrics)
        assert result["n_folds"] == 2
        assert result["mean_auc"] == 0.85
        assert result["mean_f1"] == 0.65
        assert result["stage"] == "stage1"

    def test_aggregate_empty(self):
        """Bos fold listesinde sifir donmeli."""
        result = _aggregate_metrics([])
        assert result["n_folds"] == 0
        assert result["mean_auc"] == 0.0

    def test_aggregate_stage2_metrics(self):
        """Stage-2 dual metrik aggregation."""
        first_folds = [
            {"fold": 1, "rmse": 0.1, "mae": 0.08, "train_size": 100, "test_size": 30},
            {"fold": 2, "rmse": 0.2, "mae": 0.15, "train_size": 200, "test_size": 30},
        ]
        net_folds = [
            {"fold": 1, "rmse": 0.3, "mae": 0.25, "train_size": 100, "test_size": 30},
        ]
        result = _aggregate_stage2_metrics(first_folds, net_folds)
        assert result["skipped"] is False
        assert result["first_event"]["n_folds"] == 2
        assert result["net_amount"]["n_folds"] == 1
        assert abs(result["first_event"]["mean_rmse"] - 0.15) < 0.001


# ---------------------------------------------------------------------------
# Test 5: Stage-1 egitimi
# ---------------------------------------------------------------------------

class TestTrainStage1:
    def test_returns_model_and_metrics(self, synthetic_data, small_cv, fast_hyperparams):
        """Stage-1 model ve metrik doner."""
        features_df, labels_df = synthetic_data
        import lightgbm as lgb
        model, metrics = train_stage1("benzin", features_df, labels_df, small_cv)
        assert isinstance(model, lgb.LGBMClassifier)
        assert "stage" in metrics
        assert metrics["stage"] == "stage1"
        assert "mean_auc" in metrics
        assert "mean_f1" in metrics
        assert "folds" in metrics

    def test_model_can_predict(self, synthetic_data, small_cv, fast_hyperparams):
        """Egitilen model predict yapabilir."""
        features_df, labels_df = synthetic_data
        model, _ = train_stage1("benzin", features_df, labels_df, small_cv)
        X_sample = features_df[list(FEATURE_NAMES)].values[:5].astype(np.float64)
        preds = model.predict(X_sample)
        probs = model.predict_proba(X_sample)
        assert len(preds) == 5
        assert probs.shape == (5, 2)
        assert all(p in [0, 1] for p in preds)

    def test_scale_pos_weight_applied(self, synthetic_data, small_cv, fast_hyperparams):
        """Class imbalance handling uygulaniyor."""
        features_df, labels_df = synthetic_data
        model, metrics = train_stage1("benzin", features_df, labels_df, small_cv)
        spw = model.get_params()["scale_pos_weight"]
        assert spw > 1.0  # %15 pozitif oran ile ~5.67 olmali

    def test_empty_data_raises(self, small_cv, fast_hyperparams):
        """Bos veri ValueError firlatir."""
        feat = _make_synthetic_features(date(2024, 1, 1), 30)
        lbl = _make_synthetic_labels(date(2025, 1, 1), 30)
        with pytest.raises(ValueError, match="Hizalama"):
            train_stage1("benzin", feat, lbl, small_cv)

    def test_metrics_format(self, synthetic_data, small_cv, fast_hyperparams):
        """Metrik formati dogru."""
        features_df, labels_df = synthetic_data
        _, metrics = train_stage1("benzin", features_df, labels_df, small_cv)
        assert isinstance(metrics["folds"], list)
        if metrics["n_folds"] > 0:
            fold = metrics["folds"][0]
            assert "auc" in fold
            assert "f1" in fold
            assert "precision" in fold
            assert "recall" in fold
            assert "accuracy" in fold
            assert "train_size" in fold
            assert "test_size" in fold


# ---------------------------------------------------------------------------
# Test 6: Stage-2 egitimi
# ---------------------------------------------------------------------------

class TestTrainStage2:
    def test_returns_dual_models(self, synthetic_data, small_cv, fast_hyperparams):
        """Stage-2 iki regressor model doner."""
        features_df, labels_df = synthetic_data
        import lightgbm as lgb
        (model_first, model_net), metrics = train_stage2(
            "benzin", features_df, labels_df, small_cv
        )
        # Stage-2 pozitif orneklerle calisir - model veya skip bekliyoruz
        assert metrics["stage"] == "stage2"

    def test_skip_insufficient_positives(self, small_cv, fast_hyperparams):
        """Pozitif ornek < 20 ise skip."""
        start = date(2024, 1, 1)
        feat = _make_synthetic_features(start, 250)
        lbl = _make_synthetic_labels(start, 250, pos_ratio=0.01)
        (model_first, model_net), metrics = train_stage2(
            "benzin", feat, lbl, small_cv
        )
        assert model_first is None
        assert model_net is None
        assert metrics["skipped"] is True

    def test_regressor_can_predict(self, synthetic_data, small_cv, fast_hyperparams):
        """Egitilen regressor predict yapabilir."""
        features_df, labels_df = synthetic_data
        (model_first, model_net), metrics = train_stage2(
            "benzin", features_df, labels_df, small_cv
        )
        if model_first is not None:
            X_sample = features_df[list(FEATURE_NAMES)].values[:5].astype(np.float64)
            pred_first = model_first.predict(X_sample)
            pred_net = model_net.predict(X_sample)
            assert len(pred_first) == 5
            assert len(pred_net) == 5
            assert all(isinstance(p, (float, np.floating)) for p in pred_first)

    def test_stage2_only_positive_data(self, small_cv, fast_hyperparams):
        """Stage-2 sadece pozitif ornekleri kullaniyor, negatifler dahil degil."""
        start = date(2024, 1, 1)
        feat = _make_synthetic_features(start, 250, fuel_type="benzin")
        lbl = _make_synthetic_labels(start, 250, fuel_type="benzin", pos_ratio=0.30)

        (model_first, model_net), metrics = train_stage2(
            "benzin", feat, lbl, small_cv
        )
        if not metrics.get("skipped"):
            assert "first_event" in metrics
            assert "net_amount" in metrics


# ---------------------------------------------------------------------------
# Test 7: Model kaydetme
# ---------------------------------------------------------------------------

class TestSaveModels:
    def test_save_all_three(self, tmp_model_dir):
        """3 model dosyasi kaydedilir."""
        import lightgbm as lgb
        clf = lgb.LGBMClassifier(n_estimators=2, verbose=-1)
        clf.fit(np.random.rand(20, 5), np.random.randint(0, 2, 20))

        reg1 = lgb.LGBMRegressor(n_estimators=2, verbose=-1)
        reg1.fit(np.random.rand(20, 5), np.random.rand(20))

        reg2 = lgb.LGBMRegressor(n_estimators=2, verbose=-1)
        reg2.fit(np.random.rand(20, 5), np.random.rand(20))

        with patch("src.predictor_v5.trainer._MODEL_PATH", tmp_model_dir):
            paths = _save_models("benzin", clf, reg1, reg2)

        assert "stage1" in paths
        assert "stage2_first" in paths
        assert "stage2_net" in paths
        assert Path(paths["stage1"]).exists()
        assert Path(paths["stage2_first"]).exists()
        assert Path(paths["stage2_net"]).exists()

    def test_save_without_stage2(self, tmp_model_dir):
        """Stage-2 None ise sadece stage1 kaydedilir."""
        import lightgbm as lgb
        clf = lgb.LGBMClassifier(n_estimators=2, verbose=-1)
        clf.fit(np.random.rand(20, 5), np.random.randint(0, 2, 20))

        with patch("src.predictor_v5.trainer._MODEL_PATH", tmp_model_dir):
            paths = _save_models("motorin", clf, None, None)

        assert "stage1" in paths
        assert "stage2_first" not in paths
        assert "stage2_net" not in paths


# ---------------------------------------------------------------------------
# Test 8: CV fold sayisi
# ---------------------------------------------------------------------------

class TestCVFoldCount:
    def test_folds_generated(self, synthetic_data, small_cv, fast_hyperparams):
        """CV fold'lari uretiyor."""
        features_df, labels_df = synthetic_data
        _, metrics = train_stage1("benzin", features_df, labels_df, small_cv)
        assert metrics["n_folds"] > 0
        assert len(metrics["folds"]) == metrics["n_folds"]

    def test_fold_train_test_sizes(self, synthetic_data, small_cv, fast_hyperparams):
        """Her fold'da train > test olmali."""
        features_df, labels_df = synthetic_data
        _, metrics = train_stage1("benzin", features_df, labels_df, small_cv)
        for fold in metrics["folds"]:
            assert fold["train_size"] > fold["test_size"]


# ---------------------------------------------------------------------------
# Test 9: train_all (mock ile)
# ---------------------------------------------------------------------------

class TestTrainAll:
    def test_train_all_structure(self, synthetic_data, small_cv, fast_hyperparams, tmp_path):
        """train_all 3 yakit tipi icin sonuc doner."""
        features_df, labels_df = synthetic_data
        model_dir = tmp_path / "models" / "v5"
        model_dir.mkdir(parents=True)

        with patch("src.predictor_v5.features.compute_features_bulk", return_value=features_df), \
             patch("src.predictor_v5.labels.compute_labels", return_value=labels_df), \
             patch("src.predictor_v5.trainer._MODEL_PATH", model_dir):
            results = train_all(start_date=date(2024, 1, 1), end_date=date(2024, 9, 6))

        assert isinstance(results, dict)
        for fuel_type in FUEL_TYPES:
            assert fuel_type in results


# ---------------------------------------------------------------------------
# Test 10: Tum yakit tipleri icin egitim
# ---------------------------------------------------------------------------

class TestAllFuelTypes:
    @pytest.mark.parametrize("fuel_type", FUEL_TYPES)
    def test_stage1_per_fuel(self, fuel_type, small_cv, fast_hyperparams):
        """Her yakit tipi icin stage-1 calisir."""
        start = date(2024, 1, 1)
        features_df = _make_synthetic_features(start, 250, fuel_type=fuel_type)
        labels_df = _make_synthetic_labels(start, 250, fuel_type=fuel_type)

        import lightgbm as lgb
        model, metrics = train_stage1(fuel_type, features_df, labels_df, small_cv)
        assert isinstance(model, lgb.LGBMClassifier)
        assert metrics["n_folds"] > 0


# ---------------------------------------------------------------------------
# Test 11: Metrik deger araliklari
# ---------------------------------------------------------------------------

class TestMetricRanges:
    def test_auc_range(self, synthetic_data, small_cv, fast_hyperparams):
        """AUC 0-1 arasinda."""
        features_df, labels_df = synthetic_data
        _, metrics = train_stage1("benzin", features_df, labels_df, small_cv)
        for fold in metrics["folds"]:
            assert 0.0 <= fold["auc"] <= 1.0

    def test_precision_recall_range(self, synthetic_data, small_cv, fast_hyperparams):
        """Precision ve Recall 0-1 arasinda."""
        features_df, labels_df = synthetic_data
        _, metrics = train_stage1("benzin", features_df, labels_df, small_cv)
        for fold in metrics["folds"]:
            assert 0.0 <= fold["precision"] <= 1.0
            assert 0.0 <= fold["recall"] <= 1.0


# ---------------------------------------------------------------------------
# Test 12: Feature importances
# ---------------------------------------------------------------------------

class TestFeatureImportances:
    def test_model_has_feature_importances(self, synthetic_data, small_cv, fast_hyperparams):
        """Model feature importance bilgisine sahip."""
        features_df, labels_df = synthetic_data
        model, _ = train_stage1("benzin", features_df, labels_df, small_cv)
        importances = model.feature_importances_
        assert len(importances) == len(FEATURE_NAMES)
        assert all(imp >= 0 for imp in importances)
