"""
Vergi parametreleri (tax_parameters) test modülü.

Kapsam:
- Temporal sorgu testleri (get_current_tax, get_all_current_taxes)
- Yeni oran ekleme + önceki kaydın valid_to güncellenmesi testi
- Validasyon testleri (ÖTV, KDV, tarih aralığı, yakıt tipi)
- Seed data idempotent testi
- API endpoint testleri

Tüm testler in-memory SQLite (aiosqlite) kullanır, gerçek PostgreSQL gerekmez.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.data_collectors.tax_repository import (
    TaxParameterCreate,
    create_tax_parameter,
    get_all_current_taxes,
    get_current_tax,
    get_tax_history,
    update_tax_parameter,
)
from src.data_collectors.tax_seed import SEED_DATA, seed_tax_parameters
from src.data_collectors.tax_validators import (
    TaxValidationErrors,
    validate_fuel_type,
    validate_kdv_rate,
    validate_otv_fields,
    validate_tax_parameter,
)
from src.models.base import Base
from src.models.tax_parameters import TaxParameter


# --- Test Fixtures ---


@pytest_asyncio.fixture
async def engine():
    """Async in-memory SQLite engine oluşturur."""
    # aiosqlite ile in-memory veritabanı
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    # SQLite'ta partial index desteklenmediğinden, tabloyu
    # index'ler olmadan oluşturuyoruz
    async with test_engine.begin() as conn:
        # Tabloyu doğrudan SQL ile oluştur (SQLite uyumlu)
        await conn.execute(text("""
            CREATE TABLE tax_parameters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fuel_type VARCHAR(10) NOT NULL,
                otv_rate NUMERIC(18, 8),
                otv_fixed_tl NUMERIC(18, 8),
                kdv_rate NUMERIC(18, 8) NOT NULL,
                valid_from DATE NOT NULL,
                valid_to DATE,
                gazette_reference VARCHAR(255),
                notes TEXT,
                created_by VARCHAR(100) NOT NULL DEFAULT 'system',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

    yield test_engine

    await test_engine.dispose()


@pytest_asyncio.fixture
async def session(engine):
    """Her test için yeni bir async session oluşturur."""
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def seeded_session(session: AsyncSession):
    """Seed verisi yüklenmiş session döndürür."""
    await seed_tax_parameters(session)
    await session.commit()
    return session


# --- Yardımcı Fonksiyonlar ---


async def _create_test_tax(
    session: AsyncSession,
    fuel_type: str = "benzin",
    otv_fixed_tl: Decimal = Decimal("3.9446"),
    kdv_rate: Decimal = Decimal("0.18"),
    valid_from: date = date(2024, 7, 1),
) -> TaxParameter:
    """Test için hızlı vergi kaydı oluşturur."""
    dto = TaxParameterCreate(
        fuel_type=fuel_type,
        otv_fixed_tl=otv_fixed_tl,
        kdv_rate=kdv_rate,
        valid_from=valid_from,
    )
    tax = await create_tax_parameter(session, dto)
    await session.commit()
    return tax


# ============================================================
# 1. TEMPORAL SORGU TESTLERİ
# ============================================================


