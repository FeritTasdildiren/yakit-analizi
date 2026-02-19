"""
ML tahmin API endpoint'leri (Katman 4).

Makine ogrenmesi tabanli fiyat degisim tahminleri, model egitimi,
SHAP aciklanabilirlik ve circuit breaker saglik kontrolu.
Tum endpoint'ler /api/v1/ml prefix'i altindadir.

Feature'lar DB'deki DailyMarketData, TaxParameter, CostBaseSnapshot
ve MBECalculation tablolarindan cekilir — hard-coded degerler yoktur.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_db
from src.ml.circuit_breaker import get_circuit_breaker
from src.ml.predictor import MLPredictor, get_predictor
from src.ml.schemas import (
    BacktestPerformanceResponse,
    CircuitBreakerHealthResponse,
    DegradedPredictionResponse,
    ExplainResponse,
    MLPredictionResponse,
    ModelInfoResponse,
    PredictionResponse,
    TrainResponse,
)
from src.repositories.ml_repository import (
    get_latest_prediction,
    get_prediction_by_id,
    get_predictions_range,
    upsert_ml_prediction,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ml", tags=["ML Tahmin"])


# --- Yardimci ---

VALID_FUEL_TYPES = {"benzin", "motorin", "lpg"}

# Backtest icin gereken minimum tahmin sayisi
_MIN_BACKTEST_PREDICTIONS = 2


def _validate_fuel_type(fuel_type: str) -> None:
    """Yakit tipini dogrular."""
    if fuel_type not in VALID_FUEL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Gecersiz yakit tipi: '{fuel_type}'. Gecerli: {VALID_FUEL_TYPES}",
        )


async def _fetch_feature_inputs(
    db: AsyncSession,
    fuel_type: str,
    target_date: date,
) -> dict | None:
    """
    DB'den feature hesaplama icin gerekli ham verileri ceker.

    DailyMarketData, TaxParameter, CostBaseSnapshot ve MBECalculation
    tablolarindan en guncel kayitlari toplar.

    Args:
        db: Async veritabani oturumu.
        fuel_type: Yakit tipi (benzin, motorin).
        target_date: Hedef tahmin tarihi.

    Returns:
        Feature parametreleri dict'i veya None (veri bulunamazsa).
    """
    from src.data_collectors.market_data_repository import (
        get_latest_data,
        get_data_range,
    )
    from src.data_collectors.tax_repository import get_current_tax
    from src.core.mbe_repository import (
        get_latest_mbe,
        get_mbe_range,
        get_cost_snapshots_range,
    )
    from src.core.price_change_repository import get_latest_price_change

    # --- En son piyasa verisi ---
    market = await get_latest_data(db, fuel_type)
    if market is None:
        logger.warning("Piyasa verisi bulunamadi: %s", fuel_type)
        return None

    # --- Gecmis piyasa verileri (son 15 gun) ---
    lookback_start = target_date - timedelta(days=15)
    history_records = await get_data_range(db, fuel_type, lookback_start, target_date)

    cif_history = [
        float(r.cif_med_usd_ton) for r in history_records
        if r.cif_med_usd_ton is not None
    ]
    fx_history = [
        float(r.usd_try_rate) for r in history_records
        if r.usd_try_rate is not None
    ]
    brent_history = [
        float(r.brent_usd_bbl) for r in history_records
        if r.brent_usd_bbl is not None
    ]

    # --- Aktif vergi parametreleri ---
    tax = await get_current_tax(db, fuel_type, target_date)
    otv_rate = float(tax.otv_fixed_tl or tax.otv_rate or 0) if tax else 0.0
    kdv_rate = float(tax.kdv_rate) if tax else 0.20

    # --- MBE degerleri ---
    mbe = await get_latest_mbe(db, fuel_type)

    mbe_value = float(mbe.mbe_value) if mbe and mbe.mbe_value is not None else 0.0
    mbe_pct = float(mbe.mbe_pct) if mbe and mbe.mbe_pct is not None else 0.0

    # MBE gecmisi
    mbe_range = await get_mbe_range(
        db, fuel_type, lookback_start, target_date,
    )
    mbe_history = [
        float(m.mbe_value) for m in mbe_range
        if m.mbe_value is not None
    ]

    previous_mbe = float(mbe_range[-2].mbe_value) if len(mbe_range) >= 2 else None
    mbe_3_days_ago = (
        float(mbe_range[-4].mbe_value)
        if len(mbe_range) >= 4
        else None
    )

    # --- NC gecmisi ---
    snapshots = await get_cost_snapshots_range(
        db, fuel_type, lookback_start, target_date,
    )
    nc_history = [
        float(s.cif_component_tl) for s in snapshots
        if s.cif_component_tl is not None
    ]

    # --- Son fiyat degisikligi ---
    last_change = await get_latest_price_change(db, fuel_type)
    days_since_last_hike = (
        (target_date - last_change.change_date).days
        if last_change and last_change.change_date
        else 0
    )

    # --- Rejim bilgisi ---
    regime = int(mbe.regime) if mbe and mbe.regime is not None else 0

    # --- Cost base ---
    latest_snapshot = snapshots[-1] if snapshots else None
    cost_base = (
        float(latest_snapshot.theoretical_cost_tl)
        if latest_snapshot and latest_snapshot.theoretical_cost_tl
        else 0.0
    )
    pump_price = (
        float(market.pump_price_tl_lt)
        if market.pump_price_tl_lt
        else None
    )
    margin = (
        float(latest_snapshot.margin_component_tl)
        if latest_snapshot and latest_snapshot.margin_component_tl
        else 1.20
    )
    implied_cif = (
        float(latest_snapshot.implied_cif_usd_ton)
        if latest_snapshot and latest_snapshot.implied_cif_usd_ton
        else None
    )
    cost_gap_tl = (
        float(latest_snapshot.cost_gap_tl)
        if latest_snapshot and latest_snapshot.cost_gap_tl is not None
        else 0.0
    )
    cost_gap_pct = (
        float(latest_snapshot.cost_gap_pct)
        if latest_snapshot and latest_snapshot.cost_gap_pct is not None
        else 0.0
    )

    return {
        "trade_date": target_date.isoformat(),
        "fuel_type": fuel_type,
        # MBE
        "mbe_value": mbe_value,
        "mbe_pct": mbe_pct,
        "mbe_history": mbe_history or None,
        "previous_mbe": previous_mbe,
        "mbe_3_days_ago": mbe_3_days_ago,
        # NC
        "cif_usd_ton": float(market.cif_med_usd_ton) if market.cif_med_usd_ton else 0.0,
        "fx_rate": float(market.usd_try_rate) if market.usd_try_rate else 0.0,
        "nc_history": nc_history or None,
        # Dis piyasa
        "brent_usd_bbl": float(market.brent_usd_bbl) if market.brent_usd_bbl else 0.0,
        "cif_history": cif_history or None,
        "fx_history": fx_history or None,
        "brent_history": brent_history or None,
        # Rejim
        "regime": regime,
        "days_since_last_hike": days_since_last_hike,
        # Vergi & Maliyet
        "otv_rate": otv_rate,
        "kdv_rate": kdv_rate,
        "margin_total": margin,
        "cost_base_snapshot": cost_base,
        "implied_cif": implied_cif,
        "cost_gap_tl": cost_gap_tl,
        "cost_gap_pct": cost_gap_pct,
        "pump_price": pump_price,
    }


# ────────────────────────────────────────────────────────────────────────────
#  POST /predict — Tahmin
# ────────────────────────────────────────────────────────────────────────────


@router.post(
    "/predict",
    response_model=PredictionResponse | DegradedPredictionResponse,
    summary="ML tabanli fiyat degisim tahmini",
)
async def predict(
    fuel_type: str = Query(default="motorin", description="Yakit tipi"),
    db: AsyncSession = Depends(get_db),
) -> PredictionResponse | DegradedPredictionResponse:
    """
    Belirtilen yakit tipi icin ML tabanli fiyat degisim tahmini uretir.

    Feature'lar DB'deki piyasa verisi, vergi parametreleri ve MBE
    hesaplamalarindan otomatik olarak cekilir.

    Circuit breaker OPEN ise Katman 3 deterministik sistem aktive olur
    ve degrade yanit doner.
    """
    _validate_fuel_type(fuel_type)

    cb = get_circuit_breaker()
    predictor = get_predictor()

    # Circuit breaker kontrolu
    if not cb.can_execute():
        logger.warning("Circuit breaker OPEN — degrade moda geciliyor")
        return DegradedPredictionResponse(
            status="degraded",
            prediction=None,
            risk_score=None,
            message="ML gecici olarak kullanilamiyor; deterministik sistem aktif",
            confidence="partial",
            system_mode="safe",
        )

    # Model yuklu mu?
    if not predictor.is_loaded:
        loaded = predictor.load_model()
        if not loaded:
            return DegradedPredictionResponse(
                status="degraded",
                prediction=None,
                risk_score=None,
                message="ML modeli yuklenemedi; deterministik sistem aktif",
                confidence="partial",
                system_mode="safe",
            )

    # Feature'lari DB'den cek
    today = date.today()

    try:
        feature_inputs = await _fetch_feature_inputs(db, fuel_type, today)
    except Exception as exc:
        logger.warning("Feature veri cekim hatasi: %s — fallback degerler kullanilacak", exc)
        feature_inputs = None

    # Feature hesapla
    from src.ml.feature_engineering import compute_all_features

    try:
        if feature_inputs is not None:
            record = compute_all_features(**feature_inputs)
        else:
            # Fallback: minimum parametre ile hesapla
            record = compute_all_features(
                trade_date=today.isoformat(),
                fuel_type=fuel_type,
                mbe_value=0.0,
                mbe_pct=0.0,
                cif_usd_ton=0.0,
                fx_rate=0.0,
            )
    except Exception as exc:
        cb.record_failure()
        logger.exception("Feature hesaplama hatasi: %s", exc)
        return DegradedPredictionResponse(
            status="degraded",
            prediction=None,
            message=f"Feature hesaplama hatasi: {exc}",
            system_mode="safe",
        )

    # Tahmin
    try:
        result = predictor.predict(record.features)
    except RuntimeError:
        return DegradedPredictionResponse(
            status="degraded",
            prediction=None,
            message="ML tahmin hatasi; deterministik sistem aktif",
            system_mode="safe",
        )

    # SHAP top features hesapla (model yukluyse)
    shap_top_features = result.shap_top_features
    if shap_top_features is None and predictor.is_loaded:
        try:
            from src.ml.explainability import compute_shap_for_prediction

            shap_top_features = compute_shap_for_prediction(
                model=predictor._model_pair.classifier,
                features=record.features,
                feature_names=predictor.feature_names,
                top_n=5,
                target_class=2,  # hike sinifi
            )
        except Exception as exc:
            logger.warning("SHAP hesaplama hatasi (non-critical): %s", exc)

    # DB'ye kaydet
    try:
        await upsert_ml_prediction(
            session=db,
            fuel_type=fuel_type,
            prediction_date=today,
            predicted_direction=result.predicted_direction,
            probability_hike=result.probability_hike,
            probability_stable=result.probability_stable,
            probability_cut=result.probability_cut,
            expected_change_tl=result.expected_change_tl,
            model_version=result.model_version,
            system_mode=result.system_mode,
            shap_top_features=shap_top_features,
        )
    except Exception as exc:
        logger.warning("ML tahmin DB kayit hatasi: %s", exc)

    return PredictionResponse(
        fuel_type=fuel_type,
        prediction_date=today,
        predicted_direction=result.predicted_direction,
        probability_hike=result.probability_hike,
        probability_stable=result.probability_stable,
        probability_cut=result.probability_cut,
        expected_change_tl=result.expected_change_tl,
        model_version=result.model_version,
        system_mode=result.system_mode,
        shap_top_features=shap_top_features,
        confidence=result.confidence,
    )


# ────────────────────────────────────────────────────────────────────────────
#  GET /backtest-performance — Backtest Metrikleri
# ────────────────────────────────────────────────────────────────────────────


@router.get(
    "/backtest-performance",
    response_model=BacktestPerformanceResponse,
    summary="ML backtest performans metrikleri",
)
async def backtest_performance(
    fuel_type: str = Query(default="benzin", description="Yakit tipi"),
    lookback_days: int = Query(default=90, ge=7, le=365, description="Geriye bakis gunu"),
    db: AsyncSession = Depends(get_db),
) -> BacktestPerformanceResponse:
    """
    Belirtilen yakit tipi ve donem icin ML tahmin performansini dondurur.

    Gecmis tahminleri gercek fiyat degisimleriyle karsilastirir ve
    accuracy, precision, recall, F1 ve MAE metrikleri hesaplar.
    """
    _validate_fuel_type(fuel_type)

    today = date.today()
    start_date = today - timedelta(days=lookback_days)

    predictions = await get_predictions_range(db, fuel_type, start_date, today)

    if len(predictions) < _MIN_BACKTEST_PREDICTIONS:
        return BacktestPerformanceResponse(
            fuel_type=fuel_type,
            lookback_days=lookback_days,
            total_predictions=len(predictions),
            accuracy=None,
            precision_hike=None,
            recall_hike=None,
            f1_hike=None,
            mae_tl=None,
            direction_accuracy=None,
        )

    # Gercek fiyat degisimlerini cek
    from src.core.price_change_repository import get_price_changes_range

    actual_changes = await get_price_changes_range(
        db, fuel_type, start_date, today,
    )

    if not actual_changes:
        return BacktestPerformanceResponse(
            fuel_type=fuel_type,
            lookback_days=lookback_days,
            total_predictions=len(predictions),
            accuracy=None,
            precision_hike=None,
            recall_hike=None,
            f1_hike=None,
            mae_tl=None,
            direction_accuracy=None,
        )

    # Gercek degisim tarihlerini index'le
    actual_by_date: dict[date, str] = {}
    actual_amount_by_date: dict[date, float] = {}
    for change in actual_changes:
        actual_by_date[change.change_date] = change.direction
        actual_amount_by_date[change.change_date] = float(change.change_amount)

    # Tahminleri gercekle esle
    correct = 0
    total_matched = 0
    direction_correct = 0
    mae_sum = 0.0
    mae_count = 0

    # hike precision/recall sayaclari
    tp_hike = 0  # true positive: predicted hike, actual increase
    fp_hike = 0  # false positive: predicted hike, actual != increase
    fn_hike = 0  # false negative: actual increase, predicted != hike

    # Direction mapping: prediction direction -> change direction
    dir_map = {"hike": "increase", "cut": "decrease", "stable": "no_change"}

    for pred in predictions:
        if pred.prediction_date not in actual_by_date:
            continue

        total_matched += 1
        actual_dir = actual_by_date[pred.prediction_date]
        pred_dir = dir_map.get(pred.predicted_direction, pred.predicted_direction)

        if pred_dir == actual_dir:
            correct += 1
            direction_correct += 1

        # Hike metrikleri
        if pred.predicted_direction == "hike":
            if actual_dir == "increase":
                tp_hike += 1
            else:
                fp_hike += 1
        elif actual_dir == "increase":
            fn_hike += 1

        # MAE
        if pred.expected_change_tl is not None:
            actual_amount = actual_amount_by_date.get(pred.prediction_date, 0.0)
            mae_sum += abs(float(pred.expected_change_tl) - actual_amount)
            mae_count += 1

    # Metrikleri hesapla
    accuracy = round(correct / total_matched, 4) if total_matched > 0 else None
    direction_accuracy = (
        round(direction_correct / total_matched, 4) if total_matched > 0 else None
    )

    precision_hike = (
        round(tp_hike / (tp_hike + fp_hike), 4)
        if (tp_hike + fp_hike) > 0
        else None
    )
    recall_hike = (
        round(tp_hike / (tp_hike + fn_hike), 4)
        if (tp_hike + fn_hike) > 0
        else None
    )
    f1_hike = None
    if precision_hike is not None and recall_hike is not None:
        denom = precision_hike + recall_hike
        if denom > 0:
            f1_hike = round(2 * precision_hike * recall_hike / denom, 4)

    mae_tl = round(mae_sum / mae_count, 4) if mae_count > 0 else None

    return BacktestPerformanceResponse(
        fuel_type=fuel_type,
        lookback_days=lookback_days,
        total_predictions=len(predictions),
        accuracy=accuracy,
        precision_hike=precision_hike,
        recall_hike=recall_hike,
        f1_hike=f1_hike,
        mae_tl=mae_tl,
        direction_accuracy=direction_accuracy,
    )


# ────────────────────────────────────────────────────────────────────────────
#  GET /explain/{prediction_id} — SHAP Aciklama
# ────────────────────────────────────────────────────────────────────────────


@router.get(
    "/explain/{prediction_id}",
    response_model=ExplainResponse,
    summary="ML tahmin SHAP aciklamasi",
)
async def explain_prediction(
    prediction_id: int,
    db: AsyncSession = Depends(get_db),
) -> ExplainResponse:
    """Belirtilen tahmin icin SHAP aciklamasi dondurur."""
    prediction = await get_prediction_by_id(db, prediction_id)
    if prediction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tahmin bulunamadi: id={prediction_id}",
        )

    # SHAP bilgisi DB'de varsa direkt don
    top_features = []
    if prediction.shap_top_features:
        raw = prediction.shap_top_features
        if isinstance(raw, list):
            top_features = raw
        elif isinstance(raw, dict) and "top_features" in raw:
            top_features = raw["top_features"]

    return ExplainResponse(
        prediction_id=prediction.id,
        predicted_direction=prediction.predicted_direction,
        top_features=top_features,
        global_importance=None,
    )


# ────────────────────────────────────────────────────────────────────────────
#  POST /train — Manuel Yeniden Egitim
# ────────────────────────────────────────────────────────────────────────────


@router.post(
    "/train",
    response_model=TrainResponse,
    summary="ML modelini manuel olarak yeniden egit",
)
async def train_model(
    fuel_type: str = Query(default="motorin", description="Yakit tipi"),
    db: AsyncSession | None = Depends(get_db),
) -> TrainResponse:
    """
    ML modelini yeniden egitir.

    Gecmis fiyat degisimleri ve feature verileriyle LightGBM siniflandirma
    ve regresyon modellerini egitir. Model kaydi joblib ile yapilir.

    NOT: Bu endpoint uzun surebilir. Prod ortamda Celery task olarak calistirilmali.
    """
    _validate_fuel_type(fuel_type)

    from src.ml.feature_engineering import compute_all_features, FEATURE_NAMES
    from src.ml.trainer import train_models, create_labels, get_next_version

    import numpy as np

    # --- Gecmis fiyat degisimlerini al ---
    try:
        from src.core.price_change_repository import get_price_changes_by_fuel

        price_changes = await get_price_changes_by_fuel(db, fuel_type, limit=500)
    except Exception as exc:
        logger.warning("Egitim veri cekim hatasi: %s", exc)
        return TrainResponse(
            status="failed",
            model_version=None,
            clf_metrics=None,
            reg_metrics=None,
            message=f"Veritabani baglantisi basarisiz: {exc}",
        )

    if len(price_changes) < 50:
        return TrainResponse(
            status="failed",
            model_version=None,
            clf_metrics=None,
            reg_metrics=None,
            message=(
                f"Yetersiz egitim verisi: {len(price_changes)} kayit "
                f"(minimum 50 fiyat degisikligi gerekli)"
            ),
        )

    # --- Her fiyat degisikligi icin feature vektoru olustur ---
    feature_vectors: list[list[float]] = []
    change_amounts: list[float] = []

    for pc in reversed(price_changes):  # eskiden yeniye sirala
        try:
            feature_inputs = await _fetch_feature_inputs(
                db, fuel_type, pc.change_date,
            )
            if feature_inputs is None:
                continue

            record = compute_all_features(**feature_inputs)

            feature_vec = [record.features.get(name, 0.0) for name in FEATURE_NAMES]
            feature_vectors.append(feature_vec)
            change_amounts.append(float(pc.change_amount))
        except Exception as exc:
            logger.warning(
                "Egitim verisi hazirlama hatasi (date=%s): %s",
                pc.change_date, exc,
            )
            continue

    if len(feature_vectors) < 50:
        return TrainResponse(
            status="failed",
            model_version=None,
            clf_metrics=None,
            reg_metrics=None,
            message=(
                f"Yetersiz feature verisi: {len(feature_vectors)} ornek "
                f"(minimum 50 gerekli)"
            ),
        )

    # --- Egitim ---
    X = np.array(feature_vectors, dtype=np.float64)
    y_clf, y_reg = create_labels(change_amounts)

    version = get_next_version()
    result = train_models(
        X=X,
        y_clf=y_clf,
        y_reg=y_reg,
        feature_names=FEATURE_NAMES,
        version=version,
    )

    # Basarili egitim sonrasi modeli yukle
    if result.status == "success":
        predictor = get_predictor()
        predictor.load_model(result.model_version)
        logger.info("Yeni model yuklendi: %s", result.model_version)

    return TrainResponse(
        status=result.status,
        model_version=result.model_version,
        clf_metrics=result.clf_metrics,
        reg_metrics=result.reg_metrics,
        message=result.message,
    )


# ────────────────────────────────────────────────────────────────────────────
#  GET /model-info — Model Bilgisi
# ────────────────────────────────────────────────────────────────────────────


@router.get(
    "/model-info",
    response_model=ModelInfoResponse,
    summary="Aktif ML model bilgisi",
)
async def model_info() -> ModelInfoResponse:
    """Yuklenmis ML modelinin bilgisini dondurur."""
    predictor = get_predictor()

    if not predictor.is_loaded:
        return ModelInfoResponse(
            classifier_version=None,
            regressor_version=None,
            feature_count=0,
            feature_names=[],
            last_trained=None,
        )

    return ModelInfoResponse(
        classifier_version=predictor.model_version,
        regressor_version=predictor.model_version,
        feature_count=len(predictor.feature_names),
        feature_names=predictor.feature_names,
        last_trained=None,
    )


# ────────────────────────────────────────────────────────────────────────────
#  GET /health — Circuit Breaker Durumu
# ────────────────────────────────────────────────────────────────────────────


@router.get(
    "/health",
    response_model=CircuitBreakerHealthResponse,
    summary="Circuit breaker saglik durumu",
)
async def health_check() -> CircuitBreakerHealthResponse:
    """ML servisi ve circuit breaker saglik durumunu dondurur."""
    cb = get_circuit_breaker()
    health = cb.get_health()

    return CircuitBreakerHealthResponse(
        state=health["state"],
        failure_count=health["failure_count"],
        success_count=health["success_count"],
        failure_rate=health["failure_rate"],
        last_failure_time=health["last_failure_time"],
        last_state_change=health["last_state_change"],
    )
