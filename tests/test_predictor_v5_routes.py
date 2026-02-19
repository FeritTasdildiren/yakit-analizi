"""
Predictor v5 API endpoint testleri.

5 endpoint icin response format, hata yonetimi ve gecersiz parametre testleri.
TestClient kullanarak FastAPI endpoint\x27leri test edilir.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import date, timedelta
from decimal import Decimal
from fastapi.testclient import TestClient


def _make_client():
    """TestClient olustur."""
    from src.main import app
    return TestClient(app)


# ────────────────────────────────────────────────────────────────────────────
#  1) GET /latest/{fuel_type}
# ────────────────────────────────────────────────────────────────────────────


class TestLatestPrediction:
    """Son tahmin endpoint testleri."""

    def test_latest_invalid_fuel_type_returns_422(self):
        """Gecersiz yakit tipi 422 donmeli."""
        client = _make_client()
        response = client.get("/api/v1/predictions/v5/latest/kerosen")
        assert response.status_code == 422
        data = response.json()
        assert "Gecersiz yakit tipi" in data["detail"]

    def test_latest_not_found_returns_404(self):
        """Tahmin bulunamazsa 404 donmeli."""
        client = _make_client()
        with patch(
            "src.api.predictor_v5_routes.get_db",
        ):
            # get_latest_prediction_async None doner
            with patch(
                "src.predictor_v5.repository.get_latest_prediction_async",
                new_callable=AsyncMock,
                return_value=None,
            ):
                response = client.get("/api/v1/predictions/v5/latest/benzin")
                assert response.status_code == 404
                data = response.json()
                assert "bulunamadi" in data["detail"]

    def test_latest_success_returns_200(self):
        """Tahmin varsa 200 donmeli, response format dogrulmali."""
        mock_prediction = MagicMock()
        mock_prediction.id = 1
        mock_prediction.run_date = date(2026, 2, 17)
        mock_prediction.fuel_type = "motorin"
        mock_prediction.stage1_probability = Decimal("0.7500")
        mock_prediction.stage1_label = True
        mock_prediction.first_event_direction = 1
        mock_prediction.first_event_amount = Decimal("0.5000")
        mock_prediction.first_event_type = "hike"
        mock_prediction.net_amount_3d = Decimal("0.3000")
        mock_prediction.model_version = "v5.0"
        mock_prediction.calibration_method = "platt"
        mock_prediction.alarm_triggered = False
        mock_prediction.alarm_suppressed = False
        mock_prediction.suppression_reason = None
        mock_prediction.alarm_message = None

        client = _make_client()
        with patch(
            "src.predictor_v5.repository.get_latest_prediction_async",
            new_callable=AsyncMock,
            return_value=mock_prediction,
        ):
            response = client.get("/api/v1/predictions/v5/latest/motorin")
            assert response.status_code == 200
            data = response.json()
            assert data["fuel_type"] == "motorin"
            assert data["run_date"] == "2026-02-17"
            assert data["stage1_probability"] == 0.75
            assert data["model_version"] == "v5.0"


# ────────────────────────────────────────────────────────────────────────────
#  2) GET /history/{fuel_type}?days=30
# ────────────────────────────────────────────────────────────────────────────


class TestPredictionHistory:
    """Tahmin tarihcesi endpoint testleri."""

    def test_history_invalid_fuel_type_returns_422(self):
        """Gecersiz yakit tipi 422 donmeli."""
        client = _make_client()
        response = client.get("/api/v1/predictions/v5/history/fuel_oil")
        assert response.status_code == 422

    def test_history_empty_returns_200(self):
        """Bos tarihce 200 + count=0 donmeli."""
        client = _make_client()
        with patch(
            "src.predictor_v5.repository.get_predictions_async",
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = client.get("/api/v1/predictions/v5/history/benzin?days=7")
            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 0
            assert data["predictions"] == []
            assert data["fuel_type"] == "benzin"
            assert data["days"] == 7

    def test_history_days_validation(self):
        """days < 1 veya > 365 ise 422 donmeli."""
        client = _make_client()
        response = client.get("/api/v1/predictions/v5/history/motorin?days=0")
        assert response.status_code == 422

        response2 = client.get("/api/v1/predictions/v5/history/motorin?days=999")
        assert response2.status_code == 422


# ────────────────────────────────────────────────────────────────────────────
#  3) GET /features/{fuel_type}/{run_date}
# ────────────────────────────────────────────────────────────────────────────


class TestFeatureSnapshot:
    """Feature snapshot endpoint testleri."""

    def test_features_invalid_fuel_returns_422(self):
        """Gecersiz yakit tipi 422 donmeli."""
        client = _make_client()
        response = client.get("/api/v1/predictions/v5/features/kerosin/2026-02-17")
        assert response.status_code == 422

    def test_features_not_found_returns_404(self):
        """Snapshot bulunamazsa 404 donmeli."""
        client = _make_client()
        with patch(
            "src.predictor_v5.feature_store.load_snapshot",
            return_value=None,
        ):
            response = client.get("/api/v1/predictions/v5/features/benzin/2026-02-17")
            assert response.status_code == 404
            data = response.json()
            assert "bulunamadi" in data["detail"]

    def test_features_success_returns_200(self):
        """Snapshot varsa 200 + features dict donmeli."""
        mock_snapshot = {
            "id": 1,
            "run_date": date(2026, 2, 17),
            "fuel_type": "benzin",
            "features": {"brent_close": 68.5, "fx_close": 43.7, "mbe_value": 1.2},
            "feature_version": "v5.0",
            "created_at": None,
        }

        client = _make_client()
        with patch(
            "src.predictor_v5.feature_store.load_snapshot",
            return_value=mock_snapshot,
        ):
            response = client.get("/api/v1/predictions/v5/features/benzin/2026-02-17")
            assert response.status_code == 200
            data = response.json()
            assert data["fuel_type"] == "benzin"
            assert "brent_close" in data["features"]
            assert data["feature_version"] == "v5.0"


# ────────────────────────────────────────────────────────────────────────────
#  4) POST /run — Placeholder
# ────────────────────────────────────────────────────────────────────────────


class TestRunPrediction:
    """Manuel calistirma endpoint testleri."""

    def test_run_returns_200_placeholder(self):
        """Placeholder endpoint 200 + not_implemented donmeli."""
        client = _make_client()
        response = client.post("/api/v1/predictions/v5/run")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_implemented"
        assert "henuz aktif degil" in data["message"]


# ────────────────────────────────────────────────────────────────────────────
#  5) GET /backtest/summary — Placeholder
# ────────────────────────────────────────────────────────────────────────────


class TestBacktestSummary:
    """Backtest ozet endpoint testleri."""

    def test_backtest_summary_returns_200_placeholder(self):
        """Placeholder endpoint 200 + not_implemented donmeli."""
        client = _make_client()
        response = client.get("/api/v1/predictions/v5/backtest/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_implemented"
        assert "henuz aktif degil" in data["message"]
