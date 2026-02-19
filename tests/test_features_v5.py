"""
Predictor v5 — Feature Hesaplama Testleri
==========================================
Unit testler: trading-day SMA/vol, staleness, 35 feature üretimi, bulk, edge cases

En az 15+ test.
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock
import pandas as pd

from src.predictor_v5.features import (
    _safe_decimal,
    _to_float,
    _safe_div,
    _compute_trading_day_indicators,
    _compute_features_from_data,
    compute_features,
    compute_features_bulk,
    get_price_changed_today,
    FEATURE_NAMES,
    FF_MAX_LOOKBACK,
    _STALE_THRESHOLD,
)


# ===========================================================================
# Test 1: Yardımcı Fonksiyonlar
# ===========================================================================

class TestHelpers:
    """_safe_decimal, _to_float, _safe_div testleri."""

    def test_safe_decimal_float(self):
        result = _safe_decimal(68.17)
        assert isinstance(result, Decimal)
        assert result == Decimal("68.17")

    def test_safe_decimal_none(self):
        assert _safe_decimal(None) is None

    def test_to_float_decimal(self):
        assert _to_float(Decimal("43.69")) == pytest.approx(43.69)

    def test_to_float_none(self):
        assert _to_float(None) == 0.0

    def test_safe_div_normal(self):
        assert _safe_div(10.0, 2.0) == pytest.approx(5.0)

    def test_safe_div_zero_denominator(self):
        assert _safe_div(10.0, 0.0) == 0.0


# ===========================================================================
# Test 2: Trading-Day İndikatörleri
# ===========================================================================

class TestTradingDayIndicators:
    """_compute_trading_day_indicators — SMA, vol, staleness testleri."""

    def _make_trading_days(self, values, start=date(2024, 1, 2)):
        """Ardışık iş günleri (Pzt-Cum) oluştur."""
        days = []
        current = start
        for val in values:
            # Hafta sonunu atla
            while current.weekday() >= 5:
                current += timedelta(days=1)
            days.append((current, float(val)))
            current += timedelta(days=1)
        return days

    def test_empty_trading_days(self):
        """Boş seri → stale=1.0, tüm değerler 0."""
        result = _compute_trading_day_indicators([], date(2024, 6, 1))
        assert result["stale"] == 1.0
        assert result["close"] == 0.0
        assert result["sma_5"] == 0.0

    def test_single_trading_day(self):
        """Tek trading day → close set, return=0, sma=close."""
        td = [(date(2024, 6, 3), 80.0)]
        result = _compute_trading_day_indicators(td, date(2024, 6, 3))
        assert result["close"] == 80.0
        assert result["return_1d"] == 0.0
        assert result["sma_5"] == 80.0
        assert result["stale"] == 0.0

    def test_sma_5_calculation(self):
        """5 trading day SMA doğru hesaplanır."""
        # 5 ardışık iş günü: 80, 82, 84, 86, 88 → SMA-5 = 84
        td = self._make_trading_days([80, 82, 84, 86, 88])
        target = td[-1][0]  # Son trading day
        result = _compute_trading_day_indicators(td, target)
        assert result["sma_5"] == pytest.approx(84.0)

    def test_sma_10_calculation(self):
        """10 trading day SMA doğru hesaplanır."""
        vals = [80, 81, 82, 83, 84, 85, 86, 87, 88, 89]
        td = self._make_trading_days(vals)
        target = td[-1][0]
        result = _compute_trading_day_indicators(td, target)
        assert result["sma_10"] == pytest.approx(84.5)

    def test_return_1d(self):
        """1 günlük getiri doğru hesaplanır."""
        td = [(date(2024, 6, 3), 80.0), (date(2024, 6, 4), 82.0)]
        result = _compute_trading_day_indicators(td, date(2024, 6, 4))
        expected_return = (82.0 - 80.0) / 80.0  # 0.025
        assert result["return_1d"] == pytest.approx(expected_return)

    def test_volatility_5d(self):
        """5 günlük volatilite (std dev of returns) pozitif."""
        # Volatil seri: değişken fiyatlar
        td = self._make_trading_days([80, 85, 78, 90, 82, 88])
        target = td[-1][0]
        result = _compute_trading_day_indicators(td, target)
        assert result["vol_5d"] > 0.0

    def test_forward_fill_within_lookback(self):
        """Trading day 5 gün önceydi → forward-fill yapılır, stale=0."""
        td = [(date(2024, 6, 3), 80.0)]  # Pazartesi
        target = date(2024, 6, 8)  # Cumartesi (5 gün sonra)
        result = _compute_trading_day_indicators(td, target, max_ff_lookback=15)
        assert result["close"] == 80.0
        assert result["stale"] == 0.0

    def test_stale_beyond_lookback(self):
        """Trading day 20 gün önceydi → stale=1.0."""
        td = [(date(2024, 5, 10), 80.0)]
        target = date(2024, 6, 1)  # 22 gün sonra
        result = _compute_trading_day_indicators(td, target, max_ff_lookback=15)
        assert result["stale"] == 1.0

    def test_future_trading_days_filtered(self):
        """target_date'ten sonraki trading day'ler hesaba katılmaz."""
        td = [
            (date(2024, 6, 3), 80.0),
            (date(2024, 6, 4), 82.0),
            (date(2024, 6, 5), 84.0),  # Bu ve sonrası filtrelenmeli
            (date(2024, 6, 6), 86.0),
        ]
        result = _compute_trading_day_indicators(td, date(2024, 6, 4))
        assert result["close"] == 82.0  # 6/4 son, 6/5 dahil değil


# ===========================================================================
# Test 3: Feature Hesaplama (Pure Function — DB Bağımsız)
# ===========================================================================

class TestComputeFeaturesFromData:
    """_compute_features_from_data — 35 feature üretimi."""

    def _sample_brent(self):
        """Örnek Brent trading day serisi (10 gün)."""
        base = date(2024, 6, 3)
        return [(base + timedelta(days=i), 80.0 + i * 0.5) for i in range(10)]

    def _sample_fx(self):
        """Örnek FX trading day serisi (10 gün)."""
        base = date(2024, 6, 3)
        return [(base + timedelta(days=i), 32.0 + i * 0.1) for i in range(10)]

    def _sample_mbe(self, n=5):
        """Örnek MBE kayıtları."""
        base = date(2024, 6, 3)
        records = []
        for i in range(n):
            records.append({
                "trade_date": base + timedelta(days=i),
                "mbe_value": 0.5 + i * 0.1,
                "mbe_pct": 2.0 + i * 0.2,
                "nc_forward": 19.5 + i * 0.05,
                "sma_5": 19.4 + i * 0.03,
                "sma_10": 19.3 + i * 0.02,
                "delta_mbe": 0.01 * (i + 1),
                "delta_mbe_3": 0.03 * (i + 1),
                "since_last_change_days": 5 - i,
            })
        return records

    def _sample_risk(self):
        return {
            "trade_date": date(2024, 6, 7),
            "composite_score": 0.45,
            "mbe_component": 0.15,
            "fx_volatility_component": 0.10,
            "trend_momentum_component": 0.20,
        }

    def _sample_cost(self):
        return {
            "trade_date": date(2024, 6, 7),
            "cost_gap_tl": 2.5,
            "cost_gap_pct": 5.8,
            "otv_component_tl": 3.3,
        }

    def test_produces_35_features(self):
        """35 feature üretilir, hiçbiri None değil."""
        features = _compute_features_from_data(
            target_date=date(2024, 6, 7),
            brent_trading_days=self._sample_brent(),
            fx_trading_days=self._sample_fx(),
            mbe_records=self._sample_mbe(),
            risk_record=self._sample_risk(),
            cost_record=self._sample_cost(),
        )
        assert len(features) == len(FEATURE_NAMES)
        for name in FEATURE_NAMES:
            assert name in features, f"Eksik feature: {name}"
            assert features[name] is not None, f"None feature: {name}"
            assert isinstance(features[name], (int, float)), f"Tip hatası: {name}={type(features[name])}"

    def test_feature_names_match_config(self):
        """Üretilen feature key'leri config.py FEATURE_NAMES ile tam eşleşir."""
        features = _compute_features_from_data(
            target_date=date(2024, 6, 7),
            brent_trading_days=self._sample_brent(),
            fx_trading_days=self._sample_fx(),
            mbe_records=self._sample_mbe(),
            risk_record=self._sample_risk(),
            cost_record=self._sample_cost(),
        )
        for name in FEATURE_NAMES:
            assert name in features

    def test_cif_proxy_calculation(self):
        """CIF proxy = Brent × FX / 1000."""
        brent = [(date(2024, 6, 7), 80.0)]
        fx = [(date(2024, 6, 7), 36.0)]
        features = _compute_features_from_data(
            target_date=date(2024, 6, 7),
            brent_trading_days=brent,
            fx_trading_days=fx,
            mbe_records=[],
            risk_record=None,
            cost_record=None,
        )
        expected_cif = 80.0 * 36.0 / 1000.0  # 2.88
        assert features["cif_proxy"] == pytest.approx(expected_cif)

    def test_temporal_features(self):
        """day_of_week, is_weekend doğru hesaplanır."""
        # 2024-06-07 = Cuma (weekday=4)
        features = _compute_features_from_data(
            target_date=date(2024, 6, 7),  # Cuma
            brent_trading_days=[],
            fx_trading_days=[],
            mbe_records=[],
            risk_record=None,
            cost_record=None,
        )
        assert features["day_of_week"] == 4.0  # Cuma
        assert features["is_weekend"] == 0.0

        # 2024-06-08 = Cumartesi (weekday=5)
        features_weekend = _compute_features_from_data(
            target_date=date(2024, 6, 8),  # Cumartesi
            brent_trading_days=[],
            fx_trading_days=[],
            mbe_records=[],
            risk_record=None,
            cost_record=None,
        )
        assert features_weekend["day_of_week"] == 5.0
        assert features_weekend["is_weekend"] == 1.0

    def test_staleness_all_stale_when_no_data(self):
        """Veri yoksa tüm staleness flag'leri 1.0."""
        features = _compute_features_from_data(
            target_date=date(2024, 6, 7),
            brent_trading_days=[],
            fx_trading_days=[],
            mbe_records=[],
            risk_record=None,
            cost_record=None,
        )
        assert features["mbe_stale"] == 1.0
        assert features["nc_stale"] == 1.0
        assert features["brent_stale"] == 1.0
        assert features["fx_stale"] == 1.0
        assert features["cif_stale"] == 1.0

    def test_staleness_fresh_data(self):
        """Güncel veri varsa staleness flag'leri 0.0."""
        target = date(2024, 6, 7)
        brent = [(target, 80.0)]
        fx = [(target, 36.0)]
        mbe = [{
            "trade_date": target,
            "mbe_value": 0.5, "mbe_pct": 2.0,
            "nc_forward": 19.5, "sma_5": 19.4, "sma_10": 19.3,
            "delta_mbe": 0.01, "delta_mbe_3": 0.03,
            "since_last_change_days": 1,
        }]
        features = _compute_features_from_data(
            target_date=target,
            brent_trading_days=brent,
            fx_trading_days=fx,
            mbe_records=mbe,
            risk_record=None,
            cost_record=None,
        )
        assert features["mbe_stale"] == 0.0
        assert features["nc_stale"] == 0.0
        assert features["brent_stale"] == 0.0
        assert features["fx_stale"] == 0.0
        assert features["cif_stale"] == 0.0

    def test_mbe_stale_threshold(self):
        """MBE 4 gün önceydi → stale (> 3 gün eşik)."""
        target = date(2024, 6, 7)
        mbe = [{
            "trade_date": date(2024, 6, 3),  # 4 gün önce
            "mbe_value": 0.5, "mbe_pct": 2.0,
            "nc_forward": 19.5, "sma_5": 19.4, "sma_10": 19.3,
            "delta_mbe": 0.01, "delta_mbe_3": 0.03,
            "since_last_change_days": 1,
        }]
        features = _compute_features_from_data(
            target_date=target,
            brent_trading_days=[(date(2024, 6, 7), 80.0)],
            fx_trading_days=[(date(2024, 6, 7), 36.0)],
            mbe_records=mbe,
            risk_record=None,
            cost_record=None,
        )
        assert features["mbe_stale"] == 1.0  # 4 > 3

    def test_none_nan_cleaned(self):
        """Hiçbir feature None veya NaN olamaz."""
        features = _compute_features_from_data(
            target_date=date(2024, 6, 7),
            brent_trading_days=[],
            fx_trading_days=[],
            mbe_records=[],
            risk_record=None,
            cost_record=None,
        )
        for key, val in features.items():
            assert val is not None, f"{key} is None"
            if isinstance(val, float):
                assert val == val, f"{key} is NaN"  # NaN != NaN

    def test_risk_features_populated(self):
        """Risk bileşenleri doğru aktarılır."""
        risk = {
            "trade_date": date(2024, 6, 7),
            "composite_score": 0.45,
            "mbe_component": 0.15,
            "fx_volatility_component": 0.10,
            "trend_momentum_component": 0.20,
        }
        features = _compute_features_from_data(
            target_date=date(2024, 6, 7),
            brent_trading_days=[],
            fx_trading_days=[],
            mbe_records=[],
            risk_record=risk,
            cost_record=None,
        )
        assert features["risk_composite"] == pytest.approx(0.45)
        assert features["risk_mbe_comp"] == pytest.approx(0.15)
        assert features["risk_fx_comp"] == pytest.approx(0.10)
        assert features["risk_trend_comp"] == pytest.approx(0.20)

    def test_cost_features_populated(self):
        """Cost bileşenleri doğru aktarılır."""
        cost = {
            "trade_date": date(2024, 6, 7),
            "cost_gap_tl": 2.5,
            "cost_gap_pct": 5.8,
            "otv_component_tl": 3.3,
        }
        features = _compute_features_from_data(
            target_date=date(2024, 6, 7),
            brent_trading_days=[],
            fx_trading_days=[],
            mbe_records=[],
            risk_record=None,
            cost_record=cost,
        )
        assert features["cost_gap_tl"] == pytest.approx(2.5)
        assert features["cost_gap_pct"] == pytest.approx(5.8)
        assert features["otv_component_tl"] == pytest.approx(3.3)

    def test_nc_sma_calculation(self):
        """NC SMA-3 ve SMA-5 doğru hesaplanır."""
        base = date(2024, 6, 3)
        mbe = []
        for i in range(5):
            mbe.append({
                "trade_date": base + timedelta(days=i),
                "mbe_value": 0.5, "mbe_pct": 2.0,
                "nc_forward": 19.0 + i,  # 19, 20, 21, 22, 23
                "sma_5": 19.4, "sma_10": 19.3,
                "delta_mbe": 0.01, "delta_mbe_3": 0.03,
                "since_last_change_days": 1,
            })
        features = _compute_features_from_data(
            target_date=date(2024, 6, 7),
            brent_trading_days=[(date(2024, 6, 7), 80.0)],
            fx_trading_days=[(date(2024, 6, 7), 36.0)],
            mbe_records=mbe,
            risk_record=None,
            cost_record=None,
        )
        # nc_forward = 23 (son)
        assert features["nc_forward"] == pytest.approx(23.0)
        # nc_sma_3 = (21 + 22 + 23) / 3 = 22
        assert features["nc_sma_3"] == pytest.approx(22.0)
        # nc_sma_5 = (19 + 20 + 21 + 22 + 23) / 5 = 21
        assert features["nc_sma_5"] == pytest.approx(21.0)


