"""
MBE Hesaplama Motoru birim testleri.

Sentetik veri ile calculate_nc_forward, calculate_nc_base_from_pump,
calculate_sma, calculate_mbe, calculate_cost_snapshot, detect_trend,
get_regime_config, get_rho ve calculate_full_mbe fonksiyonlarini test eder.

En az 25 test icermektedir.
"""

import pytest
from decimal import Decimal

from src.core.mbe_calculator import (
    PRECISION,
    RHO,
    REGIME_PARAMS,
    CostSnapshot,
    MBEResult,
    RegimeConfig,
    _safe_decimal,
    calculate_cost_snapshot,
    calculate_full_mbe,
    calculate_mbe,
    calculate_nc_base_from_pump,
    calculate_nc_forward,
    calculate_sma,
    detect_trend,
    get_regime_config,
    get_rho,
)


# =====================================================================
# _safe_decimal testleri
# =====================================================================


class TestSafeDecimal:
    """_safe_decimal fonksiyon testleri."""

    def test_int_to_decimal(self):
        """Tam sayidan Decimal donusumu."""
        result = _safe_decimal(42)
        assert result == Decimal("42")
        assert isinstance(result, Decimal)

    def test_float_to_decimal(self):
        """Float'tan Decimal donusumu (str uzerinden)."""
        result = _safe_decimal(3.14)
        assert result == Decimal("3.14")
        assert isinstance(result, Decimal)

    def test_str_to_decimal(self):
        """String'den Decimal donusumu."""
        result = _safe_decimal("19.5428")
        assert result == Decimal("19.5428")

    def test_decimal_passthrough(self):
        """Zaten Decimal olan deger degismeden doner."""
        val = Decimal("100.50")
        result = _safe_decimal(val)
        assert result is val

    def test_none_raises_value_error(self):
        """None deger ValueError firlatir."""
        with pytest.raises(ValueError, match="None"):
            _safe_decimal(None)

    def test_invalid_string_raises(self):
        """Gecersiz string ValueError firlatir."""
        with pytest.raises(ValueError):
            _safe_decimal("abc")


# =====================================================================
# calculate_nc_forward testleri
# =====================================================================


class TestCalculateNCForward:
    """NC_forward hesaplama testleri."""

    def test_basic_motorin(self):
        """
        CIF=680, FX=34.20, rho=1190
        NC_forward = (680 * 34.20) / 1190 = 23256 / 1190 = 19.54285714...
        """
        result = calculate_nc_forward(
            cif_usd_ton=Decimal("680"),
            fx_rate=Decimal("34.20"),
            rho=Decimal("1190"),
        )
        expected = Decimal("19.54285714")
        assert result == expected

    def test_basic_benzin(self):
        """
        CIF=700, FX=36.00, rho=1180
        NC_forward = (700 * 36.00) / 1180 = 25200 / 1180 = 21.35593220...
        """
        result = calculate_nc_forward(
            cif_usd_ton=Decimal("700"),
            fx_rate=Decimal("36.00"),
            rho=Decimal("1180"),
        )
        expected = Decimal("21.35593220")
        assert result == expected

    def test_lpg(self):
        """
        CIF=550, FX=35.00, rho=1750
        NC_forward = (550 * 35.00) / 1750 = 19250 / 1750 = 11.0
        """
        result = calculate_nc_forward(
            cif_usd_ton=Decimal("550"),
            fx_rate=Decimal("35.00"),
            rho=Decimal("1750"),
        )
        expected = Decimal("11.00000000")
        assert result == expected

    def test_accepts_float_inputs(self):
        """Float girdi kabul eder (str uzerinden Decimal'e donusur)."""
        result = calculate_nc_forward(
            cif_usd_ton=680.0,
            fx_rate=34.20,
            rho=1190,
        )
        assert isinstance(result, Decimal)
        # Float hassasiyet farki mumkun ama yaklasik olarak dogru olmali
        assert abs(result - Decimal("19.54285714")) < Decimal("0.001")

    def test_zero_rho_raises(self):
        """rho=0 oldugunda ZeroDivisionError firlatir."""
        with pytest.raises(ZeroDivisionError, match="rho"):
            calculate_nc_forward(
                cif_usd_ton=Decimal("680"),
                fx_rate=Decimal("34.20"),
                rho=Decimal("0"),
            )


# =====================================================================
# calculate_nc_base_from_pump testleri
# =====================================================================