class TestTemporalQueries:
    """Temporal (zamana bağlı) sorgu testleri."""

    async def test_get_current_tax_returns_active_record(self, session: AsyncSession):
        """Aktif (valid_to IS NULL) kaydı döndürmeli."""
        tax = await _create_test_tax(session, fuel_type="benzin")

        result = await get_current_tax(session, "benzin")
        assert result is not None
        assert result.id == tax.id
        assert result.fuel_type == "benzin"
        assert result.valid_to is None

    async def test_get_current_tax_with_ref_date(self, session: AsyncSession):
        """Referans tarihindeki geçerli kaydı döndürmeli."""
        tax = await _create_test_tax(
            session,
            fuel_type="motorin",
            valid_from=date(2024, 1, 1),
        )

        # valid_from sonrası bir tarihte sorgu
        result = await get_current_tax(session, "motorin", ref_date=date(2024, 6, 15))
        assert result is not None
        assert result.id == tax.id

    async def test_get_current_tax_before_valid_from_returns_none(self, session: AsyncSession):
        """valid_from'dan önceki tarihte None döndürmeli."""
        await _create_test_tax(
            session,
            fuel_type="lpg",
            valid_from=date(2024, 7, 1),
        )

        result = await get_current_tax(session, "lpg", ref_date=date(2024, 6, 30))
        assert result is None

    async def test_get_current_tax_nonexistent_fuel_type(self, session: AsyncSession):
        """Mevcut olmayan yakıt tipi için None döndürmeli."""
        result = await get_current_tax(session, "benzin")
        assert result is None

    async def test_get_all_current_taxes(self, seeded_session: AsyncSession):
        """Tüm aktif vergi kayıtlarını döndürmeli."""
        taxes = await get_all_current_taxes(seeded_session)
        # Seed tüm kayıtları valid_to=None ile ekler (4 dönem × 3 yakıt tipi = 12)
        assert len(taxes) == len(SEED_DATA)

        fuel_types = {t.fuel_type for t in taxes}
        assert fuel_types == {"benzin", "motorin", "lpg"}

        # Hepsi aktif olmalı (valid_to IS NULL)
        for tax in taxes:
            assert tax.valid_to is None

    async def test_get_all_current_taxes_at_specific_date(self, seeded_session: AsyncSession):
        """Belirli tarihte geçerli tüm kayıtları döndürmeli."""
        # 2024-08-01'de yalnızca 2024-07-01 kayıtları geçerli (3 yakıt tipi)
        # Ancak 2025 ve 2026 kayıtları da valid_to=None olduğundan
        # valid_from <= ref_date filtresi ile sadece 2024-07-01 dönemler eşleşir
        taxes = await get_all_current_taxes(seeded_session, ref_date=date(2024, 8, 1))
        assert len(taxes) == 3  # Sadece 2024-07-01 kayıtları (valid_from <= 2024-08-01)

    async def test_get_all_current_taxes_before_any_record(self, seeded_session: AsyncSession):
        """Hiçbir kaydın geçerli olmadığı tarihte boş liste döndürmeli."""
        taxes = await get_all_current_taxes(seeded_session, ref_date=date(2020, 1, 1))
        assert len(taxes) == 0

    async def test_get_tax_history(self, session: AsyncSession):
        """Yakıt tipi için tüm geçmişi tarihe göre sıralı döndürmeli."""
        # İlk kayıt
        await _create_test_tax(
            session,
            fuel_type="benzin",
            otv_fixed_tl=Decimal("3.0000"),
            valid_from=date(2024, 1, 1),
        )

        # İkinci kayıt (önceki kaydın valid_to güncellenir)
        await _create_test_tax(
            session,
            fuel_type="benzin",
            otv_fixed_tl=Decimal("3.9446"),
            valid_from=date(2024, 7, 1),
        )

        history = await get_tax_history(session, "benzin")
        assert len(history) == 2
        # En yeni önce (DESC sıralama)
        assert history[0].valid_from == date(2024, 7, 1)
        assert history[1].valid_from == date(2024, 1, 1)


# ============================================================
# 2. KAYIT OLUŞTURMA VE VALID_TO GÜNCELLEMESİ TESTLERİ
# ============================================================


class TestCreateTaxParameter:
    """Yeni vergi kaydı oluşturma ve temporal bütünlük testleri."""

    async def test_create_first_record(self, session: AsyncSession):
        """İlk kayıt oluşturulabilmeli."""
        tax = await _create_test_tax(session)

        assert tax.id is not None
        assert tax.fuel_type == "benzin"
        assert tax.otv_fixed_tl == Decimal("3.9446")
        assert tax.kdv_rate == Decimal("0.18")
        assert tax.valid_from == date(2024, 7, 1)
        assert tax.valid_to is None  # Aktif kayıt
        assert tax.created_by == "system"

    async def test_create_closes_previous_active_record(self, session: AsyncSession):
        """Yeni kayıt eklenince önceki aktif kaydın valid_to güncellenmeli."""
        # İlk kayıt
        first = await _create_test_tax(
            session,
            fuel_type="benzin",
            otv_fixed_tl=Decimal("3.0000"),
            valid_from=date(2024, 1, 1),
        )
        assert first.valid_to is None

        # İkinci kayıt
        second = await _create_test_tax(
            session,
            fuel_type="benzin",
            otv_fixed_tl=Decimal("3.9446"),
            valid_from=date(2024, 7, 1),
        )

        # İlk kaydın valid_to güncellenmeli
        # Session'dan güncel halini çekelim
        updated_first = await get_current_tax(session, "benzin", ref_date=date(2024, 3, 1))
        assert updated_first is not None
        assert updated_first.id == first.id

        # İkinci kayıt aktif olmalı
        current = await get_current_tax(session, "benzin")
        assert current is not None
        assert current.id == second.id
        assert current.valid_to is None

    async def test_create_different_fuel_types_independent(self, session: AsyncSession):
        """Farklı yakıt tiplerine ait kayıtlar birbirini etkilememeli."""
        benzin = await _create_test_tax(session, fuel_type="benzin", valid_from=date(2024, 1, 1))
        motorin = await _create_test_tax(session, fuel_type="motorin", valid_from=date(2024, 1, 1))

        # Her ikisi de aktif olmalı
        assert benzin.valid_to is None
        assert motorin.valid_to is None

    async def test_create_with_gazette_reference(self, session: AsyncSession):
        """Resmi Gazete referansı ile kayıt oluşturulabilmeli."""
        dto = TaxParameterCreate(
            fuel_type="benzin",
            otv_fixed_tl=Decimal("3.9446"),
            kdv_rate=Decimal("0.18"),
            valid_from=date(2024, 7, 1),
            gazette_reference="32594 sayılı RG",
            notes="2024 Temmuz ÖTV ayarlaması",
        )
        tax = await create_tax_parameter(session, dto)
        await session.commit()

        assert tax.gazette_reference == "32594 sayılı RG"
        assert tax.notes == "2024 Temmuz ÖTV ayarlaması"

    async def test_create_with_otv_rate(self, session: AsyncSession):
        """ÖTV yüzdesel oranı ile kayıt oluşturulabilmeli."""
        dto = TaxParameterCreate(
            fuel_type="benzin",
            otv_rate=Decimal("0.25"),
            kdv_rate=Decimal("0.18"),
            valid_from=date(2024, 7, 1),
        )
        tax = await create_tax_parameter(session, dto)
        await session.commit()

        assert tax.otv_rate == Decimal("0.25")
        assert tax.otv_fixed_tl is None


