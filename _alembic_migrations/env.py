import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
Alembic ortam konfigürasyonu — Async destekli.

Bu dosya Alembic migration'larını async PostgreSQL bağlantısıyla çalıştırır.
SQLAlchemy modelleri src.models.base.Base üzerinden otomatik keşfedilir.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.config.settings import settings
from src.models.base import Base

# Alembic Config nesnesi — alembic.ini'den erişim sağlar
config = context.config

# Loglama ayarları
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata — tüm modellerin tabloları burada
# NOT: market_data modelini import et ki Base.metadata'ya kaydolsun
import src.models.market_data  # noqa: F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Offline modda migration çalıştırır.

    Veritabanı bağlantısı olmadan SQL çıktısı üretir.
    """
    url = settings.sync_database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Verilen bağlantı ile migration'ları çalıştırır."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Async engine oluşturur ve migration'ları çalıştırır.

    asyncpg driver'ı kullanır.
    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.DATABASE_URL
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """
    Online modda migration çalıştırır (async).

    Canlı veritabanı bağlantısı ile migration uygular.
    """
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