# ===========================================================================
# Test 4: compute_features (DB Mock'lu)
# ===========================================================================

class TestComputeFeatures:
    """compute_features — DB sorgularını mock'layan entegrasyon testleri."""

    @patch("src.predictor_v5.features._fetch_cost")
    @patch("src.predictor_v5.features._fetch_risk")
    @patch("src.predictor_v5.features._fetch_mbe")
    @patch("src.predictor_v5.features._fetch_brent_fx")
    def test_returns_35_features(self, mock_bfx, mock_mbe, mock_risk, mock_cost):
        """compute_features 35 feature döndürür."""
        mock_bfx.return_value = (
            [(date(2024, 6, 7), 80.0)],
            [(date(2024, 6, 7), 36.0)],
        )
        mock_mbe.return_value = [{
            "trade_date": date(2024, 6, 7),
            "mbe_value": 0.5, "mbe_pct": 2.0,
            "nc_forward": 19.5, "sma_5": 19.4, "sma_10": 19.3,
            "delta_mbe": 0.01, "delta_mbe_3": 0.03,
            "since_last_change_days": 2,
        }]
        mock_risk.return_value = {
            "trade_date": date(2024, 6, 7),
            "composite_score": 0.45,
            "mbe_component": 0.15,
            "fx_volatility_component": 0.10,
            "trend_momentum_component": 0.20,
        }
        mock_cost.return_value = {
            "trade_date": date(2024, 6, 7),
            "cost_gap_tl": 2.5,
            "cost_gap_pct": 5.8,
            "otv_component_tl": 3.3,
        }

        result = compute_features("benzin", date(2024, 6, 7))
        assert isinstance(result, dict)
        assert len(result) == len(FEATURE_NAMES)
        # Config sırası kontrol
        assert list(result.keys()) == FEATURE_NAMES

    def test_invalid_fuel_type(self):
        """Geçersiz yakıt tipi ValueError fırlatır."""
        with pytest.raises(ValueError, match="Geçersiz yakıt tipi"):
            compute_features("mazot", date(2024, 6, 7))


