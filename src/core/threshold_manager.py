"""
Eşik Yöneticisi (Katman 3).

Dinamik eşik parametrelerini yöneten servis. Hysteresis (açılış/kapanış),
cooldown süresi ve varsayılan eşik seed'leme işlevlerini sağlar.

Tüm hesaplamalar Decimal ile yapılır — float YASAK.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, Sequence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThresholdDef:
    """Eşik tanımı (seed verisi için)."""

    metric_name: str
    alert_level: str
    threshold_open: Decimal
    threshold_close: Decimal
    cooldown_hours: int = 24


# --- Varsayılan Eşikler ---
DEFAULT_THRESHOLDS: list[ThresholdDef] = [
    # Risk skoru eşikleri
    ThresholdDef(
        metric_name="risk_score",
        alert_level="warning",
        threshold_open=Decimal("0.60"),
        threshold_close=Decimal("0.45"),
        cooldown_hours=24,
    ),
    ThresholdDef(
        metric_name="risk_score",
        alert_level="critical",
        threshold_open=Decimal("0.70"),
        threshold_close=Decimal("0.55"),
        cooldown_hours=12,
    ),
    # MBE eşikleri
    ThresholdDef(
        metric_name="mbe_value",
        alert_level="warning",
        threshold_open=Decimal("0.50"),
        threshold_close=Decimal("0.35"),
        cooldown_hours=24,
    ),
    ThresholdDef(
        metric_name="mbe_value",
        alert_level="critical",
        threshold_open=Decimal("0.70"),
        threshold_close=Decimal("0.55"),
        cooldown_hours=12,
    ),
]


def check_hysteresis(
    current_value: Decimal,
    threshold_open: Decimal,
    threshold_close: Decimal,
    previous_alert_active: bool,
) -> bool:
    """
    Hysteresis tabanlı eşik kontrolü.

    Alarm kapalıyken: current_value >= threshold_open → alarm AÇ
    Alarm açıkken: current_value <= threshold_close → alarm KAPAT
    Arada → mevcut durumu koru

    Args:
        current_value: Mevcut metrik değeri.
        threshold_open: Alarm açılış eşiği (üst).
        threshold_close: Alarm kapanış eşiği (alt).
        previous_alert_active: Önceki alarm durumu (True = aktif).

    Returns:
        True = alarm aktif olmalı, False = alarm kapalı olmalı.
    """
    if not previous_alert_active:
        # Alarm kapalı — açılış eşiğini kontrol et
        return current_value >= threshold_open
    else:
        # Alarm açık — kapanış eşiğini kontrol et
        # Eşik altına düşmedikçe alarm açık kalır
        return current_value > threshold_close


def check_cooldown(
    last_alert_time: Optional[datetime],
    cooldown_hours: int,
    current_time: Optional[datetime] = None,
) -> bool:
    """
    Cooldown kontrolü — aynı alarmın çok sık tetiklenmesini engeller.

    Args:
        last_alert_time: Son alarm zamanı (None ise cooldown geçmiş sayılır).
        cooldown_hours: Beklenmesi gereken saat sayısı.
        current_time: Şimdiki zaman (test için override).

    Returns:
        True = cooldown geçmiş (alarm gönderilebilir),
        False = cooldown devam ediyor (bekle).
    """
    if last_alert_time is None:
        return True

    if current_time is None:
        current_time = datetime.utcnow()

    cooldown_delta = timedelta(hours=cooldown_hours)
    elapsed = current_time - last_alert_time

    return elapsed >= cooldown_delta


def get_seed_thresholds() -> list[ThresholdDef]:
    """
    Varsayılan eşik tanımlarını döndürür.

    Bu tanımlar ilk kurulumda veritabanına seed olarak yazılır.

    Returns:
        ThresholdDef listesi.
    """
    return DEFAULT_THRESHOLDS


def build_threshold_seed_data(valid_from: Optional[date] = None) -> list[dict]:
    """
    Varsayılan eşikleri veritabanına yazılabilir dict formatında döndürür.

    Args:
        valid_from: Geçerlilik başlangıç tarihi. None ise bugün.

    Returns:
        Dict listesi (her biri ThresholdConfig modeline uygun).
    """
    if valid_from is None:
        valid_from = date.today()

    seed_data = []
    for td in DEFAULT_THRESHOLDS:
        seed_data.append({
            "fuel_type": None,  # Tüm yakıt tipleri için geçerli
            "metric_name": td.metric_name,
            "alert_level": td.alert_level,
            "threshold_open": td.threshold_open,
            "threshold_close": td.threshold_close,
            "cooldown_hours": td.cooldown_hours,
            "regime_modifier": None,
            "version": 1,
            "valid_from": valid_from,
            "valid_to": None,
        })

    return seed_data


def apply_regime_to_thresholds(
    thresholds: Sequence[dict],
    regime_modifier: dict[str, float],
    active_regime_type: str,
) -> list[dict]:
    """
    Rejim modifier'ı aktif eşiklere uygular.

    Orijinal eşikleri değiştirmez, modifiye edilmiş kopyalar döndürür.

    Args:
        thresholds: Mevcut eşik dict'leri.
        regime_modifier: Rejim tipi → çarpan eşlemesi.
        active_regime_type: Aktif rejim tipi.

    Returns:
        Modifiye edilmiş eşik dict'leri.
    """
    modifier = regime_modifier.get(active_regime_type)
    if modifier is None:
        return list(thresholds)

    modifier_decimal = Decimal(str(modifier))
    modified = []

    for t in thresholds:
        t_copy = dict(t)
        t_copy["threshold_open"] = Decimal(str(t["threshold_open"])) * modifier_decimal
        t_copy["threshold_close"] = Decimal(str(t["threshold_close"])) * modifier_decimal
        modified.append(t_copy)

    logger.info(
        "Rejim modifier uygulandı: tip=%s, çarpan=%s, eşik sayısı=%d",
        active_regime_type,
        modifier_decimal,
        len(modified),
    )

    return modified
