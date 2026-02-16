"""
003: Katman 2 hesaplama tablolari olusturma migration'i.

direction_enum, price_changes, cost_base_snapshots ve mbe_calculations
tablolarini olusturur. Tum FK, index ve unique constraint'ler dahildir.

Revision ID: 003_computation_tables
Revises: 002_create_tax_params
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic revision bilgileri
revision = "003_computation_tables"
down_revision = "002_create_tax_params"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    direction_enum olustur, ardindan price_changes, cost_base_snapshots
    ve mbe_calculations tablolarini index'leriyle birlikte olustur.
    """

    # --- direction_enum ENUM Tipini Olustur ---
    direction_enum = postgresql.ENUM(
        "increase", "decrease", "no_change",
        name="direction_enum",
        create_type=True,
    )
    direction_enum.create(op.get_bind(), checkfirst=True)

    # fuel_type_enum referansi — 001'de olusturulmus, burada sadece kullaniliyor
    fuel_type_enum = sa.Enum(
        "benzin", "motorin", "lpg",
        name="fuel_type_enum",
        create_type=False,
    )

    # =====================================================================
    # 1. price_changes Tablosu
    # =====================================================================
    op.create_table(
        "price_changes",
        sa.Column(
            "id", sa.BigInteger(), primary_key=True, autoincrement=True,
            comment="Otomatik artan birincil anahtar",
        ),
        sa.Column(
            "fuel_type", fuel_type_enum, nullable=False,
            comment="Yakit tipi: benzin, motorin, lpg",
        ),
        sa.Column(
            "change_date", sa.Date(), nullable=False,
            comment="Fiyat degisiklik tarihi",
        ),
        sa.Column(
            "direction", direction_enum, nullable=False,
            comment="Degisim yonu: increase, decrease, no_change",
        ),
        sa.Column(
            "old_price", sa.Numeric(18, 8), nullable=False,
            comment="Degisiklik oncesi pompa fiyati (TL/litre)",
        ),
        sa.Column(
            "new_price", sa.Numeric(18, 8), nullable=False,
            comment="Degisiklik sonrasi pompa fiyati (TL/litre)",
        ),
        sa.Column(
            "change_amount", sa.Numeric(18, 8), nullable=False,
            comment="Degisim miktari TL (new_price - old_price)",
        ),
        sa.Column(
            "change_pct", sa.Numeric(18, 8), nullable=False,
            comment="Degisim yuzdesi ((new - old) / old * 100)",
        ),
        sa.Column(
            "mbe_at_change", sa.Numeric(18, 8), nullable=True,
            comment="Degisiklik anindaki MBE degeri (TL/litre)",
        ),
        sa.Column(
            "source", sa.String(100), nullable=False, server_default="manual",
            comment="Veri kaynagi: epdk, manual, system",
        ),
        sa.Column(
            "notes", sa.Text(), nullable=True,
            comment="Ek notlar",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("NOW()"),
            comment="Kayit olusturulma zamani",
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("NOW()"),
            comment="Son guncelleme zamani",
        ),
        comment="Gecmis akaryakit fiyat degisiklikleri (zam/indirim)",
    )

    # Unique constraint
    op.create_unique_constraint(
        "uq_price_change_fuel_date",
        "price_changes",
        ["fuel_type", "change_date"],
    )

    # Index'ler
    op.create_index("idx_price_change_date", "price_changes", ["change_date"])
    op.create_index("idx_price_change_fuel_date", "price_changes", ["fuel_type", "change_date"])
    op.create_index("idx_price_change_direction", "price_changes", ["direction"])

    # updated_at trigger
    op.execute("""
        CREATE TRIGGER update_price_changes_updated_at
        BEFORE UPDATE ON price_changes
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """)

    # =====================================================================
    # 2. cost_base_snapshots Tablosu
    # =====================================================================
    op.create_table(
        "cost_base_snapshots",
        sa.Column(
            "id", sa.BigInteger(), primary_key=True, autoincrement=True,
            comment="Otomatik artan birincil anahtar",
        ),
        sa.Column(
            "trade_date", sa.Date(), nullable=False,
            comment="Islem tarihi",
        ),
        sa.Column(
            "fuel_type", fuel_type_enum, nullable=False,
            comment="Yakit tipi: benzin, motorin, lpg",
        ),
        sa.Column(
            "market_data_id", sa.BigInteger(),
            sa.ForeignKey("daily_market_data.id", ondelete="CASCADE"),
            nullable=False,
            comment="Iliskili piyasa verisi kaydi",
        ),
        sa.Column(
            "tax_parameter_id", sa.BigInteger(),
            sa.ForeignKey("tax_parameters.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Iliskili vergi parametresi kaydi",
        ),
        sa.Column(
            "cif_component_tl", sa.Numeric(18, 8), nullable=False,
            comment="CIF bileseni TL/litre = (CIF_USD_ton * USD_TRY) / rho",
        ),
        sa.Column(
            "otv_component_tl", sa.Numeric(18, 8), nullable=False,
            comment="OTV bileseni TL/litre",
        ),
        sa.Column(
            "kdv_component_tl", sa.Numeric(18, 8), nullable=False,
            comment="KDV bileseni TL/litre",
        ),
        sa.Column(
            "margin_component_tl", sa.Numeric(18, 8), nullable=False,
            comment="Toplam marj bileseni TL/litre (dagitim + bayi)",
        ),
        sa.Column(
            "theoretical_cost_tl", sa.Numeric(18, 8), nullable=False,
            comment="Teorik maliyet TL/litre = (CIF + OTV) * (1 + KDV) + marj",
        ),
        sa.Column(
            "actual_pump_price_tl", sa.Numeric(18, 8), nullable=False,
            comment="Gercek pompa fiyati TL/litre",
        ),
        sa.Column(
            "implied_cif_usd_ton", sa.Numeric(18, 8), nullable=True,
            comment="Pompa fiyatindan ters hesaplanan ima edilen CIF (USD/ton)",
        ),
        sa.Column(
            "cost_gap_tl", sa.Numeric(18, 8), nullable=False,
            comment="Maliyet farki TL = actual_pump - theoretical_cost",
        ),
        sa.Column(
            "cost_gap_pct", sa.Numeric(18, 8), nullable=False,
            comment="Maliyet farki yuzdesi = cost_gap_tl / theoretical_cost * 100",
        ),
        sa.Column(
            "source", sa.String(100), nullable=False, server_default="system",
            comment="Hesaplama kaynagi",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("NOW()"),
            comment="Kayit olusturulma zamani",
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("NOW()"),
            comment="Son guncelleme zamani",
        ),
        comment="Gunluk maliyet ayristirma snapshot'lari",
    )

    # Unique constraint
    op.create_unique_constraint(
        "uq_cost_snapshot_date_fuel",
        "cost_base_snapshots",
        ["trade_date", "fuel_type"],
    )

    # Index'ler
    op.create_index("idx_cost_snapshot_date", "cost_base_snapshots", ["trade_date"])
    op.create_index("idx_cost_snapshot_fuel_date", "cost_base_snapshots", ["fuel_type", "trade_date"])
    op.create_index("idx_cost_snapshot_market_data", "cost_base_snapshots", ["market_data_id"])
    op.create_index("idx_cost_snapshot_tax_param", "cost_base_snapshots", ["tax_parameter_id"])

    # updated_at trigger
    op.execute("""
        CREATE TRIGGER update_cost_base_snapshots_updated_at
        BEFORE UPDATE ON cost_base_snapshots
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """)

    # =====================================================================
    # 3. mbe_calculations Tablosu
    # =====================================================================
    op.create_table(
        "mbe_calculations",
        sa.Column(
            "id", sa.BigInteger(), primary_key=True, autoincrement=True,
            comment="Otomatik artan birincil anahtar",
        ),
        sa.Column(
            "trade_date", sa.Date(), nullable=False,
            comment="Islem tarihi",
        ),
        sa.Column(
            "fuel_type", fuel_type_enum, nullable=False,
            comment="Yakit tipi: benzin, motorin, lpg",
        ),
        sa.Column(
            "cost_snapshot_id", sa.BigInteger(),
            sa.ForeignKey("cost_base_snapshots.id", ondelete="CASCADE"),
            nullable=False,
            comment="Iliskili maliyet snapshot kaydi",
        ),
        sa.Column(
            "nc_forward", sa.Numeric(18, 8), nullable=False,
            comment="NC_forward = (CIF * FX) / rho (bugunun net maliyeti TL/litre)",
        ),
        sa.Column(
            "nc_base", sa.Numeric(18, 8), nullable=False,
            comment="NC_base: Son zam tarihindeki pompa fiyatindan ters hesaplama",
        ),
        sa.Column(
            "mbe_value", sa.Numeric(18, 8), nullable=False,
            comment="MBE degeri TL/litre = SMA(NC_forward) - SMA(NC_base)",
        ),
        sa.Column(
            "mbe_pct", sa.Numeric(18, 8), nullable=False,
            comment="MBE yuzdesi = mbe_value / nc_base * 100",
        ),
        sa.Column(
            "sma_5", sa.Numeric(18, 8), nullable=True,
            comment="5 gunluk basit hareketli ortalama (NC_forward)",
        ),
        sa.Column(
            "sma_10", sa.Numeric(18, 8), nullable=True,
            comment="10 gunluk basit hareketli ortalama (NC_forward)",
        ),
        sa.Column(
            "delta_mbe", sa.Numeric(18, 8), nullable=True,
            comment="MBE gunluk degisim = MBE_t - MBE_(t-1)",
        ),
        sa.Column(
            "delta_mbe_3", sa.Numeric(18, 8), nullable=True,
            comment="MBE 3 gunluk degisim = MBE_t - MBE_(t-3)",
        ),
        sa.Column(
            "trend_direction", direction_enum, nullable=False,
            comment="Trend yonu: increase, decrease, no_change",
        ),
        sa.Column(
            "regime", sa.Integer(), nullable=False, server_default="0",
            comment="Rejim kodu: 0=Normal, 1=Secim, 2=Kur Soku, 3=Vergi Ayarlama",
        ),
        sa.Column(
            "since_last_change_days", sa.Integer(), nullable=False, server_default="0",
            comment="Son fiyat degisikliginden bu yana gecen gun sayisi",
        ),
        sa.Column(
            "sma_window", sa.Integer(), nullable=False, server_default="5",
            comment="Kullanilan SMA pencere genisligi (rejime bagli)",
        ),
        sa.Column(
            "source", sa.String(100), nullable=False, server_default="system",
            comment="Hesaplama kaynagi",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("NOW()"),
            comment="Kayit olusturulma zamani",
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("NOW()"),
            comment="Son guncelleme zamani",
        ),
        comment="MBE (Maliyet Baz Etkisi) hesaplama sonuclari",
    )

    # Unique constraint
    op.create_unique_constraint(
        "uq_mbe_calc_date_fuel",
        "mbe_calculations",
        ["trade_date", "fuel_type"],
    )

    # Index'ler
    op.create_index("idx_mbe_calc_date", "mbe_calculations", ["trade_date"])
    op.create_index("idx_mbe_calc_fuel_date", "mbe_calculations", ["fuel_type", "trade_date"])
    op.create_index("idx_mbe_calc_regime", "mbe_calculations", ["regime"])
    op.create_index("idx_mbe_calc_snapshot", "mbe_calculations", ["cost_snapshot_id"])

    # updated_at trigger
    op.execute("""
        CREATE TRIGGER update_mbe_calculations_updated_at
        BEFORE UPDATE ON mbe_calculations
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    """
    mbe_calculations, cost_base_snapshots, price_changes tablolarini
    ve direction_enum ENUM tipini kaldirir.
    """

    # --- mbe_calculations ---
    op.execute("DROP TRIGGER IF EXISTS update_mbe_calculations_updated_at ON mbe_calculations;")
    op.drop_index("idx_mbe_calc_snapshot", table_name="mbe_calculations")
    op.drop_index("idx_mbe_calc_regime", table_name="mbe_calculations")
    op.drop_index("idx_mbe_calc_fuel_date", table_name="mbe_calculations")
    op.drop_index("idx_mbe_calc_date", table_name="mbe_calculations")
    op.drop_constraint("uq_mbe_calc_date_fuel", "mbe_calculations", type_="unique")
    op.drop_table("mbe_calculations")

    # --- cost_base_snapshots ---
    op.execute("DROP TRIGGER IF EXISTS update_cost_base_snapshots_updated_at ON cost_base_snapshots;")
    op.drop_index("idx_cost_snapshot_tax_param", table_name="cost_base_snapshots")
    op.drop_index("idx_cost_snapshot_market_data", table_name="cost_base_snapshots")
    op.drop_index("idx_cost_snapshot_fuel_date", table_name="cost_base_snapshots")
    op.drop_index("idx_cost_snapshot_date", table_name="cost_base_snapshots")
    op.drop_constraint("uq_cost_snapshot_date_fuel", "cost_base_snapshots", type_="unique")
    op.drop_table("cost_base_snapshots")

    # --- price_changes ---
    op.execute("DROP TRIGGER IF EXISTS update_price_changes_updated_at ON price_changes;")
    op.drop_index("idx_price_change_direction", table_name="price_changes")
    op.drop_index("idx_price_change_fuel_date", table_name="price_changes")
    op.drop_index("idx_price_change_date", table_name="price_changes")
    op.drop_constraint("uq_price_change_fuel_date", "price_changes", type_="unique")
    op.drop_table("price_changes")

    # --- direction_enum ---
    op.execute("DROP TYPE IF EXISTS direction_enum;")
