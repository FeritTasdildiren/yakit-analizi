"""
Veri toplama servisleri test modülü.

Brent petrol fiyatı ve USD/TRY döviz kuru collector'ları için mock testler.
Harici API'lere bağımlılık olmadan çalışır.
"""

import json
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.data_collectors.brent_collector import (
    BrentData,
    estimate_cif_med,
    fetch_brent_daily,
    _safe_decimal as brent_safe_decimal,
)
from src.data_collectors.fx_collector import (
    FXData,
    fetch_usd_try_daily,
    _safe_decimal as fx_safe_decimal,
)
from src.data_collectors.validators import (
    check_daily_change_brent,
    check_daily_change_fx,
    detect_gaps,
    fill_weekend_gaps_brent,
    fill_weekend_gaps_fx,
    validate_brent,
    validate_fx,
)


# ============================================================
# CIF Med Tahmin Testleri
# ============================================================


class TestEstimateCifMed:
    """CIF Med hesaplama fonksiyonu testleri."""

    def test_normal_brent_price(self) -> None:
        """Normal bir Brent fiyatı ile CIF Med hesaplaması."""
        brent = Decimal("80")
        result = estimate_cif_med(brent)
        # 80 * 7.45 + 20 = 596 + 20 = 616
        assert result == Decimal("616.00")

    def test_low_brent_price(self) -> None:
        """Düşük Brent fiyatı ile CIF Med hesaplaması."""
        brent = Decimal("25")
        result = estimate_cif_med(brent)
        # 25 * 7.45 + 20 = 186.25 + 20 = 206.25
        assert result == Decimal("206.25")

    def test_high_brent_price(self) -> None:
        """Yüksek Brent fiyatı ile CIF Med hesaplaması."""
        brent = Decimal("150")
        result = estimate_cif_med(brent)
        # 150 * 7.45 + 20 = 1117.50 + 20 = 1137.50
        assert result == Decimal("1137.50")

    def test_zero_brent_price(self) -> None:
        """Sıfır Brent fiyatı ile CIF Med hesaplaması."""
        brent = Decimal("0")
        result = estimate_cif_med(brent)
        # 0 * 7.45 + 20 = 20
        assert result == Decimal("20")


# ============================================================
# Decimal Dönüşüm Testleri
# ============================================================


class TestSafeDecimal:
    """Güvenli Decimal dönüşüm testleri."""

    def test_float_to_decimal(self) -> None:
        """Float değerden Decimal dönüşümü."""
        result = brent_safe_decimal(80.55)
        assert result == Decimal("80.55")

    def test_string_to_decimal(self) -> None:
        """String değerden Decimal dönüşümü."""
        result = brent_safe_decimal("36.1234")
        assert result == Decimal("36.1234")

    def test_none_returns_none(self) -> None:
        """None değer None döndürmeli."""
        result = brent_safe_decimal(None)
        assert result is None

    def test_invalid_string_returns_none(self) -> None:
        """Geçersiz string None döndürmeli."""
        result = brent_safe_decimal("geçersiz")
        assert result is None

    def test_turkish_decimal_separator(self) -> None:
        """Türkçe ondalık ayırıcı (virgül) desteği."""
        result = fx_safe_decimal("36,1234")
        assert result == Decimal("36.1234")


# ============================================================
# Brent Doğrulama Testleri
# ============================================================


class TestValidateBrent:
    """Brent fiyat doğrulama testleri."""

    def test_valid_brent_data(self) -> None:
        """Geçerli Brent verisi doğrulamayı geçmeli."""
        data = BrentData(
            trade_date=date(2026, 2, 14),
            brent_usd_bbl=Decimal("80.50"),
            cif_med_estimate_usd_ton=Decimal("619.73"),
            source="yfinance",
            raw_data=None,
        )
        is_valid, errors = validate_brent(data)
        assert is_valid is True
        assert len(errors) == 0

    def test_brent_too_low(self) -> None:
        """Çok düşük Brent fiyatı reddedilmeli."""
        data = BrentData(
            trade_date=date(2026, 2, 14),
            brent_usd_bbl=Decimal("15.00"),
            cif_med_estimate_usd_ton=Decimal("131.75"),
            source="yfinance",
            raw_data=None,
        )
        is_valid, errors = validate_brent(data)
        assert is_valid is False
        assert len(errors) >= 1

    def test_brent_too_high(self) -> None:
        """Çok yüksek Brent fiyatı reddedilmeli."""
        data = BrentData(
            trade_date=date(2026, 2, 14),
            brent_usd_bbl=Decimal("250.00"),
            cif_med_estimate_usd_ton=Decimal("1882.50"),
            source="yfinance",
            raw_data=None,
        )
        is_valid, errors = validate_brent(data)
        assert is_valid is False
        assert len(errors) >= 1

    def test_cif_med_out_of_range(self) -> None:
        """CIF Med tahmini aralık dışında olduğunda hata vermeli."""
        data = BrentData(
            trade_date=date(2026, 2, 14),
            brent_usd_bbl=Decimal("21.00"),  # Geçerli ama düşük
            cif_med_estimate_usd_ton=Decimal("176.45"),  # 200'den küçük → hata
            source="yfinance",
            raw_data=None,
        )
        is_valid, errors = validate_brent(data)
        assert is_valid is False


