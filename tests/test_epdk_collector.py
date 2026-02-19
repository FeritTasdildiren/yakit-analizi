"""
EPDK Pompa Fiyatı Veri Çekme Servisi — Test Modülü

Testler:
    1. Mock XML yanıtı ile parse testi
    2. Ortalama hesaplama testi
    3. Validasyon testi
    4. Uç durum testleri (boş veri, geçersiz format, vs.)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.data_collectors.epdk_collector import (
    EPDKRecord,
    PumpPriceData,
    _calculate_average,
    _parse_date,
    _parse_decimal,
    _records_to_pump_prices,
    parse_epdk_xml,
)
from src.data_collectors.epdk_validators import (
    ValidationSeverity,
    validate_daily_change,
    validate_distributor_deviation,
    validate_price_range,
    validate_pump_prices,
)


# ── Mock XML Verileri ─────────────────────────────────────────────────────────

MOCK_XML_VALID = """\
<?xml version="1.0" encoding="utf-8"?>
<NewDataSet>
  <Table>
    <IL_KODU>34</IL_KODU>
    <IL_ADI>İSTANBUL</IL_ADI>
    <DAGITICI>SHELL</DAGITICI>
    <BENZIN>43,72</BENZIN>
    <MOTORIN>41,85</MOTORIN>
    <LPG>18,50</LPG>
    <TARIH>15.02.2026</TARIH>
  </Table>
  <Table>
    <IL_KODU>34</IL_KODU>
    <IL_ADI>İSTANBUL</IL_ADI>
    <DAGITICI>BP</DAGITICI>
    <BENZIN>43,50</BENZIN>
    <MOTORIN>41,70</MOTORIN>
    <LPG>18,30</LPG>
    <TARIH>15.02.2026</TARIH>
  </Table>
  <Table>
    <IL_KODU>34</IL_KODU>
    <IL_ADI>İSTANBUL</IL_ADI>
    <DAGITICI>OPET</DAGITICI>
    <BENZIN>43,80</BENZIN>
    <MOTORIN>41,90</MOTORIN>
    <LPG>18,60</LPG>
    <TARIH>15.02.2026</TARIH>
  </Table>
</NewDataSet>
"""

MOCK_XML_EMPTY = """\
<?xml version="1.0" encoding="utf-8"?>
<NewDataSet>
</NewDataSet>
"""

MOCK_XML_PARTIAL = """\
<?xml version="1.0" encoding="utf-8"?>
<NewDataSet>
  <Table>
    <IL_KODU>06</IL_KODU>
    <IL_ADI>ANKARA</IL_ADI>
    <DAGITICI>TOTAL</DAGITICI>
    <BENZIN>42,90</BENZIN>
    <MOTORIN>40,80</MOTORIN>
    <TARIH>15.02.2026</TARIH>
  </Table>
</NewDataSet>
"""

MOCK_XML_COMMA_NUMBERS = """\
<?xml version="1.0" encoding="utf-8"?>
<NewDataSet>
  <Table>
    <IL_KODU>35</IL_KODU>
    <IL_ADI>İZMİR</IL_ADI>
    <DAGITICI>PETROL OFİSİ</DAGITICI>
    <BENZIN>43,15</BENZIN>
    <MOTORIN>41,25</MOTORIN>
    <LPG>18,05</LPG>
    <TARIH>15.02.2026</TARIH>
  </Table>
</NewDataSet>
"""

MOCK_XML_INVALID = "<not-valid-xml"

MOCK_XML_MISSING_FIELDS = """\
<?xml version="1.0" encoding="utf-8"?>
<NewDataSet>
  <Table>
    <IL_ADI>İSTANBUL</IL_ADI>
    <DAGITICI>SHELL</DAGITICI>
    <BENZIN>43,72</BENZIN>
  </Table>
  <Table>
    <IL_KODU>34</IL_KODU>
    <IL_ADI>İSTANBUL</IL_ADI>
    <BENZIN>43,50</BENZIN>
  </Table>
