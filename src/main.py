"""
Yakıt Analizi — FastAPI Ana Uygulama.

Türkiye Akaryakıt Zam Öngörü Sistemi — Katman 1 Veri Toplama Servisi.
Brent petrol fiyatı, USD/TRY döviz kuru ve piyasa verisi API'si.
"""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.market_data_routes import router as market_data_router
from src.api.mbe_routes import router as mbe_router
from src.api.price_change_routes import router as price_change_router
from src.api.risk_routes import router as risk_router
from src.api.regime_routes import router as regime_router
from src.api.alert_routes import router as alert_router
from src.api.delay_routes import router as delay_router
from src.api.backtest_routes import router as backtest_router
from src.api.ml_routes import router as ml_router
from src.api.telegram_admin_routes import router as telegram_admin_router
from src.api.predictor_v5_routes import router as predictor_v5_router
from src.config.database import dispose_engine

# --- Loglama Ayarları ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# --- Yaşam Döngüsü ---


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Uygulama başlatma ve kapatma olayları."""
    logger.info("Yakıt Analizi servisi başlatılıyor...")
    logger.info("Veritabanı bağlantısı hazır")

    # --- ML Model Lazy-Startup Loading ---
    try:
        from src.ml.predictor import get_predictor

        predictor = get_predictor()
        loaded = predictor.load_model()
        if loaded:
            logger.info(
                "ML modeli yuklendi: versiyon=%s, feature_count=%d",
                predictor.model_version,
                len(predictor.feature_names),
            )
        else:
            logger.info(
                "ML modeli bulunamadi — ilk /train cagrisinda egitilecek"
            )
    except Exception as exc:
        logger.warning("ML model yukleme hatasi (non-critical): %s", exc)

    # --- Telegram Bot Başlatma ---
    bot_app = None
    try:
        from src.telegram.bot import create_bot_application

        bot_app = await create_bot_application()
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling()
        logger.info("Telegram Bot başlatıldı: polling aktif")
    except Exception as exc:
        logger.warning("Telegram Bot başlatma hatası (non-critical): %s", exc)
        bot_app = None

    yield

    # --- Telegram Bot Kapatma ---
    if bot_app is not None:
        try:
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
            logger.info("Telegram Bot kapatıldı")
        except Exception as exc:
            logger.warning("Telegram Bot kapatma hatası: %s", exc)

    logger.info("Yakıt Analizi servisi kapatılıyor...")
    await dispose_engine()
    logger.info("Veritabanı bağlantısı kapatıldı")


# --- FastAPI Uygulaması ---

app = FastAPI(
    title="Yakıt Analizi API",
    description=(
        "Türkiye Akaryakıt Zam Öngörü Sistemi — Katman 1 Veri Toplama Servisi.\n\n"
        "Brent petrol fiyatı, USD/TRY döviz kuru ve piyasa verisi API'si.\n"
        "Veri kaynakları: TCMB EVDS, Yahoo Finance (yfinance)"
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Geliştirme aşamasında; prodüksiyon'da kısıtlanacak
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Router'ları Ekle ---
app.include_router(market_data_router)
app.include_router(mbe_router)
app.include_router(price_change_router)
app.include_router(risk_router)
app.include_router(regime_router)
app.include_router(alert_router)
app.include_router(delay_router)
app.include_router(backtest_router)
app.include_router(ml_router)
app.include_router(telegram_admin_router)
app.include_router(predictor_v5_router)


# --- Health Check ---


@app.get(
    "/health",
    tags=["Sistem"],
    summary="Sağlık kontrolü",
    description="Servisin çalışır durumda olup olmadığını kontrol eder.",
)
async def health_check() -> dict:
    """Servis sağlık kontrolü endpoint'i."""
    return {
        "status": "healthy",
        "service": "yakit-analizi",
        "version": "0.1.0",
    }


@app.get(
    "/",
    tags=["Sistem"],
    summary="Kök endpoint",
    include_in_schema=False,
)
async def root() -> dict:
    """API bilgi sayfasına yönlendirme."""
    return {
        "message": "Yakıt Analizi API'ye hoş geldiniz",
        "docs": "/docs",
        "health": "/health",
    }
