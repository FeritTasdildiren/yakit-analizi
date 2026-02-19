"""
v5 Entegrasyon Testleri.

Celery task, Telegram handler ve Dashboard data_fetcher v5 entegrasyonunu test eder.
"""

import pytest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock, AsyncMock


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: Celery task run_daily_prediction_v5 cagirilabiliyor (mock predictor)
# ──────────────────────────────────────────────────────────────────────────────

def test_celery_task_v5_callable():
    """run_daily_prediction_v5 task'i import edilebilir ve cagirilabilir."""
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
    assert "benzin" in result["results"]
    assert "motorin" in result["results"]
    assert "lpg" in result["results"]
    assert result["results"]["benzin"]["prob"] == 0.72
    assert result["results"]["benzin"]["alarm"] is True
    assert result["results"]["lpg"] == "HATA"


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: Telegram handler v5 rapor veri cekme ve formatlama
# ──────────────────────────────────────────────────────────────────────────────

def test_telegram_v5_format_section():
    """_format_v5_section v5 tahmin verisini dogru formatlar."""
    from src.telegram.handlers import _format_v5_section

    test_data = {
        "fuel_type": "benzin",
        "stage1_probability": 0.72,
        "first_event_type": "artis",
        "first_event_amount": 0.45,
        "net_amount_3d": 0.38,
        "alarm_triggered": True,
        "alarm_type": "consistent",
        "alarm_message": "Test alarm",
    }

    result = _format_v5_section(test_data, "BENZIN")
    assert "ML Tahmin (v5)" in result
    assert "BENZIN" in result
    assert "%72" in result
    assert "0.45 TL/L" in result
    assert "0.38 TL/L" in result

    # None data
    result_none = _format_v5_section(None, "MOTORIN")
    assert "Veri yok" in result_none


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: format_full_report v5 parametreleri kabul ediyor
# ──────────────────────────────────────────────────────────────────────────────

def test_format_full_report_with_v5():
    """format_full_report v5 parametrelerini kabul eder ve ciktiya dahil eder."""
    from src.telegram.handlers import format_full_report

    v1_data = {
        "fuel_type": "benzin",
        "pump_price": 42.50,
        "mbe_value": -0.35,
        "risk_score": 65.0,
        "ml_direction": "hike",
        "ml_probability": 72.0,
        "expected_change": 0.45,
        "model_version": "v1.0",
    }

    v5_data = {
        "fuel_type": "benzin",
        "stage1_probability": 0.72,
        "first_event_type": "artis",
        "first_event_amount": 0.45,
        "net_amount_3d": 0.38,
        "alarm_triggered": True,
        "alarm_type": "consistent",
        "alarm_message": "Benzin alarm test",
    }

    # v5 parametreleri olmadan
    report_v1 = format_full_report(v1_data, None, None)
    assert "ML Predictor v5" in report_v1  # v5 section baslik

    # v5 parametreleri ile
    report_v5 = format_full_report(
        v1_data, None, None,
        v5_benzin=v5_data, v5_motorin=None, v5_lpg=None,
    )
    assert "ML Predictor v5" in report_v5
    assert "%72" in report_v5
    assert "0.45 TL/L" in report_v5


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: Alarm mesajlari Turkce entegre
# ──────────────────────────────────────────────────────────────────────────────

def test_alarm_messages_turkish():
    """v5 alarm mesajlari Turkce olusuyor."""
    from src.predictor_v5.alarm import generate_alarm_message

    prediction = {
        "fuel_type": "benzin",
        "stage1_probability": Decimal("0.72"),
        "first_event_direction": 1,
        "first_event_amount": Decimal("0.45"),
        "net_amount_3d": Decimal("0.38"),
    }

    # consistent
    msg = generate_alarm_message("consistent", prediction, "benzin")
    assert "Benzin" in msg
    assert "TL/lt" in msg
    assert "sinyal" in msg

    # volatile
    msg_vol = generate_alarm_message("volatile", prediction, "motorin")
    assert "Motorin" in msg_vol
    assert "sinyal" in msg_vol.lower() or "Kar" in msg_vol

    # gradual
    msg_grad = generate_alarm_message("gradual", prediction, "lpg")
    assert "LPG" in msg_grad

    # no_change
    msg_nc = generate_alarm_message("no_change", prediction, "benzin")
    assert "beklenmiyor" in msg_nc

    # already_happened
    msg_ah = generate_alarm_message("already_happened", prediction, "benzin")
    assert "zaten" in msg_ah


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: v1 pipeline bozulmamis (mevcut fonksiyonlar hala calisiyor)
# ──────────────────────────────────────────────────────────────────────────────

def test_v1_pipeline_intact():
    """v1 pipeline fonksiyonlari hala dogru calisiyor."""
    # Celery task import
    from src.celery_app.tasks import (
        collect_daily_market_data,
        run_daily_prediction,
        send_daily_notifications,
        health_check,
        calculate_daily_mbe,
        calculate_daily_risk,
    )

    # Tum task'lar callable
    assert callable(collect_daily_market_data)
    assert callable(run_daily_prediction)
    assert callable(send_daily_notifications)
    assert callable(health_check)
    assert callable(calculate_daily_mbe)
    assert callable(calculate_daily_risk)

    # Telegram handlers import
    from src.telegram.handlers import (
        rapor_command,
        iptal_command,
        yardim_command,
        format_full_report,
        format_daily_notification,
        _format_fuel_section,
        _risk_level,
        get_comment,
        get_risk_icon,
    )

    # v1 format fonksiyonlari hala calisiyor
    v1_data = {
        "fuel_type": "benzin",
        "pump_price": 42.50,
        "mbe_value": -0.35,
        "risk_score": 65.0,
        "ml_direction": "hike",
        "ml_probability": 72.0,
        "expected_change": 0.45,
        "model_version": "v1.0",
    }

    section = _format_fuel_section(v1_data, "BENZIN")
    assert "BENZIN" in section
    assert "42.50" in section

    assert get_comment(-0.35) == "Takipte"
    assert get_risk_icon(75.0) == "\U0001f534"


