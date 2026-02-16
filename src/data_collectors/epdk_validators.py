"""
EPDK Pompa Fiyatı Veri Doğrulama Modülü

Çekilen fiyat verilerinin mantıksal tutarlılığını kontrol eder:
- Range check: Pompa fiyatı [0.50, 100.00] TL/lt aralığında mı?
- Günlük değişim: Bir önceki güne göre ±20% sınırı
- Dağıtıcılar arası sapma: Standart sapma > 2.0 ise uyarı
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

logger = logging.getLogger(__name__)

# ── Sabitler ──────────────────────────────────────────────────────────────────

MIN_PUMP_PRICE: Decimal = Decimal("0.50")
MAX_PUMP_PRICE: Decimal = Decimal("100.00")
MAX_DAILY_CHANGE_RATIO: Decimal = Decimal("0.20")  # ±20%
MAX_DISTRIBUTOR_STD_DEV: Decimal = Decimal("2.00")


# ── Doğrulama Sonuç Tipleri ──────────────────────────────────────────────────


class ValidationSeverity(str, Enum):
    """Doğrulama sonucu ciddiyet derecesi."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class ValidationResult:
    """Tek bir doğrulama kontrolünün sonucu."""

    passed: bool
    check_name: str
    severity: ValidationSeverity
    message: str
    details: dict | None = None