</NewDataSet>
"""


# ── 1. XML Parse Testleri ────────────────────────────────────────────────────


class TestParseEpdkXml:
    """EPDK XML parse fonksiyonu testleri."""

    def test_valid_xml_parse(self) -> None:
        """Geçerli XML'den doğru sayıda kayıt okunur."""
        records = parse_epdk_xml(MOCK_XML_VALID)
        assert len(records) == 3

    def test_valid_xml_field_values(self) -> None:
        """İlk kaydın alanları doğru parse edilir."""
        records = parse_epdk_xml(MOCK_XML_VALID)
        first = records[0]

        assert first.il_kodu == "34"
        assert first.il_adi == "İSTANBUL"
        assert first.dagitici == "SHELL"
        assert first.benzin_fiyat == Decimal("43.72")
        assert first.motorin_fiyat == Decimal("41.85")
        assert first.lpg_fiyat == Decimal("18.50")
        assert first.tarih == date(2026, 2, 15)

    def test_empty_xml(self) -> None:
        """Boş XML'den boş liste döner."""
        records = parse_epdk_xml(MOCK_XML_EMPTY)
        assert records == []

    def test_invalid_xml(self) -> None:
        """Geçersiz XML hatası yakalanır, boş liste döner."""
        records = parse_epdk_xml(MOCK_XML_INVALID)
        assert records == []

    def test_partial_data(self) -> None:
        """LPG fiyatı olmayan kayıt doğru parse edilir (None)."""
        records = parse_epdk_xml(MOCK_XML_PARTIAL)
        assert len(records) == 1
        assert records[0].lpg_fiyat is None
        assert records[0].benzin_fiyat == Decimal("42.90")
        assert records[0].motorin_fiyat == Decimal("40.80")

    def test_missing_required_fields_skipped(self) -> None:
        """il_kodu veya dagitici eksik kayıtlar atlanır."""
        records = parse_epdk_xml(MOCK_XML_MISSING_FIELDS)
        # İlk kayıt: IL_KODU eksik → atlanır
        # İkinci kayıt: DAGITICI eksik → atlanır
        assert len(records) == 0

    def test_comma_to_decimal_conversion(self) -> None:
        """Virgüllü sayılar Decimal'e doğru dönüştürülür."""
        records = parse_epdk_xml(MOCK_XML_COMMA_NUMBERS)
        assert len(records) == 1
        assert records[0].benzin_fiyat == Decimal("43.15")
        assert records[0].motorin_fiyat == Decimal("41.25")
        assert records[0].lpg_fiyat == Decimal("18.05")

    def test_dagitici_normalized(self) -> None:
        """Dağıtıcı adları UPPER + STRIP ile normalize edilir."""
        records = parse_epdk_xml(MOCK_XML_COMMA_NUMBERS)
        assert records[0].dagitici == "PETROL OFİSİ"

    def test_date_parsing(self) -> None:
        """dd.MM.yyyy formatındaki tarih doğru parse edilir."""
        records = parse_epdk_xml(MOCK_XML_VALID)
        assert records[0].tarih == date(2026, 2, 15)


class TestParseDecimal:
    """_parse_decimal yardımcı fonksiyonu testleri."""

    def test_comma_format(self) -> None:
        assert _parse_decimal("43,72") == Decimal("43.72")

    def test_dot_format(self) -> None:
        assert _parse_decimal("43.72") == Decimal("43.72")

    def test_integer(self) -> None:
        assert _parse_decimal("43") == Decimal("43")

    def test_none(self) -> None:
        assert _parse_decimal(None) is None

    def test_empty(self) -> None:
        assert _parse_decimal("") is None

    def test_dash(self) -> None:
        assert _parse_decimal("-") is None

    def test_whitespace(self) -> None:
        assert _parse_decimal("  43,72  ") == Decimal("43.72")

    def test_invalid_string(self) -> None:
        assert _parse_decimal("abc") is None


class TestParseDate:
    """_parse_date yardımcı fonksiyonu testleri."""

    def test_valid_date(self) -> None:
        assert _parse_date("15.02.2026") == date(2026, 2, 15)

    def test_none_returns_today(self) -> None:
        result = _parse_date(None)
        assert result == date.today()

    def test_empty_returns_today(self) -> None:
        result = _parse_date("")
        assert result == date.today()

    def test_invalid_format_returns_today(self) -> None:
        result = _parse_date("2026-02-15")
        assert result == date.today()