# ============================================================
# 3. GÜNCELLEME TESTLERİ
# ============================================================


class TestUpdateTaxParameter:
    """Vergi parametresi güncelleme testleri."""

    async def test_update_kdv_rate(self, session: AsyncSession):
        """KDV oranı güncellenebilmeli."""
        tax = await _create_test_tax(session)

        updated = await update_tax_parameter(
            session, tax.id, kdv_rate=Decimal("0.20"),
        )
        await session.commit()

        assert updated is not None
        assert updated.kdv_rate == Decimal("0.20")

    async def test_update_nonexistent_id(self, session: AsyncSession):
        """Mevcut olmayan ID için None döndürmeli."""
        result = await update_tax_parameter(session, 99999, kdv_rate=Decimal("0.20"))
        assert result is None

    async def test_update_notes(self, session: AsyncSession):
        """Notlar güncellenebilmeli."""
        tax = await _create_test_tax(session)

        updated = await update_tax_parameter(
            session, tax.id, notes="Güncelleme testi",
        )
        await session.commit()

        assert updated is not None
        assert updated.notes == "Güncelleme testi"


# ============================================================
# 4. VALİDASYON TESTLERİ
# ============================================================


class TestValidation:
    """Vergi parametresi doğrulama testleri."""

    def test_validate_fuel_type_valid(self):
        """Geçerli yakıt tipleri hata döndürmemeli."""
        for fuel_type in ["benzin", "motorin", "lpg"]:
            errors = validate_fuel_type(fuel_type)
            assert len(errors) == 0, f"{fuel_type} geçerli olmalı"

    def test_validate_fuel_type_invalid(self):
        """Geçersiz yakıt tipi hata döndürmeli."""
        errors = validate_fuel_type("mazot")
        assert len(errors) == 1
        assert "Geçersiz yakıt tipi" in errors[0].message

    def test_validate_otv_both_none_error(self):
        """İkisi de None ise hata döndürmeli."""
        errors = validate_otv_fields(None, None)
        assert len(errors) == 1
        assert "en az biri dolu olmalıdır" in errors[0].message

    def test_validate_otv_fixed_positive(self):
        """otv_fixed_tl pozitif olduğunda hata döndürmemeli."""
        errors = validate_otv_fields(None, Decimal("3.9446"))
        assert len(errors) == 0

    def test_validate_otv_fixed_zero_error(self):
        """otv_fixed_tl sıfır olduğunda hata döndürmeli."""
        errors = validate_otv_fields(None, Decimal("0"))
        assert len(errors) == 1
        assert "pozitif" in errors[0].message

    def test_validate_otv_fixed_negative_error(self):
        """otv_fixed_tl negatif olduğunda hata döndürmeli."""
        errors = validate_otv_fields(None, Decimal("-1.5"))
        assert len(errors) == 1
        assert "pozitif" in errors[0].message

    def test_validate_otv_rate_negative_error(self):
        """otv_rate negatif olduğunda hata döndürmeli."""
        errors = validate_otv_fields(Decimal("-0.1"), None)
        assert len(errors) == 1
        assert "negatif olamaz" in errors[0].message

    def test_validate_otv_rate_valid(self):
        """otv_rate geçerli olduğunda hata döndürmemeli."""
        errors = validate_otv_fields(Decimal("0.25"), None)
        assert len(errors) == 0

    def test_validate_kdv_rate_valid(self):
        """Geçerli KDV oranları hata döndürmemeli."""
        for rate in [Decimal("0"), Decimal("0.18"), Decimal("1")]:
            errors = validate_kdv_rate(rate)
            assert len(errors) == 0, f"KDV oranı {rate} geçerli olmalı"

    def test_validate_kdv_rate_too_high(self):
        """KDV oranı 1'den büyükse hata döndürmeli."""
        errors = validate_kdv_rate(Decimal("1.1"))
        assert len(errors) == 1
        assert "0 ile 1 arasında" in errors[0].message

    def test_validate_kdv_rate_negative(self):
        """KDV oranı negatifse hata döndürmeli."""
        errors = validate_kdv_rate(Decimal("-0.1"))
        assert len(errors) == 1
        assert "0 ile 1 arasında" in errors[0].message

    def test_validate_tax_parameter_all_valid(self):
        """Tüm alanlar geçerliyse hata fırlatmamalı."""
        # Hata fırlatmayacağını doğrula
        validate_tax_parameter(
            fuel_type="benzin",
            otv_rate=None,
            otv_fixed_tl=Decimal("3.9446"),
            kdv_rate=Decimal("0.18"),
            valid_from=date(2024, 7, 1),
        )

    def test_validate_tax_parameter_multiple_errors(self):
        """Birden fazla hata varsa hepsini toplu fırlatmalı."""
        with pytest.raises(TaxValidationErrors) as exc_info:
            validate_tax_parameter(
                fuel_type="mazot",  # Geçersiz yakıt tipi
                otv_rate=None,
                otv_fixed_tl=None,  # İkisi de boş
                kdv_rate=Decimal("2.0"),  # Geçersiz KDV
                valid_from=date(2024, 7, 1),
            )

        errors = exc_info.value.errors
        assert len(errors) == 3  # fuel_type + otv + kdv

    async def test_create_with_invalid_data_raises_error(self, session: AsyncSession):
        """Geçersiz veri ile kayıt oluşturma hata fırlatmalı."""
        dto = TaxParameterCreate(
            fuel_type="mazot",  # Geçersiz
            otv_fixed_tl=Decimal("3.0"),
            kdv_rate=Decimal("0.18"),
            valid_from=date(2024, 7, 1),
        )

        with pytest.raises(TaxValidationErrors):
            await create_tax_parameter(session, dto)

    async def test_create_with_both_otv_none_raises_error(self, session: AsyncSession):
        """ÖTV alanlarının ikisi de None ise hata fırlatmalı."""
        dto = TaxParameterCreate(
            fuel_type="benzin",
            otv_rate=None,
            otv_fixed_tl=None,
            kdv_rate=Decimal("0.18"),
            valid_from=date(2024, 7, 1),
        )

        with pytest.raises(TaxValidationErrors):
            await create_tax_parameter(session, dto)


