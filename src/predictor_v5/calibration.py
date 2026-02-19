"""
Predictor v5 — Calibration Module
===================================
Stage-1 binary classifier olasılık çıktılarını kalibre eder.

Yöntemler:
  1. Platt Scaling (birincil) — LogisticRegression sigmoid fit
  2. Beta Calibration (yedek) — a,b,c parametreleriyle beta dönüşüm
  3. Isotonic Regression (son çare) — non-parametrik monoton fit

Hedef: ECE < 0.05

Kullanım:
    from src.predictor_v5.calibration import auto_calibrate, apply_calibration
    calibrator, metrics = auto_calibrate(y_prob_train, y_true_train, y_prob_val, y_true_val)
    calibrated_probs = apply_calibration(calibrator, raw_probs)
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import joblib
import numpy as np
from scipy.optimize import minimize
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from src.predictor_v5.config import FUEL_TYPES, MODEL_DIR

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_MODEL_PATH = _PROJECT_ROOT / MODEL_DIR

ECE_THRESHOLD = 0.05
MIN_CALIBRATION_SAMPLES = 30


class PlattCalibrator:
    """Platt Scaling — Logistic Regression ile sigmoid kalibrasyon."""

    def __init__(self):
        self.lr: Optional[LogisticRegression] = None
        self.method: str = "platt"
        self._single_class_value: Optional[float] = None

    def fit(self, y_prob: np.ndarray, y_true: np.ndarray) -> "PlattCalibrator":
        y_prob = np.asarray(y_prob, dtype=np.float64).ravel()
        y_true = np.asarray(y_true, dtype=np.int32).ravel()

        if len(y_prob) < MIN_CALIBRATION_SAMPLES:
            logger.warning(
                "Platt: Yetersiz ornek (%d < %d). Yine de fit ediliyor.",
                len(y_prob), MIN_CALIBRATION_SAMPLES,
            )

        unique_classes = np.unique(y_true)
        if len(unique_classes) < 2:
            self._single_class_value = float(unique_classes[0])
            logger.warning(
                "Platt: Tek sinif (%s). Identity calibrator olarak ayarlandi.",
                unique_classes[0],
            )
            return self

        eps = 1e-7
        y_prob_clipped = np.clip(y_prob, eps, 1.0 - eps)
        log_odds = np.log(y_prob_clipped / (1.0 - y_prob_clipped))

        self.lr = LogisticRegression(
            C=1e10,
            solver="lbfgs",
            max_iter=10000,
            random_state=42,
        )
        self.lr.fit(log_odds.reshape(-1, 1), y_true)
        return self

    def transform(self, y_prob: np.ndarray) -> np.ndarray:
        if self.lr is None and self._single_class_value is None:
            raise RuntimeError("PlattCalibrator fit edilmemis. Once fit() cagirin.")

        y_prob = np.asarray(y_prob, dtype=np.float64).ravel()

        if self._single_class_value is not None:
            return np.full_like(y_prob, self._single_class_value)

        eps = 1e-7
        y_prob_clipped = np.clip(y_prob, eps, 1.0 - eps)
        log_odds = np.log(y_prob_clipped / (1.0 - y_prob_clipped))

        calibrated = self.lr.predict_proba(log_odds.reshape(-1, 1))[:, 1]
        return np.clip(calibrated, 0.0, 1.0)

    def __repr__(self) -> str:
        return "PlattCalibrator(fitted={})".format(
            self.lr is not None or self._single_class_value is not None
        )


class BetaCalibrator:
    """Beta Calibration — 3 parametreli (a, b, c) beta donusum.

    Formul: calibrated = sigmoid(c + a * log(p) + b * log(1-p))
    """

    def __init__(self):
        self.a: float = 1.0
        self.b: float = 1.0
        self.c: float = 0.0
        self.fitted: bool = False
        self.method: str = "beta"

    @staticmethod
    def _sigmoid(x: np.ndarray) -> np.ndarray:
        return np.where(
            x >= 0,
            1.0 / (1.0 + np.exp(-x)),
            np.exp(x) / (1.0 + np.exp(x)),
        )

    def _transform_raw(self, y_prob: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
        eps = 1e-7
        p = np.clip(y_prob, eps, 1.0 - eps)
        logit_component = c + a * np.log(p) + b * np.log(1.0 - p)
        return self._sigmoid(logit_component)

    def fit(self, y_prob: np.ndarray, y_true: np.ndarray) -> "BetaCalibrator":
        y_prob = np.asarray(y_prob, dtype=np.float64).ravel()
        y_true = np.asarray(y_true, dtype=np.float64).ravel()

        if len(y_prob) < MIN_CALIBRATION_SAMPLES:
            logger.warning(
                "Beta: Yetersiz ornek (%d < %d). Yine de fit ediliyor.",
                len(y_prob), MIN_CALIBRATION_SAMPLES,
            )

        def neg_log_likelihood(params):
            a, b, c = params
            eps = 1e-7
            q = self._transform_raw(y_prob, a, b, c)
            q = np.clip(q, eps, 1.0 - eps)
            nll = -np.mean(y_true * np.log(q) + (1.0 - y_true) * np.log(1.0 - q))
            return nll

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = minimize(
                neg_log_likelihood,
                x0=[1.0, 1.0, 0.0],
                method="Nelder-Mead",
                options={"maxiter": 5000, "xatol": 1e-8, "fatol": 1e-8},
            )

        self.a, self.b, self.c = result.x
        self.fitted = True

        logger.debug(
            "Beta fit: a=%.4f, b=%.4f, c=%.4f, NLL=%.6f",
            self.a, self.b, self.c, result.fun,
        )
        return self

    def transform(self, y_prob: np.ndarray) -> np.ndarray:
        if not self.fitted:
            raise RuntimeError("BetaCalibrator fit edilmemis. Once fit() cagirin.")

        y_prob = np.asarray(y_prob, dtype=np.float64).ravel()
        calibrated = self._transform_raw(y_prob, self.a, self.b, self.c)
        return np.clip(calibrated, 0.0, 1.0)

    def __repr__(self) -> str:
        if self.fitted:
            return "BetaCalibrator(a={:.4f}, b={:.4f}, c={:.4f})".format(
                self.a, self.b, self.c
            )
        return "BetaCalibrator(fitted=False)"


class IsotonicCalibrator:
    """Isotonic Regression — non-parametrik monoton kalibrasyon."""

    def __init__(self):
        self.iso: Optional[IsotonicRegression] = None
        self.method: str = "isotonic"

    def fit(self, y_prob: np.ndarray, y_true: np.ndarray) -> "IsotonicCalibrator":
        y_prob = np.asarray(y_prob, dtype=np.float64).ravel()
        y_true = np.asarray(y_true, dtype=np.float64).ravel()

        self.iso = IsotonicRegression(
            y_min=0.0, y_max=1.0, out_of_bounds="clip"
        )
        self.iso.fit(y_prob, y_true)
        return self

    def transform(self, y_prob: np.ndarray) -> np.ndarray:
        if self.iso is None:
            raise RuntimeError("IsotonicCalibrator fit edilmemis.")

        y_prob = np.asarray(y_prob, dtype=np.float64).ravel()
        calibrated = self.iso.predict(y_prob)
        return np.clip(calibrated, 0.0, 1.0)

    def __repr__(self) -> str:
        return "IsotonicCalibrator(fitted={})".format(self.iso is not None)


def calibrate_platt(y_prob: np.ndarray, y_true: np.ndarray) -> PlattCalibrator:
    """Platt scaling (logistic regression) ile olasilik kalibrasyonu."""
    calibrator = PlattCalibrator()
    calibrator.fit(y_prob, y_true)
    return calibrator


def calibrate_beta(y_prob: np.ndarray, y_true: np.ndarray) -> BetaCalibrator:
    """Beta kalibrasyon (a, b, c parametreleri)."""
    calibrator = BetaCalibrator()
    calibrator.fit(y_prob, y_true)
    return calibrator


def calibrate_isotonic(y_prob: np.ndarray, y_true: np.ndarray) -> IsotonicCalibrator:
    """Isotonic regression kalibrasyon (son care yedek)."""
    calibrator = IsotonicCalibrator()
    calibrator.fit(y_prob, y_true)
    return calibrator


def evaluate_calibration(
    y_prob_calibrated: np.ndarray,
    y_true: np.ndarray,
    n_bins: int = 10,
) -> Dict[str, Any]:
    """Kalibrasyon kalitesini degerlendir.

    Returns:
        ece, mce, brier_score, reliability_data
    """
    y_prob_calibrated = np.asarray(y_prob_calibrated, dtype=np.float64).ravel()
    y_true = np.asarray(y_true, dtype=np.float64).ravel()

    n_total = len(y_true)

    if n_total == 0:
        return {
            "ece": 0.0,
            "mce": 0.0,
            "brier_score": 0.0,
            "reliability_data": {
                "mean_predicted": [],
                "fraction_positive": [],
                "bin_counts": [],
            },
        }

    brier = float(np.mean((y_prob_calibrated - y_true) ** 2))

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    mean_predicted = []
    fraction_positive = []
    bin_counts = []

    ece = 0.0
    mce = 0.0

    for i in range(n_bins):
        lower = bin_edges[i]
        upper = bin_edges[i + 1]

        if i < n_bins - 1:
            mask = (y_prob_calibrated >= lower) & (y_prob_calibrated < upper)
        else:
            mask = (y_prob_calibrated >= lower) & (y_prob_calibrated <= upper)

        count = int(np.sum(mask))
        bin_counts.append(count)

        if count > 0:
            avg_pred = float(np.mean(y_prob_calibrated[mask]))
            avg_true = float(np.mean(y_true[mask]))
            mean_predicted.append(round(avg_pred, 6))
            fraction_positive.append(round(avg_true, 6))

            gap = abs(avg_pred - avg_true)
            ece += (count / n_total) * gap
            mce = max(mce, gap)
        else:
            mean_predicted.append(0.0)
            fraction_positive.append(0.0)

    return {
        "ece": round(float(ece), 6),
        "mce": round(float(mce), 6),
        "brier_score": round(brier, 6),
        "reliability_data": {
            "mean_predicted": mean_predicted,
            "fraction_positive": fraction_positive,
            "bin_counts": bin_counts,
        },
    }


def auto_calibrate(
    y_prob_train: np.ndarray,
    y_true_train: np.ndarray,
    y_prob_val: np.ndarray,
    y_true_val: np.ndarray,
) -> Tuple[Any, Dict[str, Any]]:
    """Otomatik kalibrasyon secimi.

    Siralama: Platt -> Beta -> Isotonic. ECE < 0.05 ise erken dur.
    """
    y_prob_train = np.asarray(y_prob_train, dtype=np.float64).ravel()
    y_true_train = np.asarray(y_true_train, dtype=np.int32).ravel()
    y_prob_val = np.asarray(y_prob_val, dtype=np.float64).ravel()
    y_true_val = np.asarray(y_true_val, dtype=np.int32).ravel()

    candidates = []

    # 1. Platt Scaling
    try:
        platt = calibrate_platt(y_prob_train, y_true_train)
        platt_probs = platt.transform(y_prob_val)
        platt_eval = evaluate_calibration(platt_probs, y_true_val)

        candidates.append({
            "calibrator": platt,
            "method": "platt",
            "ece": platt_eval["ece"],
            "metrics": platt_eval,
        })
        logger.info("Platt ECE=%.6f", platt_eval["ece"])

        if platt_eval["ece"] < ECE_THRESHOLD:
            logger.info("Platt yeterli (ECE < %.2f). Secildi.", ECE_THRESHOLD)
            return platt, {
                "selected_method": "platt",
                "ece": platt_eval["ece"],
                "mce": platt_eval["mce"],
                "brier_score": platt_eval["brier_score"],
                "all_candidates": [{"method": "platt", "ece": platt_eval["ece"]}],
            }
    except Exception as e:
        logger.warning("Platt basarisiz: %s", str(e))

    # 2. Beta Calibration
    try:
        beta = calibrate_beta(y_prob_train, y_true_train)
        beta_probs = beta.transform(y_prob_val)
        beta_eval = evaluate_calibration(beta_probs, y_true_val)

        candidates.append({
            "calibrator": beta,
            "method": "beta",
            "ece": beta_eval["ece"],
            "metrics": beta_eval,
        })
        logger.info("Beta ECE=%.6f", beta_eval["ece"])

        if beta_eval["ece"] < ECE_THRESHOLD:
            logger.info("Beta yeterli (ECE < %.2f). Secildi.", ECE_THRESHOLD)
            return beta, {
                "selected_method": "beta",
                "ece": beta_eval["ece"],
                "mce": beta_eval["mce"],
                "brier_score": beta_eval["brier_score"],
                "all_candidates": [
                    {"method": c["method"], "ece": c["ece"]} for c in candidates
                ],
            }
    except Exception as e:
        logger.warning("Beta basarisiz: %s", str(e))

    # 3. Isotonic Regression
    try:
        isotonic = calibrate_isotonic(y_prob_train, y_true_train)
        iso_probs = isotonic.transform(y_prob_val)
        iso_eval = evaluate_calibration(iso_probs, y_true_val)

        candidates.append({
            "calibrator": isotonic,
            "method": "isotonic",
            "ece": iso_eval["ece"],
            "metrics": iso_eval,
        })
        logger.info("Isotonic ECE=%.6f", iso_eval["ece"])
    except Exception as e:
        logger.warning("Isotonic basarisiz: %s", str(e))

    if not candidates:
        raise RuntimeError("Hicbir kalibrasyon yontemi calismadi!")

    best = min(candidates, key=lambda c: c["ece"])
    logger.info(
        "Secilen kalibrasyon: %s (ECE=%.6f)",
        best["method"], best["ece"],
    )

    return best["calibrator"], {
        "selected_method": best["method"],
        "ece": best["metrics"]["ece"],
        "mce": best["metrics"]["mce"],
        "brier_score": best["metrics"]["brier_score"],
        "all_candidates": [
            {"method": c["method"], "ece": c["ece"]} for c in candidates
        ],
    }


def save_calibrator(
    calibrator: Any,
    fuel_type: str,
    model_path: Optional[Path] = None,
) -> Path:
    """Kalibratoru diske kaydet. models/v5/{fuel_type}_calibrator.joblib"""
    if model_path is None:
        model_path = _MODEL_PATH

    model_path = Path(model_path)
    model_path.mkdir(parents=True, exist_ok=True)

    file_path = model_path / f"{fuel_type}_calibrator.joblib"
    joblib.dump(calibrator, file_path)

    logger.info("Kalibrator kaydedildi: %s", file_path)
    return file_path


def load_calibrator(
    fuel_type: str,
    model_path: Optional[Path] = None,
) -> Any:
    """Kalibratoru diskten yukle."""
    if model_path is None:
        model_path = _MODEL_PATH

    model_path = Path(model_path)
    file_path = model_path / f"{fuel_type}_calibrator.joblib"

    if not file_path.exists():
        raise FileNotFoundError(f"Kalibrator dosyasi bulunamadi: {file_path}")

    calibrator = joblib.load(file_path)
    logger.info("Kalibrator yuklendi: %s", file_path)
    return calibrator


def apply_calibration(calibrator: Any, y_prob: np.ndarray) -> np.ndarray:
    """Kalibratoru uygula, kalibre edilmis olasilik dondur."""
    y_prob = np.asarray(y_prob, dtype=np.float64).ravel()
    calibrated = calibrator.transform(y_prob)
    return np.clip(calibrated, 0.0, 1.0)
