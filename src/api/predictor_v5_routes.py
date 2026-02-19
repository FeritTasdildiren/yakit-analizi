"""
Predictor v5 API endpoint\x27leri.

5 endpoint: latest, history, features, run (placeholder), backtest summary (placeholder).
Tum endpoint\x27ler /api/v1/predictions/v5 prefix\x27i altindadir.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/predictions/v5", tags=["Predictor v5"])

# ---------------------------------------------------------------------------
#  Geçerli yakıt tipleri
# ---------------------------------------------------------------------------

VALID_FUEL_TYPES = {"benzin", "motorin", "lpg"}


def _validate_fuel_type(fuel_type: str) -> None:
    """Yakit tipini dogrular; gecersizse 422 doner."""
    if fuel_type not in VALID_FUEL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Gecersiz yakit tipi: \x27{fuel_type}\x27. Gecerli: {sorted(VALID_FUEL_TYPES)}",
        )


# ---------------------------------------------------------------------------
#  Response Schemas
# ---------------------------------------------------------------------------


class PredictionV5Response(BaseModel):
    """Tek tahmin sonucu."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_date: date
    fuel_type: str
    stage1_probability: Optional[float] = None
    stage1_label: Optional[bool] = None
    first_event_direction: Optional[int] = None
    first_event_amount: Optional[float] = None
    first_event_type: Optional[str] = None
    net_amount_3d: Optional[float] = None
    model_version: Optional[str] = None
    calibration_method: Optional[str] = None
    alarm_triggered: bool = False
    alarm_suppressed: bool = False
    suppression_reason: Optional[str] = None
    alarm_message: Optional[str] = None


class PredictionHistoryResponse(BaseModel):
    """Tahmin tarihcesi."""
    fuel_type: str
    days: int
    count: int
    predictions: list[PredictionV5Response]


class FeatureSnapshotResponse(BaseModel):
    """Feature snapshot yaniti."""
    run_date: date
    fuel_type: str
    features: dict[str, Any]
    feature_version: Optional[str] = None


class RunResponse(BaseModel):
    """Manuel calistirma yaniti (placeholder)."""
    status: str
    message: str


class BacktestSummaryResponse(BaseModel):
    """Backtest ozeti yaniti (placeholder)."""
    status: str
    message: str


# ────────────────────────────────────────────────────────────────────────────
#  1) GET /latest/{fuel_type} — Son tahmin
# ────────────────────────────────────────────────────────────────────────────


@router.get(
    "/latest/{fuel_type}",
    response_model=PredictionV5Response,
    summary="Son v5 tahmini",
)
async def get_latest_prediction(
    fuel_type: str,
    db: AsyncSession = Depends(get_db),
) -> PredictionV5Response:
    """Belirtilen yakit tipi icin en guncel v5 tahminini dondurur."""
    _validate_fuel_type(fuel_type)

    from src.predictor_v5.repository import get_latest_prediction_async

    prediction = await get_latest_prediction_async(db, fuel_type)

    if prediction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tahmin bulunamadi: fuel_type={fuel_type}",
        )

    return PredictionV5Response.model_validate(prediction)


# ────────────────────────────────────────────────────────────────────────────
#  2) GET /history/{fuel_type}?days=30 — Tarihce
# ────────────────────────────────────────────────────────────────────────────


@router.get(
    "/history/{fuel_type}",
    response_model=PredictionHistoryResponse,
    summary="v5 tahmin tarihcesi",
)
async def get_prediction_history(
    fuel_type: str,
    days: int = Query(default=30, ge=1, le=365, description="Geriye bakis gunu"),
    db: AsyncSession = Depends(get_db),
) -> PredictionHistoryResponse:
    """Belirtilen yakit tipi icin son N gunluk v5 tahmin tarihcesini dondurur."""
    _validate_fuel_type(fuel_type)

    from src.predictor_v5.repository import get_predictions_async

    today = date.today()
    start_date = today - timedelta(days=days)

    predictions = await get_predictions_async(db, fuel_type, start_date, today)

    items = [PredictionV5Response.model_validate(p) for p in predictions]

    return PredictionHistoryResponse(
        fuel_type=fuel_type,
        days=days,
        count=len(items),
        predictions=items,
    )


# ────────────────────────────────────────────────────────────────────────────
#  3) GET /features/{fuel_type}/{run_date} — Feature snapshot
# ────────────────────────────────────────────────────────────────────────────


@router.get(
    "/features/{fuel_type}/{run_date}",
    response_model=FeatureSnapshotResponse,
    summary="Feature snapshot",
)
async def get_feature_snapshot(
    fuel_type: str,
    run_date: date,
) -> FeatureSnapshotResponse:
    """Belirtilen yakit tipi ve tarih icin feature snapshot\x27i dondurur."""
    _validate_fuel_type(fuel_type)

    from src.predictor_v5.feature_store import load_snapshot

    snapshot = load_snapshot(fuel_type, run_date)

    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature snapshot bulunamadi: fuel_type={fuel_type}, run_date={run_date}",
        )

    return FeatureSnapshotResponse(
        run_date=snapshot["run_date"],
        fuel_type=snapshot["fuel_type"],
        features=snapshot["features"],
        feature_version=snapshot.get("feature_version"),
    )


# ────────────────────────────────────────────────────────────────────────────
#  4) POST /run — Manuel tetikleme (placeholder)
# ────────────────────────────────────────────────────────────────────────────


@router.post(
    "/run",
    response_model=RunResponse,
    summary="Manuel v5 tahmin calistir (placeholder)",
)
async def run_prediction() -> RunResponse:
    """
    Manuel v5 prediction pipeline tetiklemesi.

    NOT: Bu endpoint henuz implementasyon bekliyor.
    Trainer + calibration pipeline tamamlaninca aktif edilecek.
    """
    return RunResponse(
        status="not_implemented",
        message="v5 prediction pipeline henuz aktif degil. "
                "Trainer ve calibration tamamlaninca bu endpoint calisacak.",
    )


# ────────────────────────────────────────────────────────────────────────────
#  5) GET /backtest/summary — Backtest ozeti (placeholder)
# ────────────────────────────────────────────────────────────────────────────


@router.get(
    "/backtest/summary",
    response_model=BacktestSummaryResponse,
    summary="v5 backtest ozeti (placeholder)",
)
async def get_backtest_summary() -> BacktestSummaryResponse:
    """
    v5 backtest fold metriklerinin ozet istatistikleri.

    NOT: Bu endpoint henuz implementasyon bekliyor.
    Purged walk-forward CV tamamlaninca aktif edilecek.
    """
    return BacktestSummaryResponse(
        status="not_implemented",
        message="v5 backtest pipeline henuz aktif degil. "
                "CV modulu tamamlaninca bu endpoint ozet metrikleri donecek.",
    )