# ===========================================================================
# Test 5: compute_features_bulk (DB Mock'lu)
# ===========================================================================

class TestComputeFeaturesBulk:
    """compute_features_bulk — tarih aralığı testleri."""

    @patch("src.predictor_v5.features._fetch_cost")
    @patch("src.predictor_v5.features._fetch_risk")
    @patch("src.predictor_v5.features._fetch_mbe")
    @patch("src.predictor_v5.features._fetch_brent_fx")
    def test_bulk_returns_dataframe(self, mock_bfx, mock_mbe, mock_risk, mock_cost):
        """3 günlük bulk hesaplama doğru DataFrame döndürür."""
        mock_bfx.return_value = (
            [(date(2024, 6, 5 + i), 80.0 + i) for i in range(5)],
            [(date(2024, 6, 5 + i), 36.0 + i * 0.1) for i in range(5)],
        )
        mock_mbe.return_value = [{
            "trade_date": date(2024, 6, 7),
            "mbe_value": 0.5, "mbe_pct": 2.0,
            "nc_forward": 19.5, "sma_5": 19.4, "sma_10": 19.3,
            "delta_mbe": 0.01, "delta_mbe_3": 0.03,
            "since_last_change_days": 2,
        }]
        mock_risk.return_value = None
        mock_cost.return_value = None

        df = compute_features_bulk("benzin", date(2024, 6, 7), date(2024, 6, 9))
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3  # 3 gün
        assert "trade_date" in df.columns
        assert "fuel_type" in df.columns
        # FEATURE_NAMES feature + trade_date + fuel_type kolon
        assert len(df.columns) == len(FEATURE_NAMES) + 2
        # Feature sırası doğru mu?
        for i, name in enumerate(FEATURE_NAMES):
            assert df.columns[i + 2] == name  # İlk 2: trade_date, fuel_type

    def test_bulk_invalid_date_range(self):
        """start > end ValueError fırlatır."""
        with pytest.raises(ValueError, match="start_date"):
            compute_features_bulk("benzin", date(2024, 12, 31), date(2024, 1, 1))

    def test_bulk_invalid_fuel_type(self):
        """Geçersiz yakıt tipi ValueError fırlatır."""
        with pytest.raises(ValueError, match="Geçersiz yakıt tipi"):
            compute_features_bulk("diesel", date(2024, 6, 7), date(2024, 6, 9))


