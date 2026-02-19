"""
Celery zamanlanmış görev testleri.

Celery konfigürasyonu, Beat schedule zamanlamaları,
task fonksiyonları ve sağlık kontrolü testleri.

Gerçek Redis/Celery bağlantısı KURULMAZ — tüm external servisler mock'lanır.
"""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.schedules import crontab


# ============================================================
# Celery App Konfigürasyon Testleri
# ============================================================


class TestCeleryConfig:
    """Celery app konfigürasyon testleri."""

    def test_celery_app_creation(self) -> None:
        """Celery app instance'ı oluşturulabilmeli."""
        from src.celery_app.celery_config import celery_app

        assert celery_app is not None
        assert celery_app.main == "yakit_analizi"

    def test_celery_timezone(self) -> None:
        """Timezone Europe/Istanbul olmalı."""
        from src.celery_app.celery_config import celery_app

        assert celery_app.conf.timezone == "Europe/Istanbul"

    def test_celery_utc_enabled(self) -> None:
        """UTC modu aktif olmalı."""
        from src.celery_app.celery_config import celery_app

        assert celery_app.conf.enable_utc is True

    def test_celery_serializer_json(self) -> None:
        """Serileştirici JSON olmalı."""
        from src.celery_app.celery_config import celery_app

        assert celery_app.conf.task_serializer == "json"
        assert celery_app.conf.result_serializer == "json"
        assert "json" in celery_app.conf.accept_content

    def test_celery_time_limits(self) -> None:
        """Task zaman limitleri doğru ayarlanmalı."""
        from src.celery_app.celery_config import celery_app

        assert celery_app.conf.task_time_limit == 600
        assert celery_app.conf.task_soft_time_limit == 540

    def test_celery_worker_settings(self) -> None:
        """Worker ayarları doğru olmalı."""
        from src.celery_app.celery_config import celery_app

        assert celery_app.conf.worker_max_tasks_per_child == 100
        assert celery_app.conf.worker_prefetch_multiplier == 1

    def test_celery_includes_tasks(self) -> None:
        """Task modülü include listesinde olmalı."""
        from src.celery_app.celery_config import celery_app

        assert "src.celery_app.tasks" in celery_app.conf.include

    def test_celery_broker_url(self) -> None:
        """Broker URL settings'ten alınmalı."""
        from src.celery_app.celery_config import celery_app
        from src.config.settings import settings

        assert celery_app.conf.broker_url == settings.REDIS_URL

    def test_celery_beat_schedule_loaded(self) -> None:
        """Beat schedule yüklenmiş olmalı."""
        from src.celery_app.celery_config import celery_app

        assert celery_app.conf.beat_schedule is not None
        assert len(celery_app.conf.beat_schedule) == 12


# ============================================================
# Beat Schedule Testleri
# ============================================================


