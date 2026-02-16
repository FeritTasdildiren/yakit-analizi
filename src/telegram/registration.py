"""
Telegram kayit akisi.

ConversationHandler ile kullanici kayit sureci:
1. /start → Hosgeldin + KVKK metni
2. Telefon numarasi paylasimi (Contact butonu VEYA metin olarak yaz)
3. DB kaydi + Admin onay bekleme mesaji
"""

import logging
import re

from telegram import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import ContextTypes

from src.config.database import async_session_factory
from src.repositories.telegram_repository import (
    get_user_by_telegram_id,
    reactivate_user,
    upsert_telegram_user,
)

logger = logging.getLogger(__name__)

# ConversationHandler state'leri
WAITING_PHONE = 0

# Telefon numarasi regex: +90xxx, 05xxx, 5xxx gibi formatlar
_PHONE_REGEX = re.compile(r"^\+?\d[\d\s\-()]{7,15}$")


# ────────────────────────────────────────────────────────────────────────────
#  KVKK + Disclaimer Metni
# ────────────────────────────────────────────────────────────────────────────

WELCOME_MESSAGE = (
    "⛽ Yakıt Haber Bot'a hoş geldiniz!\n\n"
    "Bu bot, Türkiye akaryakıt fiyat değişimlerini önceden tahmin eden "
    "bir erken uyarı sistemidir.\n\n"
    "⚠️ YASAL UYARI: Bu bot yatırım tavsiyesi vermez. "
    "Paylaşılan bilgiler istatistiksel analiz ve makine öğrenmesi "
    "modellerine dayanmaktadır. Gerçek fiyat değişimleri farklılık gösterebilir.\n\n"
    "📋 KVKK AYDINLATMA: Telefon numaranız yalnızca kimlik doğrulama "
    "amacıyla saklanır. Verileriniz üçüncü taraflarla paylaşılmaz. "
    "İptal için /iptal yazabilirsiniz.\n\n"
    "Devam etmek için aşağıdaki butona basarak telefon numaranızı paylaşın\n"
    "veya numaranızı metin olarak yazın (ör: 05XX XXX XX XX):"
)

ALREADY_REGISTERED_APPROVED = (
    "✅ Zaten kayıtlısınız ve hesabınız onaylı.\n"
    "Günlük bildirimler aktif. Anlık rapor için /rapor yazın."
)

ALREADY_REGISTERED_PENDING = (
    "⏳ Kaydınız daha önce alınmıştır.\n"
    "Admin onayı bekleniyor. Onaylandığında bildirim alacaksınız."
)

REGISTRATION_SUCCESS = (
    "✅ Kaydınız başarıyla alındı!\n\n"
    "⏳ Admin onayı bekleniyor. Onaylandığında size bildirim göndereceğiz.\n"
    "Onay sonrası günlük yakıt raporu alabileceksiniz."
)

REGISTRATION_REACTIVATED = (
    "🔄 Hesabınız yeniden aktif edildi!\n\n"
    "⏳ Admin onayı bekleniyor. Onaylandığında size bildirim göndereceğiz."
)

INVALID_PHONE = (
    "❌ Geçersiz telefon numarası.\n\n"
    "Lütfen aşağıdaki butona basarak numaranızı paylaşın\n"
    "veya şu formatta yazın: 05XX XXX XX XX"
)


# ────────────────────────────────────────────────────────────────────────────
#  /start Komutu
# ────────────────────────────────────────────────────────────────────────────


