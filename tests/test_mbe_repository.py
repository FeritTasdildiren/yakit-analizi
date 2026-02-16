"""
MBE Repository birim testleri.

Not: Bu testler veritabani gerektirdiginden, gercek PostgreSQL
baglantisi olmadan calistirilmaz. Burada SQL sorgu yapisini ve
fonksiyon imzalarini dogrulariz.

Veritabani entegrasyon testleri ayri bir conftest ile yapilacaktir.
Asagidaki testler import kontrolu ve temel yapisal testlerdir.
"""

import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.mbe_repository import (
    get_cost_snapshot,
    get_cost_snapshots_range,
    get_latest_mbe,
    get_latest_mbe_all,
    get_mbe_at_date,
    get_mbe_range,
    upsert_cost_snapshot,
    upsert_mbe_calculation,
)
from src.core.price_change_repository import (
    create_price_change,
    get_latest_price_change,
    get_latest_price_changes_all,
    get_price_changes_by_fuel,
    get_price_changes_range,
    upsert_price_change,
)
from src.models.cost_base_snapshots import CostBaseSnapshot
from src.models.mbe_calculations import MBECalculation
from src.models.price_changes import PriceChange


# =====================================================================
# Import ve Model testleri
# =====================================================================


class TestModelImports:
    """Model import ve yapisal testler."""

    def test_cost_base_snapshot_model(self):
        """CostBaseSnapshot modeli dogru import edilir."""
        assert CostBaseSnapshot.__tablename__ == "cost_base_snapshots"

    def test_mbe_calculation_model(self):
        """MBECalculation modeli dogru import edilir."""
        assert MBECalculation.__tablename__ == "mbe_calculations"

    def test_price_change_model(self):
        """PriceChange modeli dogru import edilir."""
        assert PriceChange.__tablename__ == "price_changes"

    def test_cost_snapshot_columns(self):
        """CostBaseSnapshot gerekli sutunlara sahip."""
        columns = {c.name for c in CostBaseSnapshot.__table__.columns}
        required = {
            "id", "trade_date", "fuel_type", "market_data_id",
            "tax_parameter_id", "cif_component_tl", "otv_component_tl",
            "kdv_component_tl", "margin_component_tl", "theoretical_cost_tl",
            "actual_pump_price_tl", "implied_cif_usd_ton", "cost_gap_tl",
            "cost_gap_pct", "source", "created_at", "updated_at",
        }
        assert required.issubset(columns), f"Eksik sutunlar: {required - columns}"

    def test_mbe_calculation_columns(self):
        """MBECalculation gerekli sutunlara sahip."""
        columns = {c.name for c in MBECalculation.__table__.columns}
        required = {
            "id", "trade_date", "fuel_type", "cost_snapshot_id",
            "nc_forward", "nc_base", "mbe_value", "mbe_pct",
            "sma_5", "sma_10", "delta_mbe", "delta_mbe_3",
            "trend_direction", "regime", "since_last_change_days",
            "sma_window", "source", "created_at", "updated_at",
        }
        assert required.issubset(columns), f"Eksik sutunlar: {required - columns}"

    def test_price_change_columns(self):
        """PriceChange gerekli sutunlara sahip."""
        columns = {c.name for c in PriceChange.__table__.columns}
        required = {
            "id", "fuel_type", "change_date", "direction",
            "old_price", "new_price", "change_amount", "change_pct",
            "mbe_at_change", "source", "notes", "created_at", "updated_at",
        }
        assert required.issubset(columns), f"Eksik sutunlar: {required - columns}"


# =====================================================================
# Unique Constraint testleri
# =====================================================================


class TestUniqueConstraints:
    """Unique constraint dogrulamalari."""

    def test_cost_snapshot_unique_constraint(self):
        """cost_base_snapshots: (trade_date, fuel_type) unique olmali."""
        constraints = CostBaseSnapshot.__table__.constraints
        unique_names = {
            c.name for c in constraints
            if hasattr(c, 'columns') and len(c.columns) > 1
        }
        assert "uq_cost_snapshot_date_fuel" in unique_names

    def test_mbe_calculation_unique_constraint(self):
        """mbe_calculations: (trade_date, fuel_type) unique olmali."""
        constraints = MBECalculation.__table__.constraints
        unique_names = {
            c.name for c in constraints
            if hasattr(c, 'columns') and len(c.columns) > 1
        }
        assert "uq_mbe_calc_date_fuel" in unique_names

    def test_price_change_unique_constraint(self):
        """price_changes: (fuel_type, change_date) unique olmali."""
        constraints = PriceChange.__table__.constraints
        unique_names = {
            c.name for c in constraints
            if hasattr(c, 'columns') and len(c.columns) > 1
        }
        assert "uq_price_change_fuel_date" in unique_names