class TestBeatSchedule:
    """Celery Beat zamanlama testleri."""

    def test_schedule_has_all_tasks(self) -> None:
        """Schedule'da 4 görev tanımlı olmalı."""
        from src.celery_app.beat_schedule import CELERY_BEAT_SCHEDULE

        assert len(CELERY_BEAT_SCHEDULE) == 12
        assert "collect-daily-market-data" in CELERY_BEAT_SCHEDULE
        assert "run-daily-prediction" in CELERY_BEAT_SCHEDULE
        assert "send-daily-notifications" in CELERY_BEAT_SCHEDULE
        assert "health-check" in CELERY_BEAT_SCHEDULE

    def test_data_collection_schedule(self) -> None:
        """Veri toplama 18:00 UTC'de zamanlanmalı."""
        from src.celery_app.beat_schedule import CELERY_BEAT_SCHEDULE

        schedule = CELERY_BEAT_SCHEDULE["collect-daily-market-data"]
        cron = schedule["schedule"]

        assert isinstance(cron, crontab)
        assert cron.hour == {18}
        assert cron.minute == {0}

    def test_prediction_schedule(self) -> None:
        """Tahmin 18:30 UTC'de zamanlanmalı."""
        from src.celery_app.beat_schedule import CELERY_BEAT_SCHEDULE

        schedule = CELERY_BEAT_SCHEDULE["run-daily-prediction"]
        cron = schedule["schedule"]

        assert isinstance(cron, crontab)
        assert cron.hour == {18}
        assert cron.minute == {30}

    def test_notification_schedule(self) -> None:
        """Bildirim 07:00 UTC'de zamanlanmalı."""
        from src.celery_app.beat_schedule import CELERY_BEAT_SCHEDULE

        schedule = CELERY_BEAT_SCHEDULE["send-daily-notifications"]
        cron = schedule["schedule"]

        assert isinstance(cron, crontab)
        assert cron.hour == {7}
        assert cron.minute == {0}

    def test_health_check_schedule(self) -> None:
        """Sağlık kontrolü her 30 dakikada bir olmalı."""
        from src.celery_app.beat_schedule import CELERY_BEAT_SCHEDULE

        schedule = CELERY_BEAT_SCHEDULE["health-check"]
        cron = schedule["schedule"]

        assert isinstance(cron, crontab)
        # */30 → {0, 30}
        assert cron.minute == {0, 30}

    def test_queue_assignments(self) -> None:
        """Her görev doğru kuyrukta olmalı."""
        from src.celery_app.beat_schedule import CELERY_BEAT_SCHEDULE

        assert CELERY_BEAT_SCHEDULE["collect-daily-market-data"]["options"]["queue"] == "data_collection"
        assert CELERY_BEAT_SCHEDULE["run-daily-prediction"]["options"]["queue"] == "ml_prediction"
        assert CELERY_BEAT_SCHEDULE["send-daily-notifications"]["options"]["queue"] == "notifications"
        assert CELERY_BEAT_SCHEDULE["health-check"]["options"]["queue"] == "default"

    def test_task_paths(self) -> None:
        """Task yolları doğru tanımlanmış olmalı."""
        from src.celery_app.beat_schedule import CELERY_BEAT_SCHEDULE

        assert (
            CELERY_BEAT_SCHEDULE["collect-daily-market-data"]["task"]
            == "src.celery_app.tasks.collect_daily_market_data"
        )
        assert (
            CELERY_BEAT_SCHEDULE["run-daily-prediction"]["task"]
            == "src.celery_app.tasks.run_daily_prediction"
        )
        assert (
            CELERY_BEAT_SCHEDULE["send-daily-notifications"]["task"]
            == "src.celery_app.tasks.send_daily_notifications"
        )
        assert (
            CELERY_BEAT_SCHEDULE["health-check"]["task"]
            == "src.celery_app.tasks.health_check"
        )


# ============================================================
# Settings Testleri
# ============================================================


class TestSchedulerSettings:
    """Scheduler ayarları testleri."""

    def test_prediction_hour(self) -> None:
        """Tahmin saati ayarı mevcut olmalı."""
        from src.config.settings import settings

        assert hasattr(settings, "PREDICTION_HOUR")
        assert settings.PREDICTION_HOUR == 18

    def test_prediction_minute(self) -> None:
        """Tahmin dakika ayarı mevcut olmalı."""
        from src.config.settings import settings

        assert hasattr(settings, "PREDICTION_MINUTE")
        assert settings.PREDICTION_MINUTE == 30

    def test_notification_hour(self) -> None:
        """Bildirim saati ayarı mevcut olmalı."""
        from src.config.settings import settings

        assert hasattr(settings, "NOTIFICATION_HOUR")
        assert settings.NOTIFICATION_HOUR == 7

    def test_data_fetch_hour_unchanged(self) -> None:
        """Mevcut DATA_FETCH_HOUR değiştirilmemiş olmalı."""
        from src.config.settings import settings

        assert settings.DATA_FETCH_HOUR == 18

    def test_redis_url_exists(self) -> None:
        """REDIS_URL mevcut olmalı."""
        from src.config.settings import settings

        assert settings.REDIS_URL is not None
        assert settings.REDIS_URL.startswith("redis://")


# ============================================================
# Task Fonksiyon Testleri — collect_daily_market_data
# ============================================================


