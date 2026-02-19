"""
Celery zamanlanmış görev tanımları.

Günlük veri toplama, ML tahmin çalıştırma, bildirim gönderme
ve sistem sağlık kontrolü görevlerini tanımlar.

Her task sync Celery worker'da çalışır; async fonksiyonlar
asyncio.run() ile sarmalanır.

TASK-025 güncellemesi:
- collect_daily_market_data: Veri DB'ye upsert edilecek şekilde güncellendi
- run_daily_prediction: placeholder → _fetch_and_compute_features (DB'den gerçek veri)
- LPG desteği eklendi
- ML model yoksa graceful skip
"""

import asyncio
import logging
from datetime import UTC, date, datetime
from decimal import Decimal

from src.celery_app.celery_config import celery_app
from src.config.settings import settings

logger = logging.getLogger(__name__)


# ── Task 1: Günlük Piyasa Verisi Toplama ────────────────────────────────────


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300)
def collect_daily_market_data(self):
    """
    Günlük piyasa verisi topla: Brent, FX, EPDK → DB'ye kaydet.

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
    """Tüm veri kaynaklarından günlük veri çek ve DB'ye kaydet."""
    from src.config.database import async_session_factory
    from src.data_collectors.brent_collector import fetch_brent_daily
    from src.data_collectors.epdk_collector import fetch_turkey_average
    from src.data_collectors.fx_collector import fetch_usd_try_daily
    from src.data_collectors.market_data_repository import upsert_market_data

    today = date.today()
    results = {}

    # Toplanan ham verileri tutacak değişkenler
    brent_data = None
    fx_data = None
    epdk_averages = {}

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
            epdk_averages = {}
            results["epdk"] = None
            logger.warning("EPDK verisi alınamadı")
    except Exception as e:
        epdk_averages = {}
        results["epdk"] = f"HATA: {e}"
        logger.exception("EPDK veri toplama hatası")

    # 4. Toplanan verileri DB'ye kaydet (her yakıt tipi için ayrı satır)
    db_saved = 0
    try:
        async with async_session_factory() as session:
            try:
                for fuel_type in ["benzin", "motorin", "lpg"]:
                    pump_price = epdk_averages.get(fuel_type)
                    sources = []

                    # Kaynak bilgisini derle
                    if brent_data:
                        sources.append(brent_data.source)
                    if fx_data:
                        sources.append(fx_data.source)
                    if pump_price is not None:
                        sources.append("petrol_ofisi")

                    source_str = "+".join(sources) if sources else "partial"

                    await upsert_market_data(
                        session,
                        trade_date=today,
                        fuel_type=fuel_type,
                        brent_usd_bbl=(
                            brent_data.brent_usd_bbl if brent_data else None
                        ),
                        cif_med_usd_ton=(
                            brent_data.cif_med_estimate_usd_ton
                            if brent_data
                            else None
                        ),
                        usd_try_rate=(
                            fx_data.usd_try_rate if fx_data else None
                        ),
                        pump_price_tl_lt=pump_price,
                        data_quality_flag=(
                            "verified"
                            if brent_data and fx_data and pump_price
                            else "estimated"
                        ),
                        source=source_str,
                    )
                    db_saved += 1
                    logger.info(
                        "DB'ye kaydedildi: %s/%s (kaynak: %s)",
                        today,
                        fuel_type,
                        source_str,
                    )

                await session.commit()
            except Exception:
                await session.rollback()
                raise

        results["db_saved"] = db_saved
        logger.info("Toplam %d kayıt DB'ye yazıldı", db_saved)

    except Exception as e:
        results["db_error"] = str(e)
        logger.exception("DB kayıt hatası")

    return results


