"""
Telegram komut handler testleri.

/rapor, /iptal, /yardim komutlari ve rapor formatlama testleri.
Gercek Telegram API'sine istek ATILMAZ — tum dissal bagimliliklar mock'lanir.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.telegram.handlers import (
    HELP_MESSAGE,
    _risk_level,
    format_daily_notification,
    format_full_report,
    iptal_command,
    rapor_command,
    yardim_command,
)


def _make_update(user_id=123456, username="testuser"):
    """Test icin mock Update nesnesi olusturur."""
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


def _make_context():
    """Test icin mock context nesnesi olusturur."""
    return MagicMock()


def _make_report_data(
    fuel_type: str = "benzin",
    pump_price: float = 42.50,
    mbe_value: float = 0.85,
    risk_score: float = 72.0,
    ml_direction: str = "hike",
    ml_probability: float = 78.0,
    expected_change: float = 0.45,
):
    """Test icin rapor verisi dict'i olusturur."""
    return {
        "fuel_type": fuel_type,
        "pump_price": pump_price,
        "mbe_value": mbe_value,
        "risk_score": risk_score,
        "ml_direction": ml_direction,
        "ml_probability": ml_probability,
        "expected_change": expected_change,
        "model_version": "v1.0",
    }


# ────────────────────────────────────────────────────────────────────────────
#  Rapor Formatlama Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestFormatFullReport:
    """format_full_report fonksiyonu testleri."""

    def test_report_contains_benzin_section(self):
        """Rapor benzin bolumu icermeli."""
        benzin = _make_report_data("benzin")
        motorin = _make_report_data("motorin", pump_price=41.20)

        report = format_full_report(benzin, motorin)

        assert "BENZİN" in report
        assert "MOTORİN" in report
        assert "42.50" in report

    def test_report_contains_header(self):
        """Rapor baslik icermeli."""
        report = format_full_report(None, None)
        assert "Yakıt Analizi Raporu" in report

    def test_report_contains_disclaimer(self):
        """Rapor yasal uyari icermeli."""
        report = format_full_report(None, None)
        assert "yatırım tavsiyesi" in report.lower()

    def test_report_with_none_data(self):
        """None veri ile rapor hata vermemeli."""
        report = format_full_report(None, None)
        assert "Veri alınamadı" in report

    def test_report_shows_hike_direction(self):
        """ZAM yonu dogru gosterilmeli."""
        benzin = _make_report_data(ml_direction="hike")
        report = format_full_report(benzin, None)
        assert "ZAM" in report

    def test_report_shows_stable_direction(self):
        """SABİT yonu dogru gosterilmeli."""
        benzin = _make_report_data(ml_direction="stable", ml_probability=65.0)
        report = format_full_report(benzin, None)
        assert "SABİT" in report

    def test_report_shows_expected_change(self):
        """Beklenen degisim dogru gosterilmeli."""
        benzin = _make_report_data(expected_change=0.45)
        report = format_full_report(benzin, None)
        assert "+0.45" in report

    def test_report_model_version(self):
        """Model versiyonu gosterilmeli."""
        benzin = _make_report_data()
        report = format_full_report(benzin, None)
        assert "v1.0" in report


class TestFormatDailyNotification:
    """format_daily_notification fonksiyonu testleri."""

    def test_notification_shorter_than_report(self):
        """Bildirim rapordan kisa olmali."""
        benzin = _make_report_data()
        motorin = _make_report_data("motorin", pump_price=41.20)

        notification = format_daily_notification(benzin, motorin)
        report = format_full_report(benzin, motorin)

        assert len(notification) < len(report)

    def test_notification_contains_header(self):
        """Bildirim baslik icermeli."""
        notification = format_daily_notification(None, None)
        assert "Günlük Yakıt Raporu" in notification

    def test_notification_contains_disclaimer(self):
        """Bildirim yasal uyari icermeli."""
        notification = format_daily_notification(None, None)
        assert "Yatırım tavsiyesi" in notification

    def test_notification_mentions_rapor_command(self):
        """Bildirim /rapor komutunu belirtmeli."""
        notification = format_daily_notification(None, None)
        assert "/rapor" in notification

    def test_notification_with_hike_risk(self):
        """ZAM riski dogru formatlanmali."""
        benzin = _make_report_data(ml_direction="hike", ml_probability=78)
        notification = format_daily_notification(benzin, None)
        assert "ZAM" in notification
        assert "78" in notification


# ────────────────────────────────────────────────────────────────────────────
#  Risk Level Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestRiskLevel:
    """_risk_level fonksiyonu testleri."""

    def test_high_risk(self):
        """70+ risk 'Cok yuksek risk' donmeli."""
        result = _risk_level(75.0)
        assert "yüksek" in result.lower()

    def test_medium_risk(self):
        """50-70 risk 'Yuksek risk' donmeli."""
        result = _risk_level(55.0)
        assert "risk" in result.lower()

    def test_low_risk(self):
        """50 alti risk 'Normal' donmeli."""
        result = _risk_level(30.0)
        assert "Normal" in result

    def test_none_risk(self):
        """None risk 'Veri yok' donmeli."""
        result = _risk_level(None)
        assert "Veri yok" in result


