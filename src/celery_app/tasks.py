"""
Celery zamanlanmış görev tanımları.

Günlük veri toplama, ML tahmin çalıştırma, bildirim gönderme
ve sistem sağlık kontrolü görevlerini tanımlar.

Her task sync Celery worker'da çalışır; async fonksiyonlar
asyncio.run() ile sarmalanır.
"""

import asyncio
import logging
from datetime import UTC, date, datetime

from src.celery_app.celery_config import celery_app
from src.config.settings import settings

logger = logging.getLogger(__name__)


# ── Task 1: Günlük Piyasa Verisi Toplama ────────────────────────────────────


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300)
def collect_daily_market_data(self):
    """
    Günlük piyasa verisi topla: Brent, FX, EPDK.

    Zamanlama: Her gün 18:00 UTC (21:00 TSİ)
    Retry: 3 deneme, 5 dakika aralıkla.
    """
    logger.info("Günlük piyasa verisi toplama başlıyor...")

    try:
        results = asyncio.run(_collect_all_data())
        logger.info("Veri toplama tamamlandı: %s", results)
        return results
    except Exception as exc:
        logger.exception("Veri toplama hatası: %s", exc)
        raise self.retry(exc=exc)


async def _collect_all_data() -> dict:
    """Tüm veri kaynaklarından günlük veri çek."""
    from src.data_collectors.brent_collector import fetch_brent_daily
    from src.data_collectors.epdk_collector import fetch_turkey_average
    from src.data_collectors.fx_collector import fetch_usd_try_daily

    today = date.today()
    results = {}

    # 1. Brent petrol fiyatı
    try:
        brent_data = await fetch_brent_daily(today)
        if brent_data is not None:
            results["brent"] = {
                "brent_usd_bbl": str(brent_data.brent_usd_bbl),
                "cif_med_estimate_usd_ton": str(brent_data.cif_med_estimate_usd_ton),
                "source": brent_data.source,
            }
            logger.info(
                "Brent verisi alındı: %s USD/bbl (%s)",
                brent_data.brent_usd_bbl,
                brent_data.source,
            )
        else:
            results["brent"] = None
            logger.warning("Brent verisi alınamadı")
    except Exception as e:
        results["brent"] = f"HATA: {e}"
        logger.exception("Brent veri toplama hatası")

    # 2. USD/TRY döviz kuru
    try:
        fx_data = await fetch_usd_try_daily(today)
        if fx_data is not None:
            results["fx"] = {
                "usd_try_rate": str(fx_data.usd_try_rate),
                "source": fx_data.source,
            }
            logger.info(
                "FX verisi alındı: %s TRY (%s)",
                fx_data.usd_try_rate,
                fx_data.source,
            )
        else:
            results["fx"] = None
            logger.warning("FX verisi alınamadı")
    except Exception as e:
        results["fx"] = f"HATA: {e}"
        logger.exception("FX veri toplama hatası")

    # 3. EPDK pompa fiyatları (Türkiye ortalaması)
    try:
        epdk_averages = await fetch_turkey_average(today)
        if epdk_averages:
            results["epdk"] = {
                fuel_type: str(price)
                for fuel_type, price in epdk_averages.items()
            }
            logger.info("EPDK Türkiye ortalaması alındı: %s", epdk_averages)
        else:
            results["epdk"] = None
            logger.warning("EPDK verisi alınamadı")
    except Exception as e:
        results["epdk"] = f"HATA: {e}"
        logger.exception("EPDK veri toplama hatası")

    return results


# ── Task 2: Günlük ML Tahmin ────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120)
def run_daily_prediction(self):
    """
    Günlük ML tahmin çalıştır: benzin + motorin.

    Zamanlama: Her gün 18:30 UTC (21:30 TSİ)
    Retry: 2 deneme, 2 dakika aralıkla.
    """
    logger.info("Günlük ML tahmin başlıyor...")

    try:
        results = asyncio.run(_run_predictions())
        logger.info("ML tahmin tamamlandı: %s", results)
        return results
    except Exception as exc:
        logger.exception("ML tahmin hatası: %s", exc)
        raise self.retry(exc=exc)


