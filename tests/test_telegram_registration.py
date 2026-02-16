"""
Telegram kayit akisi testleri.

ConversationHandler state gecisleri, telefon numarasi validasyonu
ve kayit islem akisi testleri.
Gercek Telegram API'sine istek ATILMAZ — tum dissal bagimliliklar mock'lanir.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.telegram.registration import (
    ALREADY_REGISTERED_APPROVED,
    ALREADY_REGISTERED_PENDING,
    REGISTRATION_REACTIVATED,
    REGISTRATION_SUCCESS,
    WAITING_PHONE,
    WELCOME_MESSAGE,
    cancel_registration,
    receive_contact,
    start_command,
)


def _make_update(user_id=123456, username="testuser", first_name="Test"):
    """Test icin mock Update nesnesi olusturur."""
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.effective_user.first_name = first_name
    update.effective_user.last_name = None
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.contact = None
    return update


def _make_context():
    """Test icin mock context nesnesi olusturur."""
    return MagicMock()


# ────────────────────────────────────────────────────────────────────────────
#  /start Komutu Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestStartCommand:
    """start_command fonksiyonu testleri."""

    @pytest.mark.asyncio
    @patch("src.telegram.registration.async_session_factory")
    async def test_new_user_gets_welcome_message(self, mock_factory):
        """Yeni kullanici hosgeldin mesaji almali."""
        # DB'de kullanici yok
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "src.telegram.registration.get_user_by_telegram_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            update = _make_update()
            context = _make_context()
            result = await start_command(update, context)

        assert result == WAITING_PHONE
        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args
        assert WELCOME_MESSAGE in call_args[0] or call_args.kwargs.get("text") == WELCOME_MESSAGE

    @pytest.mark.asyncio
    @patch("src.telegram.registration.async_session_factory")
    async def test_approved_user_gets_already_registered(self, mock_factory):
        """Onaylanmis kullanici 'zaten kayitli' mesaji almali."""
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        existing_user = MagicMock()
        existing_user.is_approved = True
        existing_user.is_active = True

        with patch(
            "src.telegram.registration.get_user_by_telegram_id",
            new_callable=AsyncMock,
            return_value=existing_user,
        ):
            update = _make_update()
            context = _make_context()
            result = await start_command(update, context)

        assert result == -1  # ConversationHandler.END
        call_args = update.message.reply_text.call_args
        msg = call_args[0][0] if call_args[0] else call_args.kwargs.get("text", "")
        assert "Zaten kayıtlısınız" in msg

    @pytest.mark.asyncio
    @patch("src.telegram.registration.async_session_factory")
    async def test_pending_user_gets_waiting_message(self, mock_factory):
        """Onay bekleyen kullanici 'bekliyor' mesaji almali."""
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        existing_user = MagicMock()
        existing_user.is_approved = False
        existing_user.is_active = True

        with patch(
            "src.telegram.registration.get_user_by_telegram_id",
            new_callable=AsyncMock,
            return_value=existing_user,
        ):
            update = _make_update()
            context = _make_context()
            result = await start_command(update, context)

        assert result == -1  # ConversationHandler.END
        call_args = update.message.reply_text.call_args
        msg = call_args[0][0] if call_args[0] else call_args.kwargs.get("text", "")
        assert "onay" in msg.lower() or "bekleniyor" in msg.lower()

    @pytest.mark.asyncio
    @patch("src.telegram.registration.reactivate_user", new_callable=AsyncMock)
    @patch("src.telegram.registration.async_session_factory")
    async def test_inactive_user_gets_reactivated(self, mock_factory, mock_reactivate):
        """Deaktif kullanici yeniden aktif edilmeli."""
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        existing_user = MagicMock()
        existing_user.is_approved = False
        existing_user.is_active = False

        with patch(
            "src.telegram.registration.get_user_by_telegram_id",
            new_callable=AsyncMock,
            return_value=existing_user,
        ):
            update = _make_update()
            context = _make_context()
            result = await start_command(update, context)

        assert result == -1  # ConversationHandler.END
        mock_reactivate.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_effective_user_returns_end(self):
        """effective_user None ise -1 donmeli."""
        update = MagicMock()
        update.effective_user = None
        context = _make_context()

        result = await start_command(update, context)
        assert result == -1


# ────────────────────────────────────────────────────────────────────────────
#  Telefon Numarasi Alma Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestReceiveContact:
    """receive_contact fonksiyonu testleri."""

    @pytest.mark.asyncio
    @patch("src.telegram.registration.upsert_telegram_user", new_callable=AsyncMock)
    @patch("src.telegram.registration.async_session_factory")
    async def test_valid_contact_saves_to_db(self, mock_factory, mock_upsert):
        """Gecerli contact DB'ye kaydedilmeli."""
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        update = _make_update(user_id=789)
        update.message.contact = MagicMock()
        update.message.contact.phone_number = "+905551234567"
        update.message.contact.user_id = 789
        update.message.contact.first_name = "Test"
        update.message.contact.last_name = "User"

        context = _make_context()
        result = await receive_contact(update, context)

        assert result == -1  # ConversationHandler.END
        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args.kwargs
        assert call_kwargs["telegram_id"] == 789
        assert call_kwargs["phone_number"] == "+905551234567"

    @pytest.mark.asyncio
    async def test_no_contact_returns_error(self):
        """Contact None ise hata mesaji gonderilmeli."""
        update = _make_update()
        update.message.contact = None
        context = _make_context()

        result = await receive_contact(update, context)
        assert result == -1
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_foreign_contact_rejected(self):
        """Baska birinin contact'i reddedilmeli."""
        update = _make_update(user_id=100)
        update.message.contact = MagicMock()
        update.message.contact.phone_number = "+905559876543"
        update.message.contact.user_id = 999  # Farkli user
        update.message.contact.first_name = "Other"
        update.message.contact.last_name = None

        context = _make_context()
        result = await receive_contact(update, context)

        assert result == WAITING_PHONE  # Tekrar iste
        call_args = update.message.reply_text.call_args
        msg = call_args[0][0] if call_args[0] else ""
        assert "kendi" in msg.lower()

    @pytest.mark.asyncio
    @patch("src.telegram.registration.upsert_telegram_user", new_callable=AsyncMock)
    @patch("src.telegram.registration.async_session_factory")
    async def test_db_error_handled_gracefully(self, mock_factory, mock_upsert):
        """DB hatasi kullaniciya bildirilmeli."""
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_upsert.side_effect = Exception("DB connection error")

        update = _make_update(user_id=789)
        update.message.contact = MagicMock()
        update.message.contact.phone_number = "+905551234567"
        update.message.contact.user_id = 789
        update.message.contact.first_name = "Test"
        update.message.contact.last_name = None

        context = _make_context()
        result = await receive_contact(update, context)

        assert result == -1
        call_args = update.message.reply_text.call_args
        msg = call_args[0][0] if call_args[0] else ""
        assert "hata" in msg.lower()


# ────────────────────────────────────────────────────────────────────────────
#  /iptal (ConversationHandler fallback) Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestCancelRegistration:
    """cancel_registration fonksiyonu testleri."""

    @pytest.mark.asyncio
    async def test_cancel_returns_end(self):
        """Cancel -1 (END) donmeli."""
        update = _make_update()
        context = _make_context()

        result = await cancel_registration(update, context)
        assert result == -1

    @pytest.mark.asyncio
    async def test_cancel_sends_message(self):
        """Cancel mesaj gondermeli."""
        update = _make_update()
        context = _make_context()

        await cancel_registration(update, context)
        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "iptal" in msg.lower()
