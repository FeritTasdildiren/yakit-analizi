"""
SHAP Aciklanabilirlik Modulu (Katman 4).

LightGBM modelleri icin TreeExplainer kullanarak SHAP degerleri hesaplar.
Her tahmin icin en etkili 5 feature'i ve global feature onem sirasini saglar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from src.ml.feature_engineering import FEATURE_NAMES

logger = logging.getLogger(__name__)


@dataclass
class SHAPExplanation:
    """SHAP aciklama sonucu."""

    top_features: list[dict] = field(default_factory=list)
    global_importance: list[dict] = field(default_factory=list)
    base_value: float | None = None


def compute_shap_values(
    model: object,
    X: np.ndarray,
    feature_names: list[str] | None = None,
    top_n: int = 5,
    target_class: int | None = None,
) -> SHAPExplanation:
    """
    SHAP degerleri hesaplar ve en etkili feature'lari dondurur.

    TreeExplainer LightGBM icin optimize edilmistir.

    Args:
        model: Egitilmis LightGBM modeli.
        X: Feature matrisi (n_samples, n_features).
           Tek bir ornek icin shape (1, n_features).
        feature_names: Feature isimleri.
        top_n: En etkili kac feature donecek.
        target_class: Hedef sinif indeksi (siniflandirma icin).
            None ise regresyon modeli varsayilir.

    Returns:
        SHAPExplanation nesnesi.
    """
    if feature_names is None:
        feature_names = FEATURE_NAMES

    try:
        import shap

        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X)

        # Siniflandirma modeli: shap_values list of arrays (her sinif icin)
        # Regresyon modeli: shap_values tek array
        if isinstance(shap_values, list) and target_class is not None:
            # Siniflandirma — hedef sinifin SHAP degerleri
            sv = shap_values[target_class]
        elif isinstance(shap_values, list):
            # Siniflandirma ama hedef sinif belirtilmemis → hike (2) al
            sv = shap_values[2] if len(shap_values) > 2 else shap_values[0]
        else:
            sv = shap_values

        # Tek ornek icin
        if sv.ndim == 2:
            sv_sample = sv[0]
        else:
            sv_sample = sv

        # Base value
        base_value = None
        if hasattr(explainer, "expected_value"):
            ev = explainer.expected_value
            if isinstance(ev, (list, np.ndarray)):
                if target_class is not None and target_class < len(ev):
                    base_value = float(ev[target_class])
                elif len(ev) > 2:
                    base_value = float(ev[2])
                else:
                    base_value = float(ev[0])
            else:
                base_value = float(ev)

        # Top-N feature'lar (mutlak degere gore sirala)
        abs_shap = np.abs(sv_sample)
        top_indices = np.argsort(abs_shap)[::-1][:top_n]

        top_features = []
        for idx in top_indices:
            name = feature_names[idx] if idx < len(feature_names) else f"feature_{idx}"
            top_features.append({
                "feature_name": name,
                "shap_value": round(float(sv_sample[idx]), 6),
                "feature_value": round(float(X[0, idx]), 6) if X.shape[0] > 0 else None,
            })

        # Global importance (ortalama mutlak SHAP)
        if sv.ndim == 2 and sv.shape[0] > 1:
            mean_abs_shap = np.mean(np.abs(sv), axis=0)
        else:
            mean_abs_shap = abs_shap

        global_indices = np.argsort(mean_abs_shap)[::-1]
        global_importance = []
        for idx in global_indices:
            name = feature_names[idx] if idx < len(feature_names) else f"feature_{idx}"
            global_importance.append({
                "feature_name": name,
                "importance": round(float(mean_abs_shap[idx]), 6),
            })

        return SHAPExplanation(
            top_features=top_features,
            global_importance=global_importance,
            base_value=base_value,
        )

    except ImportError:
        logger.warning("SHAP kutuphanesi yuklu degil — aciklama uretilemedi")
        return SHAPExplanation()

    except Exception as exc:
        logger.warning("SHAP hesaplama hatasi: %s", exc)
        return SHAPExplanation()


def compute_shap_for_prediction(
    model: object,
    features: dict[str, float],
    feature_names: list[str] | None = None,
    top_n: int = 5,
    target_class: int = 2,
) -> list[dict]:
    """
    Tek bir tahmin icin SHAP aciklamasi hesaplar.

    Kolaylik fonksiyonu — feature dict'ini alir, top-N feature'lari dondurur.

    Args:
        model: Egitilmis model.
        features: Feature dict.
        feature_names: Feature isimleri.
        top_n: Kac feature donecek.
        target_class: Hedef sinif (2=hike).

    Returns:
        Top-N feature katkisi listesi.
    """
    if feature_names is None:
        feature_names = FEATURE_NAMES

    from src.ml.feature_engineering import features_dict_to_array

    X = np.array([features_dict_to_array(features)], dtype=np.float64)

    explanation = compute_shap_values(
        model=model,
        X=X,
        feature_names=feature_names,
        top_n=top_n,
        target_class=target_class,
    )

    return explanation.top_features
