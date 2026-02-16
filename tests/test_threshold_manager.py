"""
Eşik Yöneticisi testleri.

check_hysteresis, check_cooldown, seed_default_thresholds ve
apply_regime_to_thresholds fonksiyonları için kapsamlı testler.
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal

from src.core.threshold_manager import (
    DEFAULT_THRESHOLDS,
    ThresholdDef,
    apply_regime_to_thresholds,
    build_threshold_seed_data,
    check_cooldown,
    check_hysteresis,
    get_seed_thresholds,
)


# ────────────────────────────────────────────────────────────────────────────
#  check_hysteresis testleri
# ────────────────────────────────────────────────────────────────────────────


class TestCheckHysteresis:
    """check_hysteresis fonksiyonu testleri."""

    def test_alarm_opens_at_threshold(self):
        """Değer >= açılış eşiği ve alarm kapalıyken → True (alarm aç)."""
        result = check_hysteresis(
            current_value=Decimal("0.60"),
            threshold_open=Decimal("0.60"),
            threshold_close=Decimal("0.45"),
            previous_alert_active=False,
        )
        assert result is True

    def test_alarm_stays_closed_below_open(self):
        """Değer < açılış eşiği ve alarm kapalıyken → False."""
        result = check_hysteresis(
            current_value=Decimal("0.55"),
            threshold_open=Decimal("0.60"),
            threshold_close=Decimal("0.45"),
            previous_alert_active=False,
        )
        assert result is False

    def test_alarm_stays_open_in_hysteresis_band(self):
        """Alarm açıkken, kapanış üstünde ama açılış altında → True (açık kalır)."""
        result = check_hysteresis(
            current_value=Decimal("0.50"),
            threshold_open=Decimal("0.60"),
            threshold_close=Decimal("0.45"),
            previous_alert_active=True,
        )
        assert result is True

    def test_alarm_closes_at_threshold(self):
        """Alarm açıkken, değer <= kapanış → False (alarm kapat)."""
        result = check_hysteresis(
            current_value=Decimal("0.45"),
            threshold_open=Decimal("0.60"),
            threshold_close=Decimal("0.45"),
            previous_alert_active=True,
        )
        assert result is False

    def test_alarm_closes_well_below(self):
        """Alarm açıkken, değer kapanışın çok altında → False."""
        result = check_hysteresis(
            current_value=Decimal("0.20"),
            threshold_open=Decimal("0.60"),
            threshold_close=Decimal("0.45"),
            previous_alert_active=True,
        )
        assert result is False


# ────────────────────────────────────────────────────────────────────────────
#  check_cooldown testleri
# ────────────────────────────────────────────────────────────────────────────


class TestCheckCooldown:
    """check_cooldown fonksiyonu testleri."""

    def test_no_previous_alert_cooldown_passed(self):
        """Önceki alarm yoksa → cooldown geçmiş."""
        assert check_cooldown(last_alert_time=None, cooldown_hours=24) is True

    def test_cooldown_not_passed(self):
        """Cooldown süresi henüz dolmamış → False."""
        now = datetime(2026, 2, 15, 12, 0, 0)
        last = datetime(2026, 2, 15, 6, 0, 0)  # 6 saat önce
        assert check_cooldown(last, cooldown_hours=24, current_time=now) is False

    def test_cooldown_passed(self):
        """Cooldown süresi dolmuş → True."""
        now = datetime(2026, 2, 16, 12, 0, 0)
        last = datetime(2026, 2, 15, 6, 0, 0)  # 30 saat önce
        assert check_cooldown(last, cooldown_hours=24, current_time=now) is True

    def test_cooldown_exactly_at_boundary(self):
        """Tam cooldown süresi kadar geçmiş → True (>=)."""
        now = datetime(2026, 2, 16, 6, 0, 0)
        last = datetime(2026, 2, 15, 6, 0, 0)  # Tam 24 saat
        assert check_cooldown(last, cooldown_hours=24, current_time=now) is True

    def test_short_cooldown(self):
        """Kısa cooldown (12 saat) kontrolü."""
        now = datetime(2026, 2, 15, 20, 0, 0)
        last = datetime(2026, 2, 15, 6, 0, 0)  # 14 saat önce
        assert check_cooldown(last, cooldown_hours=12, current_time=now) is True


# ────────────────────────────────────────────────────────────────────────────
#  Default seed testleri
# ────────────────────────────────────────────────────────────────────────────


class TestDefaultThresholds:
    """Varsayılan eşik tanımları testleri."""

    def test_seed_returns_four_thresholds(self):
        """4 adet varsayılan eşik tanımı olmalı."""
        thresholds = get_seed_thresholds()
        assert len(thresholds) == 4

    def test_risk_score_warning_values(self):
        """Risk skoru warning eşikleri: open=0.60, close=0.45."""
        thresholds = get_seed_thresholds()
        rs_warning = [t for t in thresholds if t.metric_name == "risk_score" and t.alert_level == "warning"]
        assert len(rs_warning) == 1
        assert rs_warning[0].threshold_open == Decimal("0.60")
        assert rs_warning[0].threshold_close == Decimal("0.45")

    def test_risk_score_critical_values(self):
        """Risk skoru critical eşikleri: open=0.70, close=0.55."""
        thresholds = get_seed_thresholds()
        rs_critical = [t for t in thresholds if t.metric_name == "risk_score" and t.alert_level == "critical"]
        assert len(rs_critical) == 1
        assert rs_critical[0].threshold_open == Decimal("0.70")
        assert rs_critical[0].threshold_close == Decimal("0.55")

    def test_mbe_warning_values(self):
        """MBE warning eşikleri: open=0.50, close=0.35."""
        thresholds = get_seed_thresholds()
        mbe_warning = [t for t in thresholds if t.metric_name == "mbe_value" and t.alert_level == "warning"]
        assert len(mbe_warning) == 1
        assert mbe_warning[0].threshold_open == Decimal("0.50")
        assert mbe_warning[0].threshold_close == Decimal("0.35")

    def test_mbe_critical_values(self):
        """MBE critical eşikleri: open=0.70, close=0.55."""
        thresholds = get_seed_thresholds()
        mbe_critical = [t for t in thresholds if t.metric_name == "mbe_value" and t.alert_level == "critical"]
        assert len(mbe_critical) == 1
        assert mbe_critical[0].threshold_open == Decimal("0.70")
        assert mbe_critical[0].threshold_close == Decimal("0.55")

    def test_build_seed_data_format(self):
        """build_threshold_seed_data doğru formatta dict listesi döndürmeli."""
        from datetime import date
        seed_data = build_threshold_seed_data(valid_from=date(2026, 1, 1))
        assert len(seed_data) == 4
        for item in seed_data:
            assert "metric_name" in item
            assert "alert_level" in item
            assert "threshold_open" in item
            assert "threshold_close" in item
            assert "cooldown_hours" in item
            assert "valid_from" in item
            assert item["fuel_type"] is None  # Tüm yakıt tipleri için geçerli


# ────────────────────────────────────────────────────────────────────────────
#  Rejim modifier testleri
# ────────────────────────────────────────────────────────────────────────────


class TestApplyRegimeToThresholds:
    """apply_regime_to_thresholds fonksiyonu testleri."""

    def test_election_modifier_reduces_thresholds(self):
        """Seçim modifier eşikleri düşürmeli."""
        thresholds = [
            {"threshold_open": Decimal("0.60"), "threshold_close": Decimal("0.45")},
            {"threshold_open": Decimal("0.70"), "threshold_close": Decimal("0.55")},
        ]
        regime_modifier = {"election": 0.85}
        modified = apply_regime_to_thresholds(thresholds, regime_modifier, "election")

        assert modified[0]["threshold_open"] == Decimal("0.60") * Decimal("0.85")
        assert modified[1]["threshold_open"] == Decimal("0.70") * Decimal("0.85")

    def test_unknown_regime_returns_original(self):
        """Bilinmeyen rejim tipi → orijinal eşikler korunmalı."""
        thresholds = [
            {"threshold_open": Decimal("0.60"), "threshold_close": Decimal("0.45")},
        ]
        regime_modifier = {"election": 0.85}
        modified = apply_regime_to_thresholds(thresholds, regime_modifier, "holiday")

        assert modified[0]["threshold_open"] == Decimal("0.60")

    def test_original_not_mutated(self):
        """Orijinal eşik dict'leri değiştirilmemeli."""
        thresholds = [
            {"threshold_open": Decimal("0.60"), "threshold_close": Decimal("0.45")},
        ]
        regime_modifier = {"election": 0.85}
        apply_regime_to_thresholds(thresholds, regime_modifier, "election")

        # Orijinal değişmemiş olmalı
        assert thresholds[0]["threshold_open"] == Decimal("0.60")