class TestCalculateNCBaseFromPump:
    """NC_base (ters hesaplama) testleri."""

    def test_basic_calculation(self):
        """
        pump=40.50, OTV=2.50, KDV=0.18, M=1.20
        NC_base = (40.50 - 1.20) / (1 + 0.18) - 2.50
        = 39.30 / 1.18 - 2.50
        = 33.30508474... - 2.50
        = 30.80508474...
        """
        result = calculate_nc_base_from_pump(
            pump_price=Decimal("40.50"),
            otv=Decimal("2.50"),
            kdv=Decimal("0.18"),
            m_total=Decimal("1.20"),
        )
        expected = Decimal("30.80508475")
        assert result == expected

    def test_zero_kdv(self):
        """
        KDV=0 durumunda basit cikarma.
        NC_base = (30 - 1) / 1 - 3 = 26
        """
        result = calculate_nc_base_from_pump(
            pump_price=Decimal("30"),
            otv=Decimal("3"),
            kdv=Decimal("0"),
            m_total=Decimal("1"),
        )
        assert result == Decimal("26.00000000")

    def test_accepts_string_inputs(self):
        """String girdi kabul eder."""
        result = calculate_nc_base_from_pump(
            pump_price="40.50",
            otv="2.50",
            kdv="0.18",
            m_total="1.20",
        )
        assert isinstance(result, Decimal)
        assert abs(result - Decimal("30.80508475")) < Decimal("0.00000002")

    def test_negative_kdv_minus_one_raises(self):
        """KDV = -1 durumunda ZeroDivisionError (bolme 0'a bolme)."""
        with pytest.raises(ZeroDivisionError):
            calculate_nc_base_from_pump(
                pump_price=Decimal("40"),
                otv=Decimal("2"),
                kdv=Decimal("-1"),
                m_total=Decimal("1"),
            )


# =====================================================================
# calculate_sma testleri
# =====================================================================


class TestCalculateSMA:
    """SMA (Simple Moving Average) hesaplama testleri."""

    def test_5_day_sma(self):
        """
        5 gunluk SMA hesaplamasini dogrular.
        Seri: [10, 12, 11, 13, 15]
        SMA_5 son deger = (10 + 12 + 11 + 13 + 15) / 5 = 61 / 5 = 12.2
        """
        series = [
            Decimal("10"), Decimal("12"), Decimal("11"),
            Decimal("13"), Decimal("15"),
        ]
        result = calculate_sma(series, window=5)
        assert len(result) == 5
        # Son deger: (10+12+11+13+15)/5 = 12.2
        assert result[-1] == Decimal("12.20000000")

    def test_sma_first_element(self):
        """Ilk elemanda SMA = kendisi (pencere = 1 eleman)."""
        series = [Decimal("10"), Decimal("20"), Decimal("30")]
        result = calculate_sma(series, window=3)
        assert result[0] == Decimal("10.00000000")

    def test_sma_growing_window(self):
        """Pencere buyurken SMA degerleri degisir."""
        series = [Decimal("10"), Decimal("20"), Decimal("30")]
        result = calculate_sma(series, window=3)
        # [10] -> 10, [10,20] -> 15, [10,20,30] -> 20
        assert result[0] == Decimal("10.00000000")
        assert result[1] == Decimal("15.00000000")
        assert result[2] == Decimal("20.00000000")

    def test_sma_window_larger_than_series(self):
        """Pencere seriden buyukse mevcut verinin ortalamasi alinir."""
        series = [Decimal("10"), Decimal("20")]
        result = calculate_sma(series, window=5)
        assert len(result) == 2
        assert result[0] == Decimal("10.00000000")
        assert result[1] == Decimal("15.00000000")

    def test_sma_single_value(self):
        """Tek degerli seri."""
        series = [Decimal("42")]
        result = calculate_sma(series, window=5)
        assert result == [Decimal("42.00000000")]

    def test_sma_empty_series_raises(self):
        """Bos seri ValueError firlatir."""
        with pytest.raises(ValueError, match="en az 1"):
            calculate_sma([], window=5)

    def test_sma_zero_window_raises(self):
        """Sifir pencere ValueError firlatir."""
        with pytest.raises(ValueError, match="en az 1"):
            calculate_sma([Decimal("10")], window=0)


# =====================================================================
# calculate_mbe testleri
# =====================================================================