# ============================================================
# FX Doğrulama Testleri
# ============================================================


class TestValidateFx:
    """USD/TRY kuru doğrulama testleri."""

    def test_valid_fx_data(self) -> None:
        """Geçerli FX verisi doğrulamayı geçmeli."""
        data = FXData(
            trade_date=date(2026, 2, 14),
            usd_try_rate=Decimal("36.25"),
            source="tcmb_evds",
            raw_data=None,
        )
        is_valid, errors = validate_fx(data)
        assert is_valid is True
        assert len(errors) == 0

    def test_fx_too_low(self) -> None:
        """Çok düşük FX kuru reddedilmeli."""
        data = FXData(
            trade_date=date(2026, 2, 14),
            usd_try_rate=Decimal("0.50"),
            source="tcmb_evds",
            raw_data=None,
        )
        is_valid, errors = validate_fx(data)
        assert is_valid is False

    def test_fx_too_high(self) -> None:
        """Çok yüksek FX kuru reddedilmeli."""
        data = FXData(
            trade_date=date(2026, 2, 14),
            usd_try_rate=Decimal("150.00"),
            source="tcmb_evds",
            raw_data=None,
        )
        is_valid, errors = validate_fx(data)
        assert is_valid is False


# ============================================================
# Günlük Değişim Kontrol Testleri
# ============================================================


class TestDailyChangeCheck:
    """Günlük fiyat değişim limiti testleri."""

    def test_brent_normal_change(self) -> None:
        """Normal günlük Brent değişimi kabul edilmeli."""
        prev = BrentData(
            trade_date=date(2026, 2, 13),
            brent_usd_bbl=Decimal("80.00"),
            cif_med_estimate_usd_ton=Decimal("616.00"),
            source="yfinance",
        )
        curr = BrentData(
            trade_date=date(2026, 2, 14),
            brent_usd_bbl=Decimal("82.00"),  # %2.5 artış
            cif_med_estimate_usd_ton=Decimal("630.90"),
            source="yfinance",
        )
        is_normal, msg = check_daily_change_brent(curr, prev)
        assert is_normal is True
        assert msg is None

    def test_brent_excessive_change(self) -> None:
        """%15'ten fazla Brent değişimi uyarı vermeli."""
        prev = BrentData(
            trade_date=date(2026, 2, 13),
            brent_usd_bbl=Decimal("80.00"),
            cif_med_estimate_usd_ton=Decimal("616.00"),
            source="yfinance",
        )
        curr = BrentData(
            trade_date=date(2026, 2, 14),
            brent_usd_bbl=Decimal("95.00"),  # %18.75 artış
            cif_med_estimate_usd_ton=Decimal("727.75"),
            source="yfinance",
        )
        is_normal, msg = check_daily_change_brent(curr, prev)
        assert is_normal is False
        assert msg is not None

    def test_fx_normal_change(self) -> None:
        """Normal günlük FX değişimi kabul edilmeli."""
        prev = FXData(
            trade_date=date(2026, 2, 13),
            usd_try_rate=Decimal("36.00"),
            source="tcmb_evds",
        )
        curr = FXData(
            trade_date=date(2026, 2, 14),
            usd_try_rate=Decimal("36.50"),  # %1.4 artış
            source="tcmb_evds",
        )
        is_normal, msg = check_daily_change_fx(curr, prev)
        assert is_normal is True

    def test_fx_excessive_change(self) -> None:
        """%10'dan fazla FX değişimi uyarı vermeli."""
        prev = FXData(
            trade_date=date(2026, 2, 13),
            usd_try_rate=Decimal("36.00"),
            source="tcmb_evds",
        )
        curr = FXData(
            trade_date=date(2026, 2, 14),
            usd_try_rate=Decimal("40.00"),  # %11.1 artış
            source="tcmb_evds",
        )
        is_normal, msg = check_daily_change_fx(curr, prev)
        assert is_normal is False
        assert msg is not None