async def _run_predictions() -> dict:
    """Her yakıt türü için ML tahmin çalıştır."""
    from src.config.database import async_session_factory
    from src.ml.predictor import get_predictor
    from src.repositories.ml_repository import upsert_ml_prediction

    predictor = get_predictor()

    # Model yüklü değilse yükle
    if not predictor.is_loaded:
        loaded = predictor.load_model()
        if not loaded:
            logger.error("ML model yüklenemedi — tahmin atlanıyor")
            return {"error": "Model yüklenemedi"}

    results = {}
    today = date.today()

    for fuel_type in ["benzin", "motorin"]:
        try:
            # Tahmin yap (fallback destekli)
            features = _get_placeholder_features()
            prediction = predictor.predict_with_fallback(features)

            # DB'ye kaydet
            async with async_session_factory() as session:
                try:
                    await upsert_ml_prediction(
                        session,
                        fuel_type=fuel_type,
                        prediction_date=today,
                        predicted_direction=prediction.predicted_direction,
                        probability_hike=prediction.probability_hike,
                        probability_stable=prediction.probability_stable,
                        probability_cut=prediction.probability_cut,
                        expected_change_tl=prediction.expected_change_tl,
                        model_version=prediction.model_version,
                        system_mode=prediction.system_mode,
                        shap_top_features=prediction.shap_top_features,
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

            results[fuel_type] = {
                "direction": prediction.predicted_direction,
                "probability_hike": str(prediction.probability_hike),
                "confidence": prediction.confidence,
                "system_mode": prediction.system_mode,
            }
            logger.info(
                "%s tahmini: %s (p_hike=%s, mode=%s)",
                fuel_type,
                prediction.predicted_direction,
                prediction.probability_hike,
                prediction.system_mode,
            )

        except Exception as e:
            results[fuel_type] = f"HATA: {e}"
            logger.exception("%s tahmin hatası", fuel_type)

    return results


def _get_placeholder_features() -> dict[str, float]:
    """
    Placeholder feature sözlüğü döndürür.

    NOT: Gerçek pipeline'da bu fonksiyon yerine compute_all_features()
    kullanılacak. Şu an DB'den geçmiş veri çekilip feature hesaplanması
    gerektiğinden, bu placeholder ile predict_with_fallback çağrılır.
    """
    from src.ml.feature_engineering import FEATURE_NAMES

    return {name: 0.0 for name in FEATURE_NAMES}


# ── Task 3: Günlük Bildirim Gönderme ────────────────────────────────────────


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def send_daily_notifications(self):
    """
    Onaylı Telegram kullanıcılarına günlük bildirim gönder.

    Zamanlama: Her gün 07:00 UTC (10:00 TSİ)
    Retry: 2 deneme, 1 dakika aralıkla.

    NOT: Telegram modülü (TASK-019) tamamlandığında gerçek bildirim gönderir.
    Henüz mevcut değilse loglayıp çıkar.
    """
    logger.info("Günlük bildirim gönderme başlıyor...")

    try:
        result = asyncio.run(_send_notifications())
        logger.info("Bildirim gönderme tamamlandı: %s", result)
        return result
    except Exception as exc:
        logger.exception("Bildirim gönderme hatası: %s", exc)
        raise self.retry(exc=exc)


async def _send_notifications() -> dict:
    """Tüm aktif+onaylı kullanıcılara bildirim gönder."""
    try:
        from src.telegram.notifications import (
            send_daily_notifications as _send,
        )

        await _send()
        return {"status": "sent"}
    except ImportError:
        logger.warning(
            "Telegram modülü henüz mevcut değil (TASK-019). "
            "Bildirim atlanıyor."
        )
        return {"status": "skipped", "reason": "telegram_module_not_found"}


# ── Task 4: Sistem Sağlık Kontrolü ──────────────────────────────────────────


@celery_app.task
def health_check():
    """
    Sistem sağlık kontrolü.

    Zamanlama: Her 30 dakikada bir.
    DB, Redis ve ML model durumunu kontrol eder.
    """
    logger.info("Sağlık kontrolü başlıyor...")
    result = asyncio.run(_check_health())
    logger.info("Sağlık kontrolü tamamlandı: %s", result)
    return result


async def _check_health() -> dict:
    """DB bağlantısı, Redis ve ML model durumunu kontrol et."""
    status = {
        "db": False,
        "redis": False,
        "ml_model": False,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # DB kontrolü
    try:
        from sqlalchemy import text as sa_text

        from src.config.database import async_session_factory

        async with async_session_factory() as session:
            await session.execute(sa_text("SELECT 1"))
        status["db"] = True
    except Exception as e:
        logger.warning("DB sağlık kontrolü başarısız: %s", e)

    # Redis kontrolü
    try:
        import redis

        r = redis.from_url(settings.REDIS_URL)
        r.ping()
        status["redis"] = True
    except Exception as e:
        logger.warning("Redis sağlık kontrolü başarısız: %s", e)

    # ML model kontrolü
    try:
        from src.ml.predictor import get_predictor

        predictor = get_predictor()
        status["ml_model"] = predictor.is_loaded
    except Exception as e:
        logger.warning("ML model sağlık kontrolü başarısız: %s", e)

    return status
