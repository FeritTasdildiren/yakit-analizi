"""
Feature Engineering Pipeline testleri.

Her feature grubunun hesaplama dogrulugu test edilir.
5 grup: MBE, NC, Dis Piyasa, Rejim, Vergi & Maliyet.
"""

import pytest
from decimal import Decimal

from src.ml.feature_engineering import (
    FEATURE_NAMES,
    TOTAL_FEATURE_COUNT,
    FeatureRecord,
    compute_all_features,
    compute_external_market_features,
    compute_mbe_features,
    compute_nc_features,
    compute_regime_features,
    compute_tax_cost_features,
    features_dict_to_array,
    features_to_array,
    _compute_sma_float,
    _compute_std_float,
    _compute_momentum,
    _to_float,
)


# ────────────────────────────────────────────────────────────────────────────
#  Yardimci Fonksiyon Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestHelperFunctions:
    """Yardimci fonksiyon testleri."""

    def test_to_float_decimal(self):
        """Decimal deger float'a donusmeli."""
        result = _to_float(Decimal("36.25"))
        assert result == 36.25

    def test_to_float_none_returns_default(self):
        """None deger varsayilani dondurmeli."""
        result = _to_float(None, 0.0)
        assert result == 0.0

    def test_to_float_invalid_returns_default(self):
        """Gecersiz deger varsayilani dondurmeli."""
        result = _to_float("abc", -1.0)
        assert result == -1.0

    def test_compute_sma_float_basic(self):
        """SMA temel hesaplama testi."""
        series = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = _compute_sma_float(series, 3)
        assert result == pytest.approx(40.0)  # (30+40+50)/3

    def test_compute_sma_float_insufficient_data(self):
        """Yetersiz veride graceful degrade — mevcut ortalamayi al."""
        series = [10.0, 20.0]
        result = _compute_sma_float(series, 5)
        assert result == pytest.approx(15.0)  # (10+20)/2

    def test_compute_sma_float_empty_series(self):
        """Bos seri icin 0 donmeli."""
        result = _compute_sma_float([], 5)
        assert result == 0.0

    def test_compute_std_float(self):
        """Standart sapma testi."""
        series = [10.0, 10.0, 10.0]
        result = _compute_std_float(series)
        assert result == pytest.approx(0.0)

    def test_compute_std_float_single_value(self):
        """Tek deger icin std = 0."""
        result = _compute_std_float([42.0])
        assert result == 0.0

    def test_compute_momentum(self):
        """Momentum testi."""
        series = [10.0, 12.0, 15.0, 18.0, 20.0]
        result = _compute_momentum(series, 3)
        assert result == pytest.approx(8.0)  # 20 - 12

    def test_compute_momentum_insufficient_data(self):
        """Yetersiz veride momentum graceful degrade."""
        series = [10.0, 20.0]
        result = _compute_momentum(series, 5)
        assert result == pytest.approx(10.0)  # 20 - 10


# ────────────────────────────────────────────────────────────────────────────
#  Grup 1: MBE Ozellikleri
# ────────────────────────────────────────────────────────────────────────────


class TestMBEFeatures:
    """MBE feature hesaplama testleri."""

    def test_basic_mbe_features(self):
        """Temel MBE feature'lar dogru hesaplanmali."""
        result = compute_mbe_features(
            mbe_value=0.5,
            mbe_pct=2.5,
            mbe_history=[0.3, 0.35, 0.4, 0.45, 0.5],
            previous_mbe=0.45,
            mbe_3_days_ago=0.35,
        )

        assert result["mbe_value"] == 0.5
        assert result["mbe_pct"] == 2.5
        assert result["delta_mbe"] == pytest.approx(0.05)
        assert result["delta_mbe_3d"] == pytest.approx(0.15)
        assert "mbe_sma_5" in result
        assert "mbe_sma_10" in result

    def test_mbe_features_no_history(self):
        """Gecmis veri yokken graceful degrade."""
        result = compute_mbe_features(
            mbe_value=0.5,
            mbe_pct=2.5,
        )
        # SMA'lar mevcut MBE degerine esit olmali
        assert result["mbe_sma_5"] == 0.5
        assert result["mbe_sma_10"] == 0.5
        assert result["delta_mbe"] == 0.0
        assert result["delta_mbe_3d"] == 0.0

    def test_mbe_feature_count(self):
        """6 adet MBE feature donmeli."""
        result = compute_mbe_features(mbe_value=0.5, mbe_pct=2.5)
        assert len(result) == 6


# ────────────────────────────────────────────────────────────────────────────
#  Grup 2: NC Ozellikleri
# ────────────────────────────────────────────────────────────────────────────