# ============================================================
# Gap Detection (Boşluk Tespiti) Testleri
# ============================================================


class TestGapDetection:
    """Veri boşluk tespiti testleri."""

    def test_no_gaps(self) -> None:
        """Eksiksiz veride boşluk olmamalı."""
        existing = {
            date(2026, 2, 10),
            date(2026, 2, 11),
            date(2026, 2, 12),
        }
        gaps = detect_gaps(existing, date(2026, 2, 10), date(2026, 2, 12))
        assert len(gaps) == 0

    def test_with_gaps(self) -> None:
        """Eksik günler doğru tespit edilmeli."""
        existing = {
            date(2026, 2, 10),
            date(2026, 2, 12),  # 11 eksik
        }
        gaps = detect_gaps(existing, date(2026, 2, 10), date(2026, 2, 12))
        assert len(gaps) == 1
        assert date(2026, 2, 11) in gaps

    def test_weekend_gaps(self) -> None:
        """Hafta sonu günleri eksik olarak tespit edilmeli."""
        # Pazartesi-Cuma verisi var, Cumartesi-Pazar yok
        existing = {
            date(2026, 2, 9),   # Pazartesi
            date(2026, 2, 10),  # Salı
            date(2026, 2, 11),  # Çarşamba
            date(2026, 2, 12),  # Perşembe
            date(2026, 2, 13),  # Cuma
        }
        gaps = detect_gaps(existing, date(2026, 2, 9), date(2026, 2, 15))
        assert len(gaps) == 2  # 14 Cumartesi, 15 Pazar
        assert date(2026, 2, 14) in gaps
        assert date(2026, 2, 15) in gaps


# ============================================================
# Gap Fill (Boşluk Doldurma) Testleri
# ============================================================


class TestGapFill:
    """Hafta sonu boşluk doldurma testleri."""

    def test_fill_weekend_brent(self) -> None:
        """Hafta sonu Brent boşluğu Cuma değeri ile doldurulmalı."""
        friday_data = BrentData(
            trade_date=date(2026, 2, 13),  # Cuma
            brent_usd_bbl=Decimal("80.00"),
            cif_med_estimate_usd_ton=Decimal("616.00"),
            source="yfinance",
        )
        data_list = [friday_data]
        filled = fill_weekend_gaps_brent(
            data_list,
            date(2026, 2, 13),
            date(2026, 2, 15),
        )

        assert len(filled) == 3  # Cuma + Cumartesi + Pazar
        # Cumartesi interpolated olmalı
        saturday = filled[1]
        assert saturday.trade_date == date(2026, 2, 14)
        assert saturday.brent_usd_bbl == Decimal("80.00")
        assert "interpolated" in saturday.source

    def test_fill_weekend_fx(self) -> None:
        """Hafta sonu FX boşluğu Cuma değeri ile doldurulmalı."""
        friday_data = FXData(
            trade_date=date(2026, 2, 13),  # Cuma
            usd_try_rate=Decimal("36.25"),
            source="tcmb_evds",
        )
        data_list = [friday_data]
        filled = fill_weekend_gaps_fx(
            data_list,
            date(2026, 2, 13),
            date(2026, 2, 15),
        )

        assert len(filled) == 3
        sunday = filled[2]
        assert sunday.trade_date == date(2026, 2, 15)
        assert sunday.usd_try_rate == Decimal("36.25")
        assert "interpolated" in sunday.source


# ============================================================
# Brent Collector Mock Testleri
# ============================================================


class TestBrentCollectorMock:
    """Brent collector fonksiyonları mock testleri."""

    @pytest.mark.asyncio
    async def test_fetch_brent_daily_success(self) -> None:
        """yfinance başarılı yanıt verdiğinde BrentData döndürmeli."""
        mock_hist = MagicMock()
        mock_hist.empty = False
        mock_hist.iloc.__getitem__ = MagicMock(return_value={
            "Open": 79.50,
            "High": 81.20,
            "Low": 79.10,
            "Close": 80.75,
            "Volume": 150000,
        })

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_hist

        with patch("src.data_collectors.brent_collector.yf.Ticker", return_value=mock_ticker):
            result = await fetch_brent_daily(date(2026, 2, 14))

        assert result is not None
        assert result.source == "yfinance"
        assert result.brent_usd_bbl == Decimal("80.75")

    @pytest.mark.asyncio
    async def test_fetch_brent_daily_empty(self) -> None:
        """yfinance boş döndüğünde ve fallback da başarısız olduğunda None döndürmeli."""
        mock_hist = MagicMock()
        mock_hist.empty = True

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_hist

        with (
            patch("src.data_collectors.brent_collector.yf.Ticker", return_value=mock_ticker),
            patch("src.data_collectors.brent_collector._fetch_via_yahoo_web", return_value=None),
            patch("src.data_collectors.brent_collector.settings") as mock_settings,
        ):
            mock_settings.RETRY_COUNT = 1
            mock_settings.RETRY_BACKOFF = 0.01
            mock_settings.BRENT_FALLBACK_SOURCE = "yahoo_web"
            result = await fetch_brent_daily(date(2026, 2, 14))

        assert result is None


