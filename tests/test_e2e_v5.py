"""
v5 End-to-End Pipeline Testleri.

Tum v5 modullerinin import, pipeline zinciri, API endpoint, Celery task,
config degerleri, v1 regresyon, backtest format ve alarm mesaji testleri.
"""

import pytest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock, AsyncMock
import numpy as np


# ────────────────────────────────────────────────────────────────────────────
#  Test 1: Tum v5 modulleri import edilebiliyor
# ────────────────────────────────────────────────────────────────────────────

def test_all_v5_modules_import():
    """Tum 14 v5 modulu sorunsuz import edilmeli."""
    from src.predictor_v5.config import FUEL_TYPES, FEATURE_NAMES, THRESHOLD_TL
    from src.predictor_v5.schemas import PredictionV5Result, FeatureSnapshot, AlarmState
    from src.predictor_v5.labels import compute_labels
    from src.predictor_v5.features import compute_features_bulk
    from src.predictor_v5.cv import PurgedWalkForwardCV
    from src.predictor_v5.repository import save_prediction_sync, get_latest_prediction_sync
    from src.predictor_v5.feature_store import store_snapshot, load_snapshot
    from src.predictor_v5.trainer import train_stage1, train_stage2, train_all
    from src.predictor_v5.calibration import auto_calibrate, apply_calibration
    from src.predictor_v5.predictor import predict, predict_all, clear_model_cache
    from src.predictor_v5.alarm import evaluate_alarm, generate_alarm_message, compute_risk_trend
    from src.predictor_v5.backtest import run_backtest, run_full_backtest

    # API routes
    from src.api.predictor_v5_routes import router

    assert router is not None
    assert callable(predict)
    assert callable(predict_all)
    assert callable(train_all)


# ────────────────────────────────────────────────────────────────────────────
#  Test 2: Pipeline zinciri mock test: feature -> predict -> alarm
# ────────────────────────────────────────────────────────────────────────────

def test_pipeline_chain_mock():
    """Mock pipeline: feature hesapla -> stage1 tahmin -> alarm degerlendirme."""
    import pandas as pd
    from src.predictor_v5.config import FEATURE_NAMES
    from src.predictor_v5.alarm import evaluate_alarm, compute_risk_trend

    # 1) Mock feature DataFrame
    feature_data = {name: [0.5] for name in FEATURE_NAMES}
    features_df = pd.DataFrame(feature_data)
    assert features_df.shape == (1, len(FEATURE_NAMES))

    # 2) Mock stage-1 prediction
    mock_prob = 0.72
    prediction = {
        "fuel_type": "benzin",
        "stage1_probability": Decimal(str(mock_prob)),
        "first_event_direction": 1,
        "first_event_amount": Decimal("0.45"),
        "net_amount_3d": Decimal("0.38"),
    }

    # 3) Risk trend
    risk_scores = [0.3, 0.35, 0.4, 0.5, 0.55, 0.6]
    risk_trend = compute_risk_trend(risk_scores)
    assert risk_trend == "up"

    # 4) Alarm evaluation
    result = evaluate_alarm(
        prediction=prediction,
        risk_trend=risk_trend,
        last_alarm_time=None,
        last_price_change_time=None,
        price_changed_today=False,
    )

    assert result["should_alarm"] is True
    assert result["alarm_type"] in ("consistent", "gradual", "volatile")
    assert result["message"] is not None
    assert "Benzin" in result["message"]


# ────────────────────────────────────────────────────────────────────────────
#  Test 3: API endpoint smoke test (FastAPI TestClient)
# ────────────────────────────────────────────────────────────────────────────