class TestNCFeatures:
    """NC feature hesaplama testleri."""

    def test_nc_forward_calculation(self):
        """NC forward dogru hesaplanmali."""
        result = compute_nc_features(
            cif_usd_ton=620.0,
            fx_rate=36.25,
            fuel_type="motorin",
        )
        # NC_forward = (620 * 36.25) / 1190 ≈ 18.88
        assert result["nc_forward"] > 0
        assert result["nc_forward"] == pytest.approx(18.88, abs=0.1)

    def test_nc_trend_one_hot(self):
        """NC trend one-hot encoding dogrulamasi."""
        result = compute_nc_features(
            cif_usd_ton=620.0,
            fx_rate=36.25,
            fuel_type="motorin",
            nc_history=[17.0, 18.0, 19.0],
        )
        # Yukselen seri → increase
        assert result["nc_trend_increase"] == 1.0
        assert result["nc_trend_decrease"] == 0.0
        assert result["nc_trend_no_change"] == 0.0

    def test_nc_feature_count(self):
        """8 adet NC feature donmeli (7 + 1 ek trend)."""
        result = compute_nc_features(
            cif_usd_ton=620.0,
            fx_rate=36.25,
        )
        # nc_forward + 4 SMA + 3 trend one-hot = 8
        assert len(result) == 8

    def test_nc_with_history(self):
        """Gecmis verili NC SMA hesaplamalari."""
        history = [15.0, 16.0, 17.0, 18.0, 19.0, 20.0]
        result = compute_nc_features(
            cif_usd_ton=620.0,
            fx_rate=36.25,
            nc_history=history,
        )
        assert result["nc_sma_3"] > 0
        assert result["nc_sma_5"] > 0


# ────────────────────────────────────────────────────────────────────────────
#  Grup 3: Dis Piyasa
# ────────────────────────────────────────────────────────────────────────────


class TestExternalMarketFeatures:
    """Dis piyasa feature testleri."""

    def test_basic_external_features(self):
        """Temel dis piyasa feature'lar hesaplanmali."""
        result = compute_external_market_features(
            cif_usd_ton=620.0,
            fx_rate=36.25,
            brent_usd_bbl=80.0,
        )
        assert result["cif_usd_ton"] == 620.0
        assert result["fx_rate"] == 36.25
        assert result["brent_usd_bbl"] == 80.0

    def test_lag_features_no_history(self):
        """Gecmis veri yokken lag'lar mevcut degere esit olmali."""
        result = compute_external_market_features(
            cif_usd_ton=620.0,
            fx_rate=36.25,
            brent_usd_bbl=80.0,
        )
        assert result["cif_lag_1"] == 620.0
        assert result["fx_lag_1"] == 36.25
        assert result["brent_lag_1"] == 80.0

    def test_lag_features_with_history(self):
        """Gecmis verili lag hesaplamalari."""
        result = compute_external_market_features(
            cif_usd_ton=620.0,
            fx_rate=36.25,
            brent_usd_bbl=80.0,
            cif_history=[600.0, 610.0, 615.0, 620.0],
            fx_history=[35.0, 35.5, 36.0, 36.25],
            brent_history=[78.0, 79.0, 80.0],
        )
        assert result["cif_lag_1"] == 615.0
        assert result["fx_lag_1"] == 36.0
        assert result["brent_lag_1"] == 79.0

    def test_volatility_features(self):
        """Volatilite feature'lari sifir olmamali (yeterli veriyle)."""
        fx_hist = [35.0, 35.2, 35.5, 35.1, 35.8, 36.0, 35.5, 36.2, 35.9, 36.25]
        result = compute_external_market_features(
            cif_usd_ton=620.0,
            fx_rate=36.25,
            brent_usd_bbl=80.0,
            fx_history=fx_hist,
        )
        assert result["fx_volatility_5d"] > 0
        assert result["fx_volatility_10d"] > 0

    def test_feature_count(self):
        """13 adet dis piyasa feature donmeli."""
        result = compute_external_market_features(
            cif_usd_ton=620.0,
            fx_rate=36.25,
            brent_usd_bbl=80.0,
        )
        assert len(result) == 13


# ────────────────────────────────────────────────────────────────────────────
#  Grup 4: Rejim Ozellikleri
# ────────────────────────────────────────────────────────────────────────────


class TestRegimeFeatures:
    """Politik/ekonomik rejim feature testleri."""

    def test_normal_regime_one_hot(self):
        """Normal rejimde one-hot dogrulamasi."""
        result = compute_regime_features(regime=0)
        assert result["regime_normal"] == 1.0
        assert result["regime_election"] == 0.0
        assert result["regime_kur_shock"] == 0.0
        assert result["regime_tax"] == 0.0

    def test_election_regime_one_hot(self):
        """Secim rejiminde one-hot dogrulamasi."""
        result = compute_regime_features(regime=1)
        assert result["regime_normal"] == 0.0
        assert result["regime_election"] == 1.0

    def test_kur_shock_regime(self):
        """Kur soku rejimi one-hot."""
        result = compute_regime_features(regime=2)
        assert result["regime_kur_shock"] == 1.0

    def test_tax_regime(self):
        """Vergi ayarlama rejimi one-hot."""
        result = compute_regime_features(regime=3)
        assert result["regime_tax"] == 1.0

    def test_days_features(self):
        """Gun bazli feature'lar dogru donmeli."""
        result = compute_regime_features(
            days_since_last_hike=15,
            days_to_election=180,
        )
        assert result["days_since_last_hike"] == 15.0
        assert result["days_to_election"] == 180.0

    def test_boolean_features(self):
        """Boolean feature'lar 0.0/1.0 olarak donmeli."""
        result = compute_regime_features(
            is_holiday_period=True,
            parliamentary_session_active=False,
        )
        assert result["is_holiday_period"] == 1.0
        assert result["parliamentary_session_active"] == 0.0

    def test_feature_count(self):
        """14 adet rejim feature donmeli."""
        result = compute_regime_features()
        assert len(result) == 14