# ── 2. Ortalama Hesaplama Testleri ───────────────────────────────────────────


class TestCalculateAverage:
    """Ortalama hesaplama testleri."""

    def test_simple_average(self) -> None:
        """Basit ortalama doğru hesaplanır."""
        values = [Decimal("43.72"), Decimal("43.50"), Decimal("43.80")]
        result = _calculate_average(values)
        assert result == Decimal("43.67")

    def test_single_value(self) -> None:
        """Tek değerin ortalaması kendisidir."""
        result = _calculate_average([Decimal("43.72")])
        assert result == Decimal("43.72")

    def test_empty_list(self) -> None:
        """Boş liste için 0 döner."""
        result = _calculate_average([])
        assert result == Decimal("0.00")

    def test_precision(self) -> None:
        """Sonuç 2 ondalık haneye yuvarlanır."""
        values = [Decimal("10.00"), Decimal("10.01"), Decimal("10.02")]
        result = _calculate_average(values)
        assert result == Decimal("10.01")


class TestRecordsToPumpPrices:
    """_records_to_pump_prices dönüşüm testleri."""

    def test_three_fuel_types(self) -> None:
        """3 dağıtıcılı veri → 3 yakıt tipi (benzin, motorin, lpg) üretir."""
        records = parse_epdk_xml(MOCK_XML_VALID)
        prices = _records_to_pump_prices(records, il_kodu="34")

        assert len(prices) == 3
        fuel_types = {p.fuel_type for p in prices}
        assert fuel_types == {"benzin", "motorin", "lpg"}

    def test_average_calculation(self) -> None:
        """Ortalama fiyatlar doğru hesaplanır."""
        records = parse_epdk_xml(MOCK_XML_VALID)
        prices = _records_to_pump_prices(records, il_kodu="34")

        benzin = next(p for p in prices if p.fuel_type == "benzin")
        # (43.72 + 43.50 + 43.80) / 3 = 43.673... → 43.67
        assert benzin.pump_price_tl_lt == Decimal("43.67")

        motorin = next(p for p in prices if p.fuel_type == "motorin")
        # (41.85 + 41.70 + 41.90) / 3 = 41.816... → 41.82
        assert motorin.pump_price_tl_lt == Decimal("41.82")

        lpg = next(p for p in prices if p.fuel_type == "lpg")
        # (18.50 + 18.30 + 18.60) / 3 = 18.466... → 18.47
        assert lpg.pump_price_tl_lt == Decimal("18.47")

    def test_dagitici_count(self) -> None:
        """Dağıtıcı sayısı doğru kaydedilir."""
        records = parse_epdk_xml(MOCK_XML_VALID)
        prices = _records_to_pump_prices(records, il_kodu="34")

        for p in prices:
            assert p.dagitici_sayisi == 3

    def test_partial_fuel_types(self) -> None:
        """LPG eksik ise sadece 2 yakıt tipi üretilir."""
        records = parse_epdk_xml(MOCK_XML_PARTIAL)
        prices = _records_to_pump_prices(records, il_kodu="06")

        assert len(prices) == 2
        fuel_types = {p.fuel_type for p in prices}
        assert fuel_types == {"benzin", "motorin"}

    def test_source_field(self) -> None:
        """Source alanı 'epdk_xml' olarak set edilir."""
        records = parse_epdk_xml(MOCK_XML_VALID)
        prices = _records_to_pump_prices(records, il_kodu="34")

        for p in prices:
            assert p.source == "epdk_xml"

    def test_trade_date(self) -> None:
        """trade_date ilk kaydın tarihinden alınır."""
        records = parse_epdk_xml(MOCK_XML_VALID)
        prices = _records_to_pump_prices(records, il_kodu="34")

        for p in prices:
            assert p.trade_date == date(2026, 2, 15)

    def test_empty_records(self) -> None:
        """Boş kayıt listesinde boş liste döner."""
        prices = _records_to_pump_prices([], il_kodu="34")
        assert prices == []


