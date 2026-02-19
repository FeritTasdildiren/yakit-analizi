"""
005: ML tahmin tablosu olusturma.

Katman 4 — Makine Ogrenmesi Tabanli Fiyat Degisim Tahmini.

Tablolar: ml_predictions

NOT: fuel_type_enum 001'de olusturulmus, burada sadece referans edilir.

Revision ID: 005_ml_predictions
Revises: 004_risk_threshold
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic revision bilgileri
revision = "005_ml_predictions"
down_revision = "004_risk_threshold"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """ML tahmin tablosunu olusturur."""

    # fuel_type_enum referansi — 001'de olusturulmus
    fuel_type_enum = sa.Enum(
        "benzin", "motorin", "lpg",
        name="fuel_type_enum",
        create_type=False,
    )

    # --- ml_predictions Tablosu ---
    op.create_table(
        "ml_predictions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True,
                  comment="Otomatik artan birincil anahtar"),
        sa.Column("fuel_type", fuel_type_enum, nullable=False,
                  comment="Yakit tipi: benzin, motorin, lpg"),
        sa.Column("prediction_date", sa.Date(), nullable=False,
                  comment="Tahmin tarihi"),
        sa.Column("predicted_direction", sa.String(10), nullable=False,
                  comment="Tahmin yonu: hike, stable, cut"),
        sa.Column("probability_hike", sa.Numeric(5, 4), nullable=False,
                  comment="Zam olasiligi (0.0000-1.0000)"),
        sa.Column("probability_stable", sa.Numeric(5, 4), nullable=False,
                  comment="Sabit olasiligi (0.0000-1.0000)"),
        sa.Column("probability_cut", sa.Numeric(5, 4), nullable=False,
                  comment="Indirim olasiligi (0.0000-1.0000)"),
        sa.Column("expected_change_tl", sa.Numeric(8, 4), nullable=True,
                  comment="Beklenen degisim TL/L"),
        sa.Column("model_version", sa.String(50), nullable=False,
                  comment="Kullanilan model versiyonu"),
        sa.Column("system_mode", sa.String(20), nullable=False,
                  server_default="full",
                  comment="Sistem modu: full, partial, safe"),
        sa.Column("shap_top_features", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True,
                  comment="Top-5 SHAP feature katkilari"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()"),
                  comment="Kayit olusturulma zamani"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()"),
                  comment="Son guncelleme zamani"),
        comment="ML tahmin kayitlari — siniflandirma, regresyon, SHAP",
    )

    # --- Unique Constraint ---
    op.create_unique_constraint(
        "uq_ml_pred_fuel_date", "ml_predictions",
        ["fuel_type", "prediction_date"],
    )

    # --- Indeksler ---
    op.create_index("idx_ml_pred_date", "ml_predictions", ["prediction_date"])
    op.create_index("idx_ml_pred_fuel_date", "ml_predictions",
                    ["fuel_type", "prediction_date"])
    op.create_index("idx_ml_pred_hike", "ml_predictions", ["probability_hike"],
                    postgresql_where=sa.text("probability_hike >= 0.50"))

    # --- updated_at Trigger ---
    op.execute("""
        CREATE TRIGGER update_ml_predictions_updated_at
        BEFORE UPDATE ON ml_predictions
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    """ML tahmin tablosunu kaldirir."""

    # Trigger'i kaldir
    op.execute(
        "DROP TRIGGER IF EXISTS update_ml_predictions_updated_at ON ml_predictions;"
    )

    # Indeksleri kaldir
    op.drop_index("idx_ml_pred_hike", table_name="ml_predictions")
    op.drop_index("idx_ml_pred_fuel_date", table_name="ml_predictions")
    op.drop_index("idx_ml_pred_date", table_name="ml_predictions")

    # Unique constraint'i kaldir
    op.drop_constraint("uq_ml_pred_fuel_date", "ml_predictions", type_="unique")

    # Tabloyu kaldir
    op.drop_table("ml_predictions")
