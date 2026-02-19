"""
Predictor v5 — Backtest Unit Tests
====================================
Sentetik veri ile hızlı unit testler. Gerçek DB'ye bağımlı değil.
"""

import sys
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, "/var/www/yakit_analiz")

from src.predictor_v5.config import FEATURE_NAMES, FUEL_TYPES
from src.predictor_v5.backtest import (
    _compute_stage1_metrics,
    _compute_stage2_metrics,
    _empty_backtest_result,
    _aggregate_backtest_results,
    generate_backtest_report,
    run_backtest,
    run_full_backtest,
)


# ---------------------------------------------------------------------------
# Sentetik Veri
# ---------------------------------------------------------------------------

def _make_synthetic_data(
    n_days: int = 550,
    pos_ratio: float = 0.3,
    start: date = date(2023, 1, 1),
) -> tuple:
    np.random.seed(42)
    dates = [start + timedelta(days=i) for i in range(n_days)]

    feat_data = {"trade_date": dates, "fuel_type": ["benzin"] * n_days}
    for fname in FEATURE_NAMES:
        feat_data[fname] = np.random.randn(n_days).astype(np.float64)
    features_df = pd.DataFrame(feat_data)

    y_binary = np.zeros(n_days, dtype=np.int32)
    n_pos = int(n_days * pos_ratio)
    pos_indices = np.random.choice(n_days, size=n_pos, replace=False)
    y_binary[pos_indices] = 1

    first_event = np.where(y_binary == 1, np.random.uniform(0.25, 2.0, n_days), 0.0)
    net_amount = np.where(y_binary == 1, np.random.uniform(-1.0, 3.0, n_days), 0.0)

    labels_df = pd.DataFrame({
        "run_date": dates,
        "fuel_type": ["benzin"] * n_days,
        "y_binary": y_binary,
        "first_event_direction": np.where(y_binary == 1, np.random.choice([1, -1], n_days), 0),
        "first_event_amount": first_event,
        "first_event_type": ["daily"] * n_days,
        "net_amount_3d": net_amount,
        "ref_price": np.random.uniform(40, 60, n_days),
        "label_window_end": [d + timedelta(days=3) for d in dates],
    })

    return features_df, labels_df


# ---------------------------------------------------------------------------
# Pytest fixture: LightGBM mock
# ---------------------------------------------------------------------------

class _MockClassifier:
    """LightGBM binary classifier mock."""
    def __init__(self, **kwargs):
        self._rng = np.random.RandomState(42)

    def fit(self, X, y):
        self._n_features = X.shape[1]
        self._pos_ratio = np.mean(y) if len(y) > 0 else 0.5

    def predict_proba(self, X):
        n = X.shape[0]
        # Basit: feature'ların toplamına dayalı skor
        scores = 1.0 / (1.0 + np.exp(-X[:, 0]))  # sigmoid(feature_0)
        probs = np.column_stack([1.0 - scores, scores])
        return probs

    def predict(self, X):
        probs = self.predict_proba(X)
        return (probs[:, 1] >= 0.5).astype(np.int32)


class _MockRegressor:
    """LightGBM regressor mock."""
    def __init__(self, **kwargs):
        self._coef = None

    def fit(self, X, y):
        # Basit linear approx
        self._mean = float(np.mean(y)) if len(y) > 0 else 0.0
        self._scale = float(np.std(y)) if len(y) > 1 else 1.0

    def predict(self, X):
        n = X.shape[0]
        return np.full(n, self._mean) + X[:, 0] * self._scale * 0.1


@pytest.fixture(autouse=True)
def _mock_lgbm(monkeypatch):
    """LightGBM'i hafif mock ile değiştir."""
    import lightgbm as lgb
    monkeypatch.setattr(lgb, "LGBMClassifier", _MockClassifier)
    monkeypatch.setattr(lgb, "LGBMRegressor", _MockRegressor)


# ---------------------------------------------------------------------------
# Test: _compute_stage1_metrics
# ---------------------------------------------------------------------------

