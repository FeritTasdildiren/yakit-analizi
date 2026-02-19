"""
Predictor v5 — predictor.py Unit Tests
========================================
Mock modeller ile tam pipeline testi.
En az 10 test: pipeline, stage-2 kosullu, kalibrasyon, cache, alarm, snapshot, vb.
"""

import importlib
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# FEATURE_NAMES'i config'den al
# ---------------------------------------------------------------------------
from src.predictor_v5.config import FEATURE_NAMES, FUEL_TYPES


# ---------------------------------------------------------------------------
# Yardimci: Mock feature DataFrame olustur
# ---------------------------------------------------------------------------

def _make_features_df(fuel_type: str = "benzin", target_date=None):
    """35 feature iceren 1 satirlik DataFrame uret."""
    if target_date is None:
        target_date = date(2026, 2, 18)
    row = {"trade_date": target_date, "fuel_type": fuel_type}
    for fn in FEATURE_NAMES:
        row[fn] = np.random.uniform(0, 1)
    return pd.DataFrame([row])


def _make_mock_stage1(prob: float = 0.7):
    """predict_proba donen mock stage-1 model."""
    mock = MagicMock()
    mock.predict_proba.return_value = np.array([[1 - prob, prob]])
    return mock


def _make_mock_stage2(value: float = 0.5):
    """predict donen mock stage-2 model."""
    mock = MagicMock()
    mock.predict.return_value = np.array([value])
    return mock


# ---------------------------------------------------------------------------
# Fixture: predictor modulunu import et ve cache temizle
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_cache():
    """Her testten once model cache'i temizle."""
    from src.predictor_v5 import predictor
    predictor._model_cache.clear()
    yield
    predictor._model_cache.clear()


# ===========================================================================
# TEST 1: Tam pipeline (mock modeller)
# ===========================================================================

@patch("src.predictor_v5.predictor.store_snapshot")
@patch("src.predictor_v5.predictor.save_prediction_sync")
@patch("src.predictor_v5.predictor.get_latest_prediction_sync", return_value=None)
@patch("src.predictor_v5.predictor.get_price_changed_today", return_value=False)
@patch("src.predictor_v5.predictor._fetch_recent_risk_scores", return_value=[0.5, 0.5, 0.5, 0.6, 0.6, 0.7])
@patch("src.predictor_v5.predictor.compute_features_bulk")
@patch("src.predictor_v5.predictor._load_model")
def test_full_pipeline(
    mock_load, mock_features, mock_risk,
    mock_price_changed, mock_latest, mock_save, mock_snapshot,
):
    """Tam pipeline: features -> stage1 -> stage2 -> alarm -> DB -> snapshot."""
    from src.predictor_v5.predictor import predict

    td = date(2026, 2, 18)
    mock_features.return_value = _make_features_df("benzin", td)

    # Model mocklar
    def side_effect(fuel, name):
        if name == "stage1":
            return _make_mock_stage1(0.75)
        elif name == "stage2_first":
            return _make_mock_stage2(0.45)  # artis
        elif name == "stage2_net":
            return _make_mock_stage2(0.30)
        elif name == "calibrator":
            return None  # kalibrator yok
        return None

    mock_load.side_effect = side_effect

    result = predict("benzin", target_date=td)

    assert result is not None
    assert result["fuel_type"] == "benzin"
    assert result["target_date"] == "2026-02-18"
    assert result["model_version"] == "v5"
    assert 0.0 <= result["stage1_probability"] <= 1.0
    assert result["stage1_probability_raw"] == pytest.approx(0.75, abs=0.01)
    assert result["first_event_direction"] == 1  # artis
    assert result["first_event_amount"] > 0
    assert result["net_amount_3d"] > 0
    assert "alarm" in result
    assert "predicted_at" in result

    # DB kaydi yapildi mi?
    mock_save.assert_called_once()
    # Feature snapshot kaydi yapildi mi?
    mock_snapshot.assert_called_once()


# ===========================================================================
# TEST 2: Stage-2 sadece pozitifle calisiyor
# ===========================================================================