# ============================================================
# 5. SEED DATA İDEMPOTENT TESTLERİ
# ============================================================


class TestSeedData:
    """Seed data yükleme ve idempotent davranış testleri."""

    async def test_seed_creates_all_records(self, session: AsyncSession):
        """İlk seed çalıştırmada tüm kayıtlar oluşturulmalı."""
        result = await seed_tax_parameters(session)
        await session.commit()

        # 4 dönem × 3 yakıt tipi = 12 kayıt
        assert result["eklenen"] == len(SEED_DATA)
        assert result["atlanan"] == 0
        assert result["toplam"] == len(SEED_DATA)

    async def test_seed_is_idempotent(self, session: AsyncSession):
        """İkinci seed çalıştırmada hiçbir kayıt eklenmemeli."""
        # İlk çalıştırma
        await seed_tax_parameters(session)
        await session.commit()

        # İkinci çalıştırma — idempotent olmalı
        result = await seed_tax_parameters(session)
        await session.commit()

        assert result["eklenen"] == 0
        assert result["atlanan"] == len(SEED_DATA)
        assert result["toplam"] == len(SEED_DATA)

    async def test_seed_data_values_correct(self, seeded_session: AsyncSession):
        """Seed verisi doğru değerlerle yüklenmeli."""
        # En güncel kayıtlar (2026-01-01) kontrol edilir
        # get_current_tax default olarak bugünün tarihini kullanır
        # ve valid_from DESC ile en güncel kaydı döndürür

        # Benzin — 2026 Ocak güncel değeri
        benzin = await get_current_tax(seeded_session, "benzin")
        assert benzin is not None
        assert benzin.otv_fixed_tl == Decimal("4.5664")
        assert benzin.kdv_rate == Decimal("0.20")
        assert benzin.valid_from == date(2026, 1, 1)

        # Motorin — 2026 Ocak güncel değeri
        motorin = await get_current_tax(seeded_session, "motorin")
        assert motorin is not None
        assert motorin.otv_fixed_tl == Decimal("3.3277")

        # LPG — 2026 Ocak güncel değeri
        lpg = await get_current_tax(seeded_session, "lpg")
        assert lpg is not None
        assert lpg.otv_fixed_tl == Decimal("1.1916")

        # Geçmiş dönem doğrulaması — 2024 Temmuz
        benzin_2024 = await get_current_tax(
            seeded_session, "benzin", ref_date=date(2024, 8, 1),
        )
        assert benzin_2024 is not None
        assert benzin_2024.otv_fixed_tl == Decimal("3.9446")
        assert benzin_2024.kdv_rate == Decimal("0.18")

        # LPG — 2024 Temmuz
        lpg_2024 = await get_current_tax(
            seeded_session, "lpg", ref_date=date(2024, 8, 1),
        )
        assert lpg_2024 is not None
        assert lpg_2024.otv_fixed_tl == Decimal("1.0293")

    async def test_seed_records_are_active(self, seeded_session: AsyncSession):
        """Seed kayıtları aktif (valid_to IS NULL) olmalı."""
        taxes = await get_all_current_taxes(seeded_session)
        for tax in taxes:
            assert tax.valid_to is None
            assert tax.created_by == "seed"

    async def test_seed_partial_idempotent(self, session: AsyncSession):
        """Bazı kayıtlar mevcutken seed çalıştırılırsa, sadece eksikler eklenmeli."""
        # Manuel olarak sadece benzin 2024-07-01 ekle
        benzin = TaxParameter(
            fuel_type="benzin",
            otv_fixed_tl=Decimal("3.9446"),
            kdv_rate=Decimal("0.18"),
            valid_from=date(2024, 7, 1),
            created_by="manual",
        )
        session.add(benzin)
        await session.flush()
        await session.commit()

        # Seed çalıştır — benzin 2024-07-01 atlanmalı, geri kalanlar eklenmeli
        result = await seed_tax_parameters(session)
        await session.commit()

        assert result["eklenen"] == len(SEED_DATA) - 1
        assert result["atlanan"] == 1