class TestCalculateMBE:
    """MBE hesaplama testleri."""

    def test_positive_mbe(self):
        """
        MBE pozitif: NC_forward artmis, zam baskisi var.
        nc_forward_series = [20, 21, 22, 23, 24]
        nc_base_sma = 19
        SMA_5(son) = (20+21+22+23+24)/5 = 22
        MBE = 22 - 19 = 3
        """
        series = [Decimal("20"), Decimal("21"), Decimal("22"), Decimal("23"), Decimal("24")]
        nc_base_sma = Decimal("19")
        result = calculate_mbe(series, nc_base_sma, window=5)
        assert result == Decimal("3.00000000")

    def test_negative_mbe(self):
        """
        MBE negatif: NC_forward dusmis, indirim baskisi var.
        nc_forward_series = [15, 14, 13, 12, 11]
        nc_base_sma = 16
        SMA_5(son) = (15+14+13+12+11)/5 = 13
        MBE = 13 - 16 = -3
        """
        series = [Decimal("15"), Decimal("14"), Decimal("13"), Decimal("12"), Decimal("11")]
        nc_base_sma = Decimal("16")
        result = calculate_mbe(series, nc_base_sma, window=5)
        assert result == Decimal("-3.00000000")

    def test_zero_mbe(self):
        """MBE sifir: Degisim yok."""
        series = [Decimal("20")] * 5
        nc_base_sma = Decimal("20")
        result = calculate_mbe(series, nc_base_sma, window=5)
        assert result == Decimal("0.00000000")

    def test_mbe_empty_series_raises(self):
        """Bos seri ValueError firlatir."""
        with pytest.raises(ValueError, match="en az 1"):
            calculate_mbe([], Decimal("20"), window=5)


# =====================================================================
# calculate_cost_snapshot testleri
# =====================================================================


class TestCalculateCostSnapshot:
    """Maliyet snapshot hesaplama testleri."""

    def test_basic_snapshot(self):
        """Temel maliyet ayristirma hesaplamasi."""
        result = calculate_cost_snapshot(
            cif_usd_ton=Decimal("680"),
            fx_rate=Decimal("34.20"),
            pump_price=Decimal("40.50"),
            otv_fixed_tl=Decimal("2.50"),
            kdv_rate=Decimal("0.18"),
            rho=Decimal("1190"),
            m_total=Decimal("1.20"),
        )

        assert isinstance(result, CostSnapshot)

        # CIF bileseni = (680 * 34.20) / 1190 = 19.54285714
        assert result.cif_component_tl == Decimal("19.54285714")

        # OTV bileseni = 2.50
        assert result.otv_component_tl == Decimal("2.50")

        # KDV bileseni = (19.54285714 + 2.50) * 0.18 = 22.04285714 * 0.18
        expected_kdv = ((Decimal("19.54285714") + Decimal("2.50")) * Decimal("0.18")).quantize(PRECISION)
        assert result.kdv_component_tl == expected_kdv

        # Marj bileseni = 1.20
        assert result.margin_component_tl == Decimal("1.20")

        # Gercek pompa fiyati
        assert result.actual_pump_price_tl == Decimal("40.50")

        # Cost gap hesaplandi
        assert result.cost_gap_tl is not None
        assert result.cost_gap_pct is not None

    def test_snapshot_cost_gap_sign(self):
        """Pompa fiyati teorik maliyetten yuksekse gap pozitif."""
        result = calculate_cost_snapshot(
            cif_usd_ton=Decimal("500"),
            fx_rate=Decimal("30.00"),
            pump_price=Decimal("50.00"),
            otv_fixed_tl=Decimal("2.00"),
            kdv_rate=Decimal("0.18"),
            rho=Decimal("1190"),
            m_total=Decimal("1.00"),
        )
        # Teorik maliyet dusuk, pompa yuksek => gap pozitif
        assert result.cost_gap_tl > Decimal("0")

    def test_snapshot_implied_cif(self):
        """Ima edilen CIF hesaplanir."""
        result = calculate_cost_snapshot(
            cif_usd_ton=Decimal("680"),
            fx_rate=Decimal("34.20"),
            pump_price=Decimal("40.50"),
            otv_fixed_tl=Decimal("2.50"),
            kdv_rate=Decimal("0.18"),
            rho=Decimal("1190"),
            m_total=Decimal("1.20"),
        )
        assert result.implied_cif_usd_ton is not None
        assert result.implied_cif_usd_ton > Decimal("0")


# =====================================================================
# detect_trend testleri
# =====================================================================


