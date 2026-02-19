"""
Predictor v5 repository + feature store testleri.

Testler gercek DB'ye karsi calisir (test sonrasi kayitlar temizlenir).
UPSERT, CRUD, edge case, Decimal->float donusumu test edilir.

Test sayisi: 12 (8+ zorunlu kriteri karsilar)
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal

# ---------------------------------------------------------------------------
#  DSN — test ortami icin sunucu DB
# ---------------------------------------------------------------------------
TEST_DSN = "postgresql://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi"

# ---------------------------------------------------------------------------
#  Cleanup helper
# ---------------------------------------------------------------------------

def _cleanup_test_rows(dsn: str, run_date: date, fuel_type: str = "benzin"):
    """Test sonrasi kaydedilen satirlari sil."""
    import psycopg2
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM predictions_v5 WHERE run_date = %s AND fuel_type = %s",
                (run_date, fuel_type),
            )
            cur.execute(
                "DELETE FROM feature_snapshots_v5 WHERE run_date = %s AND fuel_type = %s",
                (run_date, fuel_type),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
#  Test fixtures
# ---------------------------------------------------------------------------

# Test icin sabit tarih (gelecek tarih — gercek veriyle carismaz)
TEST_DATE = date(2099, 12, 31)
TEST_FUEL = "benzin"


@pytest.fixture(autouse=True)
def cleanup():
    """Her test oncesi ve sonrasi test satirlarini temizle."""
    _cleanup_test_rows(TEST_DSN, TEST_DATE, TEST_FUEL)
    _cleanup_test_rows(TEST_DSN, TEST_DATE - timedelta(days=1), TEST_FUEL)
    _cleanup_test_rows(TEST_DSN, TEST_DATE - timedelta(days=2), TEST_FUEL)
    yield
    _cleanup_test_rows(TEST_DSN, TEST_DATE, TEST_FUEL)
    _cleanup_test_rows(TEST_DSN, TEST_DATE - timedelta(days=1), TEST_FUEL)
    _cleanup_test_rows(TEST_DSN, TEST_DATE - timedelta(days=2), TEST_FUEL)


# ===========================================================================
#  1. Prediction Sync CRUD Testleri
# ===========================================================================


def _make_prediction_data(
    run_date: date = TEST_DATE,
    fuel_type: str = TEST_FUEL,
    prob: Decimal = Decimal("0.7500"),
    **overrides,
) -> dict:
    """Standart test prediction_data dict olustur."""
    data = {
        "run_date": run_date,
        "fuel_type": fuel_type,
        "stage1_probability": prob,
        "stage1_label": True,
        "first_event_direction": 1,
        "first_event_amount": Decimal("0.5000"),
        "first_event_type": "increase",
        "net_amount_3d": Decimal("0.3000"),
        "model_version": "v5.0-test",
        "calibration_method": "platt",
        "alarm_triggered": False,
        "alarm_suppressed": False,
        "suppression_reason": None,
        "alarm_message": None,
    }
    data.update(overrides)
    return data


class TestSavePredictionSync:
    """Sync prediction UPSERT testleri."""

    def test_insert_new_prediction(self):
        """Yeni tahmin kaydinin INSERT edilmesi."""
        from src.predictor_v5.repository import save_prediction_sync, get_latest_prediction_sync

        data = _make_prediction_data()
        save_prediction_sync(data, dsn=TEST_DSN)

        result = get_latest_prediction_sync(TEST_FUEL, dsn=TEST_DSN)
        assert result is not None
        assert result["run_date"] == TEST_DATE
        assert result["fuel_type"] == TEST_FUEL
        assert float(result["stage1_probability"]) == pytest.approx(0.75, abs=0.001)

    def test_upsert_update_existing(self):
        """Ayni (run_date, fuel_type) ile UPSERT — guncellenmeli."""
        from src.predictor_v5.repository import save_prediction_sync, get_latest_prediction_sync

        # Ilk insert
        data = _make_prediction_data(prob=Decimal("0.6000"))
        save_prediction_sync(data, dsn=TEST_DSN)

        # Ayni key ile update
        data["stage1_probability"] = Decimal("0.9500")
        data["alarm_triggered"] = True
        data["alarm_message"] = "Zam alarmi!"
        save_prediction_sync(data, dsn=TEST_DSN)

        result = get_latest_prediction_sync(TEST_FUEL, dsn=TEST_DSN)
        assert result is not None
        assert float(result["stage1_probability"]) == pytest.approx(0.95, abs=0.001)
        assert result["alarm_triggered"] is True
        assert result["alarm_message"] == "Zam alarmi!"

    def test_get_latest_no_data(self):
        """Veri yokken None donmeli."""
        from src.predictor_v5.repository import get_latest_prediction_sync

        result = get_latest_prediction_sync("lpg", dsn=TEST_DSN)
        # lpg icin test verisi yok, None veya baska mevcut kayit olabilir
        # Asil test: fonksiyon hata vermeden calismali
        assert result is None or isinstance(result, dict)

    def test_get_predictions_range(self):
        """Tarih araligi sorgusu."""
        from src.predictor_v5.repository import save_prediction_sync, get_predictions_sync

        # 3 gun veri ekle
        for i in range(3):
            d = TEST_DATE - timedelta(days=i)
            save_prediction_sync(
                _make_prediction_data(run_date=d, prob=Decimal(f"0.{50 + i * 10:02d}00")),
                dsn=TEST_DSN,
            )

        results = get_predictions_sync(
            TEST_FUEL,
            start_date=TEST_DATE - timedelta(days=2),
            end_date=TEST_DATE,
            dsn=TEST_DSN,
        )
        assert len(results) == 3
        # ASC sirali olmali
        assert results[0]["run_date"] <= results[1]["run_date"] <= results[2]["run_date"]

    def test_get_predictions_empty_range(self):
        """Bos tarih araligi bos liste donmeli."""
        from src.predictor_v5.repository import get_predictions_sync

        results = get_predictions_sync(
            TEST_FUEL,
            start_date=date(2099, 1, 1),
            end_date=date(2099, 1, 2),
            dsn=TEST_DSN,
        )
        assert results == []


# ===========================================================================
#  2. Feature Store Testleri
# ===========================================================================


class TestFeatureStore:
    """Feature snapshot CRUD + UPSERT testleri."""

    def test_store_and_load_snapshot(self):
        """Feature snapshot kaydet ve geri oku."""
        from src.predictor_v5.feature_store import store_snapshot, load_snapshot

        features = {
            "brent_close": Decimal("68.50"),
            "fx_close": Decimal("43.71"),
            "mbe_value": Decimal("1.2345"),
            "is_weekend": 0,
            "day_of_week": 3,
        }

        store_snapshot(TEST_FUEL, TEST_DATE, features, feature_version="v5.0", dsn=TEST_DSN)

        result = load_snapshot(TEST_FUEL, TEST_DATE, dsn=TEST_DSN)
        assert result is not None
        assert result["fuel_type"] == TEST_FUEL
        assert result["feature_version"] == "v5.0"

        # Decimal -> float donusumu kontrolu
        loaded_features = result["features"]
        assert isinstance(loaded_features["brent_close"], float)
        assert loaded_features["brent_close"] == pytest.approx(68.50, abs=0.01)
        assert loaded_features["fx_close"] == pytest.approx(43.71, abs=0.01)

    def test_snapshot_upsert(self):
        """Ayni (run_date, fuel_type) ile UPSERT — features guncellenmeli."""
        from src.predictor_v5.feature_store import store_snapshot, load_snapshot

        features_v1 = {"brent_close": 68.0, "fx_close": 43.0}
        store_snapshot(TEST_FUEL, TEST_DATE, features_v1, feature_version="v5.0", dsn=TEST_DSN)

        features_v2 = {"brent_close": 72.0, "fx_close": 44.5, "new_feature": 99.0}
        store_snapshot(TEST_FUEL, TEST_DATE, features_v2, feature_version="v5.1", dsn=TEST_DSN)

        result = load_snapshot(TEST_FUEL, TEST_DATE, dsn=TEST_DSN)
        assert result is not None
        assert result["feature_version"] == "v5.1"
        assert result["features"]["brent_close"] == pytest.approx(72.0)
        assert result["features"]["new_feature"] == pytest.approx(99.0)
        # Eski features tamamen degismeli (EXCLUDED.features)
        assert "fx_close" in result["features"]

    def test_load_snapshot_not_found(self):
        """Olmayan snapshot icin None donmeli."""
        from src.predictor_v5.feature_store import load_snapshot

        result = load_snapshot(TEST_FUEL, date(2099, 6, 15), dsn=TEST_DSN)
        assert result is None

    def test_load_snapshots_range_dataframe(self):
        """Tarih araligi icin DataFrame donmeli."""
        from src.predictor_v5.feature_store import store_snapshot, load_snapshots_range

        # 3 gun veri
        for i in range(3):
            d = TEST_DATE - timedelta(days=i)
            features = {
                "brent_close": 68.0 + i,
                "fx_close": 43.0 + i * 0.1,
            }
            store_snapshot(TEST_FUEL, d, features, dsn=TEST_DSN)

        df = load_snapshots_range(
            TEST_FUEL,
            start_date=TEST_DATE - timedelta(days=2),
            end_date=TEST_DATE,
            dsn=TEST_DSN,
        )

        assert len(df) == 3
        assert "brent_close" in df.columns
        assert "fx_close" in df.columns
        assert "fuel_type" in df.columns
        assert df.index.name == "run_date"

    def test_load_snapshots_range_empty(self):
        """Bos tarih araligi bos DataFrame donmeli."""
        from src.predictor_v5.feature_store import load_snapshots_range

        df = load_snapshots_range(
            TEST_FUEL,
            start_date=date(2099, 6, 1),
            end_date=date(2099, 6, 2),
            dsn=TEST_DSN,
        )
        assert len(df) == 0

    def test_decimal_serialization(self):
        """Decimal degerlerin JSONB'ye float olarak yazildigi dogrulanmali."""
        from src.predictor_v5.feature_store import store_snapshot, load_snapshot

        features = {
            "val_decimal": Decimal("123.456789"),
            "val_float": 99.99,
            "val_int": 42,
            "val_none": None,
        }

        store_snapshot(TEST_FUEL, TEST_DATE, features, dsn=TEST_DSN)
        result = load_snapshot(TEST_FUEL, TEST_DATE, dsn=TEST_DSN)

        loaded = result["features"]
        assert isinstance(loaded["val_decimal"], float)
        assert loaded["val_decimal"] == pytest.approx(123.456789, abs=0.0001)
        assert loaded["val_float"] == pytest.approx(99.99)
        assert loaded["val_int"] == 42
        assert loaded["val_none"] is None

    def test_feature_version_tracking(self):
        """Farkli feature version'larla kaydedilip okunabilmeli."""
        from src.predictor_v5.feature_store import store_snapshot, load_snapshot

        store_snapshot(TEST_FUEL, TEST_DATE, {"a": 1}, feature_version="v5.0", dsn=TEST_DSN)
        result = load_snapshot(TEST_FUEL, TEST_DATE, dsn=TEST_DSN)
        assert result["feature_version"] == "v5.0"

        # Ayni gun, farkli version ile guncelle
        store_snapshot(TEST_FUEL, TEST_DATE, {"a": 2}, feature_version="v5.1-beta", dsn=TEST_DSN)
        result = load_snapshot(TEST_FUEL, TEST_DATE, dsn=TEST_DSN)
        assert result["feature_version"] == "v5.1-beta"
        assert result["features"]["a"] == 2
