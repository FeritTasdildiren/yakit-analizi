"""
002: tax_parameters tablosu oluşturma migration'ı.

Akaryakıt ÖTV ve KDV vergi oranlarını temporal olarak yöneten tablo.
fuel_type_enum 001 migration'ında oluşturulmuş olmalıdır.

Revision ID: 002_create_tax_parameters
Revises: 001 (fuel_type_enum ve temel tablolar)
"""

from alembic import op
import sqlalchemy as sa

# Alembic revision bilgileri
revision = "002_create_tax_params"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    tax_parameters tablosunu ve index'lerini oluşturur.

    fuel_type_enum'un zaten mevcut olduğunu varsayar (001 migration).
    """
    # fuel_type_enum referansı — 001'de oluşturulmuş, burada sadece kullanılıyor
    fuel_type_enum = sa.Enum(
        "benzin", "motorin", "lpg",
        name="fuel_type_enum",
        create_type=False,  # ENUM zaten 001'de oluşturuldu
    )

    op.create_table(
        "tax_parameters",
        # Birincil anahtar
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        # Yakıt tipi
        sa.Column(
            "fuel_type",
            fuel_type_enum,
            nullable=False,
            comment="Yakıt tipi: benzin, motorin veya lpg",
        ),
        # ÖTV alanları
        sa.Column(
            "otv_rate",
            sa.Numeric(18, 8),
            nullable=True,
            comment="ÖTV yüzdesel oranı (opsiyonel)",
        ),
        sa.Column(
            "otv_fixed_tl",
            sa.Numeric(18, 8),
            nullable=True,
            comment="ÖTV sabit tutar TRY/litre",
        ),
        # KDV
        sa.Column(
            "kdv_rate",
            sa.Numeric(18, 8),
            nullable=False,
            comment="KDV oranı (0-1 aralığında)",
        ),
        # Temporal alanlar
        sa.Column(
            "valid_from",
            sa.Date,
            nullable=False,
            comment="Geçerlilik başlangıç tarihi",
        ),
        sa.Column(
            "valid_to",
            sa.Date,
            nullable=True,
            comment="Geçerlilik bitiş tarihi — NULL ise hâlâ geçerli",
        ),
        # Referans ve notlar
        sa.Column(
            "gazette_reference",
            sa.String(255),
            nullable=True,
            comment="Resmi Gazete referans numarası",
        ),
        sa.Column(
            "notes",
            sa.Text,
            nullable=True,
            comment="Ek notlar",
        ),
        # Audit alanları
        sa.Column(
            "created_by",
            sa.String(100),
            nullable=False,
            server_default="system",
            comment="Kaydı oluşturan kullanıcı veya sistem",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="Oluşturulma zamanı (UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="Son güncelleme zamanı (UTC)",
        ),
    )

    # --- Index'ler ---

    # Yakıt tipi ve geçerlilik tarihine göre sorgulama index'i
    op.create_index(
        "idx_tax_fuel_valid",
        "tax_parameters",
        ["fuel_type", sa.text("valid_from DESC")],
    )

    # Aktif kayıtlar için partial index (valid_to IS NULL)
    op.create_index(
        "idx_tax_active",
        "tax_parameters",
        ["fuel_type"],
        postgresql_where=sa.text("valid_to IS NULL"),
    )


def downgrade() -> None:
    """
    tax_parameters tablosunu ve index'lerini kaldırır.

    fuel_type_enum kaldırılmaz (001 migration'ının sorumluluğu).
    """
    # Index'leri kaldır (tablo silinince otomatik kalkar ama açıkça yapalım)
    op.drop_index("idx_tax_active", table_name="tax_parameters")
    op.drop_index("idx_tax_fuel_valid", table_name="tax_parameters")

    # Tabloyu kaldır
    op.drop_table("tax_parameters")
