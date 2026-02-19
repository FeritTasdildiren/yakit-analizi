"""
Predictor v5 repository katmanı.

Sync (psycopg2) + Async (SQLAlchemy) dual pattern.
UPSERT: ON CONFLICT (run_date, fuel_type) DO UPDATE.

Sync fonksiyonlar Celery/pipeline için, async fonksiyonlar FastAPI endpoint için.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Optional

import psycopg2
import psycopg2.extras
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.predictions_v5 import PredictionV5

logger = logging.getLogger(__name__)

DB_DSN = "postgresql://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi"

# ---------------------------------------------------------------------------
#  Yardımcı: Decimal → float dönüşümü (JSONB uyumu)
# ---------------------------------------------------------------------------


def _dec_to_float(val):
    """Decimal değeri float'a çevir, None ise None döndür."""
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    return val


# ===========================================================================
#  SYNC — psycopg2 (Celery / pipeline)
# ===========================================================================

_UPSERT_SQL = """
INSERT INTO predictions_v5 (
    run_date, fuel_type,
    stage1_probability, stage1_label,
    first_event_direction, first_event_amount, first_event_type,
    net_amount_3d,
    model_version, calibration_method,
    alarm_triggered, alarm_suppressed, suppression_reason, alarm_message
) VALUES (
    %(run_date)s, %(fuel_type)s,
    %(stage1_probability)s, %(stage1_label)s,
    %(first_event_direction)s, %(first_event_amount)s, %(first_event_type)s,
    %(net_amount_3d)s,
    %(model_version)s, %(calibration_method)s,
    %(alarm_triggered)s, %(alarm_suppressed)s, %(suppression_reason)s, %(alarm_message)s
)
ON CONFLICT (run_date, fuel_type, model_version) DO UPDATE SET
    stage1_probability   = EXCLUDED.stage1_probability,
    stage1_label         = EXCLUDED.stage1_label,
    first_event_direction = EXCLUDED.first_event_direction,
    first_event_amount   = EXCLUDED.first_event_amount,
    first_event_type     = EXCLUDED.first_event_type,
    net_amount_3d        = EXCLUDED.net_amount_3d,
    model_version        = EXCLUDED.model_version,
    calibration_method   = EXCLUDED.calibration_method,
    alarm_triggered      = EXCLUDED.alarm_triggered,
    alarm_suppressed     = EXCLUDED.alarm_suppressed,
    suppression_reason   = EXCLUDED.suppression_reason,
    alarm_message        = EXCLUDED.alarm_message,
    updated_at           = NOW()
"""

_SELECT_LATEST_SQL = """
SELECT id, run_date, fuel_type,
       stage1_probability, stage1_label,
       first_event_direction, first_event_amount, first_event_type,
       net_amount_3d,
       model_version, calibration_method,
       alarm_triggered, alarm_suppressed, suppression_reason, alarm_message,
       created_at, updated_at
FROM predictions_v5
WHERE fuel_type = %(fuel_type)s
  AND model_version != 'v5-backfill'
ORDER BY run_date DESC
LIMIT 1
"""

_SELECT_LATEST_FALLBACK_SQL = """
SELECT id, run_date, fuel_type,
       stage1_probability, stage1_label,
       first_event_direction, first_event_amount, first_event_type,
       net_amount_3d,
       model_version, calibration_method,
       alarm_triggered, alarm_suppressed, suppression_reason, alarm_message,
       created_at, updated_at
FROM predictions_v5
WHERE fuel_type = %(fuel_type)s
ORDER BY run_date DESC
LIMIT 1
"""

_SELECT_RANGE_SQL = """
SELECT id, run_date, fuel_type,
       stage1_probability, stage1_label,
       first_event_direction, first_event_amount, first_event_type,
       net_amount_3d,
       model_version, calibration_method,
       alarm_triggered, alarm_suppressed, suppression_reason, alarm_message,
       created_at, updated_at
FROM predictions_v5
WHERE fuel_type = %(fuel_type)s
  AND run_date >= %(start_date)s
  AND run_date <= %(end_date)s
ORDER BY run_date ASC
"""


def _row_to_dict(row, cursor) -> dict:
    """cursor.description ile satırı dict'e çevir."""
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


def save_prediction_sync(prediction_data: dict, dsn: str = DB_DSN) -> None:
    """
    UPSERT: ON CONFLICT (run_date, fuel_type) DO UPDATE.

    prediction_data dict anahtarları:
        run_date, fuel_type, stage1_probability, stage1_label,
        first_event_direction, first_event_amount, first_event_type,
        net_amount_3d, model_version, calibration_method,
        alarm_triggered, alarm_suppressed, suppression_reason, alarm_message
    """
    params = {
        "run_date": prediction_data["run_date"],
        "fuel_type": prediction_data["fuel_type"],
        "stage1_probability": prediction_data.get("stage1_probability"),
        "stage1_label": prediction_data.get("stage1_label"),
        "first_event_direction": prediction_data.get("first_event_direction"),
        "first_event_amount": prediction_data.get("first_event_amount"),
        "first_event_type": prediction_data.get("first_event_type"),
        "net_amount_3d": prediction_data.get("net_amount_3d"),
        "model_version": prediction_data.get("model_version"),
        "calibration_method": prediction_data.get("calibration_method"),
        "alarm_triggered": prediction_data.get("alarm_triggered", False),
        "alarm_suppressed": prediction_data.get("alarm_suppressed", False),
        "suppression_reason": prediction_data.get("suppression_reason"),
        "alarm_message": prediction_data.get("alarm_message"),
    }

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(_UPSERT_SQL, params)
        conn.commit()
        logger.info(
            "Prediction upsert (sync): %s / %s (prob=%s)",
            params["run_date"],
            params["fuel_type"],
            params["stage1_probability"],
        )
    finally:
        conn.close()


