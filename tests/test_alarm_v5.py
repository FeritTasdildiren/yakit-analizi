"""
tests/test_alarm_v5.py — Alarm modülü testleri.

En az 8 test:
1. Yüksek prob + risk up → alarm True
2. Düşük prob → alarm False
3. Cooldown aktif → False
4. price_changed_today → already_happened
5. Volatile sinyal
6. Gradual sinyal
7. Risk trend hesaplama (up/down/stable)
8. Mesaj Türkçe kontrolü
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from src.predictor_v5.alarm import (
    compute_risk_trend,
    determine_alarm_type,
    evaluate_alarm,
    generate_alarm_message,
)


# ============================================================
# Yardımcı prediction dict'ler
# ============================================================

def _make_prediction(
    prob=0.70,
    direction=1,
    first_amount=0.50,
    net_amount=0.50,
    fuel_type="benzin",
):
    """Test için prediction dict oluştur."""
    return {
        "fuel_type": fuel_type,
        "stage1_probability": Decimal(str(prob)),
        "first_event_direction": direction,
        "first_event_amount": Decimal(str(first_amount)),
        "net_amount_3d": Decimal(str(net_amount)),
    }


# ============================================================
# Test 1: Yüksek prob + risk up → alarm True (consistent)
# ============================================================

class TestEvaluateAlarmHighProbRiskUp:
    """Yüksek olasılık + yükselen risk → alarm tetiklenmeli."""

    def test_should_alarm_true(self):
        pred = _make_prediction(prob=0.70, direction=1, net_amount=0.50)
        result = evaluate_alarm(
            prediction=pred,
            risk_trend="up",
            last_alarm_time=None,
            last_price_change_time=None,
            price_changed_today=False,
        )
        assert result["should_alarm"] is True
        assert result["alarm_type"] == "consistent"
        assert result["confidence"] == pytest.approx(0.70, abs=0.001)
        assert result["cooldown_active"] is False

    def test_message_not_none(self):
        pred = _make_prediction(prob=0.60, direction=1, net_amount=0.40)
        result = evaluate_alarm(
            prediction=pred,
            risk_trend="up",
            last_alarm_time=None,
            last_price_change_time=None,
            price_changed_today=False,
        )
        assert result["message"] is not None
        assert len(result["message"]) > 10


# ============================================================
# Test 2: Düşük prob → alarm False
# ============================================================

class TestEvaluateAlarmLowProb:
    """Düşük olasılık → alarm tetiklenmemeli."""

    def test_low_prob_no_alarm(self):
        pred = _make_prediction(prob=0.10, direction=1, net_amount=0.50)  # v6: 0.30->0.10 (threshold 0.25)
        result = evaluate_alarm(
            prediction=pred,
            risk_trend="up",
            last_alarm_time=None,
            last_price_change_time=None,
            price_changed_today=False,
        )
        assert result["should_alarm"] is False
        assert result["alarm_type"] is None

    def test_threshold_boundary_below(self):
        """Tam eşiğin altı (0.5499) → alarm yok."""
        pred = _make_prediction(prob=0.2499, direction=1, net_amount=0.50)  # v6: threshold 0.25
        result = evaluate_alarm(
            prediction=pred,
            risk_trend="up",
            last_alarm_time=None,
            last_price_change_time=None,
            price_changed_today=False,
        )
        assert result["should_alarm"] is False

    def test_threshold_boundary_exact(self):
        """Tam eşik (0.55) → alarm var (>= kontrolü)."""
        pred = _make_prediction(prob=0.55, direction=1, net_amount=0.50)
        result = evaluate_alarm(
            prediction=pred,
            risk_trend="up",
            last_alarm_time=None,
            last_price_change_time=None,
            price_changed_today=False,
        )
        assert result["should_alarm"] is True


# ============================================================
# Test 3: Cooldown aktif → alarm False
# ============================================================

class TestCooldownActive:
    """Son 24 saat içinde alarm gönderilmişse cooldown aktif."""

    def test_cooldown_blocks_alarm(self):
        recent_alarm = datetime.utcnow() - timedelta(hours=2)
        pred = _make_prediction(prob=0.80, direction=1, net_amount=0.50)
        result = evaluate_alarm(
            prediction=pred,
            risk_trend="up",
            last_alarm_time=recent_alarm,
            last_price_change_time=None,
            price_changed_today=False,
        )
        assert result["should_alarm"] is False
        assert result["cooldown_active"] is True
        assert result["cooldown_remaining_hours"] > 0

    def test_cooldown_expired(self):
        old_alarm = datetime.utcnow() - timedelta(hours=25)
        pred = _make_prediction(prob=0.80, direction=1, net_amount=0.50)
        result = evaluate_alarm(
            prediction=pred,
            risk_trend="up",
            last_alarm_time=old_alarm,
            last_price_change_time=None,
            price_changed_today=False,
        )
        assert result["should_alarm"] is True
        assert result["cooldown_active"] is False


# ============================================================
# Test 4: price_changed_today → already_happened
# ============================================================

class TestPriceChangedToday:
    """Bugün fiyat değiştiyse → already_happened tipi."""

    def test_already_happened(self):
        pred = _make_prediction(prob=0.80, direction=1, net_amount=0.50)
        result = evaluate_alarm(
            prediction=pred,
            risk_trend="up",
            last_alarm_time=None,
            last_price_change_time=None,
            price_changed_today=True,
        )
        assert result["should_alarm"] is True
        assert result["alarm_type"] == "already_happened"
        assert "fiyat" in result["message"].lower() or "değişikliği" in result["message"].lower()

    def test_already_happened_overrides_cooldown(self):
        """Fiyat değişimi cooldown'dan önce gelir."""
        recent_alarm = datetime.utcnow() - timedelta(hours=2)
        pred = _make_prediction(prob=0.80, direction=1, net_amount=0.50)
        result = evaluate_alarm(
            prediction=pred,
            risk_trend="up",
            last_alarm_time=recent_alarm,
            last_price_change_time=None,
            price_changed_today=True,
        )
        assert result["alarm_type"] == "already_happened"