# ── 3. Validasyon Testleri ───────────────────────────────────────────────────


class TestValidatePriceRange:
    """Fiyat aralığı doğrulama testleri."""

    def test_valid_price(self) -> None:
        """Geçerli fiyat doğrulamayı geçer."""
        result = validate_price_range(Decimal("43.72"), "benzin", "34")
        assert result.passed is True

    def test_min_boundary(self) -> None:
        """Minimum sınır (0.50) geçerli."""
        result = validate_price_range(Decimal("0.50"), "benzin", "34")
        assert result.passed is True

    def test_max_boundary(self) -> None:
        """Maksimum sınır (100.00) geçerli."""
        result = validate_price_range(Decimal("100.00"), "benzin", "34")
        assert result.passed is True

    def test_below_min(self) -> None:
        """Minimum altı fiyat reddedilir."""
        result = validate_price_range(Decimal("0.10"), "benzin", "34")
        assert result.passed is False
        assert result.severity == ValidationSeverity.ERROR

    def test_above_max(self) -> None:
        """Maksimum üstü fiyat reddedilir."""
        result = validate_price_range(Decimal("150.00"), "benzin", "34")
        assert result.passed is False
        assert result.severity == ValidationSeverity.ERROR

    def test_zero_price(self) -> None:
        """Sıfır fiyat reddedilir."""
        result = validate_price_range(Decimal("0.00"), "benzin", "34")
        assert result.passed is False

    def test_negative_price(self) -> None:
        """Negatif fiyat reddedilir."""
        result = validate_price_range(Decimal("-5.00"), "benzin", "34")
        assert result.passed is False


class TestValidateDailyChange:
    """Günlük değişim doğrulama testleri."""

    def test_small_change(self) -> None:
        """Küçük değişim (%5) doğrulamayı geçer."""
        result = validate_daily_change(
            Decimal("43.72"), Decimal("42.00"), "benzin", "34"
        )
        assert result.passed is True

    def test_exact_threshold(self) -> None:
        """Tam %20 sınırda geçer."""
        result = validate_daily_change(
            Decimal("48.00"), Decimal("40.00"), "benzin", "34"
        )
        assert result.passed is True

    def test_exceeds_threshold(self) -> None:
        """% 25 değişim uyarı verir."""
        result = validate_daily_change(
            Decimal("50.00"), Decimal("40.00"), "benzin", "34"
        )
        assert result.passed is False
        assert result.severity == ValidationSeverity.WARNING

    def test_decrease_exceeds(self) -> None:
        """Düşüş yönünde de %20+ uyarı verir."""
        result = validate_daily_change(
            Decimal("30.00"), Decimal("40.00"), "benzin", "34"
        )
        assert result.passed is False
        assert result.severity == ValidationSeverity.WARNING

    def test_zero_previous(self) -> None:
        """Önceki gün 0 ise karşılaştırma yapılmaz."""
        result = validate_daily_change(
            Decimal("43.72"), Decimal("0"), "benzin", "34"
        )
        assert result.passed is True

    def test_no_change(self) -> None:
        """Değişiklik yoksa sorun yok."""
        result = validate_daily_change(
            Decimal("43.72"), Decimal("43.72"), "benzin", "34"
        )
        assert result.passed is True


class TestValidateDistributorDeviation:
    """Dağıtıcılar arası sapma doğrulama testleri."""

    def test_low_deviation(self) -> None:
        """Düşük sapma doğrulamayı geçer."""
        prices = [Decimal("43.50"), Decimal("43.72"), Decimal("43.60")]
        result = validate_distributor_deviation(prices, "benzin", "34")
        assert result.passed is True

    def test_high_deviation(self) -> None:
        """Yüksek sapma (std > 2.0) uyarı verir."""
        prices = [Decimal("35.00"), Decimal("43.72"), Decimal("50.00")]
        result = validate_distributor_deviation(prices, "benzin", "34")
        assert result.passed is False
        assert result.severity == ValidationSeverity.WARNING

    def test_single_distributor(self) -> None:
        """Tek dağıtıcıda sapma kontrolü uygulanmaz."""
        prices = [Decimal("43.72")]
        result = validate_distributor_deviation(prices, "benzin", "34")
        assert result.passed is True

    def test_identical_prices(self) -> None:
        """Aynı fiyatlarda sapma 0."""
        prices = [Decimal("43.72"), Decimal("43.72"), Decimal("43.72")]
        result = validate_distributor_deviation(prices, "benzin", "34")
        assert result.passed is True