# ===========================================================================
# Test 6: get_price_changed_today
# ===========================================================================

class TestPriceChangedToday:
    """get_price_changed_today — model dışı fonksiyon testleri."""

    @patch("src.predictor_v5.features._fetch_pump_price_history")
    def test_price_changed(self, mock_fetch):
        """Fiyat değişti → True."""
        mock_fetch.return_value = [
            (date(2024, 6, 6), 58.00),
            (date(2024, 6, 7), 58.30),
        ]
        assert get_price_changed_today("benzin", date(2024, 6, 7)) is True

    @patch("src.predictor_v5.features._fetch_pump_price_history")
    def test_price_not_changed(self, mock_fetch):
        """Fiyat değişmedi → False."""
        mock_fetch.return_value = [
            (date(2024, 6, 6), 58.00),
            (date(2024, 6, 7), 58.00),
        ]
        assert get_price_changed_today("benzin", date(2024, 6, 7)) is False

    @patch("src.predictor_v5.features._fetch_pump_price_history")
    def test_insufficient_data(self, mock_fetch):
        """Tek kayıt varsa → False (karşılaştırma yapılamaz)."""
        mock_fetch.return_value = [(date(2024, 6, 7), 58.00)]
        assert get_price_changed_today("benzin", date(2024, 6, 7)) is False

    def test_invalid_fuel_type(self):
        """Geçersiz yakıt tipi ValueError fırlatır."""
        with pytest.raises(ValueError):
            get_price_changed_today("dizel", date(2024, 6, 7))


