"""
Fiyat degisiklikleri repository katmani.

price_changes tablosuna CRUD islemleri.
Tum fonksiyonlar async olarak calisir, AsyncSession kullanir.
"""

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.price_changes import PriceChange

logger = logging.getLogger(__name__)


async def upsert_price_change(
    session: AsyncSession,
    *,
    fuel_type: str,
    change_date: date,
    direction: str,
    old_price: Decimal,
    new_price: Decimal,
    change_amount: Decimal,
    change_pct: Decimal,
    mbe_at_change: Decimal | None = None,
    source: str = "manual",
    notes: str | None = None,
) -> PriceChange:
    """
    Fiyat degisikligi ekler veya gunceller (UPSERT).

    ON CONFLICT (fuel_type, change_date) DO UPDATE ile calisir.

    Args:
        session: Async veritabani oturumu.
        fuel_type: Yakit tipi.
        change_date: Degisiklik tarihi.
        direction: Degisim yonu (increase, decrease, no_change).
        old_price: Eski fiyat TL/litre.
        new_price: Yeni fiyat TL/litre.
        change_amount: Degisim miktari TL.
        change_pct: Degisim yuzdesi.
        mbe_at_change: Degisiklik anindaki MBE.
        source: Veri kaynagi.
        notes: Ek notlar.

    Returns:
        Eklenen veya guncellenen PriceChange kaydi.
    """
    values = {
        "fuel_type": fuel_type,
        "change_date": change_date,
        "direction": direction,
        "old_price": old_price,
        "new_price": new_price,
        "change_amount": change_amount,
        "change_pct": change_pct,
        "mbe_at_change": mbe_at_change,
        "source": source,
        "notes": notes,
    }

    stmt = pg_insert(PriceChange).values(**values)

    update_fields = {
        k: v for k, v in values.items() if k not in ("fuel_type", "change_date")
    }
    update_fields["updated_at"] = text("NOW()")

    stmt = stmt.on_conflict_do_update(
        constraint="uq_price_change_fuel_date",
        set_=update_fields,
    ).returning(PriceChange)

    result = await session.execute(stmt)
    row = result.scalar_one()

    logger.info(
        "Fiyat degisikligi upsert: %s / %s (yon=%s, eski=%s, yeni=%s)",
        change_date,
        fuel_type,
        direction,
        old_price,
        new_price,
    )

    return row


async def get_latest_price_change(
    session: AsyncSession,
    fuel_type: str,
) -> PriceChange | None:
    """
    Belirli yakit tipi icin en son fiyat degisikligini dondurur.

    Args:
        session: Async veritabani oturumu.
        fuel_type: Yakit tipi.

    Returns:
        PriceChange veya None.
    """
    stmt = (
        select(PriceChange)
        .where(PriceChange.fuel_type == fuel_type)
        .order_by(PriceChange.change_date.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_latest_price_changes_all(
    session: AsyncSession,
) -> list[PriceChange]:
    """
    Tum yakit tipleri icin en son fiyat degisikliklerini dondurur.

    Returns:
        PriceChange listesi.
    """
    results = []
    for fuel_type in ("benzin", "motorin", "lpg"):
        pc = await get_latest_price_change(session, fuel_type)
        if pc is not None:
            results.append(pc)
    return results


async def get_price_changes_by_fuel(
    session: AsyncSession,
    fuel_type: str,
    limit: int = 50,
) -> list[PriceChange]:
    """
    Belirli yakit tipi icin fiyat degisiklik tarihcesini dondurur.

    Args:
        session: Async veritabani oturumu.
        fuel_type: Yakit tipi.
        limit: Maksimum kayit sayisi.

    Returns:
        PriceChange listesi (change_date DESC sirali).
    """
    stmt = (
        select(PriceChange)
        .where(PriceChange.fuel_type == fuel_type)
        .order_by(PriceChange.change_date.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_price_changes_range(
    session: AsyncSession,
    fuel_type: str,
    start_date: date,
    end_date: date,
) -> list[PriceChange]:
    """
    Tarih araligindaki fiyat degisikliklerini dondurur.

    Args:
        session: Async veritabani oturumu.
        fuel_type: Yakit tipi.
        start_date: Baslangic tarihi (dahil).
        end_date: Bitis tarihi (dahil).

    Returns:
        PriceChange listesi (change_date ASC sirali).
    """
    stmt = (
        select(PriceChange)
        .where(
            PriceChange.fuel_type == fuel_type,
            PriceChange.change_date >= start_date,
            PriceChange.change_date <= end_date,
        )
        .order_by(PriceChange.change_date.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_price_change(
    session: AsyncSession,
    *,
    fuel_type: str,
    change_date: date,
    direction: str,
    old_price: Decimal,
    new_price: Decimal,
    change_amount: Decimal,
    change_pct: Decimal,
    mbe_at_change: Decimal | None = None,
    source: str = "manual",
    notes: str | None = None,
) -> PriceChange:
    """
    Yeni fiyat degisikligi kaydi olusturur (UPSERT degil, sadece INSERT).
    Cakisan kayit varsa hata firlatir.

    Args:
        session: Async veritabani oturumu.
        fuel_type: Yakit tipi.
        change_date: Degisiklik tarihi.
        direction: Degisim yonu.
        old_price: Eski fiyat.
        new_price: Yeni fiyat.
        change_amount: Degisim miktari.
        change_pct: Degisim yuzdesi.
        mbe_at_change: Degisiklik anindaki MBE.
        source: Veri kaynagi.
        notes: Ek notlar.

    Returns:
        Olusturulan PriceChange kaydi.
    """
    pc = PriceChange(
        fuel_type=fuel_type,
        change_date=change_date,
        direction=direction,
        old_price=old_price,
        new_price=new_price,
        change_amount=change_amount,
        change_pct=change_pct,
        mbe_at_change=mbe_at_change,
        source=source,
        notes=notes,
    )
    session.add(pc)
    await session.flush()

    logger.info(
        "Fiyat degisikligi olusturuldu: id=%d, %s / %s (yon=%s, %s -> %s)",
        pc.id,
        change_date,
        fuel_type,
        direction,
        old_price,
        new_price,
    )

    return pc