class TestComputeStage1Metrics:
    def test_basic_metrics(self):
        y_true = np.array([0, 0, 1, 1, 1, 0, 1, 0])
        y_prob = np.array([0.1, 0.2, 0.8, 0.7, 0.9, 0.3, 0.6, 0.15])
        y_pred = np.array([0, 0, 1, 1, 1, 0, 1, 0])

        metrics = _compute_stage1_metrics(y_true, y_prob, y_pred)

        assert "auc" in metrics
        assert "f1" in metrics
        assert "precision" in metrics
        assert "recall" in metrics
        assert "accuracy" in metrics
        assert "ece" in metrics
        assert metrics["auc"] > 0.8
        assert metrics["accuracy"] == 1.0

    def test_single_class_auc_fallback(self):
        y_true = np.array([0, 0, 0, 0])
        y_prob = np.array([0.1, 0.2, 0.3, 0.15])
        y_pred = np.array([0, 0, 0, 0])

        metrics = _compute_stage1_metrics(y_true, y_prob, y_pred)
        assert metrics["auc"] == 0.0
        assert metrics["accuracy"] == 1.0


# ---------------------------------------------------------------------------
# Test: _compute_stage2_metrics
# ---------------------------------------------------------------------------

class TestComputeStage2Metrics:
    def test_basic_metrics(self):
        y_true_first = np.array([0.5, 1.0, 1.5, 2.0])
        y_pred_first = np.array([0.6, 0.9, 1.4, 2.1])
        y_true_net = np.array([0.3, -0.5, 1.2, 0.8])
        y_pred_net = np.array([0.2, -0.3, 1.0, 0.9])

        metrics = _compute_stage2_metrics(y_true_first, y_pred_first, y_true_net, y_pred_net)

        assert "mae_first_event" in metrics
        assert "rmse_first_event" in metrics
        assert "mae_net_amount" in metrics
        assert "rmse_net_amount" in metrics
        assert "directional_accuracy" in metrics
        assert metrics["mae_first_event"] < 0.2

    def test_directional_accuracy_perfect(self):
        y_true_net = np.array([1.0, -1.0, 0.5])
        y_pred_net = np.array([0.5, -0.2, 0.1])

        metrics = _compute_stage2_metrics(np.zeros(3), np.zeros(3), y_true_net, y_pred_net)
        assert metrics["directional_accuracy"] == 1.0

    def test_directional_accuracy_mixed(self):
        y_true_net = np.array([1.0, -1.0, 0.5, -0.5])
        y_pred_net = np.array([0.5, 0.2, -0.1, -0.3])

        metrics = _compute_stage2_metrics(np.zeros(4), np.zeros(4), y_true_net, y_pred_net)
        assert metrics["directional_accuracy"] == 0.5


# ---------------------------------------------------------------------------
# Test: _empty_backtest_result
# ---------------------------------------------------------------------------

class TestEmptyBacktestResult:
    def test_structure(self):
        result = _empty_backtest_result("benzin", "test_reason")

        assert result["fuel_type"] == "benzin"
        assert result["n_folds"] == 0
        assert result["error"] == "test_reason"
        assert result["stage2"]["skipped"] is True


# ---------------------------------------------------------------------------
# Test: run_backtest
# ---------------------------------------------------------------------------

class TestRunBacktest:
    def test_returns_correct_structure(self):
        features_df, labels_df = _make_synthetic_data(n_days=550, pos_ratio=0.3)

        result = run_backtest("benzin", features_df=features_df, labels_df=labels_df)

        assert result["fuel_type"] == "benzin"
        assert result["n_folds"] > 0
        assert "stage1" in result
        assert "stage2" in result
        assert "fold_details" in result
        assert "predictions_vs_actuals" in result

    def test_stage1_metrics_calculated(self):
        features_df, labels_df = _make_synthetic_data(n_days=550, pos_ratio=0.3)

        result = run_backtest("benzin", features_df=features_df, labels_df=labels_df)

        s1 = result["stage1"]
        assert "auc_mean" in s1
        assert "f1_mean" in s1
        assert "precision_mean" in s1
        assert "ece_mean" in s1
        assert s1["accuracy_mean"] > 0.0

    def test_stage2_with_positives(self):
        features_df, labels_df = _make_synthetic_data(n_days=550, pos_ratio=0.4)

        result = run_backtest("benzin", features_df=features_df, labels_df=labels_df)

        s2 = result["stage2"]
        if not s2.get("skipped"):
            assert s2.get("n_positive_samples", 0) > 0

    def test_fold_details(self):
        features_df, labels_df = _make_synthetic_data(n_days=550)

        result = run_backtest("benzin", features_df=features_df, labels_df=labels_df)

        folds = result["fold_details"]
        assert len(folds) > 0
        for fold in folds:
            assert "fold" in fold
            assert "train_size" in fold
            assert fold["train_size"] > 0

    def test_insufficient_data(self):
        features_df, labels_df = _make_synthetic_data(n_days=30)

        result = run_backtest("benzin", features_df=features_df, labels_df=labels_df)
        assert result["n_folds"] == 0

    def test_low_positives(self):
        features_df, labels_df = _make_synthetic_data(n_days=550, pos_ratio=0.02)

        result = run_backtest("benzin", features_df=features_df, labels_df=labels_df)
        assert isinstance(result["stage2"], dict)

    def test_empty_data(self):
        empty_feat = pd.DataFrame(columns=["trade_date", "fuel_type"] + list(FEATURE_NAMES))
        empty_lbl = pd.DataFrame(columns=["run_date", "fuel_type", "y_binary",
                                           "first_event_amount", "net_amount_3d"])

        result = run_backtest("benzin", features_df=empty_feat, labels_df=empty_lbl)
        assert result["n_folds"] == 0
        assert result.get("error") is not None