@patch("src.predictor_v5.predictor.store_snapshot")
@patch("src.predictor_v5.predictor.save_prediction_sync")
@patch("src.predictor_v5.predictor.get_latest_prediction_sync", return_value=None)
@patch("src.predictor_v5.predictor.get_price_changed_today", return_value=False)
@patch("src.predictor_v5.predictor._fetch_recent_risk_scores", return_value=[])
@patch("src.predictor_v5.predictor.compute_features_bulk")
@patch("src.predictor_v5.predictor._load_model")
def test_stage2_only_on_positive(
    mock_load, mock_features, mock_risk,
    mock_price_changed, mock_latest, mock_save, mock_snapshot,
):
    """Stage-1 prob >= 0.25 (v6) ise Stage-2 calisir, dusuk ise calismaz."""
    from src.predictor_v5.predictor import predict

    td = date(2026, 2, 18)
    mock_features.return_value = _make_features_df("benzin", td)

    stage2_first_mock = _make_mock_stage2(-0.30)  # dusus
    stage2_net_mock = _make_mock_stage2(-0.25)

    def side_effect(fuel, name):
        if name == "stage1":
            return _make_mock_stage1(0.80)
        elif name == "stage2_first":
            return stage2_first_mock
        elif name == "stage2_net":
            return stage2_net_mock
        elif name == "calibrator":
            return None
        return None

    mock_load.side_effect = side_effect

    result = predict("benzin", target_date=td)

    assert result is not None
    assert result["first_event_direction"] == -1  # dusus
    assert result["first_event_amount"] < 0
    assert result["net_amount_3d"] < 0

    # Stage-2 modelleri cagirildi
    stage2_first_mock.predict.assert_called_once()
    stage2_net_mock.predict.assert_called_once()


# ===========================================================================
# TEST 3: Stage-2 skip (dusuk prob)
# ===========================================================================

@patch("src.predictor_v5.predictor.store_snapshot")
@patch("src.predictor_v5.predictor.save_prediction_sync")
@patch("src.predictor_v5.predictor.get_latest_prediction_sync", return_value=None)
@patch("src.predictor_v5.predictor.get_price_changed_today", return_value=False)
@patch("src.predictor_v5.predictor._fetch_recent_risk_scores", return_value=[])
@patch("src.predictor_v5.predictor.compute_features_bulk")
@patch("src.predictor_v5.predictor._load_model")
def test_stage2_skip_low_prob(
    mock_load, mock_features, mock_risk,
    mock_price_changed, mock_latest, mock_save, mock_snapshot,
):
    """Stage-1 prob < 0.25 (v6) -> Stage-2 atlanir, first_event=0, net_amount=0."""
    from src.predictor_v5.predictor import predict

    td = date(2026, 2, 18)
    mock_features.return_value = _make_features_df("motorin", td)

    stage2_first_mock = _make_mock_stage2(0.5)
    stage2_net_mock = _make_mock_stage2(0.3)

    def side_effect(fuel, name):
        if name == "stage1":
            return _make_mock_stage1(0.15)  # v6: dusuk prob (< 0.25)
        elif name == "stage2_first":
            return stage2_first_mock
        elif name == "stage2_net":
            return stage2_net_mock
        elif name == "calibrator":
            return None
        return None

    mock_load.side_effect = side_effect

    result = predict("motorin", target_date=td)

    assert result is not None
    assert result["stage1_probability_raw"] == pytest.approx(0.15, abs=0.01)  # v6
    assert result["first_event_direction"] == 0
    assert result["first_event_amount"] == 0.0
    assert result["net_amount_3d"] == 0.0
    assert result["first_event_type"] is None

    # Stage-2 modelleri CAGIRILMADI
    stage2_first_mock.predict.assert_not_called()
    stage2_net_mock.predict.assert_not_called()


# ===========================================================================
# TEST 4: Kalibrator yok -> raw prob
# ===========================================================================

@patch("src.predictor_v5.predictor.store_snapshot")
@patch("src.predictor_v5.predictor.save_prediction_sync")
@patch("src.predictor_v5.predictor.get_latest_prediction_sync", return_value=None)
@patch("src.predictor_v5.predictor.get_price_changed_today", return_value=False)
@patch("src.predictor_v5.predictor._fetch_recent_risk_scores", return_value=[])
@patch("src.predictor_v5.predictor.compute_features_bulk")
@patch("src.predictor_v5.predictor._load_model")
def test_no_calibrator_raw_prob(
    mock_load, mock_features, mock_risk,
    mock_price_changed, mock_latest, mock_save, mock_snapshot,
):
    """Kalibrator yoksa raw probability kullanilir."""
    from src.predictor_v5.predictor import predict

    td = date(2026, 2, 18)
    mock_features.return_value = _make_features_df("lpg", td)

    def side_effect(fuel, name):
        if name == "stage1":
            return _make_mock_stage1(0.65)
        elif name == "calibrator":
            return None  # kalibrator yok
        elif name == "stage2_first":
            return _make_mock_stage2(0.1)
        elif name == "stage2_net":
            return _make_mock_stage2(0.05)
        return None

    mock_load.side_effect = side_effect

    result = predict("lpg", target_date=td)

    assert result is not None
    # Raw prob = kalibre prob (kalibrator yok)
    assert result["stage1_probability"] == result["stage1_probability_raw"]
    assert result["calibration_method"] == "raw"