async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    user = update.effective_user
    if user is None:
        return -1

    telegram_id = user.id

    async with async_session_factory() as session:
        try:
            existing = await get_user_by_telegram_id(session, telegram_id)
            await session.commit()
        except Exception as exc:
            logger.error("DB sorgulama hatasi: %s", exc)
            existing = None

    if existing is not None:
        if existing.is_approved and existing.is_active:
            await update.message.reply_text(
                ALREADY_REGISTERED_APPROVED,
                reply_markup=ReplyKeyboardRemove(),
            )
            return -1

        if existing.is_active and not existing.is_approved:
            await update.message.reply_text(
                ALREADY_REGISTERED_PENDING,
                reply_markup=ReplyKeyboardRemove(),
            )
            return -1

        if not existing.is_active:
            async with async_session_factory() as session:
                try:
                    await reactivate_user(session, telegram_id)
                    await session.commit()
                except Exception as exc:
                    logger.error("Yeniden aktivasyon hatasi: %s", exc)

            await update.message.reply_text(
                REGISTRATION_REACTIVATED,
                reply_markup=ReplyKeyboardRemove(),
            )
            return -1

    # Yeni kullanici — telefon numarasi iste
    contact_button = KeyboardButton(
        text="📱 Telefon Numaramı Paylaş",
        request_contact=True,
    )
    reply_markup = ReplyKeyboardMarkup(
        [[contact_button]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )

    await update.message.reply_text(
        WELCOME_MESSAGE,
        reply_markup=reply_markup,
    )

    return WAITING_PHONE


# ────────────────────────────────────────────────────────────────────────────
#  Telefon Numarasi Alma — Contact butonu
# ────────────────────────────────────────────────────────────────────────────


async def receive_contact(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    user = update.effective_user
    contact = update.message.contact

    if user is None or contact is None:
        await update.message.reply_text(
            "❌ Telefon numarası alınamadı. Lütfen tekrar deneyin: /start",
            reply_markup=ReplyKeyboardRemove(),
        )
        return -1

    if contact.user_id and contact.user_id != user.id:
        await update.message.reply_text(
            "❌ Lütfen kendi telefon numaranızı paylaşın.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return WAITING_PHONE

    phone_number = contact.phone_number
    return await _save_registration(
        update, user, phone_number,
        contact.first_name, contact.last_name,
    )


# ────────────────────────────────────────────────────────────────────────────
#  Telefon Numarasi Alma — Metin olarak yazma
# ────────────────────────────────────────────────────────────────────────────


async def receive_phone_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Kullanıcı telefon numarasını metin olarak yazdığında işler."""
    user = update.effective_user
    if user is None:
        return -1

    text = update.message.text.strip()

    # Telefon numarası formatını doğrula
    cleaned = re.sub(r"[\s\-()]", "", text)
    if not _PHONE_REGEX.match(text) or len(cleaned) < 10:
        await update.message.reply_text(INVALID_PHONE)
        return WAITING_PHONE

    # Türkiye numarası normalizasyonu
    if cleaned.startswith("0"):
        cleaned = "+90" + cleaned[1:]
    elif cleaned.startswith("90") and not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    elif not cleaned.startswith("+"):
        cleaned = "+90" + cleaned

    return await _save_registration(
        update, user, cleaned,
        user.first_name, user.last_name,
    )


# ────────────────────────────────────────────────────────────────────────────
#  Ortak Kayıt Fonksiyonu
# ────────────────────────────────────────────────────────────────────────────


async def _save_registration(
    update: Update,
    user,
    phone_number: str,
    first_name: str | None,
    last_name: str | None,
) -> int:
    """Kullanıcıyı DB'ye kaydeder."""
    telegram_id = user.id
    username = user.username

    async with async_session_factory() as session:
        try:
            await upsert_telegram_user(
                session,
                telegram_id=telegram_id,
                username=username,
                first_name=first_name or user.first_name,
                last_name=last_name or user.last_name,
                phone_number=phone_number,
            )
            await session.commit()

            logger.info(
                "Yeni kayit: telegram_id=%s, username=%s, phone=%s",
                telegram_id,
                username,
                phone_number[:4] + "****",
            )
        except Exception as exc:
            logger.error("Kayit DB hatasi: %s", exc)
            await update.message.reply_text(
                "❌ Kayıt sırasında bir hata oluştu. Lütfen tekrar deneyin: /start",
                reply_markup=ReplyKeyboardRemove(),
            )
            return -1

    await update.message.reply_text(
        REGISTRATION_SUCCESS,
        reply_markup=ReplyKeyboardRemove(),
    )

    return -1


# ────────────────────────────────────────────────────────────────────────────
#  /iptal — Kayit akisini iptal et
# ────────────────────────────────────────────────────────────────────────────


async def cancel_registration(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    await update.message.reply_text(
        "❌ Kayıt işlemi iptal edildi. Tekrar başlamak için /start yazın.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return -1