def test_api_endpoints_smoke():
    """FastAPI v5 endpoint'leri dogru HTTP status donmeli."""
    from fastapi.testclient import TestClient
    from src.main import app

    client = TestClient(app)

    # Gecersiz yakit tipi 422
    r1 = client.get("/api/v1/predictions/v5/latest/kerosen")
    assert r1.status_code == 422

    # Placeholder POST /run
    r2 = client.post("/api/v1/predictions/v5/run")
    assert r2.status_code == 200
    assert r2.json()["status"] == "not_implemented"

    # Placeholder GET /backtest/summary
    r3 = client.get("/api/v1/predictions/v5/backtest/summary")
    assert r3.status_code == 200
    assert r3.json()["status"] == "not_implemented"

    # Health endpoint
    r4 = client.get("/health")
    assert r4.status_code == 200


# ────────────────────────────────────────────────────────────────────────────
#  Test 4: Celery task cagirilabilir (mock predictor)
# ────────────────────────────────────────────────────────────────────────────

def test_celery_task_v5_e2e():
    """run_daily_prediction_v5 task'i mock predictor ile calisir."""
    from src.celery_app.tasks import run_daily_prediction_v5

    mock_results = {
        "benzin": {
            "fuel_type": "benzin",
            "stage1_probability": 0.72,
            "alarm": {"should_alarm": True, "alarm_type": "consistent"},
        },
        "motorin": {
            "fuel_type": "motorin",
            "stage1_probability": 0.45,
            "alarm": {"should_alarm": False, "alarm_type": None},
        },
        "lpg": None,
    }

    with patch("src.predictor_v5.predictor.predict_all", return_value=mock_results):
        result = run_daily_prediction_v5()

    assert result["status"] == "ok"
    assert len(result["results"]) == 3
    assert result["results"]["benzin"]["prob"] == 0.72
    assert result["results"]["benzin"]["alarm"] is True
    assert result["results"]["motorin"]["alarm"] is False
    assert result["results"]["lpg"] == "HATA"


# ────────────────────────────────────────────────────────────────────────────
#  Test 5: Config degerleri dogru (FUEL_TYPES=3, FEATURE_NAMES=36)
# ────────────────────────────────────────────────────────────────────────────

def test_config_values_correct():
    """v5 config degerleri beklenen degerlerle eslesir."""
    from src.predictor_v5.config import (
        FUEL_TYPES, FEATURE_NAMES, THRESHOLD_TL,
        LABEL_WINDOW, MIN_TRAIN_DAYS, TEST_DAYS,
        EMBARGO_DAYS, ALARM_THRESHOLD, COOLDOWN_HOURS,
        MODEL_DIR,
    )

    assert len(FUEL_TYPES) == 3
    assert "benzin" in FUEL_TYPES
    assert "motorin" in FUEL_TYPES
    assert "lpg" in FUEL_TYPES

    assert len(FEATURE_NAMES) == 49  # v6: 36 + 13 yeni feature
    assert "brent_close" in FEATURE_NAMES
    assert "fx_stale" in FEATURE_NAMES  # son feature

    assert THRESHOLD_TL == Decimal("0.15")  # v6: 0.25 -> 0.15
    assert LABEL_WINDOW == 3
    assert MIN_TRAIN_DAYS == 365
    assert TEST_DAYS == 90
    assert EMBARGO_DAYS == 4
    assert ALARM_THRESHOLD == Decimal("0.25")  # v6: 0.55 -> 0.25
    assert COOLDOWN_HOURS == 12  # v6: 24h -> 12h
    assert MODEL_DIR == "models/v5"


# ────────────────────────────────────────────────────────────────────────────
#  Test 6: v1 pipeline import'lari saglam (regresyon)
# ────────────────────────────────────────────────────────────────────────────

