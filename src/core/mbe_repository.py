"""
MBE hesaplama ve maliyet snapshot repository katmani.

UPSERT pattern ile mbe_calculations ve cost_base_snapshots tablolarina
veri yazma, sorgulama islemleri.
Tum fonksiyonlar async olarak calisir, AsyncSession kullanir.
"""

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.cost_base_snapshots import CostBaseSnapshot
from src.models.mbe_calculations import MBECalculation

logger = logging.getLogger(__name__)


# --- Cost Base Snapshot Islemleri ---


async def upsert_cost_snapshot(
    session: AsyncSession,
    *,
    trade_date: date,
    fuel_type: str,
    market_data_id: int,
    tax_parameter_id: int,
    cif_component_tl: Decimal,
    otv_component_tl: Decimal,
    kdv_component_tl: Decimal,
    margin_component_tl: Decimal,
    theoretical_cost_tl: Decimal,
    actual_pump_price_tl: Decimal,
    implied_cif_usd_ton: Decimal | None,
    cost_gap_tl: Decimal,
    cost_gap_pct: Decimal,
    source: str = "system",
) -> CostBaseSnapshot:
    """
    Maliyet snapshot'ini ekler veya gunceller (UPSERT).

    ON CONFLICT (trade_date, fuel_type) DO UPDATE ile calisir.

    Args:
        session: Async veritabani oturumu.
        trade_date: Islem tarihi.
        fuel_type: Yakit tipi (benzin, motorin, lpg).
        market_data_id: Iliskili DailyMarketData kaydi ID'si.
        tax_parameter_id: Iliskili TaxParameter kaydi ID'si.
        cif_component_tl: CIF bileseni TL/litre.
        otv_component_tl: OTV bileseni TL/litre.
        kdv_component_tl: KDV bileseni TL/litre.
        margin_component_tl: Marj bileseni TL/litre.
        theoretical_cost_tl: Teorik maliyet TL/litre.
        actual_pump_price_tl: Gercek pompa fiyati TL/litre.
        implied_cif_usd_ton: Ima edilen CIF (USD/ton).
        cost_gap_tl: Maliyet farki TL.
        cost_gap_pct: Maliyet farki yuzdesi.
        source: Hesaplama kaynagi.

    Returns:
        Eklenen veya guncellenen CostBaseSnapshot kaydi.
    """
    values = {
        "trade_date": trade_date,
        "fuel_type": fuel_type,
        "market_data_id": market_data_id,
        "tax_parameter_id": tax_parameter_id,
        "cif_component_tl": cif_component_tl,
        "otv_component_tl": otv_component_tl,
        "kdv_component_tl": kdv_component_tl,
        "margin_component_tl": margin_component_tl,
        "theoretical_cost_tl": theoretical_cost_tl,
        "actual_pump_price_tl": actual_pump_price_tl,
        "implied_cif_usd_ton": implied_cif_usd_ton,
        "cost_gap_tl": cost_gap_tl,
        "cost_gap_pct": cost_gap_pct,
        "source": source,
    }

    stmt = pg_insert(CostBaseSnapshot).values(**values)

    update_fields = {
        k: v for k, v in values.items() if k not in ("trade_date", "fuel_type")
    }
    update_fields["updated_at"] = text("NOW()")

    stmt = stmt.on_conflict_do_update(
        constraint="uq_cost_snapshot_date_fuel",
        set_=update_fields,
    ).returning(CostBaseSnapshot)

    result = await session.execute(stmt)
    row = result.scalar_one()

    logger.info(
        "Maliyet snapshot upsert: %s / %s (teorik=%s, gercek=%s, fark=%s)",
        trade_date,
        fuel_type,
        theoretical_cost_tl,
        actual_pump_price_tl,
        cost_gap_tl,
    )

    return row


