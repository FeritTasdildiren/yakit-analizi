"""
Politik Gecikme State Machine (Katman 3).

MBE eşik değerini aştığında başlayan ve fiyat değişikliği gelene
kadar gecikmeyi takip eden durum makinesi.

Durumlar:
    IDLE → WATCHING (MBE ≥ θ)
    WATCHING → CLOSED (zam geldi)
    WATCHING → IDLE (MBE < θ sürekli 5 gün → ABSORBEDİLDİ)
    WATCHING → PARTIAL_CLOSE (kademeli zam)

5 gün kuralı: Eşik altında 5 gün kalırsa ABSORBE_EDİLDİ → IDLE
Kısa düşüşler (< 5 gün): Aynı watching devam, ilk cross_date korunur.

Tüm hesaplamalar Decimal ile yapılır — float YASAK.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# --- Sabitler ---
BELOW_THRESHOLD_RESET = 5  # Eşik altında bu kadar gün kalınca ABSORBE_EDİLDİ


class DelayState(str, Enum):
    """Politik gecikme takip durumları."""

    IDLE = "idle"
    WATCHING = "watching"
    CLOSED = "closed"
    ABSORBED = "absorbed"
    PARTIAL_CLOSE = "partial_close"


@dataclass
class DelayTracker:
    """
    Politik gecikme state machine durumu.

    Bir yakıt tipi için tek bir tracker instance'ı tutulur.
    Her gün update() çağrılarak durum güncellenir.
    """

    state: DelayState = DelayState.IDLE
    threshold_cross_date: Optional[str] = None  # ISO format date string
    current_delay_days: int = 0
    mbe_at_cross: Decimal = Decimal("0")
    mbe_max: Decimal = Decimal("0")
    regime: Optional[str] = None
    z_score: Decimal = Decimal("0")
    below_threshold_streak: int = 0

    def to_dict(self) -> dict:
        """State'i serileştir."""
        return {
            "state": self.state.value,
            "threshold_cross_date": self.threshold_cross_date,
            "current_delay_days": self.current_delay_days,
            "mbe_at_cross": str(self.mbe_at_cross),
            "mbe_max": str(self.mbe_max),
            "regime": self.regime,
            "z_score": str(self.z_score),
            "below_threshold_streak": self.below_threshold_streak,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DelayTracker":
        """Dict'ten state oluştur."""
        return cls(
            state=DelayState(data.get("state", "idle")),
            threshold_cross_date=data.get("threshold_cross_date"),
            current_delay_days=data.get("current_delay_days", 0),
            mbe_at_cross=Decimal(str(data.get("mbe_at_cross", "0"))),
            mbe_max=Decimal(str(data.get("mbe_max", "0"))),
            regime=data.get("regime"),
            z_score=Decimal(str(data.get("z_score", "0"))),
            below_threshold_streak=data.get("below_threshold_streak", 0),
        )


@dataclass
class DelayTransition:
    """Durum geçişi sonucu."""

    previous_state: DelayState
    new_state: DelayState
    reason: str
    tracker: DelayTracker
    should_create_record: bool = False
    should_close_record: bool = False
    close_status: Optional[str] = None


def update_tracker(
    tracker: DelayTracker,
    current_mbe: Decimal,
    threshold: Decimal,
    current_date: str,
    price_changed: bool = False,
    partial_change: bool = False,
    regime_type: Optional[str] = None,
    historical_mean_delay: Optional[Decimal] = None,
    historical_std_delay: Optional[Decimal] = None,
) -> DelayTransition:
    """
    Tracker'ı güncel MBE değeri ve fiyat değişikliği bilgisiyle günceller.

    Args:
        tracker: Mevcut tracker state'i.
        current_mbe: Bugünkü MBE değeri.
        threshold: Eşik değeri (θ).
        current_date: Bugünün tarihi (ISO format).
        price_changed: Bugün zam geldi mi?
        partial_change: Kademeli (kısmi) zam mı?
        regime_type: Aktif rejim tipi (seçim, bayram vb.).
        historical_mean_delay: Tarihsel ortalama gecikme (z-score için).
        historical_std_delay: Tarihsel std sapma (z-score için).

    Returns:
        DelayTransition: Durum geçişi bilgisi.
    """
    previous_state = tracker.state

    if tracker.state == DelayState.IDLE:
        return _handle_idle(
            tracker, current_mbe, threshold, current_date, regime_type
        )

    if tracker.state == DelayState.WATCHING:
        return _handle_watching(
            tracker,
            current_mbe,
            threshold,
            current_date,
            price_changed,
            partial_change,
            regime_type,
            historical_mean_delay,
            historical_std_delay,
        )

    # CLOSED, ABSORBED, PARTIAL_CLOSE — terminal durumlar, yeni cycle başla
    # Bu durumda tracker IDLE'a dönmeli
    tracker.state = DelayState.IDLE
    tracker.below_threshold_streak = 0
    tracker.current_delay_days = 0

    return DelayTransition(
        previous_state=previous_state,
        new_state=DelayState.IDLE,
        reason="Terminal durumdan IDLE'a dönüldü",
        tracker=tracker,
    )


def _handle_idle(
    tracker: DelayTracker,
    current_mbe: Decimal,
    threshold: Decimal,
    current_date: str,
    regime_type: Optional[str],
) -> DelayTransition:
    """IDLE durumunda MBE eşiği kontrolü."""
    if current_mbe >= threshold:
        # Eşik aşıldı → WATCHING'e geç
        tracker.state = DelayState.WATCHING
        tracker.threshold_cross_date = current_date
        tracker.current_delay_days = 0
        tracker.mbe_at_cross = current_mbe
        tracker.mbe_max = current_mbe
        tracker.regime = regime_type
        tracker.below_threshold_streak = 0
        tracker.z_score = Decimal("0")

        logger.info(
            "IDLE → WATCHING: MBE=%s ≥ θ=%s, tarih=%s",
            current_mbe,
            threshold,
            current_date,
        )

        return DelayTransition(
            previous_state=DelayState.IDLE,
            new_state=DelayState.WATCHING,
            reason=f"MBE ({current_mbe}) >= eşik ({threshold})",
            tracker=tracker,
            should_create_record=True,
        )

    # Eşik altında — IDLE devam
    return DelayTransition(
        previous_state=DelayState.IDLE,
        new_state=DelayState.IDLE,
        reason="MBE eşik altında, IDLE devam",
        tracker=tracker,
    )


def _handle_watching(
    tracker: DelayTracker,
    current_mbe: Decimal,
    threshold: Decimal,
    current_date: str,
    price_changed: bool,
    partial_change: bool,
    regime_type: Optional[str],
    historical_mean_delay: Optional[Decimal],
    historical_std_delay: Optional[Decimal],
) -> DelayTransition:
    """WATCHING durumunda günlük güncelleme."""
    tracker.current_delay_days += 1

    # MBE max güncelle
    if current_mbe > tracker.mbe_max:
        tracker.mbe_max = current_mbe

    # Rejim güncelle
    if regime_type is not None:
        tracker.regime = regime_type

    # Z-score hesapla
    if historical_mean_delay is not None and historical_std_delay is not None:
        tracker.z_score = calculate_z_score(
            Decimal(str(tracker.current_delay_days)),
            historical_mean_delay,
            historical_std_delay,
        )

    # --- Fiyat değişikliği kontrolü ---
    if price_changed and not partial_change:
        # Tam zam → CLOSED
        tracker.state = DelayState.CLOSED

        logger.info(
            "WATCHING → CLOSED: Zam geldi, gecikme=%d gün",
            tracker.current_delay_days,
        )

        return DelayTransition(
            previous_state=DelayState.WATCHING,
            new_state=DelayState.CLOSED,
            reason=f"Fiyat değişikliği (tam zam), gecikme={tracker.current_delay_days} gün",
            tracker=tracker,
            should_close_record=True,
            close_status="closed",
        )

    if price_changed and partial_change:
        # Kademeli zam → PARTIAL_CLOSE
        tracker.state = DelayState.PARTIAL_CLOSE

        logger.info(
            "WATCHING → PARTIAL_CLOSE: Kademeli zam, gecikme=%d gün",
            tracker.current_delay_days,
        )

        return DelayTransition(
            previous_state=DelayState.WATCHING,
            new_state=DelayState.PARTIAL_CLOSE,
            reason=f"Kademeli fiyat değişikliği, gecikme={tracker.current_delay_days} gün",
            tracker=tracker,
            should_close_record=True,
            close_status="partial_close",
        )

    # --- Eşik altı kontrolü (5 gün kuralı) ---
    if current_mbe < threshold:
        tracker.below_threshold_streak += 1

        if tracker.below_threshold_streak >= BELOW_THRESHOLD_RESET:
            # 5 gün üst üste eşik altında → ABSORBED
            tracker.state = DelayState.ABSORBED

            logger.info(
                "WATCHING → ABSORBED: %d gün eşik altında kaldı",
                BELOW_THRESHOLD_RESET,
            )

            return DelayTransition(
                previous_state=DelayState.WATCHING,
                new_state=DelayState.ABSORBED,
                reason=f"{BELOW_THRESHOLD_RESET} gün eşik altında → absorbe edildi",
                tracker=tracker,
                should_close_record=True,
                close_status="absorbed",
            )

        # Kısa düşüş — aynı watching devam, ilk cross_date korunur
        return DelayTransition(
            previous_state=DelayState.WATCHING,
            new_state=DelayState.WATCHING,
            reason=f"Kısa düşüş (gün {tracker.below_threshold_streak}/{BELOW_THRESHOLD_RESET})",
            tracker=tracker,
        )
    else:
        # Eşik üstüne döndü — streak sıfırla
        tracker.below_threshold_streak = 0

    # WATCHING devam
    return DelayTransition(
        previous_state=DelayState.WATCHING,
        new_state=DelayState.WATCHING,
        reason=f"WATCHING devam, gecikme={tracker.current_delay_days} gün, z={tracker.z_score}",
        tracker=tracker,
    )


def calculate_z_score(
    current_delay: Decimal,
    historical_mean: Decimal,
    historical_std: Decimal,
) -> Decimal:
    """
    Gecikme z-skoru hesaplar.

    z = (current_delay - historical_mean) / historical_std

    Yorumlama:
        z < 1.0  = Normal gecikme
        1.0-2.0  = Dikkat — ortalamanın üstünde
        z ≥ 2.0  = Anormal gecikme — müdahale gerekebilir

    Args:
        current_delay: Mevcut gecikme gün sayısı.
        historical_mean: Tarihsel ortalama gecikme.
        historical_std: Tarihsel standart sapma.

    Returns:
        Z-skoru (Decimal).
    """
    if historical_std == Decimal("0"):
        # Std sapma sıfırsa — tek gözlem veya hep aynı gecikme
        if current_delay > historical_mean:
            return Decimal("3")  # Anormal olarak işaretle
        return Decimal("0")

    z = (current_delay - historical_mean) / historical_std
    return z.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def interpret_z_score(z: Decimal) -> str:
    """
    Z-skorunu yorumlar.

    Args:
        z: Z-skoru değeri.

    Returns:
        Yorum string'i: "normal", "dikkat" veya "anormal".
    """
    if z < Decimal("1.0"):
        return "normal"
    if z < Decimal("2.0"):
        return "dikkat"
    return "anormal"