# ============================================================
# Test 5: Volatile sinyal (yönler farklı)
# ============================================================

class TestVolatileSignal:
    """first_event_direction ve net_amount_3d farklı yönlerde → volatile."""

    def test_volatile_alarm(self):
        pred = _make_prediction(prob=0.70, direction=1, net_amount=-0.20)
        result = evaluate_alarm(
            prediction=pred,
            risk_trend="up",
            last_alarm_time=None,
            last_price_change_time=None,
            price_changed_today=False,
        )
        assert result["should_alarm"] is True
        assert result["alarm_type"] == "volatile"

    def test_volatile_type_direct(self):
        pred = {"first_event_direction": 1, "net_amount_3d": Decimal("-0.30")}
        assert determine_alarm_type(pred, "up") == "volatile"


# ============================================================
# Test 6: Gradual sinyal (küçük ama tutarlı)
# ============================================================

class TestGradualSignal:
    """Yön tutarlı ama net_amount < 0.30 → gradual."""

    def test_gradual_alarm(self):
        pred = _make_prediction(prob=0.65, direction=1, net_amount=0.15)
        result = evaluate_alarm(
            prediction=pred,
            risk_trend="up",
            last_alarm_time=None,
            last_price_change_time=None,
            price_changed_today=False,
        )
        assert result["should_alarm"] is True
        assert result["alarm_type"] == "gradual"

    def test_gradual_type_direct(self):
        pred = {"first_event_direction": -1, "net_amount_3d": Decimal("-0.10")}
        assert determine_alarm_type(pred, "up") == "gradual"


# ============================================================
# Test 7: Risk trend hesaplama
# ============================================================

class TestComputeRiskTrend:
    """compute_risk_trend fonksiyonu testleri."""

    def test_trend_up(self):
        # Son 3: [0.60, 0.65, 0.70] avg=0.65
        # Önceki 3: [0.40, 0.45, 0.50] avg=0.45
        # diff=0.20 > 0.02 → "up"
        scores = [0.40, 0.45, 0.50, 0.60, 0.65, 0.70]
        assert compute_risk_trend(scores) == "up"

    def test_trend_down(self):
        # Son 3: [0.30, 0.35, 0.25] avg=0.30
        # Önceki 3: [0.60, 0.65, 0.55] avg=0.60
        # diff=-0.30 < -0.02 → "down"
        scores = [0.60, 0.65, 0.55, 0.30, 0.35, 0.25]
        assert compute_risk_trend(scores) == "down"

    def test_trend_stable(self):
        # Son 3: [0.50, 0.51, 0.49] avg≈0.50
        # Önceki 3: [0.50, 0.49, 0.51] avg≈0.50
        # diff≈0 → "stable"
        scores = [0.50, 0.49, 0.51, 0.50, 0.51, 0.49]
        assert compute_risk_trend(scores) == "stable"

    def test_insufficient_data(self):
        """6'dan az skor → stable."""
        assert compute_risk_trend([0.5, 0.6]) == "stable"
        assert compute_risk_trend([]) == "stable"

    def test_exact_threshold_boundary(self):
        """Fark eşiğin hemen altında → stable."""
        # avg_recent=0.5133, avg_prev=0.50, diff=0.0133 < 0.02 → stable
        scores = [0.50, 0.50, 0.50, 0.51, 0.52, 0.51]
        assert compute_risk_trend(scores) == "stable"

    def test_more_than_six_scores(self):
        """7+ skor → son 6'yı kullanır."""
        scores = [0.10, 0.20, 0.40, 0.45, 0.50, 0.60, 0.65, 0.70]
        assert compute_risk_trend(scores) == "up"


