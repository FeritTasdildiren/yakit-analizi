"""
Risk Hesaplama Motoru testleri.

normalize_component, calculate_risk_score, check_threshold_breach,
apply_regime_modifier ve _determine_system_mode fonksiyonları için
kapsamlı birim testleri.
"""

import pytest
from decimal import Decimal

from src.core.risk_engine import (
    DEFAULT_WEIGHTS,
    RiskComponents,
    RiskResult,
    apply_regime_modifier,
    calculate_risk_score,
    check_threshold_breach,
    normalize_component,
    _determine_system_mode,
)


# ────────────────────────────────────────────────────────────────────────────
#  normalize_component testleri
# ────────────────────────────────────────────────────────────────────────────


class TestNormalizeComponent:
    """normalize_component fonksiyonu testleri."""

    def test_normalize_mid_value(self):
        """Aralığın ortasındaki bir değer 0.5 döndürmeli."""
        result = normalize_component(Decimal("5"), Decimal("0"), Decimal("10"))
        assert result == Decimal("0.5000")

    def test_normalize_min_value(self):
        """Minimum değer 0 döndürmeli."""
        result = normalize_component(Decimal("0"), Decimal("0"), Decimal("10"))
        assert result == Decimal("0")

    def test_normalize_max_value(self):
        """Maksimum değer 1 döndürmeli."""
        result = normalize_component(Decimal("10"), Decimal("0"), Decimal("10"))
        assert result == Decimal("1")

    def test_normalize_below_min_clamped(self):
        """Min altındaki değer 0'a clamp edilmeli."""
        result = normalize_component(Decimal("-5"), Decimal("0"), Decimal("10"))
        assert result == Decimal("0")

    def test_normalize_above_max_clamped(self):
        """Max üstündeki değer 1'e clamp edilmeli."""
        result = normalize_component(Decimal("15"), Decimal("0"), Decimal("10"))
        assert result == Decimal("1")

    def test_normalize_equal_min_max_below(self):
        """Min=max durumunda değer <= min ise 0 döndürmeli."""
        result = normalize_component(Decimal("5"), Decimal("5"), Decimal("5"))
        assert result == Decimal("0")

    def test_normalize_equal_min_max_above(self):
        """Min=max durumunda değer > max ise 1 döndürmeli."""
        result = normalize_component(Decimal("6"), Decimal("5"), Decimal("5"))
        assert result == Decimal("1")

    def test_normalize_negative_range(self):
        """Negatif aralıkta doğru çalışmalı."""
        result = normalize_component(Decimal("0"), Decimal("-1"), Decimal("1"))
        assert result == Decimal("0.5000")

    def test_normalize_precision(self):
        """Sonuç 4 ondalık basamağa yuvarlanmalı."""
        result = normalize_component(Decimal("1"), Decimal("0"), Decimal("3"))
        assert result == Decimal("0.3333")


# ────────────────────────────────────────────────────────────────────────────
#  calculate_risk_score testleri
# ────────────────────────────────────────────────────────────────────────────


class TestCalculateRiskScore:
    """calculate_risk_score fonksiyonu testleri."""

    def test_all_zero_components(self):
        """Tüm bileşenler sıfır → skor 0 olmalı."""
        components = RiskComponents(
            mbe_value=Decimal("0"),
            fx_volatility=Decimal("0"),
            political_delay=Decimal("0"),
            threshold_breach=Decimal("0"),
            trend_momentum=Decimal("-1"),  # min_val=-1 → normalize → 0
        )
        result = calculate_risk_score(components)
        assert result.composite_score == Decimal("0")
        assert result.system_mode == "normal"

    def test_all_max_components(self):
        """Tüm bileşenler maksimum → skor 1 olmalı."""
        components = RiskComponents(
            mbe_value=Decimal("1"),
            fx_volatility=Decimal("0.10"),
            political_delay=Decimal("60"),
            threshold_breach=Decimal("1"),
            trend_momentum=Decimal("1"),
        )
        result = calculate_risk_score(components)
        assert result.composite_score == Decimal("1")
        assert result.system_mode == "crisis"

    def test_moderate_risk(self):
        """Orta düzey bileşenler → makul skor aralığında."""
        components = RiskComponents(
            mbe_value=Decimal("0.5"),
            fx_volatility=Decimal("0.05"),
            political_delay=Decimal("30"),
            threshold_breach=Decimal("0.5"),
            trend_momentum=Decimal("0"),
        )
        result = calculate_risk_score(components)
        assert Decimal("0.30") <= result.composite_score <= Decimal("0.70")
        assert result.system_mode in ("normal", "high_alert")

    def test_custom_weights(self):
        """Özel ağırlıklar düzgün uygulanmalı."""
        custom_weights = {
            "mbe": Decimal("1.00"),
            "fx_volatility": Decimal("0"),
            "political_delay": Decimal("0"),
            "threshold_breach": Decimal("0"),
            "trend_momentum": Decimal("0"),
        }
        components = RiskComponents(
            mbe_value=Decimal("0.7"),
            fx_volatility=Decimal("0.10"),
            political_delay=Decimal("60"),
            threshold_breach=Decimal("1"),
            trend_momentum=Decimal("1"),
        )
        result = calculate_risk_score(components, weights=custom_weights)
        # Sadece MBE ağırlığı 1.0 → skor ≈ normalize(0.7, 0, 1) = 0.7
        assert result.composite_score == Decimal("0.7000")

    def test_weight_vector_in_result(self):
        """Sonuçta weight_vector string olarak saklanmalı."""
        components = RiskComponents(
            mbe_value=Decimal("0.5"),
            fx_volatility=Decimal("0.05"),
            political_delay=Decimal("30"),
            threshold_breach=Decimal("0.5"),
            trend_momentum=Decimal("0"),
        )
        result = calculate_risk_score(components)
        assert "mbe" in result.weight_vector
        assert result.weight_vector["mbe"] == "0.30"

    def test_system_mode_normal(self):
        """Skor < 0.60 → normal mod."""
        assert _determine_system_mode(Decimal("0.30")) == "normal"

    def test_system_mode_high_alert(self):
        """0.60 <= skor < 0.80 → high_alert mod."""
        assert _determine_system_mode(Decimal("0.65")) == "high_alert"

    def test_system_mode_crisis(self):
        """Skor >= 0.80 → crisis mod."""
        assert _determine_system_mode(Decimal("0.85")) == "crisis"


