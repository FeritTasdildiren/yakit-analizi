"""
Telegram bildirim sistemi testleri.

send_daily_notifications, send_message_to_user ve broadcast_message
fonksiyonlari icin birim testleri.
Gercek Telegram API'sine istek ATILMAZ — tum dissal bagimliliklar mock'lanir.

NOT: Celery testleri sys.modules icerisinde src.telegram modülünü degistirip
yeniden yukleme yapar, bu nedenle fonksiyonlar her testte taze import edilir.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import Forbidden, BadRequest


def _make_user(telegram_id: int, username: str = "user") -> MagicMock:
    """Test icin mock TelegramUser nesnesi olusturur."""
    user = MagicMock()
    user.telegram_id = telegram_id
    user.username = username
    user.is_approved = True
    user.is_active = True
    return user


# ────────────────────────────────────────────────────────────────────────────
#  send_daily_notifications Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestSendDailyNotifications:
    """send_daily_notifications fonksiyonu testleri."""

    @pytest.mark.asyncio
    async def test_sends_to_all_active_users(self):
        """Tum aktif kullanicilara mesaj gonderilmeli."""
        import src.telegram.notifications as mod

        users = [_make_user(1, "user1"), _make_user(2, "user2"), _make_user(3, "user3")]

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()

        mock_session = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(mod, "async_session_factory", return_value=mock_cm), \
             patch.object(mod, "_fetch_report_data", new_callable=AsyncMock, return_value=None), \
             patch.object(mod, "get_active_approved_users", new_callable=AsyncMock, return_value=users):
            result = await mod.send_daily_notifications(bot=mock_bot)

        assert result["sent"] == 3
        assert result["failed"] == 0
        assert result["total"] == 3
        assert mock_bot.send_message.call_count == 3

    @pytest.mark.asyncio
    async def test_forbidden_deactivates_user(self):
        """Forbidden hatasi kullaniciyi deaktif etmeli."""
        import src.telegram.notifications as mod

        users = [_make_user(1)]
        mock_deactivate = AsyncMock()

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(
            side_effect=Forbidden("Forbidden: bot was blocked by the user")
        )

        mock_session = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(mod, "async_session_factory", return_value=mock_cm), \
             patch.object(mod, "_fetch_report_data", new_callable=AsyncMock, return_value=None), \
             patch.object(mod, "get_active_approved_users", new_callable=AsyncMock, return_value=users), \
             patch.object(mod, "_deactivate_blocked_user", mock_deactivate):
            result = await mod.send_daily_notifications(bot=mock_bot)

        assert result["failed"] == 1
        assert result["deactivated"] == 1
        mock_deactivate.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_bad_request_chat_not_found_deactivates(self):
        """BadRequest 'chat not found' kullaniciyi deaktif etmeli."""
        import src.telegram.notifications as mod

        users = [_make_user(1)]
        mock_deactivate = AsyncMock()

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(
            side_effect=BadRequest("Chat not found")
        )

        mock_session = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(mod, "async_session_factory", return_value=mock_cm), \
             patch.object(mod, "_fetch_report_data", new_callable=AsyncMock, return_value=None), \
             patch.object(mod, "get_active_approved_users", new_callable=AsyncMock, return_value=users), \
             patch.object(mod, "_deactivate_blocked_user", mock_deactivate):
            result = await mod.send_daily_notifications(bot=mock_bot)

        assert result["deactivated"] == 1

    @pytest.mark.asyncio
    async def test_no_users_returns_zero(self):
        """Kullanici yoksa sent=0 donmeli."""
        import src.telegram.notifications as mod

        mock_bot = AsyncMock()

        mock_session = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(mod, "async_session_factory", return_value=mock_cm), \
             patch.object(mod, "_fetch_report_data", new_callable=AsyncMock, return_value=None), \
             patch.object(mod, "get_active_approved_users", new_callable=AsyncMock, return_value=[]):
            result = await mod.send_daily_notifications(bot=mock_bot)

        assert result["sent"] == 0
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self):
        """Bazi basarili bazi basarisiz gonderimler dogru sayilmali."""
        import src.telegram.notifications as mod

        users = [_make_user(1), _make_user(2), _make_user(3)]

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(
            side_effect=[None, Exception("Network error"), None]
        )

        mock_session = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(mod, "async_session_factory", return_value=mock_cm), \
             patch.object(mod, "_fetch_report_data", new_callable=AsyncMock, return_value=None), \
             patch.object(mod, "get_active_approved_users", new_callable=AsyncMock, return_value=users):
            result = await mod.send_daily_notifications(bot=mock_bot)

        assert result["sent"] == 2
        assert result["failed"] == 1
        assert result["total"] == 3


# ────────────────────────────────────────────────────────────────────────────
#  send_message_to_user Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestSendMessageToUser:
    """send_message_to_user fonksiyonu testleri."""

    @pytest.mark.asyncio
    async def test_send_success(self):
        """Basarili gonderim True donmeli."""
        import src.telegram.notifications as mod

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()

        result = await mod.send_message_to_user(123, "Hello!", bot=mock_bot)
        assert result is True
        mock_bot.send_message.assert_called_once_with(chat_id=123, text="Hello!")

    @pytest.mark.asyncio
    async def test_send_forbidden_returns_false(self):
        """Forbidden hatasi False donmeli."""
        import src.telegram.notifications as mod

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(
            side_effect=Forbidden("bot blocked")
        )

        result = await mod.send_message_to_user(123, "Hello!", bot=mock_bot)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_generic_error_returns_false(self):
        """Genel hata False donmeli."""
        import src.telegram.notifications as mod

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(
            side_effect=Exception("Network error")
        )

        result = await mod.send_message_to_user(123, "Hello!", bot=mock_bot)
        assert result is False


# ────────────────────────────────────────────────────────────────────────────
#  broadcast_message Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestBroadcastMessage:
    """broadcast_message fonksiyonu testleri."""

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self):
        """Broadcast tum kullanicilara mesaj gonderilmeli."""
        import src.telegram.notifications as mod

        users = [_make_user(1), _make_user(2)]

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()

        mock_session = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(mod, "async_session_factory", return_value=mock_cm), \
             patch.object(mod, "get_active_approved_users", new_callable=AsyncMock, return_value=users):
            result = await mod.broadcast_message("Test broadcast", bot=mock_bot)

        assert result["sent"] == 2
        assert result["total"] == 2
        assert mock_bot.send_message.call_count == 2

    @pytest.mark.asyncio
    async def test_broadcast_empty_users(self):
        """Kullanici yoksa sent=0 donmeli."""
        import src.telegram.notifications as mod

        mock_bot = AsyncMock()

        mock_session = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(mod, "async_session_factory", return_value=mock_cm), \
             patch.object(mod, "get_active_approved_users", new_callable=AsyncMock, return_value=[]):
            result = await mod.broadcast_message("Test", bot=mock_bot)

        assert result["sent"] == 0
        assert result["total"] == 0


# ────────────────────────────────────────────────────────────────────────────
#  Rate Limiting Testi
# ────────────────────────────────────────────────────────────────────────────


class TestRateLimiting:
    """Rate limiting konfigurasyonu testleri."""

    def test_rate_limit_delay_within_bounds(self):
        """Rate limit gecikmesi 0 ile 1 saniye arasinda olmali."""
        import src.telegram.notifications as mod

        assert 0 < mod.RATE_LIMIT_DELAY <= 1.0

    def test_rate_limit_allows_20_per_second(self):
        """Rate limit saniyede en az 20 mesaja izin vermeli."""
        import src.telegram.notifications as mod

        messages_per_second = 1 / mod.RATE_LIMIT_DELAY
        assert messages_per_second >= 20
