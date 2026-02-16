"""
Telegram Admin API endpoint testleri.

CRUD endpoint'leri, onay/red akisi, istatistik hesaplama testleri.
TestClient kullanarak FastAPI endpoint'leri test edilir.
Gercek Telegram API'sine istek ATILMAZ — tum dissal bagimliliklar mock'lanir.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def _make_mock_user(
    telegram_id: int = 123456,
    username: str = "testuser",
    is_approved: bool = False,
    is_active: bool = True,
    is_admin: bool = False,
    phone: str = "+905551234567",
):
    """Test icin mock TelegramUser ORM nesnesi olusturur."""
    user = MagicMock()
    user.telegram_id = telegram_id
    user.username = username
    user.first_name = "Test"
    user.last_name = "User"
    user.phone_number = phone
    user.is_approved = is_approved
    user.is_active = is_active
    user.is_admin = is_admin
    user.created_at = datetime(2026, 2, 16, tzinfo=timezone.utc)
    user.updated_at = datetime(2026, 2, 16, tzinfo=timezone.utc)
    user.notification_preferences = {}
    return user


# ────────────────────────────────────────────────────────────────────────────
#  GET /users Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestListUsers:
    """GET /api/v1/telegram/users endpoint testleri."""

    @patch("src.api.telegram_admin_routes.get_all_users", new_callable=AsyncMock)
    def test_list_users_returns_200(self, mock_get_all):
        """Kullanici listesi 200 donmeli."""
        from src.main import app

        mock_get_all.return_value = [
            _make_mock_user(123, "user1"),
            _make_mock_user(456, "user2"),
        ]

        client = TestClient(app)
        response = client.get("/api/v1/telegram/users")

        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert "total" in data
        assert data["total"] == 2

    @patch("src.api.telegram_admin_routes.get_all_users", new_callable=AsyncMock)
    def test_list_users_with_pending_filter(self, mock_get_all):
        """Pending filtresi calismali."""
        from src.main import app

        mock_get_all.return_value = [_make_mock_user(123, is_approved=False)]

        client = TestClient(app)
        response = client.get("/api/v1/telegram/users?status_filter=pending")

        assert response.status_code == 200
        mock_get_all.assert_called_once()

    def test_list_users_invalid_filter_returns_400(self):
        """Gecersiz filtre 400 donmeli."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/v1/telegram/users?status_filter=invalid")

        assert response.status_code == 400

    @patch("src.api.telegram_admin_routes.get_all_users", new_callable=AsyncMock)
    def test_list_users_empty(self, mock_get_all):
        """Bos liste bos yanit donmeli."""
        from src.main import app

        mock_get_all.return_value = []

        client = TestClient(app)
        response = client.get("/api/v1/telegram/users")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["users"] == []


# ────────────────────────────────────────────────────────────────────────────
#  GET /users/{user_id} Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestGetUser:
    """GET /api/v1/telegram/users/{user_id} endpoint testleri."""

    @patch("src.api.telegram_admin_routes.get_user_by_telegram_id", new_callable=AsyncMock)
    def test_get_user_returns_200(self, mock_get):
        """Mevcut kullanici 200 donmeli."""
        from src.main import app

        mock_get.return_value = _make_mock_user(123)

        client = TestClient(app)
        response = client.get("/api/v1/telegram/users/123")

        assert response.status_code == 200
        data = response.json()
        assert data["telegram_id"] == 123

    @patch("src.api.telegram_admin_routes.get_user_by_telegram_id", new_callable=AsyncMock)
    def test_get_user_not_found_returns_404(self, mock_get):
        """Bulunamayan kullanici 404 donmeli."""
        from src.main import app

        mock_get.return_value = None

        client = TestClient(app)
        response = client.get("/api/v1/telegram/users/999999")

        assert response.status_code == 404


# ────────────────────────────────────────────────────────────────────────────
#  POST /users/{user_id}/approve Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestApproveUser:
    """POST /api/v1/telegram/users/{user_id}/approve endpoint testleri."""

    @patch("src.api.telegram_admin_routes.send_message_to_user", new_callable=AsyncMock)
    @patch("src.api.telegram_admin_routes.approve_user", new_callable=AsyncMock)
    def test_approve_returns_200(self, mock_approve, mock_send):
        """Onay 200 donmeli."""
        from src.main import app

        approved_user = _make_mock_user(123, is_approved=True)
        mock_approve.return_value = approved_user
        mock_send.return_value = True

        client = TestClient(app)
        response = client.post("/api/v1/telegram/users/123/approve")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "onaylandi" in data["message"].lower() or "123" in data["message"]

    @patch("src.api.telegram_admin_routes.approve_user", new_callable=AsyncMock)
    def test_approve_not_found_returns_404(self, mock_approve):
        """Bulunamayan kullanici 404 donmeli."""
        from src.main import app

        mock_approve.return_value = None

        client = TestClient(app)
        response = client.post("/api/v1/telegram/users/999/approve")

        assert response.status_code == 404

    @patch("src.api.telegram_admin_routes.send_message_to_user", new_callable=AsyncMock)
    @patch("src.api.telegram_admin_routes.approve_user", new_callable=AsyncMock)
    def test_approve_sends_telegram_notification(self, mock_approve, mock_send):
        """Onay sonrasi Telegram bildirimi gonderilmeli."""
        from src.main import app

        mock_approve.return_value = _make_mock_user(123, is_approved=True)
        mock_send.return_value = True

        client = TestClient(app)
        client.post("/api/v1/telegram/users/123/approve")

        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[0][0] == 123
        assert "onaylandı" in call_args[0][1].lower()