# ===========================================================================
# TEST 5: Model yok -> None don
# ===========================================================================

@patch("src.predictor_v5.predictor.compute_features_bulk")
@patch("src.predictor_v5.predictor._load_model", return_value=None)
def test_no_model_returns_none(mock_load, mock_features):
    """Stage-1 model yoksa None doner."""
    from src.predictor_v5.predictor import predict

    td = date(2026, 2, 18)
    mock_features.return_value = _make_features_df("benzin", td)

    result = predict("benzin", target_date=td)
    assert result is None


# ===========================================================================
# TEST 6: predict_all 3 yakit tipi
# ===========================================================================

@patch("src.predictor_v5.predictor.predict")
def test_predict_all(mock_predict):
    """predict_all 3 yakit tipi icin predict cagirir."""
    from src.predictor_v5.predictor import predict_all

    mock_predict.return_value = {"fuel_type": "test", "stage1_probability": 0.5}

    td = date(2026, 2, 18)
    results = predict_all(target_date=td)

    assert set(results.keys()) == {"benzin", "motorin", "lpg"}
    assert mock_predict.call_count == 3

    # Her yakit tipi icin dogru parametrelerle cagirildi mi?
    call_fuels = [c.args[0] for c in mock_predict.call_args_list]
    assert sorted(call_fuels) == sorted(FUEL_TYPES)


# ===========================================================================
# TEST 7: Model cache calisiyor
# ===========================================================================

def test_model_cache():
    """Ayni model ikinci yuklemede cache'den gelir (diskten okumaz)."""
    from src.predictor_v5.predictor import _load_model, _model_cache

    # Direkt cache'e model yerlestir
    mock_model = MagicMock()
    _model_cache["benzin_stage1"] = mock_model

    # Cache'den gelmeli
    loaded = _load_model("benzin", "stage1")
    assert loaded is mock_model


# ===========================================================================
# TEST 8: Feature snapshot kaydediliyor
# ===========================================================================

@patch("src.predictor_v5.predictor.store_snapshot")
@patch("src.predictor_v5.predictor.save_prediction_sync")
@patch("src.predictor_v5.predictor.get_latest_prediction_sync", return_value=None)
@patch("src.predictor_v5.predictor.get_price_changed_today", return_value=False)
@patch("src.predictor_v5.predictor._fetch_recent_risk_scores", return_value=[])
@patch("src.predictor_v5.predictor.compute_features_bulk")
@patch("src.predictor_v5.predictor._load_model")
def test_feature_snapshot_saved(
    mock_load, mock_features, mock_risk,
    mock_price_changed, mock_latest, mock_save, mock_snapshot,
):
    """Feature snapshot store_snapshot ile kaydedilir."""
    from src.predictor_v5.predictor import predict

    td = date(2026, 2, 18)
    mock_features.return_value = _make_features_df("benzin", td)

    def side_effect(fuel, name):
        if name == "stage1":
            return _make_mock_stage1(0.40)  # dusuk prob
        elif name == "calibrator":
            return None
        return None

    mock_load.side_effect = side_effect

    result = predict("benzin", target_date=td)
    assert result is not None

    # store_snapshot fuel_type, target_date, feature_dict ile cagirildi mi?
    mock_snapshot.assert_called_once()
    call_args = mock_snapshot.call_args
    assert call_args.args[0] == "benzin"  # fuel_type
    assert call_args.args[1] == td  # run_date
    assert isinstance(call_args.args[2], dict)  # feature_dict
    assert len(call_args.args[2]) == len(FEATURE_NAMES)


# ===========================================================================
# TEST 9: Alarm entegrasyonu
# ===========================================================================

