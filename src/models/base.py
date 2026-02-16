"""
Temel model sınıfı ve ENUM tanımları.

Tüm SQLAlchemy modelleri bu Base sınıfından türer.
PostgreSQL ENUM tipleri burada merkezi olarak tanımlanır.
"""

from sqlalchemy import Enum as PgEnum
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Tüm modellerin türediği temel sınıf."""

    pass


# --- PostgreSQL ENUM Tipleri ---

fuel_type_enum = PgEnum(
    "benzin",
    "motorin",
    "lpg",
    name="fuel_type_enum",
    create_type=True,
    schema=None,
)

data_quality_enum = PgEnum(
    "verified",
    "interpolated",
    "manual",
    "estimated",
    "stale",
    name="data_quality_enum",
    create_type=True,
    schema=None,
)

direction_enum = PgEnum(
    "increase",
    "decrease",
    "no_change",
    name="direction_enum",
    create_type=True,
    schema=None,
)

# --- Katman 3: Risk / Eşik / Politik Gecikme ENUM Tipleri ---

regime_type_enum = PgEnum(
    "election",
    "holiday",
    "economic_crisis",
    "tax_change",
    "geopolitical",
    "other",
    name="regime_type_enum",
    create_type=True,
    schema=None,
)

alert_level_enum = PgEnum(
    "info",
    "warning",
    "critical",
    name="alert_level_enum",
    create_type=True,
    schema=None,
)

alert_channel_enum = PgEnum(
    "telegram",
    "email",
    "webhook",
    "dashboard",
    name="alert_channel_enum",
    create_type=True,
    schema=None,
)