def test_v1_pipeline_imports_intact():
    """v1 ML pipeline import'lari v5 eklemesinden etkilenmemis olmali."""
    # v1 ML modulleri
    from src.ml.predictor import MLPredictor
    from src.ml.circuit_breaker import CircuitBreaker
    from src.ml.explainability import SHAPExplanation, compute_shap_values

    assert callable(MLPredictor)
    assert callable(CircuitBreaker)

    # v1 API route'lari
    from src.api.ml_routes import router as ml_router
    assert ml_router is not None

    # v1 data collectors
    from src.data_collectors.brent_collector import fetch_brent_daily, BrentData
    from src.data_collectors.fx_collector import fetch_usd_try_daily, FXData
    assert callable(fetch_brent_daily)
    assert callable(fetch_usd_try_daily)


# ────────────────────────────────────────────────────────────────────────────
#  Test 7: Backtest report format (mock data ile)
# ────────────────────────────────────────────────────────────────────────────

def test_backtest_report_format():
    """Backtest raporu beklenen formata uygun olmali."""
    from src.predictor_v5.backtest import generate_backtest_report, _empty_backtest_result

    # Mock backtest sonuclari
    mock_results = {
        "benzin": {
            "fuel_type": "benzin",
            "n_folds": 2,
            "stage1": {
                "auc_mean": 0.75, "auc_std": 0.05,
                "f1_mean": 0.68, "f1_std": 0.04,
                "precision_mean": 0.72, "precision_std": 0.03,
                "recall_mean": 0.65, "recall_std": 0.06,
                "accuracy_mean": 0.80, "accuracy_std": 0.02,
                "ece_mean": 0.05, "ece_std": 0.01,
            },
            "stage2": {"skipped": True, "reason": "test", "n_positive_samples": 0},
            "fold_details": [
                {"fold": 1, "train_size": 365, "test_size": 90,
                 "stage1": {"auc": 0.78, "f1": 0.70, "precision": 0.74, "recall": 0.67, "ece": 0.04},
                 "stage2": None, "calibration_method": "raw"},
                {"fold": 2, "train_size": 455, "test_size": 90,
                 "stage1": {"auc": 0.72, "f1": 0.66, "precision": 0.70, "recall": 0.63, "ece": 0.06},
                 "stage2": None, "calibration_method": "platt"},
            ],
            "predictions_vs_actuals": [],
            "error": None,
        },
        "motorin": _empty_backtest_result("motorin", "test_skip"),
    }

    report = generate_backtest_report(mock_results)

    # Rapor Markdown formati kontrolu
    assert isinstance(report, str)
    assert "# Predictor v5" in report
    assert "BENZIN" in report
    assert "MOTORIN" in report
    assert "Stage-1" in report
    assert "| AUC |" in report or "| auc |" in report.lower()
    assert "Fold" in report
    assert len(report) > 100


# ────────────────────────────────────────────────────────────────────────────
#  Test 8: Alarm tum tipler icin Turkce mesaj donduruyor
# ────────────────────────────────────────────────────────────────────────────

def test_alarm_all_types_turkish_messages():
    """Her alarm tipi ve her yakit tipi icin Turkce mesaj uretilmeli."""
    from src.predictor_v5.alarm import generate_alarm_message

    alarm_types = ["consistent", "volatile", "gradual", "no_change", "already_happened"]
    fuel_types = ["benzin", "motorin", "lpg"]

    prediction_up = {
        "stage1_probability": Decimal("0.72"),
        "first_event_direction": 1,
        "first_event_amount": Decimal("0.45"),
        "net_amount_3d": Decimal("0.38"),
    }

    for fuel in fuel_types:
        for alarm_type in alarm_types:
            msg = generate_alarm_message(alarm_type, prediction_up, fuel)
            assert isinstance(msg, str)
            assert len(msg) > 10  # bos olmamali

            # Turkce icerik kontrolu
            fuel_names = {"benzin": "Benzin", "motorin": "Motorin", "lpg": "LPG"}
            assert fuel_names[fuel] in msg

    # Dusus yonu de test et
    prediction_down = {
        "stage1_probability": Decimal("0.65"),
        "first_event_direction": -1,
        "first_event_amount": Decimal("-0.30"),
        "net_amount_3d": Decimal("-0.25"),
    }

    msg_down = generate_alarm_message("consistent", prediction_down, "motorin")
    assert "Motorin" in msg_down
    assert "düşüş" in msg_down.lower() or "dusus" in msg_down.lower()