@patch("src.predictor_v5.predictor.store_snapshot")
@patch("src.predictor_v5.predictor.save_prediction_sync")
@patch("src.predictor_v5.predictor.get_latest_prediction_sync", return_value=None)
@patch("src.predictor_v5.predictor.get_price_changed_today", return_value=False)
@patch("src.predictor_v5.predictor._fetch_recent_risk_scores", return_value=[0.3, 0.3, 0.3, 0.5, 0.6, 0.7])
@patch("src.predictor_v5.predictor.compute_features_bulk")
@patch("src.predictor_v5.predictor._load_model")
def test_alarm_integration(
    mock_load, mock_features, mock_risk,
    mock_price_changed, mock_latest, mock_save, mock_snapshot,
):
    """Alarm degerlendirmesi sonuc dict'ine dahil ediliyor."""
    from src.predictor_v5.predictor import predict

    td = date(2026, 2, 18)
    mock_features.return_value = _make_features_df("benzin", td)

    def side_effect(fuel, name):
        if name == "stage1":
            return _make_mock_stage1(0.80)
        elif name == "stage2_first":
            return _make_mock_stage2(0.50)
        elif name == "stage2_net":
            return _make_mock_stage2(0.40)
        elif name == "calibrator":
            return None
        return None

    mock_load.side_effect = side_effect

    result = predict("benzin", target_date=td)

    assert result is not None
    alarm = result["alarm"]
    assert "should_alarm" in alarm
    assert "alarm_type" in alarm
    assert "message" in alarm
    assert "confidence" in alarm
    assert isinstance(alarm["should_alarm"], bool)

    # Risk trend: up (son 3 > onceki 3, fark > 0.02)
    assert result["risk_trend"] == "up"


# ===========================================================================
# TEST 10: clear_model_cache
# ===========================================================================

def test_clear_model_cache():
    """clear_model_cache sonrasi cache bos."""
    from src.predictor_v5.predictor import clear_model_cache, _model_cache

    _model_cache["benzin_stage1"] = MagicMock()
    _model_cache["motorin_stage1"] = MagicMock()
    assert len(_model_cache) == 2

    clear_model_cache()
    assert len(_model_cache) == 0


# ===========================================================================
# TEST 11: Feature hesaplama hatasi -> None
# ===========================================================================

@patch("src.predictor_v5.predictor.compute_features_bulk", side_effect=Exception("DB error"))
def test_feature_error_returns_none(mock_features):
    """Feature hesaplama hatasi durumunda None doner."""
    from src.predictor_v5.predictor import predict

    result = predict("benzin", target_date=date(2026, 2, 18))
    assert result is None


# ===========================================================================
# TEST 12: Bos features DataFrame -> None
# ===========================================================================

@patch("src.predictor_v5.predictor.compute_features_bulk")
def test_empty_features_returns_none(mock_features):
    """Bos features DataFrame -> None."""
    from src.predictor_v5.predictor import predict

    cols = ["trade_date", "fuel_type"] + list(FEATURE_NAMES)
    mock_features.return_value = pd.DataFrame(columns=cols)

    result = predict("benzin", target_date=date(2026, 2, 18))
    assert result is None


# ===========================================================================
# TEST 13: DB hatasi -> tahmin yine doner
# ===========================================================================

@patch("src.predictor_v5.predictor.store_snapshot")
@patch("src.predictor_v5.predictor.save_prediction_sync", side_effect=Exception("DB write error"))
@patch("src.predictor_v5.predictor.get_latest_prediction_sync", return_value=None)
@patch("src.predictor_v5.predictor.get_price_changed_today", return_value=False)
@patch("src.predictor_v5.predictor._fetch_recent_risk_scores", return_value=[])
@patch("src.predictor_v5.predictor.compute_features_bulk")
@patch("src.predictor_v5.predictor._load_model")
def test_db_error_still_returns_result(
    mock_load, mock_features, mock_risk,
    mock_price_changed, mock_latest, mock_save, mock_snapshot,
):
    """DB kayit hatasi olsa bile tahmin sonucu doner."""
    from src.predictor_v5.predictor import predict

    td = date(2026, 2, 18)
    mock_features.return_value = _make_features_df("benzin", td)

    def side_effect(fuel, name):
        if name == "stage1":
            return _make_mock_stage1(0.60)
        elif name == "calibrator":
            return None
        elif name == "stage2_first":
            return _make_mock_stage2(0.2)
        elif name == "stage2_net":
            return _make_mock_stage2(0.1)
        return None

    mock_load.side_effect = side_effect

    result = predict("benzin", target_date=td)

    # DB hatasi olsa bile sonuc donuyor
    assert result is not None
    assert result["fuel_type"] == "benzin"
    assert result["stage1_probability"] == pytest.approx(0.60, abs=0.01)
