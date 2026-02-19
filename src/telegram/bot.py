"""
Telegram Bot baslangic ve ana konfigurasyon.

Bot uygulamasini olusturur, handler'lari kaydeder
ve FastAPI lifecycle ile entegrasyonu saglar.
"""

import logging

from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from src.config.settings import settings
from src.telegram.handlers import (
    iptal_command,
    rapor_command,
    yardim_command,
)
from src.telegram.registration import (
    WAITING_PHONE,
    cancel_registration,
    receive_contact,
    receive_phone_text,
    start_command,
)

logger = logging.getLogger(__name__)


async def create_bot_application() -> Application:
    """
    Bot uygulamasini olusturur ve handler'lari kaydeder.

    Returns:
        Yapilandirilmis Application nesnesi.
    """
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # ── Kayit conversation handler ──
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            WAITING_PHONE: [
                MessageHandler(filters.CONTACT, receive_contact),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_phone_text,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("iptal", cancel_registration),
        ],
    )

    app.add_handler(conv_handler)

    # ── Bagimsiz komut handler'lari ──
    app.add_handler(CommandHandler("rapor", rapor_command))
    app.add_handler(CommandHandler("iptal", iptal_command))
    app.add_handler(CommandHandler("yardim", yardim_command))

    # ── "📊 Rapor İste" buton handler'i ──
    # ConversationHandler DISINDA — sabit buton tiklandiginda rapor gonderir
    app.add_handler(
        MessageHandler(
            filters.Regex("^📊 Rapor İste$"),
            rapor_command,
        )
    )

    logger.info("Telegram Bot handler'lari kaydedildi")

    return app