# =====================================================================
# Repository fonksiyon imza testleri
# =====================================================================


class TestRepositorySignatures:
    """Repository fonksiyonlarinin dogru imzaya sahip oldugunu dogrular."""

    def test_upsert_cost_snapshot_is_async(self):
        """upsert_cost_snapshot async fonksiyon."""
        import asyncio
        assert asyncio.iscoroutinefunction(upsert_cost_snapshot)

    def test_upsert_mbe_calculation_is_async(self):
        """upsert_mbe_calculation async fonksiyon."""
        import asyncio
        assert asyncio.iscoroutinefunction(upsert_mbe_calculation)

    def test_get_latest_mbe_is_async(self):
        """get_latest_mbe async fonksiyon."""
        import asyncio
        assert asyncio.iscoroutinefunction(get_latest_mbe)

    def test_get_mbe_range_is_async(self):
        """get_mbe_range async fonksiyon."""
        import asyncio
        assert asyncio.iscoroutinefunction(get_mbe_range)

    def test_upsert_price_change_is_async(self):
        """upsert_price_change async fonksiyon."""
        import asyncio
        assert asyncio.iscoroutinefunction(upsert_price_change)

    def test_get_latest_price_change_is_async(self):
        """get_latest_price_change async fonksiyon."""
        import asyncio
        assert asyncio.iscoroutinefunction(get_latest_price_change)

    def test_create_price_change_is_async(self):
        """create_price_change async fonksiyon."""
        import asyncio
        assert asyncio.iscoroutinefunction(create_price_change)


# =====================================================================
# Index testleri
# =====================================================================


class TestIndexes:
    """Tablo index dogrulamalari."""

    def test_cost_snapshot_indexes(self):
        """cost_base_snapshots gerekli index'lere sahip."""
        indexes = {idx.name for idx in CostBaseSnapshot.__table__.indexes}
        required_indexes = {
            "idx_cost_snapshot_date",
            "idx_cost_snapshot_fuel_date",
            "idx_cost_snapshot_market_data",
            "idx_cost_snapshot_tax_param",
        }
        assert required_indexes.issubset(indexes), f"Eksik index'ler: {required_indexes - indexes}"

    def test_mbe_calculation_indexes(self):
        """mbe_calculations gerekli index'lere sahip."""
        indexes = {idx.name for idx in MBECalculation.__table__.indexes}
        required_indexes = {
            "idx_mbe_calc_date",
            "idx_mbe_calc_fuel_date",
            "idx_mbe_calc_regime",
            "idx_mbe_calc_snapshot",
        }
        assert required_indexes.issubset(indexes), f"Eksik index'ler: {required_indexes - indexes}"

    def test_price_change_indexes(self):
        """price_changes gerekli index'lere sahip."""
        indexes = {idx.name for idx in PriceChange.__table__.indexes}
        required_indexes = {
            "idx_price_change_date",
            "idx_price_change_fuel_date",
            "idx_price_change_direction",
        }
        assert required_indexes.issubset(indexes), f"Eksik index'ler: {required_indexes - indexes}"


# =====================================================================
# Foreign Key testleri
# =====================================================================


class TestForeignKeys:
    """Foreign key dogrulamalari."""

    def test_cost_snapshot_fk_market_data(self):
        """cost_base_snapshots -> daily_market_data FK."""
        fks = {
            fk.target_fullname
            for fk in CostBaseSnapshot.__table__.foreign_keys
        }
        assert "daily_market_data.id" in fks

    def test_cost_snapshot_fk_tax_parameters(self):
        """cost_base_snapshots -> tax_parameters FK."""
        fks = {
            fk.target_fullname
            for fk in CostBaseSnapshot.__table__.foreign_keys
        }
        assert "tax_parameters.id" in fks

    def test_mbe_calculation_fk_cost_snapshot(self):
        """mbe_calculations -> cost_base_snapshots FK."""
        fks = {
            fk.target_fullname
            for fk in MBECalculation.__table__.foreign_keys
        }
        assert "cost_base_snapshots.id" in fks
