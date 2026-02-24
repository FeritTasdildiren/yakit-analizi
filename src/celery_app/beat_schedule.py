"""
Celery Beat zamanlama konfigürasyonu.

Tüm periyodik görevlerin crontab zamanlamaları burada tanımlanır.
Celery timezone=Europe/Istanbul kullanıldığı için crontab saatleri
doğrudan TSİ (İstanbul saati) olarak yorumlanır.

Değişiklik Geçmişi:
- TASK-038: Queue routing kaldırıldı (tüm task'lar default queue'da),
  sabah veri toplama + tahmin eklendi.
- TASK-080: Timezone düzeltme — tüm saatler TSİ olarak ayarlandı,
  akşam bildirim (18:00 TSİ) eklendi.
"""

from celery.schedules import crontab

from src.config.settings import settings

CELERY_BEAT_SCHEDULE = {
    # ── Akşam Pipeline ──────────────────────────────────────────────────
    # 18:00 TSİ — piyasalar kapandıktan sonra
    "collect-daily-market-data": {
        "task": "src.celery_app.tasks.collect_daily_market_data",
        "schedule": crontab(hour=settings.DATA_FETCH_HOUR, minute=0),
    },
    # 18:10 TSİ — veri toplama bittikten 10 dk sonra
    "calculate-daily-mbe": {
        "task": "src.celery_app.tasks.calculate_daily_mbe",
        "schedule": crontab(hour=settings.DATA_FETCH_HOUR, minute=10),
    },
    # 18:20 TSİ — MBE bittikten 10 dk sonra
    "calculate-daily-risk": {
        "task": "src.celery_app.tasks.calculate_daily_risk",
        "schedule": crontab(hour=settings.DATA_FETCH_HOUR, minute=20),
    },
    # 18:30 TSİ — veri toplama bittikten 30 dk sonra
    "run-daily-prediction": {
        "task": "src.celery_app.tasks.run_daily_prediction",
        "schedule": crontab(
            hour=settings.PREDICTION_HOUR,
            minute=settings.PREDICTION_MINUTE,
        ),
    },
    # 18:35 TSİ — v5 tahmin (v1'den 5 dk sonra)
    "run-daily-prediction-v5": {
        "task": "src.celery_app.tasks.run_daily_prediction_v5",
        "schedule": crontab(hour=settings.PREDICTION_HOUR, minute=35),
    },
    # ── Sabah Pipeline ──────────────────────────────────────────────────
    # 10:15 TSİ — sabah güncel veri
    "collect-morning-market-data": {
        "task": "src.celery_app.tasks.collect_daily_market_data",
        "schedule": crontab(
            hour=settings.MORNING_DATA_FETCH_HOUR,
            minute=settings.MORNING_DATA_FETCH_MINUTE,
        ),
    },
    # 10:25 TSİ — sabah MBE hesaplama
    "calculate-morning-mbe": {
        "task": "src.celery_app.tasks.calculate_daily_mbe",
        "schedule": crontab(
            hour=settings.MORNING_DATA_FETCH_HOUR,
            minute=settings.MORNING_DATA_FETCH_MINUTE + 10,
        ),
    },
    # 10:35 TSİ — sabah risk hesaplama
    "calculate-morning-risk": {
        "task": "src.celery_app.tasks.calculate_daily_risk",
        "schedule": crontab(
            hour=settings.MORNING_DATA_FETCH_HOUR,
            minute=settings.MORNING_DATA_FETCH_MINUTE + 20,
        ),
    },
    # 10:45 TSİ — sabah tahmin güncelleme
    "run-morning-prediction": {
        "task": "src.celery_app.tasks.run_daily_prediction",
        "schedule": crontab(
            hour=settings.MORNING_PREDICTION_HOUR,
            minute=settings.MORNING_PREDICTION_MINUTE,
        ),
    },
    # 10:50 TSİ — sabah v5 tahmin
    "run-morning-prediction-v5": {
        "task": "src.celery_app.tasks.run_daily_prediction_v5",
        "schedule": crontab(
            hour=settings.MORNING_PREDICTION_HOUR,
            minute=settings.MORNING_PREDICTION_MINUTE + 5,
        ),
    },
    # ── Bildirimler ─────────────────────────────────────────────────────
    # 10:00 TSİ — sabah bildirim (kullanıcılar sabah okusun)
    "send-daily-notifications": {
        "task": "src.celery_app.tasks.send_daily_notifications",
        "schedule": crontab(
            hour=settings.NOTIFICATION_HOUR,
            minute=0,
        ),
    },
    # 18:45 TSİ — akşam bildirim (akşam pipeline tamamlandıktan sonra)
    "send-evening-notifications": {
        "task": "src.celery_app.tasks.send_evening_notifications",
        "schedule": crontab(
            hour=settings.TELEGRAM_EVENING_NOTIFICATION_HOUR,
            minute=settings.TELEGRAM_EVENING_NOTIFICATION_MINUTE,
        ),
    },
    # ── Sağlık Kontrolü ────────────────────────────────────────────────
    # Her 30 dakikada bir
    "health-check": {
        "task": "src.celery_app.tasks.health_check",
        "schedule": crontab(minute="*/30"),
    },
}