# ============================================================
# Test 8: Mesaj Türkçe kontrolü
# ============================================================

class TestTurkishMessages:
    """Tüm mesajlar Türkçe olmalı."""

    def test_consistent_message_turkish(self):
        pred = _make_prediction(prob=0.75, direction=1, net_amount=0.50, fuel_type="motorin")
        msg = generate_alarm_message("consistent", pred, "motorin")
        assert "Motorin" in msg
        assert "Fiyat" in msg
        assert "bekleniyor" in msg
        assert "güveni" in msg

    def test_volatile_message_turkish(self):
        pred = _make_prediction(prob=0.60, direction=1, net_amount=-0.30)
        msg = generate_alarm_message("volatile", pred, "benzin")
        assert "Benzin" in msg
        assert "sinyaller" in msg

    def test_gradual_message_turkish(self):
        pred = _make_prediction(prob=0.60, direction=-1, net_amount=-0.15)
        msg = generate_alarm_message("gradual", pred, "lpg")
        assert "LPG" in msg
        assert "Kademeli" in msg

    def test_no_change_message_turkish(self):
        pred = _make_prediction(prob=0.40)
        msg = generate_alarm_message("no_change", pred, "benzin")
        assert "beklenmiyor" in msg

    def test_already_happened_message_turkish(self):
        pred = _make_prediction(prob=0.80)
        msg = generate_alarm_message("already_happened", pred, "motorin")
        assert "gerçekleşti" in msg or "değişikliği" in msg
        assert "yarın" in msg


# ============================================================
# Test 9: determine_alarm_type ek testleri
# ============================================================

class TestDetermineAlarmType:
    """determine_alarm_type fonksiyon testleri."""

    def test_no_change_direction_zero(self):
        pred = {"first_event_direction": 0, "net_amount_3d": Decimal("0.50")}
        assert determine_alarm_type(pred, "up") == "no_change"

    def test_no_change_net_amount_none(self):
        pred = {"first_event_direction": 1, "net_amount_3d": None}
        assert determine_alarm_type(pred, "up") == "no_change"

    def test_consistent_negative(self):
        """Negatif yön, büyük düşüş → consistent."""
        pred = {"first_event_direction": -1, "net_amount_3d": Decimal("-0.50")}
        assert determine_alarm_type(pred, "up") == "consistent"

    def test_boundary_030(self):
        """Tam 0.30 → consistent (>= 0.30)."""
        pred = {"first_event_direction": 1, "net_amount_3d": Decimal("0.30")}
        assert determine_alarm_type(pred, "up") == "consistent"

    def test_just_below_030(self):
        """0.29 → gradual (< 0.30)."""
        pred = {"first_event_direction": 1, "net_amount_3d": Decimal("0.29")}
        assert determine_alarm_type(pred, "up") == "gradual"


# ============================================================
# Test 10: Risk trend "down" veya "stable" → alarm yok
# ============================================================

class TestRiskTrendNotUp:
    """Risk trend up değilse alarm tetiklenmemeli."""

    def test_risk_down_no_alarm(self):
        # v6: risk_trend artık engel değil, prob >= 0.25 alarm tetikler
        pred = _make_prediction(prob=0.80, direction=1, net_amount=0.50)
        result = evaluate_alarm(
            prediction=pred,
            risk_trend="down",
            last_alarm_time=None,
            last_price_change_time=None,
            price_changed_today=False,
        )
        assert result["should_alarm"] is True  # v6: gevşetilmiş koşul

    def test_risk_stable_no_alarm(self):
        # v6: risk_trend artık engel değil, prob >= 0.25 alarm tetikler
        pred = _make_prediction(prob=0.80, direction=1, net_amount=0.50)
        result = evaluate_alarm(
            prediction=pred,
            risk_trend="stable",
            last_alarm_time=None,
            last_price_change_time=None,
            price_changed_today=False,
        )
        assert result["should_alarm"] is True  # v6: gevşetilmiş koşul