class TestDetectTrend:
    """Trend tespit testleri."""

    def test_increasing_trend(self):
        """Artan seri -> 'increase'."""
        series = [Decimal("10"), Decimal("11"), Decimal("12"), Decimal("13")]
        assert detect_trend(series, lookback=3) == "increase"

    def test_decreasing_trend(self):
        """Azalan seri -> 'decrease'."""
        series = [Decimal("13"), Decimal("12"), Decimal("11"), Decimal("10")]
        assert detect_trend(series, lookback=3) == "decrease"

    def test_flat_trend(self):
        """Sabit seri -> 'no_change'."""
        series = [Decimal("10"), Decimal("10"), Decimal("10")]
        assert detect_trend(series, lookback=3) == "no_change"

    def test_empty_series(self):
        """Bos seri -> 'no_change'."""
        assert detect_trend([], lookback=3) == "no_change"

    def test_single_value(self):
        """Tek deger -> 'no_change'."""
        assert detect_trend([Decimal("10")], lookback=3) == "no_change"


# =====================================================================
# get_regime_config testleri
# =====================================================================


class TestGetRegimeConfig:
    """Rejim konfigurasyonu testleri."""

    def test_regime_0_normal(self):
        """Rejim 0 (Normal): w=5, M=1.20."""
        config = get_regime_config(0)
        assert config.window == 5
        assert config.m_total == Decimal("1.20")

    def test_regime_1_secim(self):
        """Rejim 1 (Secim): w=7, M=1.00."""
        config = get_regime_config(1)
        assert config.window == 7
        assert config.m_total == Decimal("1.00")

    def test_regime_2_kur_soku(self):
        """Rejim 2 (Kur Soku): w=3, M=1.50."""
        config = get_regime_config(2)
        assert config.window == 3
        assert config.m_total == Decimal("1.50")

    def test_regime_3_vergi(self):
        """Rejim 3 (Vergi Ayarlama): w=5, M=1.20."""
        config = get_regime_config(3)
        assert config.window == 5
        assert config.m_total == Decimal("1.20")

    def test_invalid_regime_raises(self):
        """Gecersiz rejim kodu ValueError firlatir."""
        with pytest.raises(ValueError, match="Gecersiz rejim"):
            get_regime_config(99)


# =====================================================================
# get_rho testleri
# =====================================================================


class TestGetRho:
    """Yogunluk sabiti testleri."""

    def test_benzin_rho(self):
        assert get_rho("benzin") == Decimal("1180")

    def test_motorin_rho(self):
        assert get_rho("motorin") == Decimal("1190")

    def test_lpg_rho(self):
        assert get_rho("lpg") == Decimal("1750")

    def test_invalid_fuel_raises(self):
        with pytest.raises(ValueError, match="Gecersiz yakit"):
            get_rho("diesel")


# =====================================================================
# calculate_full_mbe testleri
# =====================================================================


