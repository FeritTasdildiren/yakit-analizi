"""
Veritabanı bağlantı yönetimi.

SQLAlchemy async engine, session factory ve FastAPI dependency injection.
"""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config.settings import settings

logger = logging.getLogger(__name__)

# --- Async Engine ---
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# --- Session Factory ---
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency: her istek için yeni bir async session oluşturur.

    Kullanım:
        @router.get("/")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Veritabanı oturumu sırasında hata oluştu")
            raise
        finally:
            await session.close()


async def dispose_engine() -> None:
    """Uygulama kapanırken engine bağlantı havuzunu temizler."""
    await engine.dispose()
    logger.info("Veritabanı engine bağlantı havuzu kapatıldı")
