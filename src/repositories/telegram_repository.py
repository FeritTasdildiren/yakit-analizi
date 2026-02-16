"""
Telegram kullanici repository katmani.

UPSERT pattern ile telegram_users tablosuna veri yazma, sorgulama islemleri.
Tum fonksiyonlar async olarak calisir, AsyncSession kullanir.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.users import TelegramUser

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
#  UPSERT — Kullanici Kayit / Guncelle
# ────────────────────────────────────────────────────────────────────────────


async def upsert_telegram_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone_number: str | None = None,
) -> TelegramUser:
    """
    Telegram kullanicisini ekler veya gunceller (UPSERT).

    ON CONFLICT (telegram_id) DO UPDATE ile calisir.

    Args:
        session: Async veritabani oturumu.
        telegram_id: Telegram kullanici ID.
        username: Telegram kullanici adi (@username).
        first_name: Telegram ad.
        last_name: Telegram soyad.
        phone_number: Telefon numarasi.

    Returns:
        Eklenen veya guncellenen TelegramUser nesnesi.
    """
    values = {
        "telegram_id": telegram_id,
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "phone_number": phone_number,
    }

    stmt = pg_insert(TelegramUser).values(**values)

    update_dict = {
        "username": stmt.excluded.username,
        "first_name": stmt.excluded.first_name,
        "last_name": stmt.excluded.last_name,
    }
    # Telefon numarasini sadece bos degilse guncelle
    if phone_number is not None:
        update_dict["phone_number"] = stmt.excluded.phone_number

    stmt = stmt.on_conflict_do_update(
        index_elements=["telegram_id"],
        set_=update_dict,
    ).returning(TelegramUser)

    result = await session.execute(stmt)
    user = result.scalar_one()
    await session.flush()

    logger.info(
        "Telegram kullanici UPSERT: id=%s, username=%s",
        telegram_id,
        username,
    )
    return user


# ────────────────────────────────────────────────────────────────────────────
#  Sorgulama
# ────────────────────────────────────────────────────────────────────────────


async def get_user_by_telegram_id(
    session: AsyncSession,
    telegram_id: int,
) -> TelegramUser | None:
    """Telegram ID ile kullanici getirir."""
    stmt = select(TelegramUser).where(
        TelegramUser.telegram_id == telegram_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_all_users(
    session: AsyncSession,
    *,
    status_filter: str | None = None,
) -> list[TelegramUser]:
    """
    Tum kullanicilari getirir, opsiyonel filtre ile.

    Args:
        session: Async veritabani oturumu.
        status_filter: "pending", "approved" veya "rejected" filtresi.

    Returns:
        TelegramUser listesi.
    """
    stmt = select(TelegramUser).order_by(TelegramUser.created_at.desc())

    if status_filter == "pending":
        stmt = stmt.where(
            TelegramUser.is_approved.is_(False),
            TelegramUser.is_active.is_(True),
        )
    elif status_filter == "approved":
        stmt = stmt.where(TelegramUser.is_approved.is_(True))
    elif status_filter == "rejected":
        stmt = stmt.where(
            TelegramUser.is_approved.is_(False),
            TelegramUser.is_active.is_(False),
        )

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_active_approved_users(
    session: AsyncSession,
) -> list[TelegramUser]:
    """Aktif ve onaylanmis kullanicilari getirir (bildirim icin)."""
    stmt = select(TelegramUser).where(
        TelegramUser.is_approved.is_(True),
        TelegramUser.is_active.is_(True),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ────────────────────────────────────────────────────────────────────────────
#  Guncelleme
# ────────────────────────────────────────────────────────────────────────────


async def approve_user(
    session: AsyncSession,
    telegram_id: int,
    approved_by: str = "admin",
) -> TelegramUser | None:
    """
    Kullaniciyi onaylar.

    Args:
        session: Async veritabani oturumu.
        telegram_id: Onaylanacak kullanici.
        approved_by: Onaylayan admin bilgisi.

    Returns:
        Guncellenen TelegramUser veya None.
    """
    stmt = (
        update(TelegramUser)
        .where(TelegramUser.telegram_id == telegram_id)
        .values(
            is_approved=True,
            is_active=True,
        )
        .returning(TelegramUser)
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    await session.flush()

    if user:
        logger.info(
            "Kullanici onaylandi: id=%s, by=%s",
            telegram_id,
            approved_by,
        )
    return user


async def reject_user(
    session: AsyncSession,
    telegram_id: int,
) -> TelegramUser | None:
    """
    Kullaniciyi reddeder (is_active=False).

    Args:
        session: Async veritabani oturumu.
        telegram_id: Reddedilecek kullanici.

    Returns:
        Guncellenen TelegramUser veya None.
    """
    stmt = (
        update(TelegramUser)
        .where(TelegramUser.telegram_id == telegram_id)
        .values(is_active=False)
        .returning(TelegramUser)
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    await session.flush()

    if user:
        logger.info("Kullanici reddedildi: id=%s", telegram_id)
    return user


async def deactivate_user(
    session: AsyncSession,
    telegram_id: int,
) -> TelegramUser | None:
    """
    Kullaniciyi deaktif eder (iptal akisi).

    Args:
        session: Async veritabani oturumu.
        telegram_id: Deaktif edilecek kullanici.

    Returns:
        Guncellenen TelegramUser veya None.
    """
    stmt = (
        update(TelegramUser)
        .where(TelegramUser.telegram_id == telegram_id)
        .values(is_active=False)
        .returning(TelegramUser)
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    await session.flush()

    if user:
        logger.info("Kullanici deaktif edildi: id=%s", telegram_id)
    return user


async def reactivate_user(
    session: AsyncSession,
    telegram_id: int,
) -> TelegramUser | None:
    """
    Iptal edilmis kullaniciyi yeniden aktif eder.

    Args:
        session: Async veritabani oturumu.
        telegram_id: Aktif edilecek kullanici.

    Returns:
        Guncellenen TelegramUser veya None.
    """
    stmt = (
        update(TelegramUser)
        .where(TelegramUser.telegram_id == telegram_id)
        .values(is_active=True, is_approved=False)
        .returning(TelegramUser)
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    await session.flush()

    if user:
        logger.info("Kullanici yeniden aktif edildi: id=%s", telegram_id)
    return user


# ────────────────────────────────────────────────────────────────────────────
#  Istatistik
# ────────────────────────────────────────────────────────────────────────────


async def get_user_stats(
    session: AsyncSession,
) -> dict:
    """
    Kullanici istatistiklerini dondurur.

    Returns:
        Dict: total, approved, pending, active, inactive sayilari.
    """
    # Toplam
    total_stmt = select(func.count()).select_from(TelegramUser)
    total = (await session.execute(total_stmt)).scalar() or 0

    # Onaylanmis
    approved_stmt = select(func.count()).select_from(TelegramUser).where(
        TelegramUser.is_approved.is_(True),
    )
    approved = (await session.execute(approved_stmt)).scalar() or 0

    # Onay bekleyen (aktif ama onaysiz)
    pending_stmt = select(func.count()).select_from(TelegramUser).where(
        TelegramUser.is_approved.is_(False),
        TelegramUser.is_active.is_(True),
    )
    pending = (await session.execute(pending_stmt)).scalar() or 0

    # Aktif
    active_stmt = select(func.count()).select_from(TelegramUser).where(
        TelegramUser.is_active.is_(True),
    )
    active = (await session.execute(active_stmt)).scalar() or 0

    return {
        "total": total,
        "approved": approved,
        "pending": pending,
        "active": active,
        "inactive": total - active,
    }
