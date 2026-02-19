"""ENUM tipleri ve daily_market_data tablosu oluşturma.

Revision ID: 001
Revises:
Create Date: 2026-02-15

Bu migration aşağıdakileri oluşturur:
- fuel_type_enum: benzin, motorin, lpg
- data_quality_enum: verified, interpolated, manual, estimated, stale
- daily_market_data tablosu: Brent, döviz kuru, CIF Med, pompa fiyatı verileri
- İndeksler: trade_date, fuel_type+trade_date, partial quality index
- Unique constraint: (trade_date, fuel_type)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """ENUM tipleri ve daily_market_data tablosu oluştur."""

    # --- ENUM Tiplerini Oluştur ---
    fuel_type_enum = postgresql.ENUM(
        "benzin", "motorin", "lpg",
        name="fuel_type_enum",
        create_type=True,
    )
    fuel_type_enum.create(op.get_bind(), checkfirst=True)

    data_quality_enum = postgresql.ENUM(
        "verified", "interpolated", "manual", "estimated", "stale",
        name="data_quality_enum",
        create_type=True,
    )
    data_quality_enum.create(op.get_bind(), checkfirst=True)

    # --- daily_market_data Tablosu ---
    op.create_table(
        "daily_market_data",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
            comment="Otomatik artan birincil anahtar",
        ),
        sa.Column(
            "trade_date",
            sa.Date(),
            nullable=False,
            comment="İşlem tarihi",
        ),
        sa.Column(
            "fuel_type",
            fuel_type_enum,
            nullable=False,
            comment="Yakıt tipi: benzin, motorin, lpg",
        ),
        sa.Column(
            "cif_med_usd_ton",
            sa.Numeric(precision=18, scale=8),
            nullable=True,
            comment="CIF Akdeniz fiyatı (USD/ton)",
        ),
        sa.Column(
            "usd_try_rate",
            sa.Numeric(precision=18, scale=8),
            nullable=True,
            comment="USD/TRY döviz kuru (TCMB satış)",
        ),
        sa.Column(
            "pump_price_tl_lt",
            sa.Numeric(precision=18, scale=8),
            nullable=True,
            comment="Pompa fiyatı (TL/litre)",
        ),
        sa.Column(
            "brent_usd_bbl",
            sa.Numeric(precision=18, scale=8),
            nullable=True,
            comment="Brent petrol fiyatı (USD/varil)",
        ),
        sa.Column(
            "distribution_margin_tl",
            sa.Numeric(precision=18, scale=8),
            nullable=True,
            comment="Dağıtım marjı (TL)",
        ),
        sa.Column(
            "data_quality_flag",
            data_quality_enum,
            nullable=False,
            server_default="verified",
            comment="Veri kalite bayrağı",
        ),
        sa.Column(
            "source",
            sa.String(length=100),
            nullable=False,
            comment="Veri kaynağı: tcmb_evds, yfinance, fallback_xe, manual",
        ),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="API'den gelen ham JSON yanıt (audit trail)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="Kayıt oluşturulma zamanı",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="Son güncelleme zamanı",
        ),
        comment="Günlük piyasa verileri — Brent, döviz kuru, CIF Med, pompa fiyatı",
    )

    # --- Unique Constraint ---
    op.create_unique_constraint(
        "uq_daily_market_date_fuel",
        "daily_market_data",
        ["trade_date", "fuel_type"],
    )

    # --- İndeksler ---
    op.create_index(
        "idx_daily_market_date",
        "daily_market_data",
        ["trade_date"],
    )

    op.create_index(
        "idx_daily_market_fuel_date",
        "daily_market_data",
        ["fuel_type", "trade_date"],
    )

    # Partial index: sadece verified olmayan kayıtlar
    op.create_index(
        "idx_daily_market_quality",
        "daily_market_data",
        ["data_quality_flag"],
        postgresql_where=sa.text("data_quality_flag != 'verified'"),
    )

    # --- updated_at Trigger ---
    # PostgreSQL'de updated_at otomatik güncelleme için trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    op.execute("""
        CREATE TRIGGER update_daily_market_data_updated_at
        BEFORE UPDATE ON daily_market_data
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    """daily_market_data tablosu ve ENUM tiplerini kaldır."""

    # Trigger'ı kaldır
    op.execute("DROP TRIGGER IF EXISTS update_daily_market_data_updated_at ON daily_market_data;")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column();")

    # İndeksleri kaldır
    op.drop_index("idx_daily_market_quality", table_name="daily_market_data")
    op.drop_index("idx_daily_market_fuel_date", table_name="daily_market_data")
    op.drop_index("idx_daily_market_date", table_name="daily_market_data")

    # Unique constraint kaldır
    op.drop_constraint("uq_daily_market_date_fuel", "daily_market_data", type_="unique")

    # Tabloyu kaldır
    op.drop_table("daily_market_data")

    # ENUM tiplerini kaldır
    op.execute("DROP TYPE IF EXISTS data_quality_enum;")
    op.execute("DROP TYPE IF EXISTS fuel_type_enum;")
