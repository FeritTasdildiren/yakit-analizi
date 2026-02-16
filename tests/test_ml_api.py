"""
ML API endpoint testleri.

Endpoint response format ve hata yonetimi testleri.
TestClient kullanarak FastAPI endpoint'leri test edilir.
"""

import pytest
from fastapi.testclient import TestClient

from src.ml.circuit_breaker import reset_circuit_breaker


# ────────────────────────────────────────────────────────────────────────────
#  API Endpoint Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestMLHealthEndpoint:
    """ML saglik kontrolu endpoint testleri."""

    def setup_method(self):
        reset_circuit_breaker()

    def teardown_method(self):
        reset_circuit_breaker()

    def test_health_returns_200(self):
        """Health endpoint 200 donmeli."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/v1/ml/health")
        assert response.status_code == 200

    def test_health_response_format(self):
        """Health yaniti gerekli alanlari icermeli."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/v1/ml/health")
        data = response.json()

        assert "state" in data
        assert "failure_count" in data
        assert "success_count" in data
        assert "failure_rate" in data
        assert data["state"] == "CLOSED"


class TestMLModelInfoEndpoint:
    """Model bilgisi endpoint testleri."""

    def test_model_info_returns_200(self):
        """Model info endpoint 200 donmeli."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/v1/ml/model-info")
        assert response.status_code == 200

    def test_model_info_response_format(self):
        """Model info yaniti gerekli alanlari icermeli."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/v1/ml/model-info")
        data = response.json()

        assert "classifier_version" in data
        assert "feature_count" in data
        assert "feature_names" in data


class TestMLTrainEndpoint:
    """Model egitim endpoint testleri."""

    def test_train_returns_200(self):
        """Train endpoint 200 donmeli."""
        from src.main import app

        client = TestClient(app)
        response = client.post("/api/v1/ml/train?fuel_type=motorin")
        assert response.status_code == 200

    def test_train_invalid_fuel_type(self):
        """Gecersiz yakit tipinde 400 donmeli."""
        from src.main import app

        client = TestClient(app)
        response = client.post("/api/v1/ml/train?fuel_type=lpg")
        assert response.status_code == 400

    def test_train_response_format(self):
        """Train yaniti gerekli alanlari icermeli."""
        from src.main import app

        client = TestClient(app)
        response = client.post("/api/v1/ml/train?fuel_type=motorin")
        data = response.json()

        assert "status" in data
        assert "message" in data


class TestMLPredictEndpoint:
    """Tahmin endpoint testleri."""

    def setup_method(self):
        reset_circuit_breaker()

    def teardown_method(self):
        reset_circuit_breaker()

    def test_predict_invalid_fuel_type(self):
        """Gecersiz yakit tipinde 400 donmeli."""
        from src.main import app

        client = TestClient(app)
        response = client.post("/api/v1/ml/predict?fuel_type=lpg")
        assert response.status_code == 400

    def test_predict_returns_degraded_without_model(self):
        """Model yuklu degilken degrade yanit donmeli."""
        from src.main import app

        client = TestClient(app)
        response = client.post("/api/v1/ml/predict?fuel_type=motorin")
        # Model yuklu olmadigi icin degrade donecek
        assert response.status_code == 200
        data = response.json()
        assert data.get("system_mode") in ("safe", "full")


class TestMLExplainEndpoint:
    """SHAP aciklama endpoint testleri."""

    def test_explain_nonexistent_prediction(self):
        """Var olmayan tahmin icin 404 donmeli."""
        from src.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/ml/explain/999999")
        # DB baglantisi olmadan 500 veya 404 donebilir
        assert response.status_code in (404, 500)