# ────────────────────────────────────────────────────────────────────────────
#  Grup 5: Vergi & Maliyet
# ────────────────────────────────────────────────────────────────────────────


class TestTaxCostFeatures:
    """Vergi ve maliyet feature testleri."""

    def test_basic_tax_features(self):
        """Temel vergi/maliyet feature'lar dogru donmeli."""
        result = compute_tax_cost_features(
            otv_rate=2.5,
            kdv_rate=0.20,
            margin_total=1.20,
            cost_base_snapshot=25.0,
        )
        assert result["otv_rate"] == 2.5
        assert result["kdv_rate"] == 0.20
        assert result["margin_total"] == 1.20
        assert result["cost_base_snapshot"] == 25.0

    def test_effective_tax_rate_calculation(self):
        """Etkin vergi orani hesaplanmali."""
        result = compute_tax_cost_features(
            otv_rate=2.5,
            kdv_rate=0.20,
            margin_total=1.20,
            cost_base_snapshot=25.0,
            pump_price=40.0,
        )
        assert result["effective_tax_rate"] > 0

    def test_tax_bracket_change_flag(self):
        """OTV degisim flag boolean olarak donmeli."""
        result = compute_tax_cost_features(
            otv_rate=2.5,
            kdv_rate=0.20,
            margin_total=1.20,
            cost_base_snapshot=25.0,
            tax_bracket_change_flag=True,
        )
        assert result["tax_bracket_change_flag"] == 1.0

    def test_feature_count(self):
        """9 adet vergi/maliyet feature donmeli."""
        result = compute_tax_cost_features(
            otv_rate=2.5,
            kdv_rate=0.20,
            margin_total=1.20,
            cost_base_snapshot=25.0,
        )
        assert len(result) == 9


# ────────────────────────────────────────────────────────────────────────────
#  Ana Feature Hesaplama
# ────────────────────────────────────────────────────────────────────────────


class TestComputeAllFeatures:
    """compute_all_features ve donusum testleri."""

    def test_all_features_complete(self):
        """Tum feature'lar hesaplanmali."""
        record = compute_all_features(
            trade_date="2026-02-16",
            fuel_type="motorin",
            mbe_value=0.5,
            mbe_pct=2.5,
            cif_usd_ton=620.0,
            fx_rate=36.25,
            brent_usd_bbl=80.0,
            otv_rate=2.5,
            kdv_rate=0.20,
            margin_total=1.20,
            cost_base_snapshot=25.0,
        )
        assert isinstance(record, FeatureRecord)
        assert record.fuel_type == "motorin"
        assert record.trade_date == "2026-02-16"
        # Tum feature isimleri mevcut olmali
        for name in FEATURE_NAMES:
            assert name in record.features, f"Eksik feature: {name}"

    def test_features_to_array_length(self):
        """Feature array uzunlugu FEATURE_NAMES ile ayni olmali."""
        record = compute_all_features(
            trade_date="2026-02-16",
            fuel_type="motorin",
            mbe_value=0.5,
            mbe_pct=2.5,
            cif_usd_ton=620.0,
            fx_rate=36.25,
        )
        arr = features_to_array(record)
        assert len(arr) == TOTAL_FEATURE_COUNT

    def test_features_dict_to_array(self):
        """Dict'ten array donusumu dogru olmali."""
        features = {"mbe_value": 0.5, "fx_rate": 36.25}
        arr = features_dict_to_array(features)
        assert len(arr) == TOTAL_FEATURE_COUNT
        assert arr[0] == 0.5  # mbe_value
        # Eksik feature'lar 0.0 olmali
        assert arr[1] == 0.0  # mbe_pct

    def test_missing_features_tracked(self):
        """Eksik feature'lar missing_features listesinde olmali."""
        record = compute_all_features(
            trade_date="2026-02-16",
            fuel_type="motorin",
            mbe_value=0.5,
            mbe_pct=2.5,
            cif_usd_ton=620.0,
            fx_rate=36.25,
        )
        # Normal durumda missing bos olmali
        assert isinstance(record.missing_features, list)

    def test_feature_names_count(self):
        """FEATURE_NAMES listesi beklenen sayida feature icermeli."""
        assert TOTAL_FEATURE_COUNT > 40
