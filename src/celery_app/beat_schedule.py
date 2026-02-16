"""
Celery Beat zamanlama konfigürasyonu.

Tüm periyodik görevlerin crontab zamanlamaları burada tanımlanır.
UTC saat dilimi kullanılır (Europe/Istanbul = UTC+3).
"""

from celery.schedules import crontab

from src.config.settings import settings

CELERY_BEAT_SCHEDULE = {
    # 18:00 UTC = 21:00 TSİ — piyasalar kapandıktan sonra
    "collect-daily-market-data": {
        "task": "src.celery_app.tasks.collect_daily_market_data",
        "schedule": crontab(hour=settings.DATA_FETCH_HOUR, minute=0),
        "options": {"queue": "data_collection"},
    },
    # 18:30 UTC = 21:30 TSİ — veri toplama bittikten 30 dk sonra
    "run-daily-prediction": {
        "task": "src.celery_app.tasks.run_daily_prediction",
        "schedule": crontab(
            hour=settings.PREDICTION_HOUR,
            minute=settings.PREDICTION_MINUTE,
        ),
        "options": {"queue": "ml_prediction"},
    },
    # 07:00 UTC = 10:00 TSİ — kullanıcılar sabah okusun
    "send-daily-notifications": {
        "task": "src.celery_app.tasks.send_daily_notifications",
        "schedule": crontab(
            hour=settings.NOTIFICATION_HOUR,
            minute=0,
        ),
        "options": {"queue": "notifications"},
    },
    # Her 30 dakikada bir sağlık kontrolü
    "health-check": {
        "task": "src.celery_app.tasks.health_check",
        "schedule": crontab(minute="*/30"),
        "options": {"queue": "default"},
    },
}
