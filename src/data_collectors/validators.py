"""
Veri doğrulama ve boşluk doldurma modülü.

- Range check: Brent, USD/TRY ve CIF Med fiyatları için geçerli aralık kontrolü
- Günlük değişim kontrolü: ani sıçramaları tespit eder
- Gap-fill: hafta sonu ve tatil günleri için interpolasyon (önceki iş günü değeri)
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from src.data_collectors.brent_collector import BrentData
from src.data_collectors.fx_collector import FXData

logger = logging.getLogger(__name__)

# --- Geçerli Aralık Sabitleri ---
BRENT_RANGE = (Decimal("20"), Decimal("200"))        # USD/varil
FX_RANGE = (Decimal("1"), Decimal("100"))             # USD/TRY
CIF_MED_RANGE = (Decimal("200"), Decimal("1200"))     # USD/ton

# --- Günlük Değişim Limitleri ---
BRENT_DAILY_CHANGE_LIMIT = Decimal("0.15")   # ±%15
FX_DAILY_CHANGE_LIMIT = Decimal("0.10")      # ±%10


# --- Range Check Fonksiyonları ---


def validate_brent(data: BrentData) -> tuple[bool, list[str]]:
    """
    Brent fiyat verisini doğrular.

    Kontroller:
    1. Brent fiyatı [20, 200] USD/varil aralığında mı?
    2. CIF Med tahmini [200, 1200] USD/ton aralığında mı?

    Args:
        data: Doğrulanacak BrentData

    Returns:
        (geçerli_mi, hata_mesajları)
    """
    errors: list[str] = []

    if data.brent_usd_bbl < BRENT_RANGE[0] or data.brent_usd_bbl > BRENT_RANGE[1]:
        errors.append(
            f"Brent fiyatı aralık dışı: {data.brent_usd_bbl} USD/bbl "
            f"(beklenen: {BRENT_RANGE[0]}-{BRENT_RANGE[1]})"
        )

    if (
        data.cif_med_estimate_usd_ton < CIF_MED_RANGE[0]
        or data.cif_med_estimate_usd_ton > CIF_MED_RANGE[1]
    ):
        errors.append(
            f"CIF Med tahmini aralık dışı: {data.cif_med_estimate_usd_ton} USD/ton "
            f"(beklenen: {CIF_MED_RANGE[0]}-{CIF_MED_RANGE[1]})"
        )

    if errors:
        logger.warning("Brent doğrulama hatası (%s): %s", data.trade_date, "; ".join(errors))

    return len(errors) == 0, errors


def validate_fx(data: FXData) -> tuple[bool, list[str]]:
    """
    USD/TRY döviz kuru verisini doğrular.

    Kontrol: USD/TRY kuru [1, 100] aralığında mı?

    Args:
        data: Doğrulanacak FXData

    Returns:
        (geçerli_mi, hata_mesajları)
    """
    errors: list[str] = []

    if data.usd_try_rate < FX_RANGE[0] or data.usd_try_rate > FX_RANGE[1]:
        errors.append(
            f"USD/TRY kuru aralık dışı: {data.usd_try_rate} "
            f"(beklenen: {FX_RANGE[0]}-{FX_RANGE[1]})"
        )

    if errors:
        logger.warning("FX doğrulama hatası (%s): %s", data.trade_date, "; ".join(errors))

    return len(errors) == 0, errors


# --- Günlük Değişim Kontrolü ---


def check_daily_change_brent(
    current: BrentData, previous: BrentData
) -> tuple[bool, str | None]:
    """
    Brent fiyatındaki günlük değişimi kontrol eder.

    Eşik: ±%15'ten fazla değişim anormal kabul edilir.

    Args:
        current: Bugünkü veri
        previous: Önceki günün verisi

    Returns:
        (normal_mi, uyarı_mesajı)
    """
    if previous.brent_usd_bbl == 0:
        return True, None

    change = abs(current.brent_usd_bbl - previous.brent_usd_bbl) / previous.brent_usd_bbl

    if change > BRENT_DAILY_CHANGE_LIMIT:
        pct = change * 100
        msg = (
            f"Brent günlük değişim uyarısı: %{pct:.1f} "
            f"({previous.brent_usd_bbl} → {current.brent_usd_bbl})"
        )
        logger.warning(msg)
        return False, msg

    return True, None


def check_daily_change_fx(
    current: FXData, previous: FXData
) -> tuple[bool, str | None]:
    """
    USD/TRY kurundaki günlük değişimi kontrol eder.

    Eşik: ±%10'dan fazla değişim anormal kabul edilir.

    Args:
        current: Bugünkü veri
        previous: Önceki günün verisi

    Returns:
        (normal_mi, uyarı_mesajı)
    """
    if previous.usd_try_rate == 0:
        return True, None

    change = abs(current.usd_try_rate - previous.usd_try_rate) / previous.usd_try_rate

    if change > FX_DAILY_CHANGE_LIMIT:
        pct = change * 100
        msg = (
            f"USD/TRY günlük değişim uyarısı: %{pct:.1f} "
            f"({previous.usd_try_rate} → {current.usd_try_rate})"
        )
        logger.warning(msg)
        return False, msg

    return True, None


# --- Gap-Fill (Boşluk Doldurma) ---


def fill_weekend_gaps_brent(
    data_list: list[BrentData],
    start: date,
    end: date,
) -> list[BrentData]:
    """
    Hafta sonu ve tatil günleri için Brent verisi boşluklarını doldurur.

    Strateji: Önceki iş gününün değerini kullan, data_quality_flag='interpolated' ile işaretle.

    Args:
        data_list: Mevcut BrentData listesi (sıralı)
        start: Başlangıç tarihi
        end: Bitiş tarihi

    Returns:
        Boşlukları doldurulmuş BrentData listesi
    """
    # Mevcut tarihleri bir dict'e çevir
    existing: dict[date, BrentData] = {d.trade_date: d for d in data_list}
    filled: list[BrentData] = []
    last_known: BrentData | None = None

    current = start
    while current <= end:
        if current in existing:
            last_known = existing[current]
            filled.append(last_known)
        elif last_known is not None:
            # Boşluk: önceki değeri kopyala, kaynak olarak 'interpolated' işaretle
            interpolated = BrentData(
                trade_date=current,
                brent_usd_bbl=last_known.brent_usd_bbl,
                cif_med_estimate_usd_ton=last_known.cif_med_estimate_usd_ton,
                source=f"{last_known.source}_interpolated",
                raw_data={"interpolated_from": last_known.trade_date.isoformat()},
            )
            filled.append(interpolated)
            logger.debug(
                "Brent boşluk dolduruldu: %s → %s değeri ile (%s)",
                current,
                last_known.trade_date,
                last_known.brent_usd_bbl,
            )
        else:
            logger.warning("Brent boşluk doldurulamadı: %s (önceki veri yok)", current)

        current += timedelta(days=1)

    return filled


def fill_weekend_gaps_fx(
    data_list: list[FXData],
    start: date,
    end: date,
) -> list[FXData]:
    """
    Hafta sonu ve tatil günleri için FX verisi boşluklarını doldurur.

    Strateji: Önceki iş gününün değerini kullan, source'a '_interpolated' ekle.

    Args:
        data_list: Mevcut FXData listesi (sıralı)
        start: Başlangıç tarihi
        end: Bitiş tarihi

    Returns:
        Boşlukları doldurulmuş FXData listesi
    """
    existing: dict[date, FXData] = {d.trade_date: d for d in data_list}
    filled: list[FXData] = []
    last_known: FXData | None = None

    current = start
    while current <= end:
        if current in existing:
            last_known = existing[current]
            filled.append(last_known)
        elif last_known is not None:
            interpolated = FXData(
                trade_date=current,
                usd_try_rate=last_known.usd_try_rate,
                source=f"{last_known.source}_interpolated",
                raw_data={"interpolated_from": last_known.trade_date.isoformat()},
            )
            filled.append(interpolated)
            logger.debug(
                "FX boşluk dolduruldu: %s → %s değeri ile (%s)",
                current,
                last_known.trade_date,
                last_known.usd_try_rate,
            )
        else:
            logger.warning("FX boşluk doldurulamadı: %s (önceki veri yok)", current)

        current += timedelta(days=1)

    return filled


def detect_gaps(
    existing_dates: set[date],
    start: date,
    end: date,
) -> list[date]:
    """
    Verilen tarih aralığında eksik günleri tespit eder.

    Args:
        existing_dates: Mevcut tarihler kümesi
        start: Başlangıç tarihi
        end: Bitiş tarihi

    Returns:
        Eksik tarihlerin listesi
    """
    gaps: list[date] = []
    current = start
    while current <= end:
        if current not in existing_dates:
            gaps.append(current)
        current += timedelta(days=1)

    if gaps:
        logger.info(
            "%d eksik gün tespit edildi (%s — %s aralığında)",
            len(gaps),
            start,
            end,
        )

    return gaps
