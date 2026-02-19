"""
Predictor v5 Label modülü testleri.

DB bağımlılığı olmadan çalışır — tüm testler mock veya doğrudan
iç fonksiyonları test eder.
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from src.predictor_v5.labels import (
    _safe_decimal,
    _forward_fill_prices,
    _compute_single_label,
    compute_labels,
    compute_labels_all_fuels,
    _empty_dataframe,
    THRESHOLD_TL,
    FORWARD_FILL_MAX_DAYS,
    VALID_FUEL_TYPES,
)


# ─────────────────── _safe_decimal testleri ───────────────────


class TestSafeDecimal:
    """_safe_decimal fonksiyonu testleri."""

    def test_float_to_decimal(self):
        result = _safe_decimal(58.07)
        assert result == Decimal("58.07")

    def test_str_to_decimal(self):
        result = _safe_decimal("43.71")
        assert result == Decimal("43.71")

    def test_int_to_decimal(self):
        result = _safe_decimal(100)
        assert result == Decimal("100")

    def test_none_returns_none(self):
        assert _safe_decimal(None) is None

    def test_nan_returns_none(self):
        assert _safe_decimal(float("nan")) is None

    def test_inf_returns_none(self):
        assert _safe_decimal(float("inf")) is None

    def test_invalid_string_returns_none(self):
        assert _safe_decimal("abc") is None


# ─────────────────── _forward_fill_prices testleri ───────────────────


class TestForwardFill:
    """Forward-fill fonksiyonu testleri."""

    def test_continuous_data(self):
        """Sürekli veri — forward-fill gerekmez."""
        raw = {
            date(2026, 1, 1): Decimal("50.00"),
            date(2026, 1, 2): Decimal("50.25"),
            date(2026, 1, 3): Decimal("50.50"),
        }
        filled = _forward_fill_prices(raw, date(2026, 1, 1), date(2026, 1, 3))
        assert filled[date(2026, 1, 1)] == Decimal("50.00")
        assert filled[date(2026, 1, 2)] == Decimal("50.25")
        assert filled[date(2026, 1, 3)] == Decimal("50.50")

    def test_gap_filled(self):
        """1 günlük boşluk forward-fill edilir."""
        raw = {
            date(2026, 1, 1): Decimal("50.00"),
            # 2 Ocak eksik
            date(2026, 1, 3): Decimal("50.50"),
        }
        filled = _forward_fill_prices(raw, date(2026, 1, 1), date(2026, 1, 3))
        assert filled[date(2026, 1, 2)] == Decimal("50.00")  # FF

    def test_max_lookback_exceeded(self):
        """15 günden fazla boşlukta None döner."""
        raw = {
            date(2026, 1, 1): Decimal("50.00"),
            # 16 gün boşluk
            date(2026, 1, 18): Decimal("51.00"),
        }
        filled = _forward_fill_prices(raw, date(2026, 1, 1), date(2026, 1, 18))
        assert filled[date(2026, 1, 15)] == Decimal("50.00")  # 14 gün → OK
        assert filled[date(2026, 1, 16)] == Decimal("50.00")  # 15 gün → OK
        assert filled[date(2026, 1, 17)] is None  # 16 gün → None

    def test_no_data_returns_none(self):
        """Hiç veri yoksa tüm günler None."""
        raw: dict[date, Decimal] = {}
        filled = _forward_fill_prices(raw, date(2026, 1, 1), date(2026, 1, 3))
        assert all(v is None for v in filled.values())
        assert len(filled) == 3

    def test_data_before_start_used_for_ff(self):
        """start_date öncesi veri forward-fill için kullanılır."""
        raw = {
            date(2025, 12, 31): Decimal("49.00"),
            date(2026, 1, 3): Decimal("50.00"),
        }
        filled = _forward_fill_prices(raw, date(2026, 1, 1), date(2026, 1, 3))
        assert filled[date(2026, 1, 1)] == Decimal("49.00")
        assert filled[date(2026, 1, 2)] == Decimal("49.00")


# ─────────────────── _compute_single_label testleri ───────────────────


class TestComputeSingleLabel:
    """Tek gün label hesaplama testleri."""

    def test_no_change_all_same_price(self):
        """Tüm fiyatlar aynı — y_binary=0, event=none."""
        prices = {
            date(2026, 1, 10): Decimal("50.00"),
            date(2026, 1, 11): Decimal("50.00"),
            date(2026, 1, 12): Decimal("50.00"),
            date(2026, 1, 13): Decimal("50.00"),
        }
        result = _compute_single_label(date(2026, 1, 10), prices, "benzin")
        assert result is not None
        assert result["y_binary"] == 0
        assert result["first_event_type"] == "none"
        assert result["first_event_direction"] == 0
        assert result["net_amount_3d"] == Decimal("0")

    def test_daily_increase_above_threshold(self):
        """D+1'de 0.30 TL artış — y_binary=1, daily event."""
        prices = {
            date(2026, 1, 10): Decimal("50.00"),
            date(2026, 1, 11): Decimal("50.30"),  # +0.30
            date(2026, 1, 12): Decimal("50.30"),
            date(2026, 1, 13): Decimal("50.30"),
        }
        result = _compute_single_label(date(2026, 1, 10), prices, "benzin")
        assert result["y_binary"] == 1
        assert result["first_event_type"] == "daily"
        assert result["first_event_direction"] == 1
        assert result["first_event_amount"] == Decimal("0.30")

    def test_daily_decrease_above_threshold(self):
        """D+2'de 0.50 TL düşüş — y_binary=1, daily event, direction=-1."""
        prices = {
            date(2026, 1, 10): Decimal("50.00"),
            date(2026, 1, 11): Decimal("50.00"),
            date(2026, 1, 12): Decimal("49.50"),  # -0.50
            date(2026, 1, 13): Decimal("49.50"),
        }
        result = _compute_single_label(date(2026, 1, 10), prices, "motorin")
        assert result["y_binary"] == 1
        assert result["first_event_type"] == "daily"
        assert result["first_event_direction"] == -1
        assert result["first_event_amount"] == Decimal("-0.50")

    def test_cumulative_fallback(self):
        """Her günlük fark < 0.25 ama kümülatif >= 0.25 — cumulative event."""
        prices = {
            date(2026, 1, 10): Decimal("50.00"),
            date(2026, 1, 11): Decimal("50.10"),  # +0.10
            date(2026, 1, 12): Decimal("50.20"),  # +0.10
            date(2026, 1, 13): Decimal("50.30"),  # +0.10, cumul = +0.30
        }
        result = _compute_single_label(date(2026, 1, 10), prices, "benzin")
        assert result["y_binary"] == 1
        assert result["first_event_type"] == "cumulative"
        assert result["first_event_direction"] == 1
        # İlk kümülatif >= 0.25 olan: D+3 → 50.30 - 50.00 = 0.30
        assert result["first_event_amount"] == Decimal("0.30")

    def test_below_threshold_no_event(self):
        """Günlük ve kümülatif farklar < 0.25 — y_binary=0."""
        prices = {
            date(2026, 1, 10): Decimal("50.00"),
            date(2026, 1, 11): Decimal("50.05"),
            date(2026, 1, 12): Decimal("50.10"),
            date(2026, 1, 13): Decimal("50.15"),  # cumul = +0.15 < 0.25
        }
        result = _compute_single_label(date(2026, 1, 10), prices, "lpg")
        assert result["y_binary"] == 0
        assert result["first_event_type"] == "none"

    def test_ref_price_none_returns_none(self):
        """D günü fiyatı None ise label üretilmez."""
        prices = {
            date(2026, 1, 10): None,
            date(2026, 1, 11): Decimal("50.00"),
        }
        result = _compute_single_label(date(2026, 1, 10), prices, "benzin")
        assert result is None

    def test_d_plus_1_none_returns_none(self):
        """D+1 fiyatı None ise label üretilmez."""
        prices = {
            date(2026, 1, 10): Decimal("50.00"),
        }
        result = _compute_single_label(date(2026, 1, 10), prices, "benzin")
        assert result is None

    def test_net_amount_3d_calculation(self):
        """net_amount_3d = price(D+3) - ref doğruluğu."""
        prices = {
            date(2026, 1, 10): Decimal("50.00"),
            date(2026, 1, 11): Decimal("50.50"),
            date(2026, 1, 12): Decimal("51.00"),
            date(2026, 1, 13): Decimal("49.75"),
        }
        result = _compute_single_label(date(2026, 1, 10), prices, "benzin")
        assert result["net_amount_3d"] == Decimal("-0.25")

    def test_label_window_end_correct(self):
        """label_window_end = D + 3."""
        prices = {
            date(2026, 1, 10): Decimal("50.00"),
            date(2026, 1, 11): Decimal("50.00"),
            date(2026, 1, 12): Decimal("50.00"),
            date(2026, 1, 13): Decimal("50.00"),
        }
        result = _compute_single_label(date(2026, 1, 10), prices, "benzin")
        assert result["label_window_end"] == date(2026, 1, 13)

    def test_exact_threshold_triggers(self):
        """Tam 0.25 TL fark eşik değerinde y_binary=1 olmalı."""
        prices = {
            date(2026, 1, 10): Decimal("50.00"),
            date(2026, 1, 11): Decimal("50.25"),  # tam 0.25
            date(2026, 1, 12): Decimal("50.25"),
            date(2026, 1, 13): Decimal("50.25"),
        }
        result = _compute_single_label(date(2026, 1, 10), prices, "benzin")
        assert result["y_binary"] == 1
        assert result["first_event_type"] == "daily"
        assert result["first_event_amount"] == Decimal("0.25")

    def test_first_event_picks_earliest(self):
        """Birden fazla günlük eşik aşımı — ilk olan seçilir."""
        prices = {
            date(2026, 1, 10): Decimal("50.00"),
            date(2026, 1, 11): Decimal("50.30"),  # +0.30 (ilk)
            date(2026, 1, 12): Decimal("50.80"),  # +0.50 (ikinci)
            date(2026, 1, 13): Decimal("50.80"),
        }
        result = _compute_single_label(date(2026, 1, 10), prices, "motorin")
        assert result["first_event_amount"] == Decimal("0.30")
        assert result["first_event_type"] == "daily"

    def test_partial_window_d3_missing(self):
        """D+3 fiyatı eksik — net_amount_3d son bilinen fiyattan hesaplanır."""
        prices = {
            date(2026, 1, 10): Decimal("50.00"),
            date(2026, 1, 11): Decimal("50.40"),
            date(2026, 1, 12): Decimal("50.60"),
            # D+3 = 13 Ocak eksik
        }
        result = _compute_single_label(date(2026, 1, 10), prices, "benzin")
        assert result is not None
        # D+3 yok, son bilinen D+2 = 50.60
        assert result["net_amount_3d"] == Decimal("0.60")