class TestCalculateFullMBE:
    """Tam MBE hesaplama testleri."""

    def test_basic_full_mbe(self):
        """Temel tam MBE hesaplamasi."""
        nc_forward_series = [
            Decimal("19"), Decimal("20"), Decimal("21"),
            Decimal("22"), Decimal("23"),
        ]
        nc_base = Decimal("18")

        result = calculate_full_mbe(
            nc_forward_series=nc_forward_series,
            nc_base=nc_base,
            regime=0,
        )

        assert isinstance(result, MBEResult)
        assert result.nc_forward == Decimal("23")
        assert result.nc_base == Decimal("18")
        assert result.mbe_value > Decimal("0")
        assert result.regime == 0
        assert result.sma_window == 5
        assert result.sma_5 is not None
        assert result.sma_10 is not None
        assert result.trend_direction in ("increase", "decrease", "no_change")

    def test_regime_change_window(self):
        """Rejim degisiminde SMA penceresi degisir."""
        series = [Decimal("20")] * 10
        nc_base = Decimal("20")

        result_normal = calculate_full_mbe(series, nc_base, regime=0)
        result_secim = calculate_full_mbe(series, nc_base, regime=1)
        result_kur = calculate_full_mbe(series, nc_base, regime=2)

        assert result_normal.sma_window == 5
        assert result_secim.sma_window == 7
        assert result_kur.sma_window == 3

    def test_delta_mbe_calculation(self):
        """Delta MBE hesaplanir."""
        series = [Decimal("20")] * 5
        nc_base = Decimal("18")
        previous_mbe = Decimal("1.50")

        result = calculate_full_mbe(
            nc_forward_series=series,
            nc_base=nc_base,
            regime=0,
            previous_mbe=previous_mbe,
        )

        assert result.delta_mbe is not None
        expected_mbe = Decimal("20") - nc_base  # = 2.0
        expected_delta = expected_mbe - previous_mbe  # = 0.5
        assert result.delta_mbe == expected_delta.quantize(PRECISION)

    def test_delta_mbe_3_calculation(self):
        """3 gunluk delta MBE hesaplanir."""
        series = [Decimal("20")] * 5
        nc_base = Decimal("18")
        mbe_3_ago = Decimal("1.00")

        result = calculate_full_mbe(
            nc_forward_series=series,
            nc_base=nc_base,
            regime=0,
            mbe_3_days_ago=mbe_3_ago,
        )

        assert result.delta_mbe_3 is not None

    def test_mbe_pct_calculation(self):
        """MBE yuzdesi dogru hesaplanir."""
        series = [Decimal("22")] * 5
        nc_base = Decimal("20")

        result = calculate_full_mbe(series, nc_base, regime=0)

        # MBE = 22 - 20 = 2, MBE% = 2/20 * 100 = 10%
        assert result.mbe_pct == Decimal("10.00000000")

    def test_empty_series_raises(self):
        """Bos seri ValueError firlatir."""
        with pytest.raises(ValueError, match="bos olamaz"):
            calculate_full_mbe([], Decimal("20"), regime=0)

    def test_no_delta_when_previous_none(self):
        """Onceki MBE yoksa delta None."""
        series = [Decimal("20")] * 5
        result = calculate_full_mbe(series, Decimal("18"), regime=0)
        assert result.delta_mbe is None
        assert result.delta_mbe_3 is None


# =====================================================================
# Edge case testleri
# =====================================================================


class TestEdgeCases:
    """Sinir durumlari testleri."""

    def test_insufficient_data_sma(self):
        """Yetersiz veriyle SMA: mevcut verilerin ortalamasi alinir."""
        series = [Decimal("10"), Decimal("20")]
        result = calculate_sma(series, window=10)
        assert len(result) == 2
        # Ilk deger: sadece 10
        assert result[0] == Decimal("10.00000000")
        # Ikinci deger: (10 + 20) / 2 = 15
        assert result[1] == Decimal("15.00000000")

    def test_nc_base_with_zero_base(self):
        """NC_base sifir oldugunda MBE yuzdesi sifir doner."""
        series = [Decimal("20")] * 5
        result = calculate_full_mbe(series, Decimal("0"), regime=0)
        assert result.mbe_pct == Decimal("0")

    def test_large_values(self):
        """Buyuk degerlerle hesaplama."""
        result = calculate_nc_forward(
            cif_usd_ton=Decimal("1500"),
            fx_rate=Decimal("50.00"),
            rho=Decimal("1190"),
        )
        # 1500 * 50 / 1190 = 63.0252...
        assert result > Decimal("63")
        assert result < Decimal("64")

    def test_very_small_values(self):
        """Cok kucuk degerlerle hassasiyet kontrolu."""
        result = calculate_nc_forward(
            cif_usd_ton=Decimal("0.001"),
            fx_rate=Decimal("0.001"),
            rho=Decimal("1"),
        )
        assert result == Decimal("0.00000100")


# =====================================================================
# LPG-spesifik entegrasyon testleri
# =====================================================================