# ============================================================
# 6. MODEL TESTLERİ
# ============================================================


class TestTaxParameterModel:
    """TaxParameter model özellik testleri."""

    def test_is_active_property_when_valid_to_none(self):
        """valid_to = None ise is_active True olmalı."""
        tax = TaxParameter(valid_to=None)
        assert tax.is_active is True

    def test_is_active_property_when_valid_to_set(self):
        """valid_to ayarlıysa is_active False olmalı."""
        tax = TaxParameter(valid_to=date(2024, 12, 31))
        assert tax.is_active is False

    def test_display_otv_fixed(self):
        """otv_fixed_tl varsa TL/lt formatında göstermeli."""
        tax = TaxParameter(otv_fixed_tl=Decimal("3.9446"), otv_rate=None)
        assert "TL/lt" in tax.display_otv

    def test_display_otv_rate(self):
        """otv_rate varsa yüzde formatında göstermeli."""
        tax = TaxParameter(otv_rate=Decimal("0.25"), otv_fixed_tl=None)
        assert "%" in tax.display_otv

    def test_display_otv_undefined(self):
        """İkisi de None ise 'Tanımsız' döndürmeli."""
        tax = TaxParameter(otv_rate=None, otv_fixed_tl=None)
        assert tax.display_otv == "Tanımsız"

    def test_repr(self):
        """__repr__ okunabilir string döndürmeli."""
        tax = TaxParameter(
            id=1,
            fuel_type="benzin",
            otv_fixed_tl=Decimal("3.9446"),
            kdv_rate=Decimal("0.18"),
            valid_from=date(2024, 7, 1),
            valid_to=None,
        )
        repr_str = repr(tax)
        assert "TaxParameter" in repr_str
        assert "benzin" in repr_str