# ── Task 2: Günlük ML Tahmin ────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120)
def run_daily_prediction(self):
    """
    Günlük ML tahmin çalıştır: benzin, motorin, LPG.

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
            logger.warning(
                "ML model dosyası bulunamadı — ilk eğitim henüz yapılmamış. "
                "Tahmin atlanıyor. Model eğitmek için: POST /api/v1/ml/train"
            )
            return {"status": "skipped", "reason": "model_not_found"}

    results = {}
    today = date.today()

    for fuel_type in ["benzin", "motorin", "lpg"]:
        try:
            # DB'den gerçek feature hesapla
            features = await _fetch_and_compute_features(fuel_type, today)

            # Tahmin yap (fallback destekli)
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


async def _fetch_and_compute_features(
    fuel_type: str, target_date: date
) -> dict[str, float]:
    """
    DB'den piyasa verisi çekip ML feature'ları hesaplar.

    Strateji:
    1. daily_market_data'dan son N günlük veriyi çek
    2. mbe_calculations'dan MBE geçmişini çek
    3. tax_parameters'dan güncel vergiyi çek
    4. compute_all_features() ile feature vektörü oluştur

    Veri yetersizse sıfır değerlerle fallback yapar — ML durmuyor.

    Args:
        fuel_type: Yakıt tipi (benzin, motorin, lpg)
        target_date: Tahmin tarihi

    Returns:
        Feature adı → değer sözlüğü
    """
    from datetime import timedelta

    from src.config.database import async_session_factory
    from src.ml.feature_engineering import FEATURE_NAMES, compute_all_features

    # Varsayılan sıfır feature'lar (fallback)
    zero_features = {name: 0.0 for name in FEATURE_NAMES}

    try:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from sqlalchemy.sql import func

            from src.models.market_data import DailyMarketData
            from src.models.mbe_calculations import MBECalculation
            from src.models.tax_parameters import TaxParameter

            # Son 15 günlük piyasa verisi çek
            lookback_start = target_date - timedelta(days=15)
            market_stmt = (
                select(DailyMarketData)
                .where(
                    DailyMarketData.fuel_type == fuel_type,
                    DailyMarketData.trade_date >= lookback_start,
                    DailyMarketData.trade_date <= target_date,
                )
                .order_by(DailyMarketData.trade_date.asc())
            )
            market_result = await session.execute(market_stmt)
            market_rows = list(market_result.scalars().all())

            if not market_rows:
                logger.warning(
                    "%s için piyasa verisi bulunamadı — sıfır feature fallback",
                    fuel_type,
                )
                return zero_features

            # En son kaydı al
            latest = market_rows[-1]
            brent = float(latest.brent_usd_bbl or Decimal("0"))
            fx = float(latest.usd_try_rate or Decimal("0"))
            cif = float(latest.cif_med_usd_ton or Decimal("0"))
            pump = float(latest.pump_price_tl_lt or Decimal("0"))

            # Geçmiş seriler oluştur
            brent_history = [
                float(r.brent_usd_bbl or 0) for r in market_rows
            ]
            fx_history = [
                float(r.usd_try_rate or 0) for r in market_rows
            ]
            cif_history = [
                float(r.cif_med_usd_ton or 0) for r in market_rows
            ]

            # MBE geçmişi çek
            mbe_stmt = (
                select(MBECalculation)
                .where(
                    MBECalculation.fuel_type == fuel_type,
                    MBECalculation.trade_date >= lookback_start,
                    MBECalculation.trade_date <= target_date,
                )
                .order_by(MBECalculation.trade_date.asc())
            )
            mbe_result = await session.execute(mbe_stmt)
            mbe_rows = list(mbe_result.scalars().all())

            mbe_value = 0.0
            mbe_pct = 0.0
            mbe_history = []
            previous_mbe = None
            mbe_3_days_ago = None
            nc_history = []

            if mbe_rows:
                latest_mbe = mbe_rows[-1]
                mbe_value = float(latest_mbe.mbe_value or 0)
                mbe_pct = float(latest_mbe.mbe_pct or 0)
                mbe_history = [float(r.mbe_value or 0) for r in mbe_rows]
                nc_history = [float(r.nc_forward or 0) for r in mbe_rows]

                if len(mbe_rows) >= 2:
                    previous_mbe = float(mbe_rows[-2].mbe_value or 0)
                if len(mbe_rows) >= 4:
                    mbe_3_days_ago = float(mbe_rows[-4].mbe_value or 0)

            # Güncel vergi parametresini çek
            tax_stmt = (
                select(TaxParameter)
                .where(
                    TaxParameter.fuel_type == fuel_type,
                    TaxParameter.valid_from <= target_date,
                )
                .order_by(TaxParameter.valid_from.desc())
                .limit(1)
            )
            tax_result = await session.execute(tax_stmt)
            tax_row = tax_result.scalar_one_or_none()

            otv_rate = float(tax_row.otv_fixed_tl or 0) if tax_row else 0.0
            kdv_rate = float(tax_row.kdv_rate or Decimal("0.20")) if tax_row else 0.20

        # Feature hesapla
        record = compute_all_features(
            trade_date=target_date.isoformat(),
            fuel_type=fuel_type,
            mbe_value=mbe_value,
            mbe_pct=mbe_pct,
            mbe_history=mbe_history or None,
            previous_mbe=previous_mbe,
            mbe_3_days_ago=mbe_3_days_ago,
            cif_usd_ton=cif,
            fx_rate=fx,
            nc_history=nc_history or None,
            brent_usd_bbl=brent,
            cif_history=cif_history or None,
            fx_history=fx_history or None,
            brent_history=brent_history or None,
            otv_rate=otv_rate,
            kdv_rate=kdv_rate,
            pump_price=pump,
        )

        logger.info(
            "%s feature hesaplandı: %d feature, %d eksik",
            fuel_type,
            len(record.features),
            len(record.missing_features),
        )

        return record.features

    except Exception as exc:
        logger.warning(
            "%s feature hesaplama hatası — sıfır fallback: %s",
            fuel_type,
            exc,
        )
        return zero_features


# ── Task 3: Günlük Bildirim Gönderme ────────────────────────────────────────


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def send_daily_notifications(self):
    """
    Onaylı Telegram kullanıcılarına günlük bildirim gönder.

    Zamanlama: Her gün 07:00 UTC (10:00 TSİ)
    Retry: 2 deneme, 1 dakika aralıkla.
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

        result = await _send()
        return {"status": "sent", "details": result}
    except ImportError:
        logger.warning(
            "Telegram modülü henüz mevcut değil. Bildirim atlanıyor."
        )
        return {"status": "skipped", "reason": "telegram_module_not_found"}
    except Exception as exc:
        logger.warning("Bildirim gönderim hatası: %s", exc)
        return {"status": "error", "reason": str(exc)}


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
