"""
Predictor v5 — Label Uretim Testleri
=====================================
Unit testler: _safe_decimal, _forward_fill_prices, _compute_single_label, compute_labels
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock
import pandas as pd

# Modul importlari
from src.predictor_v5.labels import (
    _safe_decimal,
    _forward_fill_prices,
    _compute_single_label,
    compute_labels,
    compute_all_labels,
    THRESHOLD,
    MAX_FF_LOOKBACK,
    _empty_dataframe,
)


# ===== Test 1: _safe_decimal donusumleri =====

class TestSafeDecimal:
    def test_float_to_decimal(self):
        result = _safe_decimal(58.07)
        assert isinstance(result, Decimal)
        assert result == Decimal("58.07")

    def test_int_to_decimal(self):
        assert _safe_decimal(42) == Decimal("42")

    def test_str_to_decimal(self):
        assert _safe_decimal("30.06") == Decimal("30.06")

    def test_none_returns_none(self):
        assert _safe_decimal(None) is None

    def test_float_precision(self):
        """float 0.1 + 0.2 != 0.3 sorunu olmamali"""
        result = _safe_decimal(0.1)
        assert result == Decimal("0.1")


# ===== Test 2: Forward-fill =====

class TestForwardFill:
    def test_no_gaps(self):
        """Eksik gun yoksa aynen doner."""
        prices = {
            date(2024, 1, 1): Decimal("58.00"),
            date(2024, 1, 2): Decimal("58.10"),
            date(2024, 1, 3): Decimal("58.20"),
        }
        filled = _forward_fill_prices(prices, date(2024, 1, 1), date(2024, 1, 3))
        assert filled[date(2024, 1, 1)] == Decimal("58.00")
        assert filled[date(2024, 1, 2)] == Decimal("58.10")
        assert filled[date(2024, 1, 3)] == Decimal("58.20")

    def test_gap_filled(self):
        """2 gunluk bosluk forward-fill ile doldurulur."""
        prices = {
            date(2024, 1, 1): Decimal("58.00"),
            # 2 ve 3 eksik
            date(2024, 1, 4): Decimal("58.50"),
        }
        filled = _forward_fill_prices(prices, date(2024, 1, 1), date(2024, 1, 4))
        assert filled[date(2024, 1, 1)] == Decimal("58.00")
        assert filled[date(2024, 1, 2)] == Decimal("58.00")  # FF
        assert filled[date(2024, 1, 3)] == Decimal("58.00")  # FF
        assert filled[date(2024, 1, 4)] == Decimal("58.50")

    def test_max_lookback_exceeded(self):
        """15 gunden fazla bosluk olursa None."""
        prices = {
            date(2024, 1, 1): Decimal("58.00"),
            # 16 gun bos
            date(2024, 1, 18): Decimal("59.00"),
        }
        filled = _forward_fill_prices(prices, date(2024, 1, 1), date(2024, 1, 18), max_lookback=15)
        assert filled[date(2024, 1, 15)] == Decimal("58.00")  # 14 gun gap = OK
        assert filled[date(2024, 1, 16)] == Decimal("58.00")  # 15 gun gap = OK
        assert filled[date(2024, 1, 17)] is None               # 16 gun gap = None

    def test_no_initial_data(self):
        """Baslangicta veri yoksa None."""
        prices = {
            date(2024, 1, 5): Decimal("58.00"),
        }
        filled = _forward_fill_prices(prices, date(2024, 1, 1), date(2024, 1, 5))
        assert filled[date(2024, 1, 1)] is None
        assert filled[date(2024, 1, 4)] is None
        assert filled[date(2024, 1, 5)] == Decimal("58.00")


# ===== Test 3: _compute_single_label — normal senaryo =====

class TestComputeSingleLabel:
    def _make_filled(self, prices_list):
        """Kolaylik: [(date, Decimal), ...] -> dict"""
        return {d: p for d, p in prices_list}

    def test_no_change(self):
        """Hic degisim yok: y_binary=0, first_event_type=none."""
        filled = self._make_filled([
            (date(2024, 1, 1), Decimal("58.00")),
            (date(2024, 1, 2), Decimal("58.00")),
            (date(2024, 1, 3), Decimal("58.00")),
            (date(2024, 1, 4), Decimal("58.00")),
        ])
        result = _compute_single_label(date(2024, 1, 1), filled)
        assert result is not None
        assert result["y_binary"] == 0
        assert result["first_event_type"] == "none"
        assert result["first_event_direction"] == 0
        assert result["first_event_amount"] == Decimal("0")
        assert result["net_amount_3d"] == Decimal("0")
        assert result["ref_price"] == Decimal("58.00")
        assert result["label_window_end"] == date(2024, 1, 4)

    def test_daily_increase_above_threshold(self):
        """D+1'de +0.30 artis: y_binary=1, daily event."""
        filled = self._make_filled([
            (date(2024, 1, 1), Decimal("58.00")),
            (date(2024, 1, 2), Decimal("58.30")),  # +0.30 >= 0.25
            (date(2024, 1, 3), Decimal("58.30")),
            (date(2024, 1, 4), Decimal("58.30")),
        ])
        result = _compute_single_label(date(2024, 1, 1), filled)
        assert result["y_binary"] == 1
        assert result["first_event_type"] == "daily"
        assert result["first_event_direction"] == 1
        assert result["first_event_amount"] == Decimal("0.30")
        assert result["net_amount_3d"] == Decimal("0.30")

    def test_daily_decrease_above_threshold(self):
        """D+2'de -0.50 dusus: y_binary=1, daily event, direction=-1."""
        filled = self._make_filled([
            (date(2024, 1, 1), Decimal("58.00")),
            (date(2024, 1, 2), Decimal("58.00")),
            (date(2024, 1, 3), Decimal("57.50")),  # -0.50 >= 0.25
            (date(2024, 1, 4), Decimal("57.50")),
        ])
        result = _compute_single_label(date(2024, 1, 1), filled)
        assert result["y_binary"] == 1
        assert result["first_event_type"] == "daily"
        assert result["first_event_direction"] == -1
        assert result["first_event_amount"] == Decimal("-0.50")
        assert result["net_amount_3d"] == Decimal("-0.50")

    def test_cumulative_fallback(self):
        """Her gun +0.05 ama 3 gunde toplam +0.15 >= 0.15: cumulative fallback. (v6)"""
        filled = self._make_filled([
            (date(2024, 1, 1), Decimal("58.00")),
            (date(2024, 1, 2), Decimal("58.05")),  # daily: +0.05 < 0.15
            (date(2024, 1, 3), Decimal("58.10")),  # daily: +0.05 < 0.15, cumul: +0.10 < 0.15
            (date(2024, 1, 4), Decimal("58.15")),  # daily: +0.05 < 0.15, cumul: +0.15 >= 0.15
        ])
        result = _compute_single_label(date(2024, 1, 1), filled)
        assert result["y_binary"] == 1
        assert result["first_event_type"] == "cumulative"
        assert result["first_event_direction"] == 1
        assert result["first_event_amount"] == Decimal("0.15")

    def test_below_threshold_both(self):
        """Gunluk ve kumulatif olarak esik altinda: y_binary=0. (v6: threshold=0.15)"""
        filled = self._make_filled([
            (date(2024, 1, 1), Decimal("58.00")),
            (date(2024, 1, 2), Decimal("58.03")),  # +0.03
            (date(2024, 1, 3), Decimal("58.06")),  # +0.03, cumul: +0.06
            (date(2024, 1, 4), Decimal("58.09")),  # +0.03, cumul: +0.09 < 0.15
        ])
        result = _compute_single_label(date(2024, 1, 1), filled)
        assert result["y_binary"] == 0
        assert result["first_event_type"] == "none"

    def test_ref_none_returns_none(self):
        """ref (D gunu) fiyati None ise label uretilmez."""
        filled = {
            date(2024, 1, 1): None,
            date(2024, 1, 2): Decimal("58.00"),
            date(2024, 1, 3): Decimal("58.00"),
            date(2024, 1, 4): Decimal("58.00"),
        }
        result = _compute_single_label(date(2024, 1, 1), filled)
        assert result is None

    def test_window_day_missing_returns_none(self):
        """Pencere icerisinde bir gun None ise label uretilmez."""
        filled = {
            date(2024, 1, 1): Decimal("58.00"),
            date(2024, 1, 2): Decimal("58.00"),
            date(2024, 1, 3): None,  # eksik
            date(2024, 1, 4): Decimal("58.00"),
        }
        result = _compute_single_label(date(2024, 1, 1), filled)
        assert result is None

    def test_exact_threshold(self):
        """Tam esik degerinde (0.15): y_binary=1 (>= kontrol). (v6)"""
        filled = self._make_filled([
            (date(2024, 1, 1), Decimal("58.00")),
            (date(2024, 1, 2), Decimal("58.15")),  # +0.15 == threshold
            (date(2024, 1, 3), Decimal("58.15")),
            (date(2024, 1, 4), Decimal("58.15")),
        ])
        result = _compute_single_label(date(2024, 1, 1), filled)
        assert result["y_binary"] == 1
        assert result["first_event_type"] == "daily"
        assert result["first_event_amount"] == Decimal("0.15")

    def test_just_below_threshold(self):
        """Esigin hemen altinda (0.14): y_binary=0. (v6: threshold=0.15)"""
        filled = self._make_filled([
            (date(2024, 1, 1), Decimal("58.00")),
            (date(2024, 1, 2), Decimal("58.14")),  # +0.14 < 0.15
            (date(2024, 1, 3), Decimal("58.14")),
            (date(2024, 1, 4), Decimal("58.14")),
        ])
        result = _compute_single_label(date(2024, 1, 1), filled)
        # Kumulatif: 0.14 < 0.15
        assert result["y_binary"] == 0
        assert result["first_event_type"] == "none"

    def test_first_event_picks_earliest_day(self):
        """Birden fazla gun esigi asarsa ilk gunu secer."""
        filled = self._make_filled([
            (date(2024, 1, 1), Decimal("58.00")),
            (date(2024, 1, 2), Decimal("58.30")),  # +0.30 (gun 1)
            (date(2024, 1, 3), Decimal("58.80")),  # +0.50 (gun 2)
            (date(2024, 1, 4), Decimal("59.20")),  # +0.40 (gun 3)
        ])
        result = _compute_single_label(date(2024, 1, 1), filled)
        assert result["first_event_type"] == "daily"
        # Ilk esik asimi gun 1'de: +0.30
        assert result["first_event_amount"] == Decimal("0.30")
        assert result["net_amount_3d"] == Decimal("1.20")

    def test_net_amount_negative(self):
        """net_amount_3d negatif olabilir."""
        filled = self._make_filled([
            (date(2024, 1, 1), Decimal("60.00")),
            (date(2024, 1, 2), Decimal("59.50")),  # -0.50
            (date(2024, 1, 3), Decimal("59.00")),  # -0.50
            (date(2024, 1, 4), Decimal("58.50")),  # -0.50
        ])
        result = _compute_single_label(date(2024, 1, 1), filled)
        assert result["net_amount_3d"] == Decimal("-1.50")