@dataclass
class ValidationReport:
    """Tüm doğrulama sonuçlarını içeren rapor."""

    results: list[ValidationResult] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Tüm kontroller geçti mi? (ERROR/CRITICAL yok)"""
        return all(
            r.passed or r.severity in (ValidationSeverity.INFO, ValidationSeverity.WARNING)
            for r in self.results
        )

    @property
    def has_warnings(self) -> bool:
        """Uyarı var mı?"""
        return any(
            r.severity == ValidationSeverity.WARNING and not r.passed
            for r in self.results
        )

    @property
    def errors(self) -> list[ValidationResult]:
        """Sadece ERROR ve CRITICAL sonuçları."""
        return [
            r
            for r in self.results
            if not r.passed and r.severity in (ValidationSeverity.ERROR, ValidationSeverity.CRITICAL)
        ]

    @property
    def warnings(self) -> list[ValidationResult]:
        """Sadece WARNING sonuçları."""
        return [
            r for r in self.results if not r.passed and r.severity == ValidationSeverity.WARNING
        ]

    def add(self, result: ValidationResult) -> None:
        """Rapora yeni sonuç ekler."""
        self.results.append(result)
        if not result.passed:
            log_fn = {
                ValidationSeverity.INFO: logger.info,
                ValidationSeverity.WARNING: logger.warning,
                ValidationSeverity.ERROR: logger.error,
                ValidationSeverity.CRITICAL: logger.critical,
            }.get(result.severity, logger.warning)
            log_fn("[%s] %s: %s", result.check_name, result.severity.value, result.message)


# ── Doğrulama Fonksiyonları ──────────────────────────────────────────────────


def validate_price_range(
    price: Decimal,
    fuel_type: str,
    il_kodu: str | None = None,
) -> ValidationResult:
    """
    Pompa fiyatının mantıklı aralıkta olup olmadığını kontrol eder.

    Geçerli aralık: [0.50, 100.00] TL/lt

    Args:
        price: Kontrol edilecek fiyat (Decimal).
        fuel_type: Yakıt tipi (benzin, motorin, lpg).
        il_kodu: İl kodu (opsiyonel, log için).

    Returns:
        ValidationResult.
    """
    passed = MIN_PUMP_PRICE <= price <= MAX_PUMP_PRICE

    if passed:
        return ValidationResult(
            passed=True,
            check_name="price_range",
            severity=ValidationSeverity.INFO,
            message=f"{fuel_type} fiyatı ({price} TL/lt) geçerli aralıkta.",
            details={"price": str(price), "fuel_type": fuel_type, "il_kodu": il_kodu},
        )

    return ValidationResult(
        passed=False,
        check_name="price_range",
        severity=ValidationSeverity.ERROR,
        message=(
            f"{fuel_type} fiyatı ({price} TL/lt) geçerli aralık dışında "
            f"[{MIN_PUMP_PRICE}, {MAX_PUMP_PRICE}]. İl: {il_kodu}"
        ),
        details={
            "price": str(price),
            "fuel_type": fuel_type,
            "il_kodu": il_kodu,
            "min": str(MIN_PUMP_PRICE),
            "max": str(MAX_PUMP_PRICE),
        },
    )


def validate_daily_change(
    current_price: Decimal,
    previous_price: Decimal,
    fuel_type: str,
    il_kodu: str | None = None,
) -> ValidationResult:
    """
    Günlük fiyat değişiminin ±20% sınırını aşıp aşmadığını kontrol eder.

    Args:
        current_price: Bugünkü fiyat.
        previous_price: Bir önceki günün fiyatı.
        fuel_type: Yakıt tipi.
        il_kodu: İl kodu (opsiyonel).

    Returns:
        ValidationResult.
    """
    if previous_price == Decimal("0"):
        return ValidationResult(
            passed=True,
            check_name="daily_change",
            severity=ValidationSeverity.INFO,
            message=f"{fuel_type}: Önceki gün fiyatı 0, karşılaştırma yapılamıyor.",
            details={"fuel_type": fuel_type, "il_kodu": il_kodu},
        )

    change_ratio = abs(current_price - previous_price) / previous_price

    passed = change_ratio <= MAX_DAILY_CHANGE_RATIO
    change_pct = (change_ratio * Decimal("100")).quantize(Decimal("0.01"))

    if passed:
        return ValidationResult(
            passed=True,
            check_name="daily_change",
            severity=ValidationSeverity.INFO,
            message=f"{fuel_type}: Günlük değişim %{change_pct} — kabul edilebilir.",
            details={
                "fuel_type": fuel_type,
                "il_kodu": il_kodu,
                "current": str(current_price),
                "previous": str(previous_price),
                "change_pct": str(change_pct),
            },
        )

    return ValidationResult(
        passed=False,
        check_name="daily_change",
        severity=ValidationSeverity.WARNING,
        message=(
            f"{fuel_type}: Günlük değişim %{change_pct} — "
            f"±{MAX_DAILY_CHANGE_RATIO * Decimal('100')}% sınırını aşıyor! "
            f"({previous_price} → {current_price} TL/lt). İl: {il_kodu}"
        ),
        details={
            "fuel_type": fuel_type,
            "il_kodu": il_kodu,
            "current": str(current_price),
            "previous": str(previous_price),
            "change_pct": str(change_pct),
            "threshold_pct": str(MAX_DAILY_CHANGE_RATIO * Decimal("100")),
        },
    )


def validate_distributor_deviation(
    prices: list[Decimal],
    fuel_type: str,
    il_kodu: str | None = None,
) -> ValidationResult:
    """
    Dağıtıcılar arasındaki fiyat sapmasını kontrol eder.

    Standart sapma > 2.0 TL ise uyarı verir (manipülasyon veya veri hatası olabilir).

    Args:
        prices: Aynı il ve yakıt tipindeki dağıtıcı fiyatları.
        fuel_type: Yakıt tipi.
        il_kodu: İl kodu (opsiyonel).

    Returns:
        ValidationResult.
    """
    n = len(prices)

    if n < 2:
        return ValidationResult(
            passed=True,
            check_name="distributor_deviation",
            severity=ValidationSeverity.INFO,
            message=f"{fuel_type}: Tek dağıtıcı — sapma kontrolü uygulanamıyor.",
            details={"fuel_type": fuel_type, "il_kodu": il_kodu, "count": n},
        )

    # Ortalama
    mean = sum(prices) / n

    # Standart sapma (popülasyon std dev)
    variance = sum((p - mean) ** 2 for p in prices) / n
    # Decimal'de sqrt yok, Newton's method kullan
    std_dev = _decimal_sqrt(variance)

    passed = std_dev <= MAX_DISTRIBUTOR_STD_DEV
    std_dev_rounded = std_dev.quantize(Decimal("0.01"))

    if passed:
        return ValidationResult(
            passed=True,
            check_name="distributor_deviation",
            severity=ValidationSeverity.INFO,
            message=(
                f"{fuel_type}: Dağıtıcı sapması {std_dev_rounded} TL — "
                f"eşik ({MAX_DISTRIBUTOR_STD_DEV} TL) altında."
            ),
            details={
                "fuel_type": fuel_type,
                "il_kodu": il_kodu,
                "std_dev": str(std_dev_rounded),
                "mean": str(mean.quantize(Decimal("0.01"))),
                "count": n,
            },
        )

    return ValidationResult(
        passed=False,
        check_name="distributor_deviation",
        severity=ValidationSeverity.WARNING,
        message=(
            f"{fuel_type}: Dağıtıcılar arası sapma YÜKSEK! "
            f"std={std_dev_rounded} TL > eşik={MAX_DISTRIBUTOR_STD_DEV} TL. "
            f"İl: {il_kodu}, Dağıtıcı sayısı: {n}"
        ),
        details={
            "fuel_type": fuel_type,
            "il_kodu": il_kodu,
            "std_dev": str(std_dev_rounded),
            "threshold": str(MAX_DISTRIBUTOR_STD_DEV),
            "mean": str(mean.quantize(Decimal("0.01"))),
            "count": n,
            "prices": [str(p) for p in prices],
        },
    )


def validate_pump_prices(
    prices: list[Decimal],
    fuel_type: str,
    il_kodu: str | None = None,
    previous_average: Decimal | None = None,
) -> ValidationReport:
    """
    Belirli bir yakıt tipi ve il için tüm doğrulama kontrollerini çalıştırır.

    Args:
        prices: Dağıtıcı bazlı fiyat listesi.
        fuel_type: Yakıt tipi.
        il_kodu: İl kodu.
        previous_average: Bir önceki günün ortalama fiyatı (opsiyonel).

    Returns:
        ValidationReport — tüm kontrol sonuçlarını içerir.
    """
    report = ValidationReport()

    # 1. Her fiyat için aralık kontrolü
    for price in prices:
        report.add(validate_price_range(price, fuel_type, il_kodu))

    # 2. Dağıtıcılar arası sapma kontrolü
    report.add(validate_distributor_deviation(prices, fuel_type, il_kodu))

    # 3. Günlük değişim kontrolü (önceki gün verisi varsa)
    if previous_average is not None and prices:
        current_avg = sum(prices) / len(prices)
        report.add(validate_daily_change(current_avg, previous_average, fuel_type, il_kodu))

    return report


# ── Yardımcı Fonksiyonlar ────────────────────────────────────────────────────


def _decimal_sqrt(value: Decimal, precision: Decimal = Decimal("0.0001")) -> Decimal:
    """
    Decimal karekök hesaplama (Newton-Raphson yöntemi).

    Args:
        value: Karekökü alınacak değer.
        precision: Yakınsama hassasiyeti.

    Returns:
        Decimal karekök.
    """
    if value < Decimal("0"):
        raise ValueError("Negatif sayının karekökü alınamaz.")
    if value == Decimal("0"):
        return Decimal("0")

    # Başlangıç tahmini
    guess = value / Decimal("2")
    prev_guess = Decimal("0")

    while abs(guess - prev_guess) > precision:
        prev_guess = guess
        guess = (guess + value / guess) / Decimal("2")

    return guess.quantize(Decimal("0.01"))
