"""
ML tahmin repository katmani.

UPSERT pattern ile ml_predictions tablosuna veri yazma,
sorgulama islemleri. Tum fonksiyonlar async olarak calisir.
"""

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.ml_predictions import MLPrediction

logger = logging.getLogger(__name__)


async def upsert_ml_prediction(
    session: AsyncSession,
    *,
    fuel_type: str,
    prediction_date: date,
    predicted_direction: str,
    probability_hike: Decimal,
    probability_stable: Decimal,
    probability_cut: Decimal,
    expected_change_tl: Decimal | None = None,
    model_version: str,
    system_mode: str = "full",
    shap_top_features: dict | list | None = None,
) -> MLPrediction:
    """
    ML tahmin kaydini ekler veya gunceller (UPSERT).

    ON CONFLICT (fuel_type, prediction_date) DO UPDATE ile calisir.

    Args:
        session: Async veritabani oturumu.
        fuel_type: Yakit tipi (benzin, motorin, lpg).
        prediction_date: Tahmin tarihi.
        predicted_direction: Tahmin yonu (hike, stable, cut).
        probability_hike: Zam olasiligi.
        probability_stable: Sabit olasiligi.
        probability_cut: Indirim olasiligi.
        expected_change_tl: Beklenen degisim TL/L.
        model_version: Model versiyonu.
        system_mode: Sistem modu.
        shap_top_features: Top SHAP feature katkilari.

    Returns:
        Eklenen veya guncellenen MLPrediction kaydi.
    """
    values = {
        "fuel_type": fuel_type,
        "prediction_date": prediction_date,
        "predicted_direction": predicted_direction,
        "probability_hike": probability_hike,
        "probability_stable": probability_stable,
        "probability_cut": probability_cut,
        "expected_change_tl": expected_change_tl,
        "model_version": model_version,
        "system_mode": system_mode,
        "shap_top_features": shap_top_features,
    }

    stmt = pg_insert(MLPrediction).values(**values)

    update_fields = {
        k: v for k, v in values.items()
        if k not in ("fuel_type", "prediction_date")
    }
    update_fields["updated_at"] = text("NOW()")

    stmt = stmt.on_conflict_do_update(
        constraint="uq_ml_pred_fuel_date",
        set_=update_fields,
    ).returning(MLPrediction)

    result = await session.execute(stmt)
    row = result.scalar_one()

    logger.info(
        "ML tahmin upsert: %s / %s (yon=%s, p_hike=%s, mode=%s)",
        prediction_date,
        fuel_type,
        predicted_direction,
        probability_hike,
        system_mode,
    )

    return row


async def get_latest_prediction(
    session: AsyncSession,
    fuel_type: str,
) -> MLPrediction | None:
    """
    Belirli yakit tipi icin en son ML tahminini dondurur.

    Args:
        session: Async veritabani oturumu.
        fuel_type: Yakit tipi.

    Returns:
        MLPrediction veya None.
    """
    stmt = (
        select(MLPrediction)
        .where(MLPrediction.fuel_type == fuel_type)
        .order_by(MLPrediction.prediction_date.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_prediction_by_id(
    session: AsyncSession,
    prediction_id: int,
) -> MLPrediction | None:
    """
    ID ile ML tahmin kaydini dondurur.

    Args:
        session: Async veritabani oturumu.
        prediction_id: Tahmin kaydi ID.

    Returns:
        MLPrediction veya None.
    """
    stmt = select(MLPrediction).where(MLPrediction.id == prediction_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_predictions_range(
    session: AsyncSession,
    fuel_type: str,
    start_date: date,
    end_date: date,
) -> list[MLPrediction]:
    """
    Tarih araligindaki ML tahminlerini dondurur.

    Args:
        session: Async veritabani oturumu.
        fuel_type: Yakit tipi.
        start_date: Baslangic tarihi (dahil).
        end_date: Bitis tarihi (dahil).

    Returns:
        MLPrediction listesi (prediction_date'e gore sirali).
    """
    stmt = (
        select(MLPrediction)
        .where(
            MLPrediction.fuel_type == fuel_type,
            MLPrediction.prediction_date >= start_date,
            MLPrediction.prediction_date <= end_date,
        )
        .order_by(MLPrediction.prediction_date.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_hike_predictions(
    session: AsyncSession,
    fuel_type: str,
    min_probability: Decimal = Decimal("0.50"),
    limit: int = 10,
) -> list[MLPrediction]:
    """
    Yuksek zam olasilikli tahminleri dondurur.

    Args:
        session: Async veritabani oturumu.
        fuel_type: Yakit tipi.
        min_probability: Minimum zam olasiligi (varsayilan 0.50).
        limit: Maksimum kayit sayisi.

    Returns:
        MLPrediction listesi.
    """
    stmt = (
        select(MLPrediction)
        .where(
            MLPrediction.fuel_type == fuel_type,
            MLPrediction.probability_hike >= min_probability,
        )
        .order_by(MLPrediction.prediction_date.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
