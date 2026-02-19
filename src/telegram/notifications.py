"""
Gunluk bildirim sistemi.

Aktif ve onaylanmis kullanicilara gunluk yakit raporu gonderir.
Rate limiting ile Telegram API limitlerini asmayi onler.
Hata yonetimi: Mesaj gonderilemezse kullaniciyi deaktif eder.

v2: Streak-based bildirim — predictions_v5'ten ardisik gun sinyali.
"""

import asyncio
import logging

from telegram import Bot
from telegram.error import Forbidden, BadRequest

from src.config.database import async_session_factory
from src.config.settings import settings
from src.repositories.telegram_repository import (
    deactivate_user,
    get_active_approved_users,
)
from src.telegram.handlers import format_daily_notification

logger = logging.getLogger(__name__)

# Telegram API rate limit: saniyede max 30 mesaj
# Guvenli deger: 0.05s = 20 mesaj/s
RATE_LIMIT_DELAY = 0.05


# ────────────────────────────────────────────────────────────────────────────
#  Gunluk Bildirim Gonderme
# ────────────────────────────────────────────────────────────────────────────


async def send_daily_notifications(bot: Bot | None = None) -> dict:
    """
    Tum aktif ve onaylanmis kullanicilara gunluk bildirim gonderir.

    Streak-based format: format_daily_notification() async olarak
    predictions_v5'ten veri ceker ve kisa bildirim olusturur.

    Args:
        bot: Telegram Bot instance. None ise yeni olusturulur.

    Returns:
        Sonuc dict: {"sent": int, "failed": int, "total": int, "deactivated": int}
    """
    if bot is None:
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

    # Streak-based bildirim mesajini olustur (tum kullanicilar icin ayni)
    message_text = await format_daily_notification()

    # Hedef kullanicilari al
    async with async_session_factory() as session:
        try:
            users = await get_active_approved_users(session)
            await session.commit()
        except Exception as exc:
            logger.error("Bildirim kullanici listesi alinamadi: %s", exc)
            return {"sent": 0, "failed": 0, "total": 0, "deactivated": 0}

    total = len(users)
    sent = 0
    failed = 0
    deactivated = 0

    logger.info("Gunluk bildirim baslatiliyor: %d kullanici hedef", total)

    for user in users:
        try:
            await bot.send_message(
                chat_id=user.telegram_id,
                text=message_text,
            )
            sent += 1

        except Forbidden:
            # Kullanici botu engelledi
            logger.warning(
                "Bot engellendi, deaktif ediliyor: telegram_id=%s",
                user.telegram_id,
            )
            await _deactivate_blocked_user(user.telegram_id)
            failed += 1
            deactivated += 1

        except BadRequest as exc:
            # Chat bulunamadi veya gecersiz
            logger.warning(
                "Mesaj gonderilemedi (BadRequest): telegram_id=%s, hata=%s",
                user.telegram_id,
                exc,
            )
            if "chat not found" in str(exc).lower():
                await _deactivate_blocked_user(user.telegram_id)
                deactivated += 1
            failed += 1

        except Exception as exc:
            logger.error(
                "Mesaj gonderim hatasi: telegram_id=%s, hata=%s",
                user.telegram_id,
                exc,
            )
            failed += 1

        # Rate limiting
        await asyncio.sleep(RATE_LIMIT_DELAY)

    logger.info(
        "Gunluk bildirim tamamlandi: sent=%d, failed=%d, total=%d, deactivated=%d",
        sent,
        failed,
        total,
        deactivated,
    )

    return {
        "sent": sent,
        "failed": failed,
        "total": total,
        "deactivated": deactivated,
    }


async def _deactivate_blocked_user(telegram_id: int) -> None:
    """Botu engelleyen veya silen kullaniciyi deaktif eder."""
    async with async_session_factory() as session:
        try:
            await deactivate_user(session, telegram_id)
            await session.commit()
        except Exception as exc:
            logger.error(
                "Deaktivasyon hatasi: telegram_id=%s, hata=%s",
                telegram_id,
                exc,
            )


# ────────────────────────────────────────────────────────────────────────────
#  Tekil Mesaj Gonderme
# ────────────────────────────────────────────────────────────────────────────


async def send_message_to_user(
    telegram_id: int,
    text: str,
    bot: Bot | None = None,
) -> bool:
    """
    Belirli bir kullaniciya mesaj gonderir.

    Args:
        telegram_id: Hedef Telegram kullanici ID.
        text: Gonderilecek mesaj metni.
        bot: Telegram Bot instance. None ise yeni olusturulur.

    Returns:
        True ise basarili, False ise hata olustu.
    """
    if bot is None:
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

    try:
        await bot.send_message(chat_id=telegram_id, text=text)
        logger.info("Mesaj gonderildi: telegram_id=%s", telegram_id)
        return True
    except Forbidden:
        logger.warning(
            "Mesaj gonderilemedi (engellenmis): telegram_id=%s",
            telegram_id,
        )
        return False
    except Exception as exc:
        logger.error(
            "Mesaj gonderim hatasi: telegram_id=%s, hata=%s",
            telegram_id,
            exc,
        )
        return False


# ────────────────────────────────────────────────────────────────────────────
#  Toplu Mesaj (Broadcast)
# ────────────────────────────────────────────────────────────────────────────


async def broadcast_message(
    text: str,
    bot: Bot | None = None,
) -> dict:
    """
    Tum aktif ve onaylanmis kullanicilara ozel mesaj gonderir.

    Args:
        text: Gonderilecek mesaj.
        bot: Telegram Bot instance.

    Returns:
        Sonuc dict: {"sent": int, "failed": int, "total": int}
    """
    if bot is None:
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

    async with async_session_factory() as session:
        try:
            users = await get_active_approved_users(session)
            await session.commit()
        except Exception as exc:
            logger.error("Broadcast kullanici listesi alinamadi: %s", exc)
            return {"sent": 0, "failed": 0, "total": 0}

    total = len(users)
    sent = 0
    failed = 0

    for user in users:
        try:
            await bot.send_message(chat_id=user.telegram_id, text=text)
            sent += 1
        except Exception as exc:
            logger.warning(
                "Broadcast mesaj hatasi: telegram_id=%s, hata=%s",
                user.telegram_id,
                exc,
            )
            failed += 1

        await asyncio.sleep(RATE_LIMIT_DELAY)

    logger.info("Broadcast tamamlandi: sent=%d, failed=%d, total=%d", sent, failed, total)

    return {"sent": sent, "failed": failed, "total": total}
