"""
Predictor v5/v6 — Inference Pipeline
===================================
v6: Kalibrasyon bypass, gevşetilmiş threshold, deterministik alarm entegrasyonu.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional

import joblib
import numpy as np
import pandas as pd

from src.predictor_v5.config import (
    ALARM_THRESHOLD,
    FEATURE_NAMES,
    FUEL_TYPES,
    MODEL_DIR,
    USE_CALIBRATION,
)
from src.predictor_v5.features import compute_features_bulk, get_price_changed_today
from src.predictor_v5.alarm import compute_risk_trend, evaluate_alarm
from src.predictor_v5.repository import (
    save_prediction_sync,
    get_latest_prediction_sync,
    get_predictions_sync,
    DB_DSN,
)
from src.predictor_v5.feature_store import store_snapshot

# Stage-2 output clipping sinirlari
_CLIP_LIMITS = {
    "benzin":  {"first_event": 2.50, "net_3d": 4.00},
    "motorin": {"first_event": 2.50, "net_3d": 4.00},
    "lpg":     {"first_event": 1.50, "net_3d": 2.50},
}

# Kalibrasyon modulu
try:
    from src.predictor_v5.calibration import load_calibrator, apply_calibration
except ImportError:
    load_calibrator = None
    apply_calibration = None

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_MODEL_PATH = _PROJECT_ROOT / MODEL_DIR

_model_cache: Dict[str, object] = {}

# v6: Threshold düşürüldü (0.55 -> 0.25)
_STAGE1_THRESHOLD = float(ALARM_THRESHOLD)


def _load_model(fuel_type: str, model_name: str) -> Optional[object]:
    """Model dosyasını yükle (lazy loading + cache)."""
    cache_key = f"{fuel_type}_{model_name}"

    if cache_key in _model_cache:
        return _model_cache[cache_key]

    model_path = _MODEL_PATH / f"{fuel_type}_{model_name}.joblib"

    if not model_path.exists():
        logger.warning("Model dosyasi bulunamadi: %s", model_path)
        return None

    try:
        model = joblib.load(model_path)
        _model_cache[cache_key] = model
        logger.info("Model yuklendi ve cache'e alindi: %s", cache_key)
        return model
    except Exception as exc:
        logger.error("Model yuklenemedi (%s): %s", model_path, exc)
        return None


def _fetch_recent_risk_scores(
    fuel_type: str,
    target_date: date,
    dsn: str = DB_DSN,
    days: int = 6,
) -> list[float]:
    """Son N günlük risk composite skorlarını çek."""
    import psycopg2

    query = """
        SELECT composite_score
        FROM risk_scores
        WHERE fuel_type = %s
          AND trade_date > %s
          AND trade_date <= %s
        ORDER BY trade_date ASC
    """
    start = target_date - timedelta(days=days)

    try:
        conn = psycopg2.connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(query, (fuel_type, start, target_date))
                rows = cur.fetchall()
            return [float(r[0]) for r in rows if r[0] is not None]
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Risk skorlari cekilemedi: %s", exc)
        return []


def predict(
    fuel_type: str,
    target_date: Optional[date] = None,
    db_url: Optional[str] = None,
) -> Optional[dict]:
    """
    Tek yakıt tipi için tam tahmin pipeline.

    v6 Değişiklikler:
    - USE_CALIBRATION=False → raw probability kullanılır
    - Stage-2 tetikleme eşiği düşürüldü (0.55 → 0.25)
    - Alarm'a feature dict iletilir (deterministik alarm için)
    """
    if target_date is None:
        target_date = date.today()
    dsn = db_url or DB_DSN

    logger.info("Tahmin baslatiliyor: fuel=%s, date=%s", fuel_type, target_date)

    # 1. Feature hesapla
    try:
        features_df = compute_features_bulk(fuel_type, target_date, target_date, dsn=dsn)
        if features_df.empty:
            logger.error("Feature hesaplanamadi (bos DataFrame): %s / %s", fuel_type, target_date)
            return None
    except Exception as exc:
        logger.error("Feature hesaplama hatasi: %s / %s — %s", fuel_type, target_date, exc)
        return None

    # Feature matrisi
    X = features_df[list(FEATURE_NAMES)].values

    # Feature dict'i kaydet (alarm için)
    feature_dict = features_df[list(FEATURE_NAMES)].iloc[0].to_dict()

    # 2. Stage-1 model -> binary probability
    stage1_model = _load_model(fuel_type, "stage1")
    if stage1_model is None:
        logger.warning("Stage-1 model bulunamadi: %s — tahmin yapilamiyor", fuel_type)
        return None

    try:
        stage1_prob_raw = float(stage1_model.predict_proba(X)[:, 1][0])
    except Exception as exc:
        logger.error("Stage-1 tahmin hatasi: %s — %s", fuel_type, exc)
        return None

    # 3. Kalibrasyon — v6: USE_CALIBRATION flag'ine bağlı
    calibration_method = "raw"
    stage1_prob = stage1_prob_raw

    if USE_CALIBRATION and apply_calibration is not None and load_calibrator is not None:
        try:
            calibrator = _load_model(fuel_type, "calibrator")
            if calibrator is not None:
                calibrated = apply_calibration(calibrator, np.array([stage1_prob_raw]))
                stage1_prob = float(calibrated[0])
                calibration_method = getattr(calibrator, "method", "calibrated")
                logger.info("Kalibrasyon uygulandi (%s): raw=%.4f -> calibrated=%.4f", calibration_method, stage1_prob_raw, stage1_prob)
            else:
                logger.warning("Kalibrator bulunamadi: %s — raw probability kullaniliyor", fuel_type)
        except Exception as exc:
            logger.warning("Kalibrasyon hatasi: %s — raw probability kullaniliyor: %s", fuel_type, exc)
    else:
        logger.info("Kalibrasyon devre disi (USE_CALIBRATION=%s) — raw probability kullaniliyor", USE_CALIBRATION)

    # 4. Stage-2 (koşullu) — v6: düşük eşik
    first_event_amount = 0.0
    net_amount_3d = 0.0
    first_event_direction = 0

    if stage1_prob >= _STAGE1_THRESHOLD:
        # Stage-2: first_event_amount
        stage2_first = _load_model(fuel_type, "stage2_first")
        if stage2_first is not None:
            try:
                first_event_amount = float(stage2_first.predict(X)[0])
                clip_limit = _CLIP_LIMITS.get(fuel_type, _CLIP_LIMITS["benzin"])
                first_event_amount = float(np.clip(first_event_amount, -clip_limit["first_event"], clip_limit["first_event"]))
                first_event_direction = 1 if first_event_amount > 0 else -1
            except Exception as exc:
                logger.warning("Stage-2 first_event hatasi: %s — %s", fuel_type, exc)
                first_event_amount = 0.0
        else:
            logger.warning("Stage-2 first model yok: %s — first_event=0", fuel_type)

        # Stage-2: net_amount_3d
        stage2_net = _load_model(fuel_type, "stage2_net")
        if stage2_net is not None:
            try:
                net_amount_3d_raw = float(stage2_net.predict(X)[0])
                clip_limit_net = _CLIP_LIMITS.get(fuel_type, _CLIP_LIMITS["benzin"])
                net_amount_3d = float(np.clip(net_amount_3d_raw, -clip_limit_net["net_3d"], clip_limit_net["net_3d"]))
                if abs(net_amount_3d_raw - net_amount_3d) > 0.001:
                    logger.info("Stage-2 net clipped: %.4f -> %.4f", net_amount_3d_raw, net_amount_3d)
            except Exception as exc:
                logger.warning("Stage-2 net_amount hatasi: %s — %s", fuel_type, exc)
                net_amount_3d = 0.0
        else:
            logger.warning("Stage-2 net model yok: %s — net_amount=0", fuel_type)
    else:
        logger.info("Stage-1 prob (%.4f) < threshold (%.2f) — Stage-2 atlandi", stage1_prob, _STAGE1_THRESHOLD)

    # 5. Alarm değerlendirmesi — v6: features dict iletilir
    prediction_for_alarm = {
        "fuel_type": fuel_type,
        "stage1_probability": Decimal(str(round(stage1_prob, 6))),
        "first_event_direction": first_event_direction,
        "first_event_amount": Decimal(str(round(first_event_amount, 6))),
        "net_amount_3d": Decimal(str(round(net_amount_3d, 6))),
    }

    # Risk trend
    risk_scores = _fetch_recent_risk_scores(fuel_type, target_date, dsn=dsn)
    risk_trend = compute_risk_trend(risk_scores)

    # Son alarm zamanı
    last_alarm_time = None
    try:
        latest_pred = get_latest_prediction_sync(fuel_type, dsn=dsn)
        if latest_pred and latest_pred.get("alarm_triggered"):
            updated_at = latest_pred.get("updated_at")
            if isinstance(updated_at, datetime):
                last_alarm_time = updated_at
    except Exception:
        pass

    # Fiyat değişimi
    try:
        price_changed = get_price_changed_today(fuel_type, target_date, dsn=dsn)
    except Exception:
        price_changed = False

    last_price_change_time = None

    alarm_result = evaluate_alarm(
        prediction=prediction_for_alarm,
        risk_trend=risk_trend,
        last_alarm_time=last_alarm_time,
        last_price_change_time=last_price_change_time,
        price_changed_today=price_changed,
        features=feature_dict,  # v6: deterministik alarm için
    )

    # 6. Sonuç dict
    stage1_label = 1 if stage1_prob >= _STAGE1_THRESHOLD else 0

    if first_event_direction == 1:
        first_event_type = "artis"
    elif first_event_direction == -1:
        first_event_type = "dusus"
    else:
        first_event_type = None

    result = {
        "fuel_type": fuel_type,
        "target_date": target_date.isoformat(),
        "stage1_probability": round(stage1_prob, 6),
        "stage1_probability_raw": round(stage1_prob_raw, 6),
        "stage1_label": bool(stage1_label),
        "first_event_direction": first_event_direction,
        "first_event_amount": round(first_event_amount, 6),
        "first_event_type": first_event_type,
        "net_amount_3d": round(net_amount_3d, 6),
        "alarm": {
            "should_alarm": alarm_result.get("should_alarm", False),
            "alarm_type": alarm_result.get("alarm_type"),
            "message": alarm_result.get("message"),
            "confidence": alarm_result.get("confidence", stage1_prob),
            "deterministic_rules": alarm_result.get("deterministic_rules"),
        },
        "risk_trend": risk_trend,
        "calibration_method": calibration_method,
        "model_version": "v5",
        "predicted_at": datetime.utcnow().isoformat(),
    }

    # 7. DB kayıt
    try:
        db_record = {
            "run_date": target_date,
            "fuel_type": fuel_type,
            "stage1_probability": result["stage1_probability"],
            "stage1_label": bool(stage1_label),
            "first_event_direction": first_event_direction,
            "first_event_amount": first_event_amount,
            "first_event_type": first_event_type,
            "net_amount_3d": net_amount_3d,
            "model_version": "v5",
            "calibration_method": calibration_method,
            "alarm_triggered": alarm_result.get("should_alarm", False),
            "alarm_suppressed": alarm_result.get("cooldown_active", False),
            "suppression_reason": "cooldown" if alarm_result.get("cooldown_active") else None,
            "alarm_message": alarm_result.get("message"),
        }
        save_prediction_sync(db_record, dsn=dsn)
        logger.info("Tahmin DB'ye kaydedildi: %s / %s", fuel_type, target_date)
    except Exception as exc:
        logger.error("DB kayit hatasi (tahmin yine donuyor): %s — %s", fuel_type, exc)

    # 8. Feature snapshot
    try:
        store_snapshot(fuel_type, target_date, feature_dict, feature_version="v5.0", dsn=dsn)
        logger.info("Feature snapshot kaydedildi: %s / %s", fuel_type, target_date)
    except Exception as exc:
        logger.error("Feature snapshot hatasi: %s — %s", fuel_type, exc)

    logger.info(
        "Tahmin tamamlandi: %s / %s — prob=%.4f (raw=%.4f), dir=%d, alarm=%s",
        fuel_type,
        target_date,
        stage1_prob,
        stage1_prob_raw,
        first_event_direction,
        alarm_result.get("should_alarm"),
    )

    return result


def predict_all(
    target_date: Optional[date] = None,
    db_url: Optional[str] = None,
) -> dict:
    """3 yakıt tipi için tahmin."""
    results = {}
    for fuel in FUEL_TYPES:
        try:
            results[fuel] = predict(fuel, target_date=target_date, db_url=db_url)
        except Exception as exc:
            logger.error("predict_all hatasi: %s — %s", fuel, exc)
            results[fuel] = None
    return results


def clear_model_cache() -> None:
    """Model cache'i temizle."""
    global _model_cache
    count = len(_model_cache)
    _model_cache.clear()
    logger.info("Model cache temizlendi: %d model silindi", count)
