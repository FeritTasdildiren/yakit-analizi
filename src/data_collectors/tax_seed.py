"""
Vergi parametreleri başlangıç verisi (seed data) modülü.

Türkiye akaryakıt ÖTV ve KDV oranlarının güncel değerlerini
veritabanına idempotent olarak yükler. Birden fazla kez çalıştırılabilir;
zaten mevcut olan kayıtlar tekrar eklenmez.
"""

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tax_parameters import TaxParameter

logger = logging.getLogger(__name__)

# --- Başlangıç Verisi ---
# Kaynak: 32594 sayılı Resmi Gazete (2024 Temmuz ÖTV ayarlaması)
SEED_DATA: list[dict] = [
    {
        "fuel_type": "benzin",
        "otv_fixed_tl": Decimal("3.9446"),
        "kdv_rate": Decimal("0.18"),
        "valid_from": date(2024, 7, 1),
        "gazette_reference": "32594 sayılı RG",
        "notes": "2024 Temmuz ÖTV ayarlaması",
    },
    {
        "fuel_type": "motorin",
        "otv_fixed_tl": Decimal("2.8746"),
        "kdv_rate": Decimal("0.18"),
        "valid_from": date(2024, 7, 1),
        "gazette_reference": "32594 sayılı RG",
        "notes": "2024 Temmuz ÖTV ayarlaması",
    },
    {
        "fuel_type": "lpg",
        "otv_fixed_tl": Decimal("1.0293"),
        "kdv_rate": Decimal("0.18"),
        "valid_from": date(2024, 7, 1),
        "gazette_reference": "32594 sayılı RG",
        "notes": "2024 Temmuz ÖTV ayarlaması",
    },
    # --- 2025 Ocak güncellemeleri ---
    # Kaynak: 32766 sayılı Resmi Gazete (2025 Ocak ÖTV ayarlaması)
    {
        "fuel_type": "benzin",
        "otv_fixed_tl": Decimal("4.1418"),
        "kdv_rate": Decimal("0.20"),
        "valid_from": date(2025, 1, 1),
        "gazette_reference": "32766 sayılı RG",
        "notes": "2025 Ocak ÖTV ayarlaması — KDV %20'ye yükseltildi",
    },
    {
        "fuel_type": "motorin",
        "otv_fixed_tl": Decimal("3.0183"),
        "kdv_rate": Decimal("0.20"),
        "valid_from": date(2025, 1, 1),
        "gazette_reference": "32766 sayılı RG",
        "notes": "2025 Ocak ÖTV ayarlaması — KDV %20'ye yükseltildi",
    },
    {
        "fuel_type": "lpg",
        "otv_fixed_tl": Decimal("1.0808"),
        "kdv_rate": Decimal("0.20"),
        "valid_from": date(2025, 1, 1),
        "gazette_reference": "32766 sayılı RG",
        "notes": "2025 Ocak ÖTV ayarlaması — LPG ÖTV düşük tutuldu, KDV %20",
    },
    # --- 2025 Temmuz güncellemeleri ---
    # Kaynak: 32948 sayılı Resmi Gazete (2025 Temmuz ÖTV ayarlaması)
    {
        "fuel_type": "benzin",
        "otv_fixed_tl": Decimal("4.3489"),
        "kdv_rate": Decimal("0.20"),
        "valid_from": date(2025, 7, 1),
        "gazette_reference": "32948 sayılı RG",
        "notes": "2025 Temmuz ÖTV ayarlaması",
    },
    {
        "fuel_type": "motorin",
        "otv_fixed_tl": Decimal("3.1692"),
        "kdv_rate": Decimal("0.20"),
        "valid_from": date(2025, 7, 1),
        "gazette_reference": "32948 sayılı RG",
        "notes": "2025 Temmuz ÖTV ayarlaması",
    },
    {
        "fuel_type": "lpg",
        "otv_fixed_tl": Decimal("1.1348"),
        "kdv_rate": Decimal("0.20"),
        "valid_from": date(2025, 7, 1),
        "gazette_reference": "32948 sayılı RG",
        "notes": "2025 Temmuz ÖTV ayarlaması — LPG ÖTV benzinin ~1/4'ü seviyesinde",
    },
    # --- 2026 Ocak güncellemeleri ---
    # Kaynak: 33130 sayılı Resmi Gazete (2026 Ocak ÖTV ayarlaması)
    {
        "fuel_type": "benzin",
        "otv_fixed_tl": Decimal("4.5664"),
        "kdv_rate": Decimal("0.20"),
        "valid_from": date(2026, 1, 1),
        "gazette_reference": "33130 sayılı RG",
        "notes": "2026 Ocak ÖTV ayarlaması",
    },
    {
        "fuel_type": "motorin",
        "otv_fixed_tl": Decimal("3.3277"),
        "kdv_rate": Decimal("0.20"),
        "valid_from": date(2026, 1, 1),
        "gazette_reference": "33130 sayılı RG",
        "notes": "2026 Ocak ÖTV ayarlaması",
    },
    {
        "fuel_type": "lpg",
        "otv_fixed_tl": Decimal("1.1916"),
        "kdv_rate": Decimal("0.20"),
        "valid_from": date(2026, 1, 1),
        "gazette_reference": "33130 sayılı RG",
        "notes": "2026 Ocak ÖTV ayarlaması — LPG ÖTV benzinin ~1/4'ü seviyesinde",
    },
]