async def get_cost_snapshot(
    session: AsyncSession,
    trade_date: date,
    fuel_type: str,
) -> CostBaseSnapshot | None:
    """
    Belirli tarih ve yakit tipi icin maliyet snapshot'ini dondurur.

    Args:
        session: Async veritabani oturumu.
        trade_date: Islem tarihi.
        fuel_type: Yakit tipi.

    Returns:
        CostBaseSnapshot veya None.
    """
    stmt = (
        select(CostBaseSnapshot)
        .where(
            CostBaseSnapshot.trade_date == trade_date,
            CostBaseSnapshot.fuel_type == fuel_type,
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_cost_snapshots_range(
    session: AsyncSession,
    fuel_type: str,
    start_date: date,
    end_date: date,
) -> list[CostBaseSnapshot]:
    """
    Tarih araligindaki maliyet snapshot'larini dondurur.

    Args:
        session: Async veritabani oturumu.
        fuel_type: Yakit tipi.
        start_date: Baslangic tarihi (dahil).
        end_date: Bitis tarihi (dahil).

    Returns:
        CostBaseSnapshot listesi (trade_date'e gore sirali).
    """
    stmt = (
        select(CostBaseSnapshot)
        .where(
            CostBaseSnapshot.fuel_type == fuel_type,
            CostBaseSnapshot.trade_date >= start_date,
            CostBaseSnapshot.trade_date <= end_date,
        )
        .order_by(CostBaseSnapshot.trade_date.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# --- MBE Calculation Islemleri ---


async def upsert_mbe_calculation(
    session: AsyncSession,
    *,
    trade_date: date,
    fuel_type: str,
    cost_snapshot_id: int,
    nc_forward: Decimal,
    nc_base: Decimal,
    mbe_value: Decimal,
    mbe_pct: Decimal,
    sma_5: Decimal | None = None,
    sma_10: Decimal | None = None,
    delta_mbe: Decimal | None = None,
    delta_mbe_3: Decimal | None = None,
    trend_direction: str = "no_change",
    regime: int = 0,
    since_last_change_days: int = 0,
    sma_window: int = 5,
    source: str = "system",
) -> MBECalculation:
    """
    MBE hesaplama sonucunu ekler veya gunceller (UPSERT).

    ON CONFLICT (trade_date, fuel_type) DO UPDATE ile calisir.

    Args:
        session: Async veritabani oturumu.
        trade_date: Islem tarihi.
        fuel_type: Yakit tipi.
        cost_snapshot_id: Iliskili CostBaseSnapshot kaydi ID'si.
        nc_forward: NC_forward degeri.
        nc_base: NC_base degeri.
        mbe_value: MBE degeri.
        mbe_pct: MBE yuzdesi.
        sma_5: 5 gunluk SMA.
        sma_10: 10 gunluk SMA.
        delta_mbe: Gunluk MBE degisimi.
        delta_mbe_3: 3 gunluk MBE degisimi.
        trend_direction: Trend yonu.
        regime: Rejim kodu.
        since_last_change_days: Son zam tarihinden gun sayisi.
        sma_window: Kullanilan SMA pencere genisligi.
        source: Hesaplama kaynagi.

    Returns:
        Eklenen veya guncellenen MBECalculation kaydi.
    """
    values = {
        "trade_date": trade_date,
        "fuel_type": fuel_type,
        "cost_snapshot_id": cost_snapshot_id,
        "nc_forward": nc_forward,
        "nc_base": nc_base,
        "mbe_value": mbe_value,
        "mbe_pct": mbe_pct,
        "sma_5": sma_5,
        "sma_10": sma_10,
        "delta_mbe": delta_mbe,
        "delta_mbe_3": delta_mbe_3,
        "trend_direction": trend_direction,
        "regime": regime,
        "since_last_change_days": since_last_change_days,
        "sma_window": sma_window,
        "source": source,
    }

    stmt = pg_insert(MBECalculation).values(**values)

    update_fields = {
        k: v for k, v in values.items() if k not in ("trade_date", "fuel_type")
    }
    update_fields["updated_at"] = text("NOW()")

    stmt = stmt.on_conflict_do_update(
        constraint="uq_mbe_calc_date_fuel",
        set_=update_fields,
    ).returning(MBECalculation)

    result = await session.execute(stmt)
    row = result.scalar_one()

    logger.info(
        "MBE hesaplama upsert: %s / %s (mbe=%s, trend=%s, regime=%d)",
        trade_date,
        fuel_type,
        mbe_value,
        trend_direction,
        regime,
    )

    return row


async def get_latest_mbe(
    session: AsyncSession,
    fuel_type: str,
) -> MBECalculation | None:
    """
    Belirli yakit tipi icin en son MBE hesaplamasini dondurur.

    Args:
        session: Async veritabani oturumu.
        fuel_type: Yakit tipi.

    Returns:
        MBECalculation veya None.
    """
    stmt = (
        select(MBECalculation)
        .where(MBECalculation.fuel_type == fuel_type)
        .order_by(MBECalculation.trade_date.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_latest_mbe_all(
    session: AsyncSession,
) -> list[MBECalculation]:
    """
    Tum yakit tipleri icin en son MBE hesaplamalarini dondurur.

    Returns:
        MBECalculation listesi.
    """
    results = []
    for fuel_type in ("benzin", "motorin", "lpg"):
        mbe = await get_latest_mbe(session, fuel_type)
        if mbe is not None:
            results.append(mbe)
    return results


async def get_mbe_range(
    session: AsyncSession,
    fuel_type: str,
    start_date: date,
    end_date: date,
) -> list[MBECalculation]:
    """
    Tarih araligindaki MBE hesaplamalarini dondurur.

    Args:
        session: Async veritabani oturumu.
        fuel_type: Yakit tipi.
        start_date: Baslangic tarihi (dahil).
        end_date: Bitis tarihi (dahil).

    Returns:
        MBECalculation listesi (trade_date'e gore sirali).
    """
    stmt = (
        select(MBECalculation)
        .where(
            MBECalculation.fuel_type == fuel_type,
            MBECalculation.trade_date >= start_date,
            MBECalculation.trade_date <= end_date,
        )
        .order_by(MBECalculation.trade_date.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_mbe_at_date(
    session: AsyncSession,
    trade_date: date,
    fuel_type: str,
) -> MBECalculation | None:
    """
    Belirli tarih ve yakit tipi icin MBE hesaplamasini dondurur.

    Args:
        session: Async veritabani oturumu.
        trade_date: Islem tarihi.
        fuel_type: Yakit tipi.

    Returns:
        MBECalculation veya None.
    """
    stmt = (
        select(MBECalculation)
        .where(
            MBECalculation.trade_date == trade_date,
            MBECalculation.fuel_type == fuel_type,
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