class TestCollectDailyMarketData:
    """Günlük veri toplama task testleri."""

    def test_task_is_registered(self) -> None:
        """Task Celery'ye kayıtlı olmalı."""
        from src.celery_app.tasks import collect_daily_market_data

        assert collect_daily_market_data.name == "src.celery_app.tasks.collect_daily_market_data"

    def test_task_max_retries(self) -> None:
        """Task max_retries 3 olmalı."""
        from src.celery_app.tasks import collect_daily_market_data

        assert collect_daily_market_data.max_retries == 3

    def test_task_retry_delay(self) -> None:
        """Task retry delay 300 saniye (5 dakika) olmalı."""
        from src.celery_app.tasks import collect_daily_market_data

        assert collect_daily_market_data.default_retry_delay == 300

    @pytest.mark.asyncio
    async def test_collect_all_data_success(self) -> None:
        """Tüm collector'lar başarılı olduğunda sonuçlar dönmeli."""
        from src.data_collectors.brent_collector import BrentData
        from src.data_collectors.fx_collector import FXData

        mock_brent = BrentData(
            trade_date=date(2026, 2, 16),
            brent_usd_bbl=Decimal("80.50"),
            cif_med_estimate_usd_ton=Decimal("619.73"),
            source="yfinance",
            raw_data=None,
        )
        mock_fx = FXData(
            trade_date=date(2026, 2, 16),
            usd_try_rate=Decimal("36.25"),
            source="tcmb_evds",
            raw_data=None,
        )
        mock_epdk = {
            "benzin": Decimal("43.50"),
            "motorin": Decimal("41.20"),
        }

        # Mock'ları kaynak modüllerde hedefle (lazy import olduğu için)
        with (
            patch(
                "src.data_collectors.brent_collector.fetch_brent_daily",
                new_callable=AsyncMock,
                return_value=mock_brent,
            ),
            patch(
                "src.data_collectors.fx_collector.fetch_usd_try_daily",
                new_callable=AsyncMock,
                return_value=mock_fx,
            ),
            patch(
                "src.data_collectors.epdk_collector.fetch_turkey_average",
                new_callable=AsyncMock,
                return_value=mock_epdk,
            ),
        ):
            from src.celery_app.tasks import _collect_all_data

            results = await _collect_all_data()

        assert results["brent"] is not None
        assert results["brent"]["brent_usd_bbl"] == "80.50"
        assert results["brent"]["source"] == "yfinance"
        assert results["fx"]["usd_try_rate"] == "36.25"
        assert results["epdk"]["benzin"] == "43.50"

    @pytest.mark.asyncio
    async def test_collect_all_data_brent_failure(self) -> None:
        """Brent çekimi başarısız olduğunda diğerleri etkilenmemeli."""
        mock_fx = MagicMock()
        mock_fx.usd_try_rate = Decimal("36.25")
        mock_fx.source = "tcmb_evds"

        with (
            patch(
                "src.data_collectors.brent_collector.fetch_brent_daily",
                new_callable=AsyncMock,
                side_effect=Exception("API hatası"),
            ),
            patch(
                "src.data_collectors.fx_collector.fetch_usd_try_daily",
                new_callable=AsyncMock,
                return_value=mock_fx,
            ),
            patch(
                "src.data_collectors.epdk_collector.fetch_turkey_average",
                new_callable=AsyncMock,
                return_value={"benzin": Decimal("43.50")},
            ),
        ):
            from src.celery_app.tasks import _collect_all_data

            results = await _collect_all_data()

        # Brent hata mesajı içermeli
        assert "HATA" in results["brent"]
        # Diğerleri etkilenmemeli
        assert results["fx"] is not None
        assert results["epdk"] is not None

    @pytest.mark.asyncio
    async def test_collect_all_data_returns_none(self) -> None:
        """Collector None döndürdüğünde sonuç None olmalı."""
        with (
            patch(
                "src.data_collectors.brent_collector.fetch_brent_daily",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.data_collectors.fx_collector.fetch_usd_try_daily",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.data_collectors.epdk_collector.fetch_turkey_average",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from src.celery_app.tasks import _collect_all_data

            results = await _collect_all_data()

        assert results["brent"] is None
        assert results["fx"] is None
        assert results["epdk"] is None


# ============================================================
# Task Fonksiyon Testleri — run_daily_prediction
# ============================================================


class TestRunDailyPrediction:
    """Günlük ML tahmin task testleri."""

    def test_task_is_registered(self) -> None:
        """Task Celery'ye kayıtlı olmalı."""
        from src.celery_app.tasks import run_daily_prediction

        assert run_daily_prediction.name == "src.celery_app.tasks.run_daily_prediction"

    def test_task_max_retries(self) -> None:
        """Task max_retries 2 olmalı."""
        from src.celery_app.tasks import run_daily_prediction

        assert run_daily_prediction.max_retries == 2

    def test_task_retry_delay(self) -> None:
        """Task retry delay 120 saniye (2 dakika) olmalı."""
        from src.celery_app.tasks import run_daily_prediction

        assert run_daily_prediction.default_retry_delay == 120

    @pytest.mark.asyncio
    async def test_run_predictions_model_not_loaded(self) -> None:
        """Model yüklenemediğinde hata mesajı dönmeli."""
        mock_predictor = MagicMock()
        mock_predictor.is_loaded = False
        mock_predictor.load_model.return_value = False

        with patch(
            "src.ml.predictor.get_predictor",
            return_value=mock_predictor,
        ):
            from src.celery_app.tasks import _run_predictions

            results = await _run_predictions()

        assert "error" in results
        assert results["error"] == "Model yüklenemedi"

    @pytest.mark.asyncio
    async def test_run_predictions_success(self) -> None:
        """Model başarıyla tahmin yaptığında sonuçlar kaydedilmeli."""
        from src.ml.predictor import PredictionResult

        mock_prediction = PredictionResult(
            predicted_direction="stable",
            probability_hike=Decimal("0.2500"),
            probability_stable=Decimal("0.6000"),
            probability_cut=Decimal("0.1500"),
            expected_change_tl=Decimal("0.0500"),
            model_version="v1",
            system_mode="full",
            confidence="high",
        )

        mock_predictor = MagicMock()
        mock_predictor.is_loaded = True
        mock_predictor.predict_with_fallback.return_value = mock_prediction

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        mock_session_factory = MagicMock(return_value=mock_session)

        with (
            patch(
                "src.ml.predictor.get_predictor",
                return_value=mock_predictor,
            ),
            patch(
                "src.config.database.async_session_factory",
                mock_session_factory,
            ),
            patch(
                "src.repositories.ml_repository.upsert_ml_prediction",
                new_callable=AsyncMock,
            ) as mock_upsert,
        ):
            from src.celery_app.tasks import _run_predictions

            results = await _run_predictions()

        # 2 yakıt türü (benzin + motorin) için tahmin yapılmış olmalı
        assert "benzin" in results
        assert "motorin" in results
        assert results["benzin"]["direction"] == "stable"
        assert results["motorin"]["direction"] == "stable"

        # upsert 2 kez çağrılmış olmalı
        assert mock_upsert.call_count == 2

    def test_placeholder_features(self) -> None:
        """Placeholder features tüm FEATURE_NAMES'i kapsamalı."""
        from src.celery_app.tasks import _get_placeholder_features
        from src.ml.feature_engineering import FEATURE_NAMES

        features = _get_placeholder_features()

        assert isinstance(features, dict)
        assert len(features) == len(FEATURE_NAMES)
        for name in FEATURE_NAMES:
            assert name in features
            assert features[name] == 0.0


# ============================================================
# Task Fonksiyon Testleri — send_daily_notifications
# ============================================================


class TestSendDailyNotifications:
    """Günlük bildirim task testleri."""

    def test_task_is_registered(self) -> None:
        """Task Celery'ye kayıtlı olmalı."""
        from src.celery_app.tasks import send_daily_notifications

        assert send_daily_notifications.name == "src.celery_app.tasks.send_daily_notifications"

    def test_task_max_retries(self) -> None:
        """Task max_retries 2 olmalı."""
        from src.celery_app.tasks import send_daily_notifications

        assert send_daily_notifications.max_retries == 2

    def test_task_retry_delay(self) -> None:
        """Task retry delay 60 saniye (1 dakika) olmalı."""
        from src.celery_app.tasks import send_daily_notifications

        assert send_daily_notifications.default_retry_delay == 60

    @pytest.mark.asyncio
    async def test_notifications_skipped_when_import_fails(self) -> None:
        """Telegram modülü import edilemediğinde bildirim atlanmalı."""
        import builtins
        import importlib

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "src.telegram.notifications":
                raise ImportError("Simulated: module not found")
            return original_import(name, *args, **kwargs)

        import src.celery_app.tasks

        with patch("builtins.__import__", side_effect=mock_import):
            # Modül cache'ini temizle ki tekrar import denensin
            import sys

            saved = sys.modules.pop("src.telegram.notifications", None)
            saved_parent = sys.modules.pop("src.telegram", None)
            try:
                importlib.reload(src.celery_app.tasks)
                result = await src.celery_app.tasks._send_notifications()

                assert result["status"] == "skipped"
                assert result["reason"] == "telegram_module_not_found"
            finally:
                # Temizlik: orijinal modülleri geri koy
                if saved is not None:
                    sys.modules["src.telegram.notifications"] = saved
                if saved_parent is not None:
                    sys.modules["src.telegram"] = saved_parent
                importlib.reload(src.celery_app.tasks)

    @pytest.mark.asyncio
    async def test_notifications_sent_when_module_exists(self) -> None:
        """Telegram modülü mevcutken bildirim gönderilmeli."""
        import importlib
        import sys

        mock_send_func = AsyncMock()

        # telegram.notifications modülünü simüle et
        mock_module = MagicMock()
        mock_module.send_daily_notifications = mock_send_func

        sys.modules["src.telegram"] = MagicMock()
        sys.modules["src.telegram.notifications"] = mock_module

        try:
            # tasks modülünü reload et ki yeni mock modülü görsün
            import src.celery_app.tasks

            importlib.reload(src.celery_app.tasks)
            result = await src.celery_app.tasks._send_notifications()

            assert result["status"] == "sent"
            mock_send_func.assert_called_once()
        finally:
            # Temizlik: sahte modülleri kaldır ve reload et
            sys.modules.pop("src.telegram.notifications", None)
            sys.modules.pop("src.telegram", None)
            importlib.reload(src.celery_app.tasks)


# ============================================================
# Task Fonksiyon Testleri — health_check
# ============================================================


class TestHealthCheck:
    """Sistem sağlık kontrolü task testleri."""

    def test_task_is_registered(self) -> None:
        """Task Celery'ye kayıtlı olmalı."""
        from src.celery_app.tasks import health_check

        assert health_check.name == "src.celery_app.tasks.health_check"

    @pytest.mark.asyncio
    async def test_health_check_format(self) -> None:
        """Sağlık kontrolü doğru formatta sonuç dönmeli."""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()

        mock_session_factory = MagicMock(return_value=mock_session)

        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True

        mock_predictor = MagicMock()
        mock_predictor.is_loaded = True

        with (
            patch(
                "src.config.database.async_session_factory",
                mock_session_factory,
            ),
            patch("redis.from_url", return_value=mock_redis_instance),
            patch(
                "src.ml.predictor.get_predictor",
                return_value=mock_predictor,
            ),
        ):
            from src.celery_app.tasks import _check_health

            result = await _check_health()

        assert "db" in result
        assert "redis" in result
        assert "ml_model" in result
        assert "timestamp" in result
        assert isinstance(result["db"], bool)
        assert isinstance(result["redis"], bool)
        assert isinstance(result["ml_model"], bool)

    @pytest.mark.asyncio
    async def test_health_check_all_healthy(self) -> None:
        """Tüm servisler sağlıklıyken hepsi True olmalı."""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock()

        mock_session_factory = MagicMock(return_value=mock_session)

        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.return_value = True

        mock_predictor = MagicMock()
        mock_predictor.is_loaded = True

        with (
            patch(
                "src.config.database.async_session_factory",
                mock_session_factory,
            ),
            patch("redis.from_url", return_value=mock_redis_instance),
            patch(
                "src.ml.predictor.get_predictor",
                return_value=mock_predictor,
            ),
        ):
            from src.celery_app.tasks import _check_health

            result = await _check_health()

        assert result["db"] is True
        assert result["redis"] is True
        assert result["ml_model"] is True

    @pytest.mark.asyncio
    async def test_health_check_all_unhealthy(self) -> None:
        """Tüm servisler başarısız olduğunda hepsi False olmalı."""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(side_effect=Exception("DB bağlantısı yok"))

        mock_session_factory = MagicMock(return_value=mock_session)

        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.side_effect = Exception("Redis bağlantısı yok")

        mock_predictor = MagicMock()
        mock_predictor.is_loaded = False

        with (
            patch(
                "src.config.database.async_session_factory",
                mock_session_factory,
            ),
            patch("redis.from_url", return_value=mock_redis_instance),
            patch(
                "src.ml.predictor.get_predictor",
                return_value=mock_predictor,
            ),
        ):
            from src.celery_app.tasks import _check_health

            result = await _check_health()

        assert result["db"] is False
        assert result["redis"] is False
        assert result["ml_model"] is False

    @pytest.mark.asyncio
    async def test_health_check_timestamp_format(self) -> None:
        """Timestamp ISO 8601 formatında olmalı."""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(side_effect=Exception("test"))

        mock_session_factory = MagicMock(return_value=mock_session)

        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.side_effect = Exception("test")

        mock_predictor = MagicMock()
        mock_predictor.is_loaded = False

        with (
            patch(
                "src.config.database.async_session_factory",
                mock_session_factory,
            ),
            patch("redis.from_url", return_value=mock_redis_instance),
            patch(
                "src.ml.predictor.get_predictor",
                return_value=mock_predictor,
            ),
        ):
            from src.celery_app.tasks import _check_health

            result = await _check_health()

        # ISO 8601 formatında parse edilebilmeli
        timestamp = result["timestamp"]
        parsed = datetime.fromisoformat(timestamp)
        assert isinstance(parsed, datetime)


# ============================================================
# Hata Yönetimi Testleri
# ============================================================


class TestErrorHandling:
    """Hata yönetimi ve retry mekanizması testleri."""

    @pytest.mark.asyncio
    async def test_collect_data_partial_failure(self) -> None:
        """Bir collector başarısız olduğunda diğerleri çalışmaya devam etmeli."""
        from src.data_collectors.brent_collector import BrentData

        mock_brent = BrentData(
            trade_date=date(2026, 2, 16),
            brent_usd_bbl=Decimal("80.50"),
            cif_med_estimate_usd_ton=Decimal("619.73"),
            source="yfinance",
            raw_data=None,
        )

        with (
            patch(
                "src.data_collectors.brent_collector.fetch_brent_daily",
                new_callable=AsyncMock,
                return_value=mock_brent,
            ),
            patch(
                "src.data_collectors.fx_collector.fetch_usd_try_daily",
                new_callable=AsyncMock,
                side_effect=Exception("FX hatası"),
            ),
            patch(
                "src.data_collectors.epdk_collector.fetch_turkey_average",
                new_callable=AsyncMock,
                side_effect=Exception("EPDK hatası"),
            ),
        ):
            from src.celery_app.tasks import _collect_all_data

            results = await _collect_all_data()

        # Brent başarılı
        assert results["brent"] is not None
        assert results["brent"]["brent_usd_bbl"] == "80.50"
        # FX ve EPDK hata mesajı içermeli
        assert "HATA" in results["fx"]
        assert "HATA" in results["epdk"]

    @pytest.mark.asyncio
    async def test_prediction_per_fuel_error_isolation(self) -> None:
        """Bir yakıt tahmininde hata olduğunda diğeri etkilenmemeli."""
        from src.ml.predictor import PredictionResult

        call_count = 0

        def mock_predict_with_fallback(features, risk_score=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Benzin tahmin hatası")
            return PredictionResult(
                predicted_direction="stable",
                probability_hike=Decimal("0.2500"),
                probability_stable=Decimal("0.6000"),
                probability_cut=Decimal("0.1500"),
                expected_change_tl=Decimal("0.0500"),
                model_version="v1",
                system_mode="full",
                confidence="high",
            )

        mock_predictor = MagicMock()
        mock_predictor.is_loaded = True
        mock_predictor.predict_with_fallback.side_effect = mock_predict_with_fallback

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock()

        mock_session_factory = MagicMock(return_value=mock_session)

        with (
            patch(
                "src.ml.predictor.get_predictor",
                return_value=mock_predictor,
            ),
            patch(
                "src.config.database.async_session_factory",
                mock_session_factory,
            ),
            patch(
                "src.repositories.ml_repository.upsert_ml_prediction",
                new_callable=AsyncMock,
            ),
        ):
            from src.celery_app.tasks import _run_predictions

            results = await _run_predictions()

        # Benzin hata, motorin başarılı olmalı
        assert "HATA" in results["benzin"]
        assert results["motorin"]["direction"] == "stable"


# ============================================================
# Modül Import Testleri
# ============================================================


class TestModuleImports:
    """Modül import testleri — tüm modüller import edilebilmeli."""

    def test_import_celery_config(self) -> None:
        """celery_config modülü import edilebilmeli."""
        from src.celery_app.celery_config import celery_app

        assert celery_app is not None

    def test_import_tasks(self) -> None:
        """tasks modülü import edilebilmeli."""
        from src.celery_app.tasks import (
            collect_daily_market_data,
            health_check,
            run_daily_prediction,
            send_daily_notifications,
        )

        assert collect_daily_market_data is not None
        assert run_daily_prediction is not None
        assert send_daily_notifications is not None
        assert health_check is not None

    def test_import_beat_schedule(self) -> None:
        """beat_schedule modülü import edilebilmeli."""
        from src.celery_app.beat_schedule import CELERY_BEAT_SCHEDULE

        assert CELERY_BEAT_SCHEDULE is not None

    def test_import_init(self) -> None:
        """__init__ modülü import edilebilmeli."""
        import src.celery_app

        assert src.celery_app is not None