# ===== Test 4: compute_labels (DB mock'lu) =====

class TestComputeLabels:
    @patch("src.predictor_v5.labels._fetch_pump_prices")
    def test_basic_label_generation(self, mock_fetch):
        """3 gun icin label uretimi (DB mock)."""
        mock_fetch.return_value = {
            date(2024, 1, 1): Decimal("58.00"),
            date(2024, 1, 2): Decimal("58.30"),
            date(2024, 1, 3): Decimal("58.30"),
            date(2024, 1, 4): Decimal("58.30"),
            date(2024, 1, 5): Decimal("58.30"),
            date(2024, 1, 6): Decimal("58.30"),
        }
        df = compute_labels("benzin", date(2024, 1, 1), date(2024, 1, 3))
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert list(df.columns) == [
            "run_date", "fuel_type", "y_binary", "first_event_direction",
            "first_event_amount", "first_event_type", "net_amount_3d",
            "ref_price", "label_window_end",
        ]
        # Ilk gun: +0.30 => y_binary=1
        assert df.iloc[0]["y_binary"] == 1
        assert df.iloc[0]["fuel_type"] == "benzin"

    @patch("src.predictor_v5.labels._fetch_pump_prices")
    def test_empty_data(self, mock_fetch):
        """Veri yoksa bos DataFrame doner."""
        mock_fetch.return_value = {}
        df = compute_labels("benzin", date(2024, 1, 1), date(2024, 1, 10))
        assert len(df) == 0
        assert "run_date" in df.columns

    def test_invalid_fuel_type(self):
        """Gecersiz yakit tipi ValueError firlatir."""
        with pytest.raises(ValueError, match="Gecersiz yakit tipi"):
            compute_labels("dizel", date(2024, 1, 1), date(2024, 1, 10))

    def test_invalid_date_range(self):
        """start > end ValueError firlatir."""
        with pytest.raises(ValueError, match="start_date"):
            compute_labels("benzin", date(2024, 12, 31), date(2024, 1, 1))


