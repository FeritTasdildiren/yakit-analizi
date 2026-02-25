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

    Zamanlama: Her gün 18:00 TSİ (İstanbul saati)
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
    from src.data_collectors.epdk_collector import fetch_istanbul_avrupa
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

    # 3. PO pompa fiyatlari (Istanbul Avrupa / Avcilar)
    try:
        epdk_averages = await fetch_istanbul_avrupa(today)
        if epdk_averages:
            results["epdk"] = {
                fuel_type: str(price)
                for fuel_type, price in epdk_averages.items()
            }
            logger.info("PO Istanbul Avrupa fiyatlari alindi: %s", epdk_averages)
        else:
            epdk_averages = {}
            results["epdk"] = None
            logger.warning("PO Istanbul fiyatlari alinamadi")
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
                        sources.append("po_istanbul_avcilar")

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

    Zamanlama: Her gün 18:30 TSİ (İstanbul saati)
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

    Zamanlama: Her gün 11:00 TSİ (İstanbul saati)
    Retry: 2 deneme, 1 dakika aralıkla.

    Sync psycopg2 ile mesaj oluşturur, asyncpg event loop
    çakışmasını önlemek için async_session_factory kullanmaz.
    """
    logger.info("Günlük bildirim gönderme başlıyor...")

    try:
        message_text = _build_notification_message_sync()
        result = _send_notification_sync(message_text)
        logger.info("Bildirim gönderme tamamlandı: %s", result)
        return result
    except Exception as exc:
        logger.exception("Bildirim gönderme hatası: %s", exc)
        raise self.retry(exc=exc)


# ── Task 3b: Akşam Bildirim Gönderme ────────────────────────────────────────


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def send_evening_notifications(self):
    """
    Onaylı Telegram kullanıcılarına akşam bildirim gönder.

    Zamanlama: Her gün 18:45 TSİ (akşam pipeline tamamlandıktan sonra)
    Retry: 2 deneme, 1 dakika aralıkla.
    """
    logger.info("Akşam bildirim gönderme başlıyor...")

    try:
        message_text = _build_notification_message_sync()
        result = _send_notification_sync(message_text)
        logger.info("Akşam bildirim gönderme tamamlandı: %s", result)
        return result
    except Exception as exc:
        logger.exception("Akşam bildirim gönderme hatası: %s", exc)
        raise self.retry(exc=exc)


def _build_notification_message_sync() -> str:
    """
    Bildirim mesajını psycopg2 ile sync oluşturur.

    asyncpg event loop çakışmasını önlemek için async_session_factory
    yerine doğrudan psycopg2 kullanır. handlers.py'deki
    format_daily_notification() ile aynı formatı üretir.
    """
    import psycopg2

    DB_URL = settings.sync_database_url
    MONTHS_TR = {
        1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan",
        5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
        9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
    }

    today = date.today()
    date_str = f"{today.day} {MONTHS_TR[today.month]}"
    lines = [f"🔔 Günlük Rapor — {date_str}\n"]

    short_labels = {"benzin": "Benzin", "motorin": "Motorin", "lpg": "LPG"}

    conn = psycopg2.connect(DB_URL)
    try:
        cur = conn.cursor()
        for fuel_type, label in short_labels.items():
            # Streak hesapla — predictions_v5'ten son 10 günü çek
            cur.execute(
                "SELECT run_date, first_event_type, first_event_amount "
                "FROM predictions_v5 "
                "WHERE fuel_type = %s "
                "ORDER BY run_date DESC LIMIT 10",
                (fuel_type,)
            )
            rows = cur.fetchall()

            streak_count = 0
            streak_direction = None
            latest_amount = 0.0

            if rows:
                for row in rows:
                    event_type = row[1] or None
                    amount = float(row[2] or 0)

                    if event_type is None or amount == 0.0:
                        break

                    if streak_direction is None:
                        streak_direction = event_type
                        streak_count = 1
                        latest_amount = abs(amount)
                        continue

                    if event_type == streak_direction:
                        streak_count += 1
                    else:
                        break

            # Format — handlers.py ile aynı mantık
            if streak_count == 0 or streak_direction is None:
                lines.append(f"⛽ {label}: Sabit ✅")
            else:
                # streak_to_probability
                if streak_count == 1:
                    probability = 33
                elif streak_count == 2:
                    probability = 66
                else:
                    probability = 99

                if streak_direction == "artis":
                    lines.append(
                        f"⛽ {label}: 🔴 %{probability} Zam Olasılığı "
                        f"(~{latest_amount:.2f} TL)"
                    )
                else:
                    lines.append(
                        f"⛽ {label}: 🟢 %{probability} İndirim Olasılığı "
                        f"(~{latest_amount:.2f} TL)"
                    )

        cur.close()
    finally:
        conn.close()

    lines.append("\nDetay → /rapor")
    return "\n".join(lines)


def _send_notification_sync(message_text: str) -> dict:
    """
    Mesajı tüm aktif+onaylı kullanıcılara gönderir.

    Kullanıcı listesini psycopg2 ile çeker, mesaj gönderimini
    asyncio.run() ile yapar (sadece Telegram API çağrısı, DB yok).
    """
    import psycopg2

    from telegram import Bot

    DB_URL = settings.sync_database_url

    # Kullanıcı listesini sync çek
    conn = psycopg2.connect(DB_URL)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT telegram_id FROM telegram_users "
            "WHERE is_active = true AND is_approved = true"
        )
        user_ids = [row[0] for row in cur.fetchall()]
        cur.close()
    finally:
        conn.close()

    total = len(user_ids)
    if total == 0:
        logger.info("Bildirim gönderilecek kullanıcı yok")
        return {"sent": 0, "failed": 0, "total": 0}

    # Telegram mesaj gönderimi (async — DB kullanmaz, event loop sorunu yok)
    async def _send_all():
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        sent = 0
        failed = 0
        for tid in user_ids:
            try:
                await bot.send_message(chat_id=tid, text=message_text)
                sent += 1
            except Exception as exc:
                logger.warning("Mesaj gönderilemedi: tid=%s, hata=%s", tid, exc)
                failed += 1
            await asyncio.sleep(0.05)  # rate limit
        return {"sent": sent, "failed": failed, "total": total}

    return asyncio.run(_send_all())


# ── Task 5: Günlük MBE Hesaplama ────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120)
def calculate_daily_mbe(self):
    """
    Günlük MBE hesaplama: cost_base_snapshots + mbe_calculations.

    Zamanlama: Veri toplamadan 10 dk sonra (18:10 / 08:10 TSİ).
    daily_market_data ve tax_parameters üzerinden hesaplama yapar.
    """
    logger.info("Günlük MBE hesaplama başlıyor...")
    try:
        results = _calculate_mbe_sync()
        logger.info("MBE hesaplama tamamlandı: %s", results)
        return results
    except Exception as exc:
        logger.exception("MBE hesaplama hatası: %s", exc)
        raise self.retry(exc=exc)


def _calculate_mbe_sync() -> dict:
    """Sync MBE hesaplama — psycopg2 ile doğrudan DB erişimi."""
    import math
    import psycopg2
    import psycopg2.extras
    from decimal import ROUND_HALF_UP

    DB_URL = settings.sync_database_url
    RHO = {"benzin": Decimal("1180"), "motorin": Decimal("1190"), "lpg": Decimal("1750")}
    PRECISION = Decimal("0.00000001")
    FUEL_TYPES = ["benzin", "motorin", "lpg"]

    def _sd(v):
        return Decimal(str(v)) if v is not None else Decimal("0")

    today = date.today()
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()
    results = {}

    try:
        # Tax params yükle
        cur.execute("SELECT fuel_type, valid_from, otv_fixed_tl, kdv_rate FROM tax_parameters ORDER BY fuel_type, valid_from")
        tax_params = {}
        for r in cur.fetchall():
            tax_params.setdefault(r[0], []).append({"valid_from": r[1], "otv": r[2], "kdv": r[3]})

        def find_tax(ft, td):
            tps = tax_params.get(ft, [])
            valid = [t for t in tps if t["valid_from"] <= td]
            return valid[-1] if valid else None

        for ft in FUEL_TYPES:
            rho = RHO[ft]

            # Bugünün market data'sını çek
            cur.execute(
                "SELECT id, brent_usd_bbl, usd_try_rate, pump_price_tl_lt, cif_med_usd_ton "
                "FROM daily_market_data WHERE trade_date=%s AND fuel_type=%s",
                (today, ft)
            )
            row = cur.fetchone()
            if not row:
                results[ft] = "market_data_yok"
                logger.warning("%s için %s market data bulunamadı", ft, today)
                continue

            md_id, brent, fx, pump, cif = row
            if brent is None or fx is None:
                results[ft] = "brent_veya_fx_null"
                continue

            brent_d = _sd(brent)
            fx_d = _sd(fx)
            cif_d = _sd(cif) if cif else (brent_d * Decimal("7.33")).quantize(PRECISION, rounding=ROUND_HALF_UP)
            pump_d = _sd(pump) if pump else Decimal("0")

            # Fiyat değişimi tespiti — önceki günün pompa fiyatıyla karşılaştır
            price_changed = False
            if pump_d:
                cur.execute(
                    "SELECT pump_price_tl_lt FROM daily_market_data "
                    "WHERE fuel_type=%s AND trade_date<%s AND pump_price_tl_lt IS NOT NULL "
                    "ORDER BY trade_date DESC LIMIT 1",
                    (ft, today)
                )
                prev_pump_row = cur.fetchone()
                if prev_pump_row:
                    prev_pump_d = _sd(prev_pump_row[0])
                    price_changed = abs(pump_d - prev_pump_d) > Decimal("0.01")

            # Tax param
            tp = find_tax(ft, today)
            if not tp:
                results[ft] = "tax_param_yok"
                continue
            otv = _sd(tp["otv"])
            kdv = _sd(tp["kdv"])

            # Cost snapshot hesapla
            nc_fwd = (cif_d * fx_d / rho).quantize(PRECISION, rounding=ROUND_HALF_UP)
            otv_comp = otv
            pre_kdv = nc_fwd + otv_comp + Decimal("0.04")  # marj
            kdv_comp = (pre_kdv * kdv).quantize(PRECISION, rounding=ROUND_HALF_UP)
            theoretical = (pre_kdv + kdv_comp).quantize(PRECISION, rounding=ROUND_HALF_UP)
            cost_gap = (pump_d - theoretical).quantize(PRECISION, rounding=ROUND_HALF_UP) if pump_d else Decimal("0")
            cost_gap_pct = ((cost_gap / theoretical) * Decimal("100")).quantize(PRECISION, rounding=ROUND_HALF_UP) if theoretical else Decimal("0")

            # tax_parameter id bul
            cur.execute(
                "SELECT id FROM tax_parameters WHERE fuel_type=%s AND valid_from<=%s ORDER BY valid_from DESC LIMIT 1",
                (ft, today)
            )
            tp_row = cur.fetchone()
            tp_id = tp_row[0] if tp_row else 1

            # Cost snapshot upsert
            cur.execute("""
                INSERT INTO cost_base_snapshots
                    (trade_date, fuel_type, market_data_id, tax_parameter_id,
                     cif_component_tl, otv_component_tl, kdv_component_tl,
                     margin_component_tl, theoretical_cost_tl, actual_pump_price_tl,
                     implied_cif_usd_ton, cost_gap_tl, cost_gap_pct, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (trade_date, fuel_type) DO UPDATE SET
                    market_data_id=EXCLUDED.market_data_id, tax_parameter_id=EXCLUDED.tax_parameter_id,
                    cif_component_tl=EXCLUDED.cif_component_tl, otv_component_tl=EXCLUDED.otv_component_tl,
                    kdv_component_tl=EXCLUDED.kdv_component_tl, margin_component_tl=EXCLUDED.margin_component_tl,
                    theoretical_cost_tl=EXCLUDED.theoretical_cost_tl, actual_pump_price_tl=EXCLUDED.actual_pump_price_tl,
                    implied_cif_usd_ton=EXCLUDED.implied_cif_usd_ton, cost_gap_tl=EXCLUDED.cost_gap_tl,
                    cost_gap_pct=EXCLUDED.cost_gap_pct, source=EXCLUDED.source, updated_at=NOW()
                RETURNING id
            """, (today, ft, md_id, tp_id,
                   float(nc_fwd), float(otv_comp), float(kdv_comp),
                   0.04, float(theoretical), float(pump_d),
                   float(cif_d) if cif else None, float(cost_gap), float(cost_gap_pct), "celery"))
            cs_id = cur.fetchone()[0]

            # MBE hesapla — son 10 günlük nc_forward geçmişi al
            cur.execute(
                "SELECT nc_forward FROM mbe_calculations WHERE fuel_type=%s AND trade_date<%s ORDER BY trade_date DESC LIMIT 10",
                (ft, today)
            )
            prev_nc = [Decimal(str(r[0])) for r in cur.fetchall()][::-1]  # eski→yeni

            # SMA-5 (nc_base'den önce hesaplanmalı — fiyat değişiminde nc_base = sma5)
            all_nc = prev_nc + [nc_fwd]
            window5 = all_nc[-5:] if len(all_nc) >= 5 else all_nc
            sma5 = sum(window5) / Decimal(str(len(window5)))

            # SMA-10
            window10 = all_nc[-10:] if len(all_nc) >= 10 else all_nc
            sma10 = sum(window10) / Decimal(str(len(window10)))

            # nc_base: fiyat değişiminde SMA-5 ile güncelle, yoksa öncekini koru
            if price_changed:
                nc_base = sma5
                logger.info(
                    "%s fiyat değişimi tespit edildi: %s → %s, nc_base=%s",
                    ft, prev_pump_d, pump_d, nc_base,
                )
            else:
                cur.execute(
                    "SELECT nc_base FROM mbe_calculations "
                    "WHERE fuel_type=%s AND trade_date<%s ORDER BY trade_date DESC LIMIT 1",
                    (ft, today)
                )
                prev_base_row = cur.fetchone()
                nc_base = Decimal(str(prev_base_row[0])) if prev_base_row else nc_fwd

            # MBE
            mbe_val = (sma5 - nc_base).quantize(PRECISION, rounding=ROUND_HALF_UP)
            mbe_pct = ((mbe_val / nc_base) * Decimal("100")).quantize(PRECISION, rounding=ROUND_HALF_UP) if nc_base != 0 else Decimal("0")

            # Delta MBE
            cur.execute(
                "SELECT mbe_value FROM mbe_calculations WHERE fuel_type=%s AND trade_date<%s ORDER BY trade_date DESC LIMIT 3",
                (ft, today)
            )
            prev_mbe = [Decimal(str(r[0])) for r in cur.fetchall()]
            delta_mbe = float(mbe_val - prev_mbe[0]) if prev_mbe else None
            delta_mbe_3 = float(mbe_val - prev_mbe[2]) if len(prev_mbe) >= 3 else None

            # Trend
            trend = "no_change"
            if len(all_nc) >= 3:
                if all_nc[-1] > all_nc[-3]: trend = "increase"
                elif all_nc[-1] < all_nc[-3]: trend = "decrease"

            # since_last_change — fiyat değişiminde sıfırla
            if price_changed:
                dslc = 1
            else:
                cur.execute(
                    "SELECT since_last_change_days FROM mbe_calculations "
                    "WHERE fuel_type=%s AND trade_date<%s ORDER BY trade_date DESC LIMIT 1",
                    (ft, today)
                )
                slc_row = cur.fetchone()
                dslc = (slc_row[0] + 1) if slc_row else 1

            # MBE upsert
            cur.execute("""
                INSERT INTO mbe_calculations
                    (trade_date, fuel_type, cost_snapshot_id, nc_forward, nc_base,
                     mbe_value, mbe_pct, sma_5, sma_10, delta_mbe, delta_mbe_3,
                     trend_direction, regime, since_last_change_days, sma_window, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (trade_date, fuel_type) DO UPDATE SET
                    cost_snapshot_id=EXCLUDED.cost_snapshot_id, nc_forward=EXCLUDED.nc_forward,
                    nc_base=EXCLUDED.nc_base, mbe_value=EXCLUDED.mbe_value, mbe_pct=EXCLUDED.mbe_pct,
                    sma_5=EXCLUDED.sma_5, sma_10=EXCLUDED.sma_10, delta_mbe=EXCLUDED.delta_mbe,
                    delta_mbe_3=EXCLUDED.delta_mbe_3, trend_direction=EXCLUDED.trend_direction,
                    regime=EXCLUDED.regime, since_last_change_days=EXCLUDED.since_last_change_days,
                    sma_window=EXCLUDED.sma_window, source=EXCLUDED.source, updated_at=NOW()
            """, (today, ft, cs_id, float(nc_fwd), float(nc_base),
                   float(mbe_val), float(mbe_pct), float(sma5), float(sma10),
                   delta_mbe, delta_mbe_3, trend, 0, dslc, 5, "celery"))

            results[ft] = {"mbe": float(mbe_val), "nc_fwd": float(nc_fwd), "cs_id": cs_id}
            logger.info("%s MBE=%s nc_fwd=%s", ft, mbe_val, nc_fwd)

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

    return results


# ── Task 6: Günlük Risk Hesaplama ───────────────────────────────────────────


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120)
def calculate_daily_risk(self):
    """
    Günlük risk skoru hesaplama.

    Zamanlama: MBE hesaplamasından 10 dk sonra (18:20 / 08:20 TSİ).
    MBE, FX volatilite, politik gecikme, threshold breach, trend momentum.
    """
    logger.info("Günlük risk hesaplama başlıyor...")
    try:
        results = _calculate_risk_sync()
        logger.info("Risk hesaplama tamamlandı: %s", results)
        return results
    except Exception as exc:
        logger.exception("Risk hesaplama hatası: %s", exc)
        raise self.retry(exc=exc)


def _calculate_risk_sync() -> dict:
    """Sync risk hesaplama — psycopg2 ile doğrudan DB erişimi."""
    import math
    import psycopg2

    DB_URL = settings.sync_database_url
    FUEL_TYPES = ["benzin", "motorin", "lpg"]
    WJ = '{"mbe": "0.30", "fx_volatility": "0.15", "political_delay": "0.20", "threshold_breach": "0.20", "trend_momentum": "0.15"}'

    today = date.today()
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()
    results = {}

    try:
        for ft in FUEL_TYPES:
            # Bugünün MBE'sini al
            cur.execute(
                "SELECT mbe_value, since_last_change_days FROM mbe_calculations WHERE fuel_type=%s AND trade_date=%s",
                (ft, today)
            )
            mbe_row = cur.fetchone()
            if not mbe_row:
                results[ft] = "mbe_yok"
                continue

            mbe_val = float(mbe_row[0])
            dslc = mbe_row[1] or 1

            # MBE bileşeni: |MBE| / 5, normalize [0,1]
            mbe_abs = abs(mbe_val)
            mbe_norm = min(1.0, mbe_abs / 5.0)

            # FX volatilite: son 5 günün USD/TRY standart sapması
            cur.execute(
                "SELECT usd_try_rate FROM daily_market_data WHERE fuel_type=%s AND trade_date<=%s AND usd_try_rate IS NOT NULL ORDER BY trade_date DESC LIMIT 5",
                (ft, today)
            )
            fx_rows = [float(r[0]) for r in cur.fetchall()]
            fx_vol = 0.0
            if len(fx_rows) >= 2:
                mean_fx = sum(fx_rows) / len(fx_rows)
                fx_vol = math.sqrt(sum((x - mean_fx) ** 2 for x in fx_rows) / (len(fx_rows) - 1))
            fx_norm = min(1.0, fx_vol / 2.0)

            # Politik gecikme: dslc / 60
            pol_norm = min(1.0, dslc / 60.0)

            # Threshold breach: MBE > 0.1 ise aktif
            thresh_norm = min(1.0, mbe_abs / 1.0) if mbe_abs > 0.1 else 0.0

            # Trend momentum: son 3 MBE değişim oranı
            cur.execute(
                "SELECT mbe_value FROM mbe_calculations WHERE fuel_type=%s AND trade_date<=%s ORDER BY trade_date DESC LIMIT 3",
                (ft, today)
            )
            mbe_hist = [float(r[0]) for r in cur.fetchall()]
            mom = 0.5
            if len(mbe_hist) >= 3:
                m1, m3 = mbe_hist[0], mbe_hist[2]
                mr = (m1 - m3) / max(abs(m3), 0.01)
                mom = min(1.0, max(0.0, (mr + 1) / 2))

            # Composite skor
            composite = min(1.0, max(0.0,
                0.30 * mbe_norm + 0.15 * fx_norm + 0.20 * pol_norm +
                0.20 * thresh_norm + 0.15 * mom
            ))
            sm = "crisis" if composite >= 0.80 else ("high_alert" if composite >= 0.60 else "normal")

            # Risk upsert
            cur.execute("""
                INSERT INTO risk_scores
                    (trade_date, fuel_type, composite_score, mbe_component,
                     fx_volatility_component, political_delay_component,
                     threshold_breach_component, trend_momentum_component,
                     weight_vector, system_mode)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                ON CONFLICT (trade_date, fuel_type) DO UPDATE SET
                    composite_score=EXCLUDED.composite_score, mbe_component=EXCLUDED.mbe_component,
                    fx_volatility_component=EXCLUDED.fx_volatility_component,
                    political_delay_component=EXCLUDED.political_delay_component,
                    threshold_breach_component=EXCLUDED.threshold_breach_component,
                    trend_momentum_component=EXCLUDED.trend_momentum_component,
                    weight_vector=EXCLUDED.weight_vector, system_mode=EXCLUDED.system_mode, updated_at=NOW()
            """, (today, ft, round(composite, 4), round(mbe_norm, 4), round(fx_norm, 4),
                   round(pol_norm, 4), round(thresh_norm, 4), round(mom, 4), WJ, sm))

            results[ft] = {"composite": round(composite, 4), "mode": sm}
            logger.info("%s risk=%s mode=%s", ft, round(composite, 4), sm)

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

    return results

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


# ── Task 7: Günlük ML Tahmin v5 ─────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120)
def run_daily_prediction_v5(self):
    """
    v5 predictor ile günlük tahmin çalıştır.

    v5 pipeline: feature -> stage-1 -> kalibrasyon -> stage-2 -> alarm -> DB.
    v1 korunur, v5 yan yana çalışır.

    Zamanlama: Akşam 18:35 TSİ — v1'den 5 dk sonra
               Sabah 08:35 TSİ — sabah v1'den 5 dk sonra
    """
    logger.info("v5 günlük ML tahmin başlıyor...")

    try:
        from src.predictor_v5.predictor import predict_all

        results = predict_all()
        logger.info("v5 tahmin tamamlandı: %s", results)

        # Sonuç özetini çıkar
        summary = {}
        for fuel_type, result in results.items():
            if result is None:
                summary[fuel_type] = "HATA"
            else:
                summary[fuel_type] = {
                    "prob": result.get("stage1_probability"),
                    "alarm": result.get("alarm", {}).get("should_alarm"),
                    "alarm_type": result.get("alarm", {}).get("alarm_type"),
                }
        logger.info("v5 tahmin özeti: %s", summary)
        return {"status": "ok", "results": summary}

    except Exception as exc:
        logger.exception("v5 tahmin hatası: %s", exc)
        raise self.retry(exc=exc)
