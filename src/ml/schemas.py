"""
ML Katmani Pydantic semalari.

API request/response modelleri ve dahili veri yapilari.
Tum finansal degerler Decimal olarak saklanir.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ────────────────────────────────────────────────────────────────────────────
#  Tahmin Request / Response
# ────────────────────────────────────────────────────────────────────────────


class PredictionRequest(BaseModel):
    """Tahmin istegi schemasi."""

    fuel_type: str = Field(
        description="Yakit tipi: benzin, motorin",
        examples=["motorin"],
    )


class PredictionResponse(BaseModel):
    """Tahmin sonucu schemasi."""

    fuel_type: str = Field(description="Yakit tipi")
    prediction_date: date = Field(description="Tahmin tarihi")
    predicted_direction: str = Field(
        description="Tahmin yonu: hike, stable, cut"
    )
    probability_hike: Decimal = Field(description="Zam olasiligi (0-1)")
    probability_stable: Decimal = Field(description="Sabit olasiligi (0-1)")
    probability_cut: Decimal = Field(description="Indirim olasiligi (0-1)")
    expected_change_tl: Decimal | None = Field(
        default=None, description="Beklenen degisim TL/L"
    )
    model_version: str = Field(description="Model versiyonu")
    system_mode: str = Field(description="Sistem modu: full, partial, safe")
    shap_top_features: list[dict] | None = Field(
        default=None, description="En etkili 5 feature ve katkilari"
    )
    confidence: str = Field(
        default="high", description="Guven seviyesi: high, partial, low"
    )


class DegradedPredictionResponse(BaseModel):
    """Circuit breaker aktifken kullanilan degrade yanit."""

    status: str = Field(default="degraded")
    prediction: None = Field(default=None)
    risk_score: Decimal | None = Field(
        default=None, description="Katman 3 risk skoru"
    )
    message: str = Field(
        default="ML gecici olarak kullanilamiyor; deterministik sistem aktif"
    )
    confidence: str = Field(default="partial")
    system_mode: str = Field(default="safe")


# ────────────────────────────────────────────────────────────────────────────
#  Egitim Request / Response
# ────────────────────────────────────────────────────────────────────────────


class TrainRequest(BaseModel):
    """Model egitim istegi."""

    fuel_type: str = Field(
        default="motorin", description="Yakit tipi"
    )
    force_retrain: bool = Field(
        default=False, description="Mevcut modeli yeniden egit"
    )


class TrainResponse(BaseModel):
    """Model egitim sonucu."""

    status: str = Field(description="Egitim durumu: success, failed")
    model_version: str | None = Field(
        default=None, description="Olusturulan model versiyonu"
    )
    clf_metrics: dict | None = Field(
        default=None, description="Siniflandirma metrikleri"
    )
    reg_metrics: dict | None = Field(
        default=None, description="Regresyon metrikleri"
    )
    message: str = Field(default="", description="Ek bilgi")


# ────────────────────────────────────────────────────────────────────────────
#  SHAP Aciklanabilirlik
# ────────────────────────────────────────────────────────────────────────────


class SHAPFeatureContribution(BaseModel):
    """Tek bir feature'in SHAP katkisi."""

    feature_name: str = Field(description="Feature adi")
    shap_value: float = Field(description="SHAP degeri")
    feature_value: float | None = Field(
        default=None, description="Feature'in gercek degeri"
    )


class ExplainResponse(BaseModel):
    """SHAP aciklama yaniti."""

    prediction_id: int = Field(description="Tahmin kaydi ID")
    predicted_direction: str = Field(description="Tahmin yonu")
    top_features: list[SHAPFeatureContribution] = Field(
        description="En etkili 5 feature"
    )
    global_importance: list[dict] | None = Field(
        default=None, description="Genel feature onem sirasi"
    )


# ────────────────────────────────────────────────────────────────────────────
#  Model Bilgi / Saglik
# ────────────────────────────────────────────────────────────────────────────


class ModelInfoResponse(BaseModel):
    """Aktif model bilgisi."""

    classifier_version: str | None = Field(default=None)
    regressor_version: str | None = Field(default=None)
    feature_count: int = Field(default=0)
    feature_names: list[str] = Field(default_factory=list)
    last_trained: str | None = Field(default=None)


class CircuitBreakerHealthResponse(BaseModel):
    """Circuit breaker saglik durumu."""

    state: str = Field(description="CLOSED, OPEN, HALF_OPEN")
    failure_count: int = Field(description="Son penceredeki hata sayisi")
    success_count: int = Field(description="Son penceredeki basarili istek")
    failure_rate: float = Field(description="Hata orani (0-1)")
    last_failure_time: str | None = Field(default=None)
    last_state_change: str | None = Field(default=None)


class BacktestPerformanceResponse(BaseModel):
    """ML backtest performans metrikleri."""

    fuel_type: str
    lookback_days: int
    total_predictions: int
    accuracy: float | None = None
    precision_hike: float | None = None
    recall_hike: float | None = None
    f1_hike: float | None = None
    mae_tl: float | None = None
    direction_accuracy: float | None = None


# ────────────────────────────────────────────────────────────────────────────
#  DB Model Response
# ────────────────────────────────────────────────────────────────────────────


class MLPredictionResponse(BaseModel):
    """ML tahmin DB kaydi yaniti."""

    id: int
    fuel_type: str
    prediction_date: date
    predicted_direction: str
    probability_hike: Decimal
    probability_stable: Decimal
    probability_cut: Decimal
    expected_change_tl: Decimal | None
    model_version: str
    system_mode: str
    shap_top_features: list[dict] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