# ────────────────────────────────────────────────────────────────────────────
#  Test 9: Predictor predict fonksiyonu mock model ile
# ────────────────────────────────────────────────────────────────────────────

def test_predict_with_mock_models():
    """predict() fonksiyonu mock model/DB ile tam pipeline calistirmali."""
    import pandas as pd
    from src.predictor_v5.config import FEATURE_NAMES
    from src.predictor_v5.predictor import predict, clear_model_cache

    clear_model_cache()

    # Mock feature DataFrame
    feature_data = {name: [0.5] for name in FEATURE_NAMES}
    mock_features_df = pd.DataFrame(feature_data)

    # Mock stage-1 model (LightGBM gibi)
    mock_stage1 = MagicMock()
    mock_stage1.predict_proba.return_value = np.array([[0.28, 0.72]])

    # Mock stage-2 modeller
    mock_stage2_first = MagicMock()
    mock_stage2_first.predict.return_value = np.array([0.45])

    mock_stage2_net = MagicMock()
    mock_stage2_net.predict.return_value = np.array([0.38])

    def mock_load_model(fuel_type, model_name):
        if model_name == "stage1":
            return mock_stage1
        elif model_name == "stage2_first":
            return mock_stage2_first
        elif model_name == "stage2_net":
            return mock_stage2_net
        return None  # calibrator yok

    with patch("src.predictor_v5.predictor._load_model", side_effect=mock_load_model), \
         patch("src.predictor_v5.predictor.compute_features_bulk", return_value=mock_features_df), \
         patch("src.predictor_v5.predictor.get_price_changed_today", return_value=False), \
         patch("src.predictor_v5.predictor._fetch_recent_risk_scores", return_value=[0.3, 0.35, 0.4, 0.5, 0.55, 0.6]), \
         patch("src.predictor_v5.predictor.get_latest_prediction_sync", return_value=None), \
         patch("src.predictor_v5.predictor.save_prediction_sync"), \
         patch("src.predictor_v5.predictor.store_snapshot"):

        result = predict("benzin", date(2026, 2, 18))

    assert result is not None
    assert result["fuel_type"] == "benzin"
    assert result["stage1_probability"] == pytest.approx(0.72, abs=0.01)
    assert result["first_event_direction"] == 1
    assert result["first_event_amount"] == pytest.approx(0.45, abs=0.01)
    assert result["net_amount_3d"] == pytest.approx(0.38, abs=0.01)
    assert result["model_version"] == "v5"
    assert result["alarm"]["should_alarm"] is True
    assert result["alarm"]["alarm_type"] in ("consistent", "gradual")

    clear_model_cache()


# ────────────────────────────────────────────────────────────────────────────
#  Test 10: Schemas validation (Pydantic)
# ────────────────────────────────────────────────────────────────────────────

def test_schemas_validation():
    """v5 Pydantic schemalari dogru validate etmeli."""
    from src.predictor_v5.schemas import PredictionV5Result, AlarmState

    # Valid prediction
    pred = PredictionV5Result(
        run_date=date(2026, 2, 18),
        fuel_type="benzin",
        stage1_probability=Decimal("0.72"),
        first_event_direction=1,
        first_event_amount=Decimal("0.45"),
        net_amount_3d=Decimal("0.38"),
        alarm_triggered=True,
        model_version="v5",
        calibration_method="platt",
    )
    assert pred.fuel_type == "benzin"
    assert pred.alarm_triggered is True

    # Valid alarm
    alarm = AlarmState(
        is_alarm=True,
        message="Test alarm mesaji",
        probability=0.72,
        suppressed=False,
    )
    assert alarm.is_alarm is True
    assert alarm.probability == 0.72