async def seed_tax_parameters(session: AsyncSession) -> dict[str, int]:
    """
    Vergi parametreleri başlangıç verisini veritabanına yükler (idempotent).

    Her kayıt için (fuel_type, valid_from) kombinasyonunu kontrol eder.
    Eşleşen kayıt zaten varsa atlar, yoksa ekler.

    Args:
        session: Async veritabanı oturumu.

    Returns:
        İşlem sonucu istatistikleri: {"eklenen": X, "atlanan": Y, "toplam": Z}
    """
    eklenen = 0
    atlanan = 0

    for data in SEED_DATA:
        # İdempotent kontrol: aynı fuel_type ve valid_from ile kayıt var mı?
        stmt = select(TaxParameter).where(
            and_(
                TaxParameter.fuel_type == data["fuel_type"],
                TaxParameter.valid_from == data["valid_from"],
            )
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            logger.info(
                "Seed verisi zaten mevcut, atlanıyor: fuel_type=%s, valid_from=%s (id=%d)",
                data["fuel_type"],
                data["valid_from"],
                existing.id,
            )
            atlanan += 1
            continue

        # Yeni kayıt oluştur
        new_tax = TaxParameter(
            fuel_type=data["fuel_type"],
            otv_rate=data.get("otv_rate"),
            otv_fixed_tl=data.get("otv_fixed_tl"),
            kdv_rate=data["kdv_rate"],
            valid_from=data["valid_from"],
            valid_to=None,  # Aktif kayıt
            gazette_reference=data.get("gazette_reference"),
            notes=data.get("notes"),
            created_by="seed",
        )
        session.add(new_tax)
        eklenen += 1

        logger.info(
            "Seed verisi eklendi: fuel_type=%s, otv_fixed_tl=%s, kdv_rate=%s, valid_from=%s",
            data["fuel_type"],
            data.get("otv_fixed_tl"),
            data["kdv_rate"],
            data["valid_from"],
        )

    # Flush ile ID ataması yapılır (commit üst katmanda yapılır)
    await session.flush()

    sonuc = {
        "eklenen": eklenen,
        "atlanan": atlanan,
        "toplam": len(SEED_DATA),
    }

    logger.info(
        "Seed işlemi tamamlandı: %d eklendi, %d atlandı, toplam %d kayıt",
        eklenen,
        atlanan,
        len(SEED_DATA),
    )

    return sonuc


async def run_seed(session: AsyncSession) -> None:
    """
    Seed fonksiyonunu çalıştırıp sonucu loglar.

    Standalone kullanım veya uygulama başlangıcında çağrılabilir.

    Args:
        session: Async veritabanı oturumu.
    """
    sonuc = await seed_tax_parameters(session)
    logger.info("Vergi parametreleri seed sonucu: %s", sonuc)
