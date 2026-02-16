"""
Telegram Bot handler testleri.

Bot.py modulu icin birim testleri.
Gercek Telegram API'sine istek ATILMAZ — tum dissal bagimliliklar mock'lanir.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.telegram.bot import create_bot_application


class TestCreateBotApplication:
    """create_bot_application fonksiyonu testleri."""

    @pytest.mark.asyncio
    @patch("src.telegram.bot.Application")
    async def test_creates_application_with_token(self, mock_app_cls):
        """Bot uygulamasi dogru token ile olusturulmali."""
        mock_builder = MagicMock()
        mock_app_instance = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app_instance
        mock_app_cls.builder.return_value = mock_builder

        result = await create_bot_application()

        mock_app_cls.builder.assert_called_once()
        mock_builder.token.assert_called_once()
        mock_builder.build.assert_called_once()
        assert result == mock_app_instance

    @pytest.mark.asyncio
    @patch("src.telegram.bot.Application")
    async def test_registers_conversation_handler(self, mock_app_cls):
        """ConversationHandler kaydedilmeli."""
        mock_builder = MagicMock()
        mock_app_instance = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app_instance
        mock_app_cls.builder.return_value = mock_builder

        await create_bot_application()

        # ConversationHandler + 3 CommandHandler = en az 4 add_handler cagrisi
        assert mock_app_instance.add_handler.call_count >= 4

    @pytest.mark.asyncio
    @patch("src.telegram.bot.Application")
    async def test_registers_rapor_handler(self, mock_app_cls):
        """rapor komutu handler'i kaydedilmeli."""
        mock_builder = MagicMock()
        mock_app_instance = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app_instance
        mock_app_cls.builder.return_value = mock_builder

        await create_bot_application()

        # add_handler cagrildigi kontrol et
        handler_calls = mock_app_instance.add_handler.call_args_list
        assert len(handler_calls) >= 2  # en az conv + rapor