# ──────────────────────────────────────────────────────────────────────────────
# Test 6: Beat schedule pipeline sirasi dogru (predict_v5 18:35'te)
# ──────────────────────────────────────────────────────────────────────────────

def test_beat_schedule_v5_timing():
    """v5 prediction task'i beat schedule'da dogru zamanlama ile yer aliyor."""
    from src.celery_app.beat_schedule import CELERY_BEAT_SCHEDULE

    # v5 aksam schedule mevcut
    assert "run-daily-prediction-v5" in CELERY_BEAT_SCHEDULE
    v5_sched = CELERY_BEAT_SCHEDULE["run-daily-prediction-v5"]
    assert v5_sched["task"] == "src.celery_app.tasks.run_daily_prediction_v5"

    # Aksam pipeline sira kontrolu:
    # collect(18:00) -> MBE(18:10) -> risk(18:20) -> predict_v1(18:30) -> predict_v5(18:35)
    collect_sched = CELERY_BEAT_SCHEDULE["collect-daily-market-data"]["schedule"]
    mbe_sched = CELERY_BEAT_SCHEDULE["calculate-daily-mbe"]["schedule"]
    risk_sched = CELERY_BEAT_SCHEDULE["calculate-daily-risk"]["schedule"]
    v1_sched = CELERY_BEAT_SCHEDULE["run-daily-prediction"]["schedule"]
    v5_evening = CELERY_BEAT_SCHEDULE["run-daily-prediction-v5"]["schedule"]

    # Minute sirasi: 0, 10, 20, 30, 35
    assert collect_sched.minute == {0}
    assert mbe_sched.minute == {10}
    assert risk_sched.minute == {20}
    assert v1_sched.minute == {30}
    assert v5_evening.minute == {35}

    # Sabah v5 schedule mevcut
    assert "run-morning-prediction-v5" in CELERY_BEAT_SCHEDULE
    v5_morning = CELERY_BEAT_SCHEDULE["run-morning-prediction-v5"]
    assert v5_morning["task"] == "src.celery_app.tasks.run_daily_prediction_v5"


# ──────────────────────────────────────────────────────────────────────────────
# Test 7: Dashboard data_fetcher v5 fonksiyonlari import edilebilir
# ──────────────────────────────────────────────────────────────────────────────

def test_dashboard_data_fetcher_v5_import():
    """Dashboard data_fetcher v5 fonksiyonlari import edilebilir."""
    # Streamlit cache'i mock'la
    import sys
    mock_st = MagicMock()
    mock_st.cache_data = lambda ttl=0: lambda f: f  # passthrough decorator
    sys.modules['streamlit'] = mock_st

    try:
        from dashboard.components.data_fetcher import (
            get_latest_prediction_v5,
            get_prediction_v5_history_df,
            _fetch_latest_prediction_v5,
            _fetch_prediction_v5_history,
        )

        assert callable(get_latest_prediction_v5)
        assert callable(get_prediction_v5_history_df)
        assert callable(_fetch_latest_prediction_v5)
        assert callable(_fetch_prediction_v5_history)
    finally:
        if 'streamlit' in sys.modules and isinstance(sys.modules['streamlit'], MagicMock):
            del sys.modules['streamlit']


# ──────────────────────────────────────────────────────────────────────────────
# Test 8: format_daily_notification v5 alarmlarini gosteriyor
# ──────────────────────────────────────────────────────────────────────────────

def test_daily_notification_v5_alarm():
    """format_daily_notification v5 alarm bilgilerini iceriyor."""
    from src.telegram.handlers import format_daily_notification

    v1_data = {
        "fuel_type": "benzin",
        "pump_price": 42.50,
        "mbe_value": -0.35,
        "risk_score": 65.0,
        "ml_direction": "hike",
        "ml_probability": 72.0,
        "expected_change": 0.45,
        "model_version": "v1.0",
    }

    v5_data = {
        "fuel_type": "benzin",
        "stage1_probability": 0.72,
        "first_event_type": "artis",
        "first_event_amount": 0.45,
        "net_amount_3d": 0.38,
        "alarm_triggered": True,
        "alarm_type": "consistent",
        "alarm_message": "Benzin fiyat alarmi test",
    }

    # v5 alarm ile
    msg = format_daily_notification(
        v1_data, None, None,
        v5_benzin=v5_data, v5_motorin=None, v5_lpg=None,
    )
    assert "ML v5 Alarm" in msg
    assert "Benzin fiyat alarmi test" in msg

    # v5 alarm olmadan
    v5_no_alarm = {
        "fuel_type": "benzin",
        "stage1_probability": 0.40,
        "alarm_triggered": False,
        "alarm_message": None,
    }
    msg_no = format_daily_notification(
        v1_data, None, None,
        v5_benzin=v5_no_alarm,
    )
    assert "ML v5 Alarm" not in msg_no