# ============================================================
# FX Collector Mock Testleri
# ============================================================


class TestFxCollectorMock:
    """FX collector fonksiyonları mock testleri."""

    @pytest.mark.asyncio
    async def test_fetch_fx_daily_tcmb_success(self) -> None:
        """TCMB EVDS başarılı yanıt verdiğinde FXData döndürmeli."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [
                {
                    "Tarih": "14-02-2026",
                    "TP_DK_USD_S_YTL": "36.2500",
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("src.data_collectors.fx_collector.httpx.AsyncClient", return_value=mock_client),
            patch("src.data_collectors.fx_collector.settings") as mock_settings,
        ):
            mock_settings.TCMB_EVDS_API_KEY = "test_key"
            mock_settings.RETRY_COUNT = 1
            mock_settings.RETRY_BACKOFF = 0.01

            result = await fetch_usd_try_daily(date(2026, 2, 14))

        assert result is not None
        assert result.source == "tcmb_evds"
        assert result.usd_try_rate == Decimal("36.2500")

    @pytest.mark.asyncio
    async def test_fetch_fx_daily_no_api_key(self) -> None:
        """TCMB API anahtarı yokken fallback'e düşmeli."""
        mock_hist = MagicMock()
        mock_hist.empty = False
        mock_hist.iloc.__getitem__ = MagicMock(return_value={
            "Open": 36.10,
            "High": 36.40,
            "Low": 36.05,
            "Close": 36.25,
        })

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_hist

        with (
            patch("src.data_collectors.fx_collector.yf.Ticker", return_value=mock_ticker),
            patch("src.data_collectors.fx_collector.settings") as mock_settings,
        ):
            mock_settings.TCMB_EVDS_API_KEY = ""
            mock_settings.RETRY_COUNT = 1
            mock_settings.RETRY_BACKOFF = 0.01

            result = await fetch_usd_try_daily(date(2026, 2, 14))

        assert result is not None
        assert result.source == "yfinance_fx"


# ============================================================
# Pydantic Model Testleri
# ============================================================


class TestPydanticModels:
    """Pydantic model doğrulama testleri."""

    def test_brent_data_creation(self) -> None:
        """BrentData modeli doğru oluşturulmalı."""
        data = BrentData(
            trade_date=date(2026, 2, 14),
            brent_usd_bbl=Decimal("80.50"),
            cif_med_estimate_usd_ton=Decimal("619.73"),
            source="yfinance",
            raw_data={"close": 80.50},
        )
        assert data.trade_date == date(2026, 2, 14)
        assert data.brent_usd_bbl == Decimal("80.50")
        assert data.source == "yfinance"
        assert data.raw_data is not None

    def test_fx_data_creation(self) -> None:
        """FXData modeli doğru oluşturulmalı."""
        data = FXData(
            trade_date=date(2026, 2, 14),
            usd_try_rate=Decimal("36.25"),
            source="tcmb_evds",
            raw_data={"Tarih": "14-02-2026", "TP_DK_USD_S_YTL": "36.25"},
        )
        assert data.usd_try_rate == Decimal("36.25")
        assert data.source == "tcmb_evds"

    def test_brent_data_without_raw(self) -> None:
        """BrentData raw_data olmadan oluşturulabilmeli."""
        data = BrentData(
            trade_date=date(2026, 2, 14),
            brent_usd_bbl=Decimal("80.50"),
            cif_med_estimate_usd_ton=Decimal("619.73"),
            source="manual",
        )
        assert data.raw_data is None

    def test_brent_data_json_serialization(self) -> None:
        """BrentData JSON'a serileştirilebilmeli."""
        data = BrentData(
            trade_date=date(2026, 2, 14),
            brent_usd_bbl=Decimal("80.50"),
            cif_med_estimate_usd_ton=Decimal("619.73"),
            source="yfinance",
        )
        json_str = data.model_dump_json()
        assert "80.50" in json_str or "80.5" in json_str