# ─────────────────── compute_labels entegrasyon testleri ───────────────────


class TestComputeLabels:
    """compute_labels fonksiyonu testleri (DB mock'lu)."""

    def test_invalid_fuel_type_raises(self):
        """Geçersiz yakıt tipi ValueError verir."""
        with pytest.raises(ValueError, match="Geçersiz fuel_type"):
            compute_labels("kerosin", date(2026, 1, 1), date(2026, 1, 10))

    def test_start_after_end_raises(self):
        """start > end ValueError verir."""
        with pytest.raises(ValueError, match="start_date"):
            compute_labels("benzin", date(2026, 2, 1), date(2026, 1, 1))

    @patch("src.predictor_v5.labels._fetch_pump_prices")
    def test_empty_db_returns_empty_df(self, mock_fetch):
        """DB'de veri yoksa boş DataFrame döner."""
        mock_fetch.return_value = {}
        df = compute_labels("benzin", date(2026, 1, 1), date(2026, 1, 10))
        assert df.empty
        assert list(df.columns) == [
            "run_date", "fuel_type", "y_binary",
            "first_event_direction", "first_event_amount",
            "first_event_type", "net_amount_3d", "ref_price",
            "label_window_end",
        ]

    @patch("src.predictor_v5.labels._fetch_pump_prices")
    def test_normal_scenario(self, mock_fetch):
        """Normal senaryo: 5 gün veri → 2 label üretilir (ilk 2 gün, D+3 sınırı)."""
        mock_fetch.return_value = {
            date(2026, 1, 1): Decimal("50.00"),
            date(2026, 1, 2): Decimal("50.30"),
            date(2026, 1, 3): Decimal("50.30"),
            date(2026, 1, 4): Decimal("50.30"),
            date(2026, 1, 5): Decimal("50.30"),
        }
        df = compute_labels("benzin", date(2026, 1, 1), date(2026, 1, 2))
        assert len(df) == 2
        # 1 Ocak: D+1=50.30, daily_diff=+0.30 >= 0.25 → y_binary=1
        row0 = df[df["run_date"] == date(2026, 1, 1)].iloc[0]
        assert row0["y_binary"] == 1
        assert row0["first_event_type"] == "daily"

    @patch("src.predictor_v5.labels._fetch_pump_prices")
    def test_lpg_scenario(self, mock_fetch):
        """LPG senaryosu — geçerli fuel_type."""
        mock_fetch.return_value = {
            date(2026, 1, 1): Decimal("30.00"),
            date(2026, 1, 2): Decimal("30.00"),
            date(2026, 1, 3): Decimal("30.00"),
            date(2026, 1, 4): Decimal("30.00"),
        }
        df = compute_labels("lpg", date(2026, 1, 1), date(2026, 1, 1))
        assert len(df) == 1
        assert df.iloc[0]["fuel_type"] == "lpg"
        assert df.iloc[0]["y_binary"] == 0

    @patch("src.predictor_v5.labels._fetch_pump_prices")
    def test_dataframe_dtypes(self, mock_fetch):
        """DataFrame kolon tipleri doğru mu."""
        mock_fetch.return_value = {
            date(2026, 1, 1): Decimal("50.00"),
            date(2026, 1, 2): Decimal("50.30"),
            date(2026, 1, 3): Decimal("50.30"),
            date(2026, 1, 4): Decimal("50.30"),
        }
        df = compute_labels("motorin", date(2026, 1, 1), date(2026, 1, 1))
        assert len(df) == 1
        assert df["y_binary"].dtype in ("int64", "int32", "int")
        assert df["first_event_direction"].dtype in ("int64", "int32", "int")