# ────────────────────────────────────────────────────────────────────────────
#  POST /users/{user_id}/reject Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestRejectUser:
    """POST /api/v1/telegram/users/{user_id}/reject endpoint testleri."""

    @patch("src.api.telegram_admin_routes.send_message_to_user", new_callable=AsyncMock)
    @patch("src.api.telegram_admin_routes.reject_user", new_callable=AsyncMock)
    def test_reject_returns_200(self, mock_reject, mock_send):
        """Red 200 donmeli."""
        from src.main import app

        rejected_user = _make_mock_user(123, is_active=False)
        mock_reject.return_value = rejected_user
        mock_send.return_value = True

        client = TestClient(app)
        response = client.post("/api/v1/telegram/users/123/reject")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @patch("src.api.telegram_admin_routes.reject_user", new_callable=AsyncMock)
    def test_reject_not_found_returns_404(self, mock_reject):
        """Bulunamayan kullanici 404 donmeli."""
        from src.main import app

        mock_reject.return_value = None

        client = TestClient(app)
        response = client.post("/api/v1/telegram/users/999/reject")

        assert response.status_code == 404

    @patch("src.api.telegram_admin_routes.send_message_to_user", new_callable=AsyncMock)
    @patch("src.api.telegram_admin_routes.reject_user", new_callable=AsyncMock)
    def test_reject_sends_notification(self, mock_reject, mock_send):
        """Red sonrasi kullaniciya bildirim gonderilmeli."""
        from src.main import app

        mock_reject.return_value = _make_mock_user(123, is_active=False)
        mock_send.return_value = True

        client = TestClient(app)
        client.post(
            "/api/v1/telegram/users/123/reject",
            json={"reason": "Test nedeni"},
        )

        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert "reddedildi" in call_args[0][1].lower()


# ────────────────────────────────────────────────────────────────────────────
#  GET /stats Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestTelegramStats:
    """GET /api/v1/telegram/stats endpoint testleri."""

    @patch("src.api.telegram_admin_routes.get_user_stats", new_callable=AsyncMock)
    def test_stats_returns_200(self, mock_stats):
        """Istatistik 200 donmeli."""
        from src.main import app

        mock_stats.return_value = {
            "total": 10,
            "approved": 7,
            "pending": 2,
            "active": 9,
            "inactive": 1,
        }

        client = TestClient(app)
        response = client.get("/api/v1/telegram/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 10
        assert data["approved"] == 7
        assert data["pending"] == 2
        assert data["active"] == 9
        assert data["inactive"] == 1

    @patch("src.api.telegram_admin_routes.get_user_stats", new_callable=AsyncMock)
    def test_stats_empty_returns_zeros(self, mock_stats):
        """Kullanici yoksa sifir donmeli."""
        from src.main import app

        mock_stats.return_value = {
            "total": 0,
            "approved": 0,
            "pending": 0,
            "active": 0,
            "inactive": 0,
        }

        client = TestClient(app)
        response = client.get("/api/v1/telegram/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0


# ────────────────────────────────────────────────────────────────────────────
#  POST /broadcast Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestBroadcast:
    """POST /api/v1/telegram/broadcast endpoint testleri."""

    @patch("src.api.telegram_admin_routes.broadcast_message", new_callable=AsyncMock)
    def test_broadcast_returns_200(self, mock_broadcast):
        """Broadcast 200 donmeli."""
        from src.main import app

        mock_broadcast.return_value = {"sent": 5, "failed": 0, "total": 5}

        client = TestClient(app)
        response = client.post(
            "/api/v1/telegram/broadcast",
            json={"message": "Test mesaji"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["sent"] == 5
        assert data["total"] == 5

    def test_broadcast_empty_message_returns_422(self):
        """Bos mesaj 422 donmeli."""
        from src.main import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/telegram/broadcast",
            json={"message": ""},
        )

        assert response.status_code == 422

    @patch("src.api.telegram_admin_routes.broadcast_message", new_callable=AsyncMock)
    def test_broadcast_with_failures(self, mock_broadcast):
        """Kismi basari dogru sayilmali."""
        from src.main import app

        mock_broadcast.return_value = {"sent": 3, "failed": 2, "total": 5}

        client = TestClient(app)
        response = client.post(
            "/api/v1/telegram/broadcast",
            json={"message": "Test"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["sent"] == 3
        assert data["failed"] == 2


# ────────────────────────────────────────────────────────────────────────────
#  Schema Validation Testleri
# ────────────────────────────────────────────────────────────────────────────


class TestSchemaValidation:
    """Pydantic schema dogrulama testleri."""

    def test_telegram_user_response_from_attributes(self):
        """TelegramUserResponse model_validate calismali."""
        from src.telegram.schemas import TelegramUserResponse

        mock_user = _make_mock_user(789)
        response = TelegramUserResponse.model_validate(mock_user)

        assert response.telegram_id == 789
        assert response.username == "testuser"
        assert response.is_approved is False
        assert response.is_active is True

    def test_broadcast_request_validation(self):
        """BroadcastRequest mesaj uzunluk dogrulamasi calismali."""
        from src.telegram.schemas import BroadcastRequest

        # Gecerli mesaj
        req = BroadcastRequest(message="Test mesaji")
        assert req.message == "Test mesaji"

        # Bos mesaj (min_length=1)
        with pytest.raises(Exception):
            BroadcastRequest(message="")

    def test_approve_request_default_admin(self):
        """ApproveRequest varsayilan admin degeri dogru olmali."""
        from src.telegram.schemas import ApproveRequest

        req = ApproveRequest()
        assert req.approved_by == "admin"

    def test_stats_response_fields(self):
        """TelegramStatsResponse alanlari dogru olmali."""
        from src.telegram.schemas import TelegramStatsResponse

        stats = TelegramStatsResponse(
            total=10, approved=7, pending=2, active=9, inactive=1
        )
        assert stats.total == 10
        assert stats.inactive == 1
