"""
Telegram Admin API endpoint'leri.

Kullanici onay/red, listeleme, istatistik ve broadcast islemleri.
Tum endpoint'ler /api/v1/telegram prefix'i altindadir.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_db
from src.repositories.telegram_repository import (
    approve_user,
    get_all_users,
    get_user_by_telegram_id,
    get_user_stats,
    reject_user,
)
from src.telegram.notifications import (
    broadcast_message,
    send_message_to_user,
)
from src.telegram.schemas import (
    ActionResponse,
    ApproveRequest,
    BroadcastRequest,
    BroadcastResponse,
    RejectRequest,
    TelegramStatsResponse,
    TelegramUserListResponse,
    TelegramUserResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/telegram", tags=["Telegram Admin"])


# ────────────────────────────────────────────────────────────────────────────
#  GET /users — Kullanici Listesi
# ────────────────────────────────────────────────────────────────────────────


@router.get(
    "/users",
    response_model=TelegramUserListResponse,
    summary="Tum Telegram kullanicilarini listele",
)
async def list_users(
    status_filter: str | None = Query(
        default=None,
        description="Filtre: pending, approved, rejected",
    ),
    db: AsyncSession = Depends(get_db),
) -> TelegramUserListResponse:
    """
    Tum Telegram kullanicilarini listeler.

    Opsiyonel filtreler:
    - pending: Onay bekleyenler
    - approved: Onaylanmislar
    - rejected: Reddedilenler
    """
    if status_filter and status_filter not in {"pending", "approved", "rejected"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Gecersiz filtre: '{status_filter}'. Gecerli: pending, approved, rejected",
        )

    users = await get_all_users(db, status_filter=status_filter)

    user_responses = [TelegramUserResponse.model_validate(u) for u in users]

    return TelegramUserListResponse(
        users=user_responses,
        total=len(user_responses),
    )


# ────────────────────────────────────────────────────────────────────────────
#  GET /users/{user_id} — Tek Kullanici
# ────────────────────────────────────────────────────────────────────────────


@router.get(
    "/users/{user_id}",
    response_model=TelegramUserResponse,
    summary="Tek Telegram kullanici detayi",
)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> TelegramUserResponse:
    """Belirtilen Telegram ID ile kullaniciyi getirir."""
    user = await get_user_by_telegram_id(db, user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Kullanici bulunamadi: telegram_id={user_id}",
        )

    return TelegramUserResponse.model_validate(user)


# ────────────────────────────────────────────────────────────────────────────
#  POST /users/{user_id}/approve — Kullanici Onayla
# ────────────────────────────────────────────────────────────────────────────


@router.post(
    "/users/{user_id}/approve",
    response_model=ActionResponse,
    summary="Kullaniciyi onayla",
)
async def approve_user_endpoint(
    user_id: int,
    body: ApproveRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ActionResponse:
    """
    Kullaniciyi onaylar ve Telegram uzerinden bilgilendirir.

    1. DB'de is_approved=True olarak gunceller.
    2. Kullaniciya "Kaydiniz onaylandi" mesaji gonderir.
    """
    approved_by = body.approved_by if body else "admin"

    user = await approve_user(db, user_id, approved_by=approved_by)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Kullanici bulunamadi: telegram_id={user_id}",
        )

    # Kullaniciya Telegram mesaji gonder
    try:
        await send_message_to_user(
            user_id,
            "✅ Kaydınız onaylandı! Artık günlük bildirim alacaksınız.\n"
            "Anlık rapor için /rapor yazabilirsiniz.",
        )
    except Exception as exc:
        logger.warning("Onay bildirimi gonderilemedi: %s", exc)

    return ActionResponse(
        success=True,
        message=f"Kullanici {user_id} onaylandi",
        user=TelegramUserResponse.model_validate(user),
    )


# ────────────────────────────────────────────────────────────────────────────
#  POST /users/{user_id}/reject — Kullanici Reddet
# ────────────────────────────────────────────────────────────────────────────


@router.post(
    "/users/{user_id}/reject",
    response_model=ActionResponse,
    summary="Kullaniciyi reddet",
)
async def reject_user_endpoint(
    user_id: int,
    body: RejectRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ActionResponse:
    """
    Kullaniciyi reddeder (is_active=False) ve bilgilendirir.

    1. DB'de is_active=False olarak gunceller.
    2. Kullaniciya "Kaydiniz reddedildi" mesaji gonderir.
    """
    user = await reject_user(db, user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Kullanici bulunamadi: telegram_id={user_id}",
        )

    # Kullaniciya Telegram mesaji gonder
    reject_msg = "❌ Kaydınız reddedildi."
    if body and body.reason:
        reject_msg += f"\nNeden: {body.reason}"

    try:
        await send_message_to_user(user_id, reject_msg)
    except Exception as exc:
        logger.warning("Red bildirimi gonderilemedi: %s", exc)

    return ActionResponse(
        success=True,
        message=f"Kullanici {user_id} reddedildi",
        user=TelegramUserResponse.model_validate(user),
    )


# ────────────────────────────────────────────────────────────────────────────
#  GET /stats — Istatistikler
# ────────────────────────────────────────────────────────────────────────────


@router.get(
    "/stats",
    response_model=TelegramStatsResponse,
    summary="Telegram kullanici istatistikleri",
)
async def telegram_stats(
    db: AsyncSession = Depends(get_db),
) -> TelegramStatsResponse:
    """Toplam, onaylanmis, bekleyen, aktif kullanici sayilarini dondurur."""
    stats = await get_user_stats(db)
    return TelegramStatsResponse(**stats)


# ────────────────────────────────────────────────────────────────────────────
#  POST /broadcast — Toplu Mesaj
# ────────────────────────────────────────────────────────────────────────────


@router.post(
    "/broadcast",
    response_model=BroadcastResponse,
    summary="Tum onaylanmis kullanicilara mesaj gonder",
)
async def broadcast(
    body: BroadcastRequest,
) -> BroadcastResponse:
    """Tum aktif ve onaylanmis kullanicilara mesaj gonderir."""
    result = await broadcast_message(body.message)

    return BroadcastResponse(
        sent=result["sent"],
        failed=result["failed"],
        total=result["total"],
    )
