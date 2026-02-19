"""
ML Model Yukleme ve Tahmin Servisi (Katman 4).

Egitilmis LightGBM modellerini yukler ve tahmin yapar.
Circuit breaker entegrasyonu ile graceful degradation destegi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import joblib
import numpy as np

from src.ml.circuit_breaker import CircuitBreaker, get_circuit_breaker
from src.ml.feature_engineering import FEATURE_NAMES, features_dict_to_array
from src.ml.trainer import CLASS_LABELS, DEFAULT_MODEL_DIR

logger = logging.getLogger(__name__)


@dataclass
class PredictionResult:
    """ML tahmin sonucu."""

    predicted_direction: str  # hike, stable, cut
    probability_hike: Decimal
    probability_stable: Decimal
    probability_cut: Decimal
    expected_change_tl: Decimal | None = None
    model_version: str = ""
    system_mode: str = "full"
    shap_top_features: list[dict] | None = None
    confidence: str = "high"


@dataclass
class ModelPair:
    """Yuklu siniflandirma + regresyon model cifti."""

    classifier: object = None
    regressor: object = None
    feature_names: list[str] = field(default_factory=list)
    version: str = ""


class MLPredictor:
    """
    ML tahmin servisi.

    Modelleri yukler, feature vektorunu alir ve tahmin uretir.
    Circuit breaker entegrasyonu ile hata durumunda degrade moduna gecer.
    """

    def __init__(
        self,
        model_dir: Path | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._model_dir = model_dir or DEFAULT_MODEL_DIR
        self._circuit_breaker = circuit_breaker or get_circuit_breaker()
        self._model_pair: ModelPair | None = None

    @property
    def is_loaded(self) -> bool:
        """Modelin yuklu olup olmadigini dondurur."""
        return (
            self._model_pair is not None
            and self._model_pair.classifier is not None
            and self._model_pair.regressor is not None
        )

    @property
    def model_version(self) -> str | None:
        """Yuklu model versiyonu."""
        return self._model_pair.version if self._model_pair else None

    @property
    def feature_names(self) -> list[str]:
        """Yuklu modelin feature isimleri."""
        if self._model_pair and self._model_pair.feature_names:
            return self._model_pair.feature_names
        return FEATURE_NAMES

    def load_model(self, version: str | None = None) -> bool:
        """
        Model dosyalarini yukler.

        Args:
            version: Yuklenecek model versiyonu (orn: "v1").
                     None ise en son versiyonu bulur.

        Returns:
            True: Basarili. False: Basarisiz.
        """
        try:
            if version is None:
                version = self._find_latest_version()

            if version is None:
                logger.warning("Hicbir model dosyasi bulunamadi: %s", self._model_dir)
                return False

            clf_path = self._model_dir / f"ml_classifier_{version}.joblib"
            reg_path = self._model_dir / f"ml_regressor_{version}.joblib"

            if not clf_path.exists() or not reg_path.exists():
                logger.warning(
                    "Model dosyalari bulunamadi: %s veya %s", clf_path, reg_path
                )
                return False

            clf_payload = joblib.load(clf_path)
            reg_payload = joblib.load(reg_path)

            self._model_pair = ModelPair(
                classifier=clf_payload["model"],
                regressor=reg_payload["model"],
                feature_names=clf_payload.get("feature_names", FEATURE_NAMES),
                version=clf_payload.get("version", version),
            )

            logger.info("Model yuklendi: %s", version)
            return True

        except Exception as exc:
            logger.exception("Model yukleme hatasi: %s", exc)
            return False

    def predict(self, features: dict[str, float]) -> PredictionResult:
        """
        Feature dict'inden tahmin uretir.

        Circuit breaker kontrolu yapar. Model yuklu degilse veya
        circuit breaker OPEN ise hata firlatir.

        Args:
            features: Feature adi -> deger eslesmesi.

        Returns:
            PredictionResult nesnesi.

        Raises:
            RuntimeError: Model yuklu degilse veya circuit breaker OPEN ise.
        """
        # Circuit breaker kontrolu
        if not self._circuit_breaker.can_execute():
            raise RuntimeError(
                "Circuit breaker OPEN — ML tahminleri gecici olarak durduruldu"
            )

        if not self.is_loaded:
            raise RuntimeError("Model yuklu degil — once load_model() cagirilmali")

        try:
            # Feature vektor olustur — model'in feature_names listesini kullan
            model_features = self._model_pair.feature_names or FEATURE_NAMES
            feature_vector = [features.get(name, 0.0) for name in model_features]
            X = np.array([feature_vector], dtype=np.float64)

            # Siniflandirma
            clf = self._model_pair.classifier
            probabilities = clf.predict_proba(X)[0]  # shape: (3,)

            prob_cut = Decimal(str(round(float(probabilities[0]), 4)))
            prob_stable = Decimal(str(round(float(probabilities[1]), 4)))
            prob_hike = Decimal(str(round(float(probabilities[2]), 4)))

            # En yuksek olasilikli sinif
            predicted_class = int(np.argmax(probabilities))
            predicted_direction = CLASS_LABELS[predicted_class]

            # Regresyon
            reg = self._model_pair.regressor
            expected_change = float(reg.predict(X)[0])
            expected_change_tl = Decimal(str(round(expected_change, 4)))

            # Guven seviyesi
            max_prob = max(float(prob_hike), float(prob_stable), float(prob_cut))
            if max_prob >= 0.7:
                confidence = "high"
            elif max_prob >= 0.5:
                confidence = "medium"
            else:
                confidence = "low"

            # Basari kaydet
            self._circuit_breaker.record_success()

            return PredictionResult(
                predicted_direction=predicted_direction,
                probability_hike=prob_hike,
                probability_stable=prob_stable,
                probability_cut=prob_cut,
                expected_change_tl=expected_change_tl,
                model_version=self._model_pair.version,
                system_mode="full",
                confidence=confidence,
            )

        except Exception as exc:
            # Hata kaydet
            self._circuit_breaker.record_failure()
            logger.exception("ML tahmin hatasi: %s", exc)
            raise RuntimeError(f"ML tahmin hatasi: {exc}") from exc

    def predict_with_fallback(
        self,
        features: dict[str, float],
        risk_score: Decimal | None = None,
    ) -> PredictionResult:
        """
        Tahmin yap, hata durumunda degrade moduna gec.

        Circuit breaker OPEN ise veya tahmin basarisiz olursa,
        Katman 3 risk skorunu kullanarak degrade yanit uretir.

        Args:
            features: Feature dict.
            risk_score: Katman 3 risk skoru (fallback icin).

        Returns:
            PredictionResult — normal veya degrade modda.
        """
        try:
            return self.predict(features)
        except RuntimeError:
            # Degrade moda gec
            return PredictionResult(
                predicted_direction="stable",
                probability_hike=Decimal("0"),
                probability_stable=Decimal("1"),
                probability_cut=Decimal("0"),
                expected_change_tl=None,
                model_version="degraded",
                system_mode="safe",
                confidence="partial",
            )

    def _find_latest_version(self) -> str | None:
        """Model dizinindeki en son versiyonu bulur."""
        if not self._model_dir.exists():
            return None

        versions = []
        for f in self._model_dir.glob("ml_classifier_v*.joblib"):
            try:
                v = int(f.stem.split("_v")[-1])
                versions.append(v)
            except (ValueError, IndexError):
                continue

        if not versions:
            return None

        return f"v{max(versions)}"


# --- Singleton Instance ---
_default_predictor: MLPredictor | None = None


def get_predictor() -> MLPredictor:
    """Varsayilan MLPredictor instance'ini dondurur."""
    global _default_predictor
    if _default_predictor is None:
        _default_predictor = MLPredictor()
    return _default_predictor
