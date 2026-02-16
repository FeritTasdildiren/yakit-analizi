"""
ML model egitim ve tahmin testleri.

Model egitim pipeline, label olusturma, class weights,
predictor yukle/tahmin ve SHAP aciklanabilirlik testleri.
"""

import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.ml.trainer import (
    CLASS_LABELS,
    CHANGE_THRESHOLD,
    LABEL_TO_INT,
    TrainResult,
    compute_class_weights,
    create_labels,
    get_next_version,
    train_models,
)
from src.ml.feature_engineering import FEATURE_NAMES, TOTAL_FEATURE_COUNT
from src.ml.predictor import MLPredictor, PredictionResult
from src.ml.circuit_breaker import CircuitBreaker, CircuitBreakerConfig


# ────────────────────────────────────────────────────────────────────────────
#  Label Olusturma Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestCreateLabels:
    """Label olusturma fonksiyonu testleri."""

    def test_hike_label(self):
        """Esik ustundeki degisim 'hike' (2) olmali."""
        y_clf, y_reg = create_labels([0.5])
        assert y_clf[0] == 2  # hike

    def test_cut_label(self):
        """Esik altindaki negatif degisim 'cut' (0) olmali."""
        y_clf, y_reg = create_labels([-0.5])
        assert y_clf[0] == 0  # cut

    def test_stable_label(self):
        """Esik icindeki degisim 'stable' (1) olmali."""
        y_clf, y_reg = create_labels([0.1])
        assert y_clf[0] == 1  # stable

    def test_threshold_boundary(self):
        """Tam esik degerinde stable olmali."""
        y_clf, _ = create_labels([CHANGE_THRESHOLD])
        assert y_clf[0] == 1  # stable (not > threshold)

    def test_negative_threshold_boundary(self):
        """Tam negatif esik degerinde stable olmali."""
        y_clf, _ = create_labels([-CHANGE_THRESHOLD])
        assert y_clf[0] == 1  # stable (not < -threshold)

    def test_regression_labels_preserved(self):
        """Regresyon etiketleri orijinal degerler olmali."""
        changes = [0.5, -0.3, 0.1, 0.0]
        _, y_reg = create_labels(changes)
        np.testing.assert_array_almost_equal(y_reg, changes)

    def test_multiple_labels(self):
        """Karisik verilerle dogru label dagilimi."""
        changes = [0.5, -0.5, 0.1, 0.0, 0.3, -0.1]
        y_clf, _ = create_labels(changes)
        assert list(y_clf) == [2, 0, 1, 1, 2, 1]

    def test_class_labels_mapping(self):
        """Sinif etiket eslesmesi dogru olmali."""
        assert CLASS_LABELS[0] == "cut"
        assert CLASS_LABELS[1] == "stable"
        assert CLASS_LABELS[2] == "hike"
        assert LABEL_TO_INT["hike"] == 2


# ────────────────────────────────────────────────────────────────────────────
#  Sinif Agirliklari Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestComputeClassWeights:
    """Sinif agirligi hesaplama testleri."""

    def test_balanced_weights(self):
        """Dengesiz dagilimda agirliklar ayarlanmali."""
        # %88 stable, %8 hike, %4 cut (tipik dagilim)
        y = np.array(
            [1] * 88 + [2] * 8 + [0] * 4,
            dtype=np.int32,
        )
        weights = compute_class_weights(y)

        assert 0 in weights  # cut
        assert 1 in weights  # stable
        assert 2 in weights  # hike

        # Hike agirligi 8-12x arasinda olmali
        assert 8.0 <= weights[2] <= 12.0

        # Cut agirligi 4-6x arasinda olmali
        assert 4.0 <= weights[0] <= 6.0

        # Stable agirligi ~1x olmali
        assert 0.5 <= weights[1] <= 1.5

    def test_equal_distribution(self):
        """Esit dagilimda agirliklar sinirlandirilmali."""
        y = np.array([0, 0, 1, 1, 2, 2], dtype=np.int32)
        weights = compute_class_weights(y)

        # Sinirlamalar uygulanmali
        assert 8.0 <= weights[2] <= 12.0  # hike min 8x
        assert 4.0 <= weights[0] <= 6.0   # cut min 4x