# ===== Test 5: compute_all_labels (3 yakit tipi) =====

class TestComputeAllLabels:
    @patch("src.predictor_v5.labels._fetch_pump_prices")
    def test_all_fuel_types(self, mock_fetch):
        """3 yakit tipi icin birlesik uretim."""
        mock_fetch.return_value = {
            date(2024, 1, 1): Decimal("58.00"),
            date(2024, 1, 2): Decimal("58.30"),
            date(2024, 1, 3): Decimal("58.30"),
            date(2024, 1, 4): Decimal("58.30"),
        }
        df = compute_all_labels(date(2024, 1, 1), date(2024, 1, 1))
        assert len(df) == 3
        fuel_types = set(df["fuel_type"].tolist())
        assert fuel_types == {"benzin", "motorin", "lpg"}


# ===== Test 6: Edge case — D gunu pencere disinda =====

class TestEdgeCases:
    @patch("src.predictor_v5.labels._fetch_pump_prices")
    def test_window_beyond_data(self, mock_fetch):
        """Pencere sonu (D+3) verisiz: o gun icin label uretilmez."""
        # Sadece 2024-01-01 ve 2024-01-02 var
        mock_fetch.return_value = {
            date(2024, 1, 1): Decimal("58.00"),
            date(2024, 1, 2): Decimal("58.30"),
        }
        df = compute_labels("benzin", date(2024, 1, 1), date(2024, 1, 1))
        # D+3 (2024-01-04) yok ve FF de olusmaz cunku D+2 bile yok aslinda
        # Ama FF ile D+2 = D+3 = 58.30 olur (lookback 15 gun icerisinde)
        # Aslinda FF baslangic = start_date - 15 = 2023-12-17
        # D+3 = 2024-01-04, FF ile 58.30 olur
        # Boylece label uretilebilir
        assert len(df) == 1

    @patch("src.predictor_v5.labels._fetch_pump_prices")
    def test_multiple_days_constant_price(self, mock_fetch):
        """Tum gunler ayni fiyat: tum labellar y_binary=0."""
        prices = {}
        for i in range(30):
            prices[date(2024, 1, 1) + timedelta(days=i)] = Decimal("58.00")
        mock_fetch.return_value = prices

        df = compute_labels("motorin", date(2024, 1, 1), date(2024, 1, 20))
        assert len(df) == 20
        assert df["y_binary"].sum() == 0
        assert all(df["first_event_type"] == "none")
        assert all(df["net_amount_3d"] == Decimal("0"))

    def test_empty_dataframe_columns(self):
        """Bos DataFrame doğru kolonlara sahip."""
        df = _empty_dataframe("benzin")
        expected = [
            "run_date", "fuel_type", "y_binary", "first_event_direction",
            "first_event_amount", "first_event_type", "net_amount_3d",
            "ref_price", "label_window_end",
        ]
        assert list(df.columns) == expected
        assert len(df) == 0
