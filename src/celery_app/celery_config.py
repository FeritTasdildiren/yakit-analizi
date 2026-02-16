"""
Celery uygulama konfigürasyonu.

Celery app instance'ı, broker/backend ayarları ve
Beat schedule yüklemesi burada yapılır.
"""

from celery import Celery

from src.config.settings import settings

celery_app = Celery(
    "yakit_analizi",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["src.celery_app.tasks"],
)

celery_app.conf.update(
    # Saat dilimi
    timezone="Europe/Istanbul",
    enable_utc=True,
    # Serileştirme
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Task izleme
    task_track_started=True,
    # Zaman limitleri
    task_time_limit=600,  # 10 dakika hard limit
    task_soft_time_limit=540,  # 9 dakika soft limit
    # Worker kaynak yönetimi
    worker_max_tasks_per_child=100,  # Memory leak önleme
    worker_prefetch_multiplier=1,  # Eşzamanlı prefetch sınırla
)

# Beat zamanlamasını yükle
from src.celery_app.beat_schedule import CELERY_BEAT_SCHEDULE  # noqa: E402

celery_app.conf.beat_schedule = CELERY_BEAT_SCHEDULE