# ────────────────────────────────────────────────────────────────────────────
#  Model Egitim Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestTrainModels:
    """Model egitim pipeline testleri."""

    def _create_synthetic_data(self, n_samples: int = 200):
        """Sentetik egitim verisi olusturur."""
        rng = np.random.default_rng(42)
        n_features = TOTAL_FEATURE_COUNT
        X = rng.standard_normal((n_samples, n_features))

        # Basit sinyal: ilk feature pozitif → hike egilimi
        changes = X[:, 0] * 0.3 + rng.normal(0, 0.1, n_samples)
        y_clf, y_reg = create_labels(changes.tolist())

        return X, y_clf, y_reg

    def test_train_success(self):
        """Yeterli veriyle model basariyla egitilmeli."""
        X, y_clf, y_reg = self._create_synthetic_data(200)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = train_models(
                X, y_clf, y_reg,
                feature_names=FEATURE_NAMES,
                model_dir=Path(tmpdir),
                version=1,
            )

            assert result.status == "success"
            assert result.model_version == "v1"
            assert result.clf_metrics is not None
            assert result.reg_metrics is not None
            assert "accuracy" in result.clf_metrics
            assert "mae" in result.reg_metrics

    def test_train_insufficient_data(self):
        """Yetersiz veriyle egitim basarisiz olmali."""
        rng = np.random.default_rng(42)
        X = rng.standard_normal((10, TOTAL_FEATURE_COUNT))
        y_clf = np.array([1] * 10, dtype=np.int32)
        y_reg = np.zeros(10)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = train_models(
                X, y_clf, y_reg,
                model_dir=Path(tmpdir),
            )
            assert result.status == "failed"
            assert "Yetersiz veri" in result.message

    def test_model_files_saved(self):
        """Egitim sonrasi model dosyalari kaydedilmeli."""
        X, y_clf, y_reg = self._create_synthetic_data(200)

        with tempfile.TemporaryDirectory() as tmpdir:
            model_dir = Path(tmpdir)
            result = train_models(
                X, y_clf, y_reg,
                feature_names=FEATURE_NAMES,
                model_dir=model_dir,
                version=1,
            )

            assert result.status == "success"
            clf_path = model_dir / "ml_classifier_v1.joblib"
            reg_path = model_dir / "ml_regressor_v1.joblib"
            assert clf_path.exists()
            assert reg_path.exists()

    def test_prediction_shape(self):
        """Tahmin ciktisi dogru shape'de olmali."""
        X, y_clf, y_reg = self._create_synthetic_data(200)

        with tempfile.TemporaryDirectory() as tmpdir:
            model_dir = Path(tmpdir)
            train_models(
                X, y_clf, y_reg,
                feature_names=FEATURE_NAMES,
                model_dir=model_dir,
                version=1,
            )

            predictor = MLPredictor(
                model_dir=model_dir,
                circuit_breaker=CircuitBreaker(
                    CircuitBreakerConfig(failure_threshold=0.5)
                ),
            )
            loaded = predictor.load_model("v1")
            assert loaded is True

            # Tahmin yap
            features = {name: 0.0 for name in FEATURE_NAMES}
            result = predictor.predict(features)

            assert isinstance(result, PredictionResult)
            assert result.predicted_direction in ("hike", "stable", "cut")

    def test_probability_range(self):
        """Olasiliklar 0-1 arasinda olmali."""
        X, y_clf, y_reg = self._create_synthetic_data(200)

        with tempfile.TemporaryDirectory() as tmpdir:
            model_dir = Path(tmpdir)
            train_models(
                X, y_clf, y_reg,
                feature_names=FEATURE_NAMES,
                model_dir=model_dir,
                version=1,
            )

            predictor = MLPredictor(
                model_dir=model_dir,
                circuit_breaker=CircuitBreaker(
                    CircuitBreakerConfig(failure_threshold=0.5)
                ),
            )
            predictor.load_model("v1")

            features = {name: float(i) * 0.1 for i, name in enumerate(FEATURE_NAMES)}
            result = predictor.predict(features)

            assert 0 <= float(result.probability_hike) <= 1
            assert 0 <= float(result.probability_stable) <= 1
            assert 0 <= float(result.probability_cut) <= 1

            # Olasiliklar toplami ~1 olmali
            total = (
                float(result.probability_hike)
                + float(result.probability_stable)
                + float(result.probability_cut)
            )
            assert total == pytest.approx(1.0, abs=0.01)


# ────────────────────────────────────────────────────────────────────────────
#  Model Versiyon Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestModelVersioning:
    """Model versiyon yonetimi testleri."""

    def test_get_next_version_empty_dir(self):
        """Bos dizinde ilk versiyon 1 olmali."""
        with tempfile.TemporaryDirectory() as tmpdir:
            version = get_next_version(Path(tmpdir))
            assert version == 1

    def test_get_next_version_nonexistent_dir(self):
        """Var olmayan dizinde versiyon 1 olmali."""
        version = get_next_version(Path("/tmp/nonexistent_model_dir_xyz"))
        assert version == 1


# ────────────────────────────────────────────────────────────────────────────
#  Predictor Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestMLPredictor:
    """ML Predictor testleri."""

    def test_predictor_not_loaded(self):
        """Model yuklu degilken is_loaded False olmali."""
        predictor = MLPredictor(
            model_dir=Path("/tmp/nonexistent"),
            circuit_breaker=CircuitBreaker(),
        )
        assert predictor.is_loaded is False

    def test_predict_without_load_raises(self):
        """Model yuklenmeden tahmin hatasi vermeli."""
        predictor = MLPredictor(
            model_dir=Path("/tmp/nonexistent"),
            circuit_breaker=CircuitBreaker(),
        )
        with pytest.raises(RuntimeError, match="Model yuklu degil"):
            predictor.predict({"mbe_value": 0.5})

    def test_predict_with_fallback(self):
        """Fallback modunda degrade yanit donmeli."""
        predictor = MLPredictor(
            model_dir=Path("/tmp/nonexistent"),
            circuit_breaker=CircuitBreaker(),
        )
        result = predictor.predict_with_fallback({"mbe_value": 0.5})

        assert result.system_mode == "safe"
        assert result.predicted_direction == "stable"
        assert result.confidence == "partial"

    def test_load_nonexistent_model(self):
        """Var olmayan model dosyasi yuklenemez."""
        predictor = MLPredictor(
            model_dir=Path("/tmp/nonexistent"),
            circuit_breaker=CircuitBreaker(),
        )
        loaded = predictor.load_model("v999")
        assert loaded is False

    def test_circuit_breaker_blocks_prediction(self):
        """Circuit breaker OPEN iken tahmin engellenmeli."""
        config = CircuitBreakerConfig(
            failure_threshold=0.10,
            window_size=10,
        )
        cb = CircuitBreaker(config)

        # Trip the breaker
        for _ in range(8):
            cb.record_success()
        cb.record_failure()
        cb.record_failure()

        predictor = MLPredictor(
            model_dir=Path("/tmp/nonexistent"),
            circuit_breaker=cb,
        )

        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            predictor.predict({"mbe_value": 0.5})
