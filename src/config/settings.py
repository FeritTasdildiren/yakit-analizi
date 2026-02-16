"""
Uygulama konfigürasyonu.

Pydantic BaseSettings ile ortam değişkenlerinden okunan merkezi konfigürasyon.
.env dosyası destekler; ortam değişkenleri her zaman önceliklidir.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Yakıt Analizi uygulama ayarları."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Veritabanı ---
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/yakit_analizi"

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- TCMB EVDS API ---
    TCMB_EVDS_API_KEY: str = ""

    # --- Brent Veri Kaynağı ---
    # Birincil kaynak: yfinance. Fallback: "yahoo_web"
    BRENT_FALLBACK_SOURCE: str = "yahoo_web"

    # --- Zamanlama ---
    # Günlük veri çekme saati (UTC). 18 UTC = 21:00 TSİ
    DATA_FETCH_HOUR: int = 18

    # --- Celery Scheduler ---
    # Tahmin çalıştırma saati (UTC). 18:30 UTC = 21:30 TSİ
    PREDICTION_HOUR: int = 18
    PREDICTION_MINUTE: int = 30
    # Bildirim gönderme saati (UTC). 07:00 UTC = 10:00 TSİ
    NOTIFICATION_HOUR: int = 7

    # --- Telegram Bot ---
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_DAILY_NOTIFICATION_HOUR: int = 7  # UTC (10:00 TSİ)

    # --- Yeniden Deneme ---
    RETRY_COUNT: int = 3
    RETRY_BACKOFF: float = 2.0

    @property
    def sync_database_url(self) -> str:
        """Alembic gibi senkron araçlar için URL döndürür."""
        return self.DATABASE_URL.replace("+asyncpg", "")


# Tekil ayar nesnesi — import ederek kullan
settings = Settings()