# ────────────────────────────────────────────────────────────────────────────
#  check_threshold_breach testleri
# ────────────────────────────────────────────────────────────────────────────


class TestCheckThresholdBreach:
    """check_threshold_breach fonksiyonu testleri."""

    def test_breach_opens_alarm(self):
        """Eşik aşılınca alarm açılmalı."""
        result = check_threshold_breach(
            composite_score=Decimal("0.65"),
            threshold_open=Decimal("0.60"),
            threshold_close=Decimal("0.45"),
            previous_alert_active=False,
        )
        assert result is not None
        assert result["action"] == "open"

    def test_below_open_no_alarm(self):
        """Eşik aşılmamışsa alarm açılmamalı."""
        result = check_threshold_breach(
            composite_score=Decimal("0.55"),
            threshold_open=Decimal("0.60"),
            threshold_close=Decimal("0.45"),
            previous_alert_active=False,
        )
        assert result is None

    def test_hysteresis_alarm_stays_open(self):
        """Alarm açıkken, kapanış eşiğinin üstünde → alarm açık kalır."""
        result = check_threshold_breach(
            composite_score=Decimal("0.50"),
            threshold_open=Decimal("0.60"),
            threshold_close=Decimal("0.45"),
            previous_alert_active=True,
        )
        assert result is None  # Alarm devam eder (kapanmaz)

    def test_hysteresis_alarm_closes(self):
        """Alarm açıkken, kapanış eşiğinin altına düşünce → alarm kapanır."""
        result = check_threshold_breach(
            composite_score=Decimal("0.40"),
            threshold_open=Decimal("0.60"),
            threshold_close=Decimal("0.45"),
            previous_alert_active=True,
        )
        assert result is not None
        assert result["action"] == "close"


# ────────────────────────────────────────────────────────────────────────────
#  apply_regime_modifier testleri
# ────────────────────────────────────────────────────────────────────────────


class TestApplyRegimeModifier:
    """apply_regime_modifier fonksiyonu testleri."""

    def test_election_modifier(self):
        """Seçim modifier eşiği düşürmeli."""
        result = apply_regime_modifier(
            threshold_open=Decimal("0.60"),
            regime_modifier={"election": 0.85},
            active_regime_type="election",
        )
        assert result == Decimal("0.5100")

    def test_no_modifier_returns_original(self):
        """Modifier None ise orijinal eşik döndürmeli."""
        result = apply_regime_modifier(
            threshold_open=Decimal("0.60"),
            regime_modifier=None,
            active_regime_type="election",
        )
        assert result == Decimal("0.60")

    def test_no_active_regime_returns_original(self):
        """Aktif rejim None ise orijinal eşik döndürmeli."""
        result = apply_regime_modifier(
            threshold_open=Decimal("0.60"),
            regime_modifier={"election": 0.85},
            active_regime_type=None,
        )
        assert result == Decimal("0.60")

    def test_unknown_regime_type_returns_original(self):
        """Modifier'da olmayan rejim tipi → orijinal eşik."""
        result = apply_regime_modifier(
            threshold_open=Decimal("0.60"),
            regime_modifier={"election": 0.85},
            active_regime_type="holiday",
        )
        assert result == Decimal("0.60")