class TestLPGIntegration:
    """LPG yakit tipi icin entegrasyon testleri."""

    def test_lpg_rho_sabiti(self):
        """LPG yogunluk sabiti RHO dict'inde tanimli olmali."""
        assert "lpg" in RHO
        assert RHO["lpg"] == Decimal("1750")

    def test_lpg_nc_forward(self):
        """
        LPG icin NC_forward hesaplamasi.
        CIF=450, FX=36.50, rho=1750
        NC_forward = (450 * 36.50) / 1750 = 16425 / 1750 = 9.38571428...
        """
        result = calculate_nc_forward(
            cif_usd_ton=Decimal("450"),
            fx_rate=Decimal("36.50"),
            rho=RHO["lpg"],
        )
        expected = Decimal("9.38571429")
        assert result == expected

    def test_lpg_nc_base_from_pump(self):
        """
        LPG pompa fiyatindan NC_base ters hesaplama.
        pump=18.50, OTV=1.1916, KDV=0.20, M=1.20
        NC_base = (18.50 - 1.20) / (1 + 0.20) - 1.1916
        = 17.30 / 1.20 - 1.1916
        = 14.41666666... - 1.1916
        = 13.22506667...
        """
        result = calculate_nc_base_from_pump(
            pump_price=Decimal("18.50"),
            otv=Decimal("1.1916"),
            kdv=Decimal("0.20"),
            m_total=Decimal("1.20"),
        )
        # (18.50 - 1.20) / 1.20 - 1.1916 = 14.41666667 - 1.1916 = 13.22506667
        expected = Decimal("13.22506667")
        assert result == expected

    def test_lpg_cost_snapshot(self):
        """LPG icin maliyet snapshot hesaplamasi."""
        result = calculate_cost_snapshot(
            cif_usd_ton=Decimal("450"),
            fx_rate=Decimal("36.50"),
            pump_price=Decimal("18.50"),
            otv_fixed_tl=Decimal("1.1916"),
            kdv_rate=Decimal("0.20"),
            rho=RHO["lpg"],
            m_total=Decimal("1.20"),
        )

        assert isinstance(result, CostSnapshot)
        # CIF bileseni = (450 * 36.50) / 1750 = 9.38571429
        assert result.cif_component_tl == Decimal("9.38571429")
        # OTV bileseni = 1.1916
        assert result.otv_component_tl == Decimal("1.1916")
        # Gercek pompa fiyati
        assert result.actual_pump_price_tl == Decimal("18.50")
        # Teorik maliyet ve cost gap hesaplanmali
        assert result.theoretical_cost_tl is not None
        assert result.cost_gap_tl is not None
        assert result.cost_gap_pct is not None

    def test_lpg_full_mbe(self):
        """LPG icin tam MBE hesaplamasi."""
        # LPG icin tipik NC_forward degerleri (daha dusuk CIF -> daha dusuk NC)
        nc_forward_series = [
            Decimal("9.00"), Decimal("9.20"), Decimal("9.40"),
            Decimal("9.60"), Decimal("9.80"),
        ]
        nc_base = Decimal("8.50")

        result = calculate_full_mbe(
            nc_forward_series=nc_forward_series,
            nc_base=nc_base,
            regime=0,
        )

        assert isinstance(result, MBEResult)
        # Son NC_forward = 9.80
        assert result.nc_forward == Decimal("9.80")
        assert result.nc_base == Decimal("8.50")
        # MBE pozitif olmali (NC_forward > NC_base)
        assert result.mbe_value > Decimal("0")
        # SMA_5(son) = (9+9.2+9.4+9.6+9.8)/5 = 47/5 = 9.4
        # MBE = 9.4 - 8.5 = 0.9
        assert result.mbe_value == Decimal("0.90000000")
        # Trend: artan seri
        assert result.trend_direction == "increase"
        # MBE% = 0.9 / 8.5 * 100 = 10.5882...
        assert result.mbe_pct > Decimal("10")

    def test_lpg_otv_benzinden_dusuk(self):
        """LPG OTV'si benzin OTV'sinden belirgin sekilde dusuk olmali (yaklasik 1/4)."""
        # Bu test LPG'nin vergi avantajini dogrular
        lpg_otv = Decimal("1.1916")      # 2026 Ocak LPG OTV
        benzin_otv = Decimal("4.5664")    # 2026 Ocak Benzin OTV
        motorin_otv = Decimal("3.3277")   # 2026 Ocak Motorin OTV

        # LPG OTV < Motorin OTV < Benzin OTV
        assert lpg_otv < motorin_otv < benzin_otv

        # LPG OTV benzinin yaklasik 1/4'u
        oran = lpg_otv / benzin_otv
        assert oran < Decimal("0.30")  # %30'dan dusuk
        assert oran > Decimal("0.20")  # %20'den yuksek

    def test_lpg_rho_benzin_motorinden_yuksek(self):
        """LPG yogunluk katsayisi benzin ve motorinden yuksek olmali."""
        assert RHO["lpg"] > RHO["benzin"]
        assert RHO["lpg"] > RHO["motorin"]

    def test_lpg_get_rho(self):
        """get_rho fonksiyonu LPG icin dogru deger dondurmeli."""
        rho = get_rho("lpg")
        assert rho == Decimal("1750")
        assert isinstance(rho, Decimal)