# ---------------------------------------------------------------------------
# Test: run_full_backtest
# ---------------------------------------------------------------------------

class TestRunFullBacktest:
    def test_three_fuel_types(self):
        with patch("src.predictor_v5.backtest.run_backtest") as mock_bt:
            mock_bt.return_value = {
                "fuel_type": "test", "n_folds": 2,
                "stage1": {"auc_mean": 0.7},
                "stage2": {"skipped": True},
                "fold_details": [], "predictions_vs_actuals": [],
            }
            results = run_full_backtest()
            assert len(results) == 3
            for ft in FUEL_TYPES:
                assert ft in results


# ---------------------------------------------------------------------------
# Test: generate_backtest_report
# ---------------------------------------------------------------------------

class TestGenerateBacktestReport:
    def test_returns_markdown(self):
        results = {
            "benzin": {
                "fuel_type": "benzin", "n_folds": 2,
                "stage1": {
                    "auc_mean": 0.75, "auc_std": 0.05,
                    "f1_mean": 0.65, "f1_std": 0.03,
                    "precision_mean": 0.7, "precision_std": 0.04,
                    "recall_mean": 0.6, "recall_std": 0.02,
                    "accuracy_mean": 0.8, "accuracy_std": 0.01,
                    "ece_mean": 0.03, "ece_std": 0.01,
                },
                "stage2": {"skipped": True, "reason": "test"},
                "fold_details": [{
                    "fold": 1, "train_size": 365, "test_size": 90,
                    "calibration_method": "platt",
                    "stage1": {"auc": 0.75, "f1": 0.65, "precision": 0.7,
                               "recall": 0.6, "ece": 0.03},
                    "stage2": None,
                }],
                "predictions_vs_actuals": [],
            }
        }

        report = generate_backtest_report(results)
        assert isinstance(report, str)
        assert "# Predictor v5" in report
        assert "BENZIN" in report
        assert "AUC" in report

    def test_error_result(self):
        results = {"motorin": _empty_backtest_result("motorin", "no_data")}
        report = generate_backtest_report(results)
        assert "MOTORIN" in report
        assert "no_data" in report


# ---------------------------------------------------------------------------
# Test: _aggregate_backtest_results
# ---------------------------------------------------------------------------

class TestAggregateBacktestResults:
    def test_mean_std(self):
        fold_details = [
            {
                "fold": 1, "train_size": 365, "test_size": 90,
                "calibration_method": "platt",
                "stage1": {"auc": 0.8, "f1": 0.7, "precision": 0.75,
                           "recall": 0.65, "accuracy": 0.85, "ece": 0.02},
                "stage2": None,
            },
            {
                "fold": 2, "train_size": 455, "test_size": 90,
                "calibration_method": "platt",
                "stage1": {"auc": 0.7, "f1": 0.6, "precision": 0.65,
                           "recall": 0.55, "accuracy": 0.75, "ece": 0.04},
                "stage2": None,
            },
        ]

        result = _aggregate_backtest_results("benzin", fold_details, [])
        s1 = result["stage1"]
        assert s1["auc_mean"] == 0.75
        assert s1["f1_mean"] == 0.65
        assert s1["auc_std"] > 0


# ---------------------------------------------------------------------------
# Test: Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_all_same_class(self):
        features_df, labels_df = _make_synthetic_data(n_days=550, pos_ratio=0.0)
        labels_df["y_binary"] = 0

        result = run_backtest("benzin", features_df=features_df, labels_df=labels_df)

        if result["n_folds"] > 0:
            assert result["stage1"]["auc_mean"] == 0.0
