"""
Pytest konfigürasyonu ve ortak fixture'lar.

Test ortamı için async session, mock'lar ve ortak veriler burada tanımlanır.
"""

import pytest


@pytest.fixture
def sample_brent_price():
    """Örnek Brent fiyat verisi."""
    from decimal import Decimal
    from datetime import date
    from src.data_collectors.brent_collector import BrentData

    return BrentData(
        trade_date=date(2026, 2, 14),
        brent_usd_bbl=Decimal("80.50"),
        cif_med_estimate_usd_ton=Decimal("619.73"),
        source="yfinance",
        raw_data={"close": 80.50, "volume": 150000},
    )


@pytest.fixture
def sample_fx_rate():
    """Örnek USD/TRY kuru verisi."""
    from decimal import Decimal
    from datetime import date
    from src.data_collectors.fx_collector import FXData

    return FXData(
        trade_date=date(2026, 2, 14),
        usd_try_rate=Decimal("36.25"),
        source="tcmb_evds",
        raw_data={"Tarih": "14-02-2026", "TP_DK_USD_S_YTL": "36.25"},
    )