# ────────────────────────────────────────────────────────────────────────────
#  /rapor Komutu Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestRaporCommand:
    """/rapor komut isleyicisi testleri."""

    @pytest.mark.asyncio
    @patch("src.telegram.handlers._fetch_report_data", new_callable=AsyncMock)
    @patch("src.telegram.handlers._check_approved_user", new_callable=AsyncMock)
    async def test_approved_user_gets_report(self, mock_check, mock_fetch):
        """Onaylanmis kullanici rapor almali."""
        mock_check.return_value = True
        mock_fetch.return_value = _make_report_data()

        update = _make_update()
        context = _make_context()

        await rapor_command(update, context)

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "Yakıt Analizi Raporu" in msg

    @pytest.mark.asyncio
    @patch("src.telegram.handlers._check_approved_user", new_callable=AsyncMock)
    async def test_unapproved_user_denied(self, mock_check):
        """Onaysiz kullanici rapor alamamali."""
        mock_check.return_value = False

        update = _make_update()
        context = _make_context()

        await rapor_command(update, context)

        # _check_approved_user icinde mesaj gonderilir, rapor mesaji yok
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.telegram.handlers._fetch_report_data", new_callable=AsyncMock)
    @patch("src.telegram.handlers._check_approved_user", new_callable=AsyncMock)
    async def test_report_with_no_data(self, mock_check, mock_fetch):
        """Veri yoksa bile rapor donmeli."""
        mock_check.return_value = True
        mock_fetch.return_value = None

        update = _make_update()
        context = _make_context()

        await rapor_command(update, context)

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "Yakıt Analizi Raporu" in msg


# ────────────────────────────────────────────────────────────────────────────
#  /iptal Komutu Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestIptalCommand:
    """/iptal komut isleyicisi testleri."""

    @pytest.mark.asyncio
    @patch("src.telegram.handlers.deactivate_user", new_callable=AsyncMock)
    @patch("src.telegram.handlers.get_user_by_telegram_id", new_callable=AsyncMock)
    @patch("src.telegram.handlers.async_session_factory")
    async def test_active_user_deactivated(
        self, mock_factory, mock_get_user, mock_deactivate
    ):
        """Aktif kullanici deaktif edilmeli."""
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        existing_user = MagicMock()
        existing_user.is_active = True
        mock_get_user.return_value = existing_user

        update = _make_update()
        context = _make_context()

        await iptal_command(update, context)

        mock_deactivate.assert_called_once()
        call_args = update.message.reply_text.call_args
        msg = call_args[0][0] if call_args[0] else ""
        assert "iptal" in msg.lower()

    @pytest.mark.asyncio
    @patch("src.telegram.handlers.get_user_by_telegram_id", new_callable=AsyncMock)
    @patch("src.telegram.handlers.async_session_factory")
    async def test_unregistered_user_message(self, mock_factory, mock_get_user):
        """Kayitsiz kullanici uygun mesaj almali."""
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_get_user.return_value = None

        update = _make_update()
        context = _make_context()

        await iptal_command(update, context)

        call_args = update.message.reply_text.call_args
        msg = call_args[0][0] if call_args[0] else ""
        assert "kayıtlı değilsiniz" in msg.lower() or "start" in msg.lower()

    @pytest.mark.asyncio
    @patch("src.telegram.handlers.get_user_by_telegram_id", new_callable=AsyncMock)
    @patch("src.telegram.handlers.async_session_factory")
    async def test_already_inactive_user(self, mock_factory, mock_get_user):
        """Zaten inaktif kullanici uygun mesaj almali."""
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        existing_user = MagicMock()
        existing_user.is_active = False
        mock_get_user.return_value = existing_user

        update = _make_update()
        context = _make_context()

        await iptal_command(update, context)

        call_args = update.message.reply_text.call_args
        msg = call_args[0][0] if call_args[0] else ""
        assert "zaten" in msg.lower()


# ────────────────────────────────────────────────────────────────────────────
#  /yardim Komutu Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestYardimCommand:
    """/yardim komut isleyicisi testleri."""

    @pytest.mark.asyncio
    async def test_yardim_sends_help_message(self):
        """/yardim yardim mesajini gondermeli."""
        update = _make_update()
        context = _make_context()

        await yardim_command(update, context)

        update.message.reply_text.assert_called_once_with(HELP_MESSAGE)

    @pytest.mark.asyncio
    async def test_help_contains_all_commands(self):
        """Yardim mesaji tum komutlari icermeli."""
        assert "/start" in HELP_MESSAGE
        assert "/rapor" in HELP_MESSAGE
        assert "/iptal" in HELP_MESSAGE
        assert "/yardim" in HELP_MESSAGE

    @pytest.mark.asyncio
    async def test_help_contains_disclaimer(self):
        """Yardim mesaji yasal uyari icermeli."""
        assert "yatırım tavsiyesi" in HELP_MESSAGE.lower()