def get_latest_prediction_sync(fuel_type: str, dsn: str = DB_DSN) -> Optional[dict]:
    """Son tahmin kaydini getir (backfill haric, fallback ile)."""
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            # Once normal v5 kaydini dene
            cur.execute(_SELECT_LATEST_SQL, {"fuel_type": fuel_type})
            row = cur.fetchone()
            if row is not None:
                return _row_to_dict(row, cur)
            # Normal v5 yoksa backfill dahil fallback
            cur.execute(_SELECT_LATEST_FALLBACK_SQL, {"fuel_type": fuel_type})
            row = cur.fetchone()
            if row is None:
                return None
            return _row_to_dict(row, cur)
    finally:
        conn.close()


def get_predictions_sync(
    fuel_type: str,
    start_date: date,
    end_date: date,
    dsn: str = DB_DSN,
) -> list[dict]:
    """Tarih aralığı için tahminler."""
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                _SELECT_RANGE_SQL,
                {
                    "fuel_type": fuel_type,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
            rows = cur.fetchall()
            return [_row_to_dict(r, cur) for r in rows]
    finally:
        conn.close()


# ===========================================================================
#  ASYNC — SQLAlchemy (FastAPI endpoint)
# ===========================================================================


async def save_prediction_async(
    session: AsyncSession,
    prediction_data: dict,
) -> PredictionV5:
    """
    Async UPSERT: ON CONFLICT (run_date, fuel_type) DO UPDATE.

    Proje standart pattern: pg_insert -> on_conflict_do_update -> returning.
    """
    values = {
        "run_date": prediction_data["run_date"],
        "fuel_type": prediction_data["fuel_type"],
        "stage1_probability": prediction_data.get("stage1_probability"),
        "stage1_label": prediction_data.get("stage1_label"),
        "first_event_direction": prediction_data.get("first_event_direction"),
        "first_event_amount": prediction_data.get("first_event_amount"),
        "first_event_type": prediction_data.get("first_event_type"),
        "net_amount_3d": prediction_data.get("net_amount_3d"),
        "model_version": prediction_data.get("model_version"),
        "calibration_method": prediction_data.get("calibration_method"),
        "alarm_triggered": prediction_data.get("alarm_triggered", False),
        "alarm_suppressed": prediction_data.get("alarm_suppressed", False),
        "suppression_reason": prediction_data.get("suppression_reason"),
        "alarm_message": prediction_data.get("alarm_message"),
    }

    stmt = pg_insert(PredictionV5).values(**values)

    update_fields = {
        k: v for k, v in values.items()
        if k not in ("run_date", "fuel_type")
    }
    update_fields["updated_at"] = text("NOW()")

    stmt = stmt.on_conflict_do_update(
        constraint="uq_predictions_v5_run_fuel_version",
        set_=update_fields,
    ).returning(PredictionV5)

    result = await session.execute(stmt)
    row = result.scalar_one()

    logger.info(
        "Prediction upsert (async): %s / %s (prob=%s)",
        values["run_date"],
        values["fuel_type"],
        values.get("stage1_probability"),
    )
    return row


async def get_latest_prediction_async(
    session: AsyncSession,
    fuel_type: str,
) -> Optional[PredictionV5]:
    """Async son tahmin (backfill haric, fallback ile)."""
    # Once normal v5 kaydini dene
    stmt = (
        select(PredictionV5)
        .where(
            PredictionV5.fuel_type == fuel_type,
            PredictionV5.model_version != "v5-backfill",
        )
        .order_by(PredictionV5.run_date.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    prediction = result.scalar_one_or_none()
    if prediction is not None:
        return prediction
    # Normal v5 yoksa backfill dahil fallback
    stmt_fallback = (
        select(PredictionV5)
        .where(PredictionV5.fuel_type == fuel_type)
        .order_by(PredictionV5.run_date.desc())
        .limit(1)
    )
    result_fb = await session.execute(stmt_fallback)
    return result_fb.scalar_one_or_none()


async def get_predictions_async(
    session: AsyncSession,
    fuel_type: str,
    start_date: date,
    end_date: date,
) -> list[PredictionV5]:
    """Async tarih araligi tahminleri."""
    stmt = (
        select(PredictionV5)
        .where(
            PredictionV5.fuel_type == fuel_type,
            PredictionV5.run_date >= start_date,
            PredictionV5.run_date <= end_date,
        )
        .order_by(PredictionV5.run_date.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