# ===========================================================================
# Test 7: Edge Cases
# ===========================================================================

class TestEdgeCases:
    """Sınır durumları ve köşe vakaları."""

    def test_all_features_are_float(self):
        """Tüm feature değerleri float olmalı (model uyumu)."""
        features = _compute_features_from_data(
            target_date=date(2024, 6, 7),
            brent_trading_days=[(date(2024, 6, 7), 80.0)],
            fx_trading_days=[(date(2024, 6, 7), 36.0)],
            mbe_records=[],
            risk_record=None,
            cost_record=None,
        )
        for key, val in features.items():
            assert isinstance(val, (int, float)), f"{key} tipi float değil: {type(val)}"

    def test_weekend_is_weekend(self):
        """Pazar günü is_weekend=1.0."""
        features = _compute_features_from_data(
            target_date=date(2024, 6, 9),  # Pazar
            brent_trading_days=[],
            fx_trading_days=[],
            mbe_records=[],
            risk_record=None,
            cost_record=None,
        )
        assert features["is_weekend"] == 1.0
        assert features["day_of_week"] == 6.0  # Pazar

    def test_cif_stale_when_brent_stale(self):
        """Brent stale ise CIF de stale olmalı."""
        # FX fresh ama Brent stale
        features = _compute_features_from_data(
            target_date=date(2024, 6, 30),  # Brent 20+ gün önce
            brent_trading_days=[(date(2024, 6, 1), 80.0)],  # 29 gün önce
            fx_trading_days=[(date(2024, 6, 30), 36.0)],  # Bugün
            mbe_records=[],
            risk_record=None,
            cost_record=None,
        )
        assert features["brent_stale"] == 1.0
        assert features["cif_stale"] == 1.0

    def test_feature_count_matches_config(self):
        """FEATURE_NAMES listesinde tam 36 eleman var (config.py ile uyumlu)."""
        assert len(FEATURE_NAMES) == 49  # v6: 36 + 13 yeni feature
