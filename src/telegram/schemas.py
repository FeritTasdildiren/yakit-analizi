"""
Telegram Pydantic semalari.

Admin API endpoint'leri ve bot icerisinde kullanilan
veri transfer nesneleri (DTO'lar).
"""

from datetime import datetime

from pydantic import BaseModel, Field


# ────────────────────────────────────────────────────────────────────────────
#  Kullanici Semalari
# ────────────────────────────────────────────────────────────────────────────


class TelegramUserResponse(BaseModel):
    """Telegram kullanici API yanit modeli."""

    telegram_id: int = Field(description="Telegram kullanici ID")
    username: str | None = Field(default=None, description="Telegram @username")
    first_name: str | None = Field(default=None, description="Ad")
    last_name: str | None = Field(default=None, description="Soyad")
    phone_number: str | None = Field(default=None, description="Telefon numarasi")
    is_approved: bool = Field(description="Onay durumu")
    is_active: bool = Field(description="Aktif mi")
    is_admin: bool = Field(default=False, description="Admin mi")
    created_at: datetime | None = Field(default=None, description="Kayit tarihi")
    updated_at: datetime | None = Field(default=None, description="Son guncelleme")

    model_config = {"from_attributes": True}


class TelegramUserListResponse(BaseModel):
    """Kullanici listesi yaniti."""

    users: list[TelegramUserResponse]
    total: int


# ────────────────────────────────────────────────────────────────────────────
#  Admin Islem Semalari
# ────────────────────────────────────────────────────────────────────────────


class ApproveRequest(BaseModel):
    """Onay istegi."""

    approved_by: str = Field(default="admin", description="Onaylayan admin")


class RejectRequest(BaseModel):
    """Red istegi."""

    reason: str | None = Field(default=None, description="Red nedeni")


class BroadcastRequest(BaseModel):
    """Toplu mesaj istegi."""

    message: str = Field(description="Gonderilecek mesaj metni", min_length=1, max_length=4000)


class BroadcastResponse(BaseModel):
    """Toplu mesaj sonucu."""

    sent: int = Field(description="Basariyla gonderilen mesaj sayisi")
    failed: int = Field(description="Basarisiz mesaj sayisi")
    total: int = Field(description="Toplam hedef kullanici sayisi")


# ────────────────────────────────────────────────────────────────────────────
#  Istatistik Semalari
# ────────────────────────────────────────────────────────────────────────────


class TelegramStatsResponse(BaseModel):
    """Telegram kullanici istatistik yaniti."""

    total: int = Field(description="Toplam kullanici sayisi")
    approved: int = Field(description="Onaylanmis kullanici sayisi")
    pending: int = Field(description="Onay bekleyen kullanici sayisi")
    active: int = Field(description="Aktif kullanici sayisi")
    inactive: int = Field(description="Inaktif kullanici sayisi")


# ────────────────────────────────────────────────────────────────────────────
#  Genel Yanitlar
# ────────────────────────────────────────────────────────────────────────────


class ActionResponse(BaseModel):
    """Genel islem sonucu yaniti."""

    success: bool
    message: str
    user: TelegramUserResponse | None = None