# ─────────────────── compute_labels_all_fuels testleri ───────────────────


class TestComputeLabelsAllFuels:
    """compute_labels_all_fuels fonksiyonu testleri."""

    @patch("src.predictor_v5.labels._fetch_pump_prices")
    def test_all_fuels_concatenated(self, mock_fetch):
        """3 yakıt tipi birleşik DataFrame."""
        mock_fetch.return_value = {
            date(2026, 1, 1): Decimal("50.00"),
            date(2026, 1, 2): Decimal("50.00"),
            date(2026, 1, 3): Decimal("50.00"),
            date(2026, 1, 4): Decimal("50.00"),
        }
        df = compute_labels_all_fuels(date(2026, 1, 1), date(2026, 1, 1))
        assert len(df) == 3
        assert set(df["fuel_type"]) == {"benzin", "lpg", "motorin"}


# ─────────────────── edge case testleri ───────────────────


class TestEdgeCases:
    """Kenar durumlar ve sınır değerler."""

    def test_empty_dataframe_columns(self):
        """Boş DataFrame doğru kolonlara sahip."""
        df = _empty_dataframe()
        assert len(df) == 0
        assert "run_date" in df.columns
        assert "y_binary" in df.columns
        assert len(df.columns) == 9

    def test_threshold_constant(self):
        """Eşik sabiti 0.25 TL."""
        assert THRESHOLD_TL == Decimal("0.25")

    def test_forward_fill_max_constant(self):
        """Forward-fill max gün 15."""
        assert FORWARD_FILL_MAX_DAYS == 15

    def test_valid_fuel_types(self):
        """Geçerli yakıt tipleri."""
        assert VALID_FUEL_TYPES == {"benzin", "motorin", "lpg"}

    def test_cumulative_negative_fallback(self):
        """Negatif yönde kümülatif fallback."""
        prices = {
            date(2026, 1, 10): Decimal("50.00"),
            date(2026, 1, 11): Decimal("49.90"),  # -0.10
            date(2026, 1, 12): Decimal("49.80"),  # -0.10
            date(2026, 1, 13): Decimal("49.70"),  # -0.10, cumul = -0.30
        }
        result = _compute_single_label(date(2026, 1, 10), prices, "benzin")
        assert result["y_binary"] == 1
        assert result["first_event_type"] == "cumulative"
        assert result["first_event_direction"] == -1
        assert result["first_event_amount"] == Decimal("-0.30")

    def test_weekend_same_price_ff(self):
        """Hafta sonu aynı fiyat forward-fill — no event."""
        # Cuma 50.00, Cumartesi/Pazar aynı, Pazartesi de aynı
        friday = date(2026, 1, 9)  # Cuma
        prices = {
            friday: Decimal("50.00"),
            friday + timedelta(days=1): Decimal("50.00"),  # C.tesi FF
            friday + timedelta(days=2): Decimal("50.00"),  # Pazar FF
            friday + timedelta(days=3): Decimal("50.00"),  # P.tesi
        }
        result = _compute_single_label(friday, prices, "motorin")
        assert result["y_binary"] == 0
        assert result["net_amount_3d"] == Decimal("0")