class TestValidatePumpPricesReport:
    """Toplu doğrulama raporu testleri."""

    def test_all_valid(self) -> None:
        """Tüm fiyatlar geçerli ise rapor valid."""
        prices = [Decimal("43.50"), Decimal("43.72"), Decimal("43.60")]
        report = validate_pump_prices(prices, "benzin", "34")
        assert report.is_valid is True

    def test_with_invalid_price(self) -> None:
        """Geçersiz fiyat varsa rapor invalid."""
        prices = [Decimal("43.50"), Decimal("200.00"), Decimal("43.60")]
        report = validate_pump_prices(prices, "benzin", "34")
        assert report.is_valid is False
        assert len(report.errors) >= 1

    def test_with_previous_day_change(self) -> None:
        """Önceki gün verisi ile günlük değişim kontrolü çalışır."""
        prices = [Decimal("43.50"), Decimal("43.72"), Decimal("43.60")]
        report = validate_pump_prices(
            prices, "benzin", "34", previous_average=Decimal("42.00")
        )
        assert report.is_valid is True

    def test_high_deviation_produces_warning(self) -> None:
        """Yüksek sapma uyarı üretir ama rapor hala valid olabilir."""
        prices = [Decimal("35.00"), Decimal("43.72"), Decimal("50.00")]
        report = validate_pump_prices(prices, "benzin", "34")
        assert report.has_warnings is True
        # Warning seviyesi valid sayılır (hata değil)
        # Ama aralık dışı fiyat yoksa overall valid
        assert report.is_valid is True


# ── 4. Entegrasyon / Uç Durum Testleri ──────────────────────────────────────


class TestEdgeCases:
    """Uç durum testleri."""

    def test_xml_with_extra_whitespace(self) -> None:
        """Fazladan boşluk içeren XML doğru parse edilir."""
        xml = """\
<?xml version="1.0" encoding="utf-8"?>
<NewDataSet>
  <Table>
    <IL_KODU>  34  </IL_KODU>
    <IL_ADI>  İSTANBUL  </IL_ADI>
    <DAGITICI>  shell  </DAGITICI>
    <BENZIN>  43,72  </BENZIN>
    <MOTORIN>  41,85  </MOTORIN>
    <LPG>  18,50  </LPG>
    <TARIH>15.02.2026</TARIH>
  </Table>
</NewDataSet>
"""
        records = parse_epdk_xml(xml)
        assert len(records) == 1
        assert records[0].il_kodu == "34"
        assert records[0].dagitici == "SHELL"  # normalized
        assert records[0].benzin_fiyat == Decimal("43.72")

    def test_pump_price_data_model(self) -> None:
        """PumpPriceData Pydantic modeli doğru çalışır."""
        ppd = PumpPriceData(
            trade_date=date(2026, 2, 15),
            fuel_type="benzin",
            pump_price_tl_lt=Decimal("43.72"),
            il_kodu="34",
            dagitici_sayisi=5,
        )
        assert ppd.source == "petrol_ofisi"
        assert ppd.pump_price_tl_lt == Decimal("43.72")

    def test_epdk_record_model(self) -> None:
        """EPDKRecord Pydantic modeli doğru çalışır."""
        rec = EPDKRecord(
            il_kodu="34",
            il_adi="İSTANBUL",
            dagitici="SHELL",
            benzin_fiyat=Decimal("43.72"),
            motorin_fiyat=None,
            lpg_fiyat=None,
            tarih=date(2026, 2, 15),
        )
        assert rec.benzin_fiyat == Decimal("43.72")
        assert rec.motorin_fiyat is None
