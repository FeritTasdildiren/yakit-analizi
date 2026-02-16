"""
Risk Hesaplama Motoru (Katman 3).

Bileşik risk skoru hesaplama servisi. Beş bileşeni ağırlıklı
olarak birleştirerek 0-1 arasında tek bir risk skoru üretir.

Formül:
    risk_score(t) = 0.30 × normalize(MBE)
                  + 0.15 × normalize(FX_volatility)
                  + 0.20 × normalize(political_delay)
                  + 0.20 × normalize(threshold_breach)
                  + 0.15 × normalize(trend_momentum)

Tüm hesaplamalar Decimal ile yapılır — float YASAK.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

logger = logging.getLogger(__name__)

# --- Varsayılan Ağırlık Vektörü ---
DEFAULT_WEIGHTS: dict[str, Decimal] = {
    "mbe": Decimal("0.30"),
    "fx_volatility": Decimal("0.15"),
    "political_delay": Decimal("0.20"),
    "threshold_breach": Decimal("0.20"),
    "trend_momentum": Decimal("0.15"),
}


@dataclass(frozen=True)
class RiskComponents:
    """Risk skoru hesaplaması için girdi bileşenleri."""

    mbe_value: Decimal
    fx_volatility: Decimal
    political_delay: Decimal
    threshold_breach: Decimal
    trend_momentum: Decimal


@dataclass
class RiskResult:
    """Risk skoru hesaplama sonucu."""

    composite_score: Decimal
    mbe_component: Decimal
    fx_volatility_component: Decimal
    political_delay_component: Decimal
    threshold_breach_component: Decimal
    trend_momentum_component: Decimal
    weight_vector: dict[str, str]
    system_mode: str
    triggered_alerts: list[str] = field(default_factory=list)


def normalize_component(
    value: Decimal,
    min_val: Decimal,
    max_val: Decimal,
) -> Decimal:
    """
    Bir değeri [0, 1] aralığına normalize eder.

    min-max normalizasyon: (value - min) / (max - min)
    Sonuç [0, 1] aralığına clamp edilir.

    Args:
        value: Normalize edilecek değer.
        min_val: Minimum referans değeri.
        max_val: Maksimum referans değeri.

    Returns:
        [0, 1] arasında Decimal değer.
    """
    if max_val == min_val:
        # Sıfıra bölme koruması — eğer aralık yoksa değer min'de mi max'da mı bak
        if value <= min_val:
            return Decimal("0")
        return Decimal("1")

    normalized = (value - min_val) / (max_val - min_val)

    # Clamp [0, 1]
    if normalized < Decimal("0"):
        return Decimal("0")
    if normalized > Decimal("1"):
        return Decimal("1")

    return normalized.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def calculate_risk_score(
    components: RiskComponents,
    normalization_ranges: dict[str, tuple[Decimal, Decimal]] | None = None,
    weights: dict[str, Decimal] | None = None,
) -> RiskResult:
    """
    Bileşik risk skoru hesaplar.

    Args:
        components: Ham bileşen değerleri.
        normalization_ranges: Her bileşen için (min, max) aralıkları.
            Belirtilmezse varsayılan aralıklar kullanılır.
        weights: Bileşen ağırlıkları. Belirtilmezse DEFAULT_WEIGHTS.

    Returns:
        RiskResult nesnesi.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS

    # Varsayılan normalizasyon aralıkları
    if normalization_ranges is None:
        normalization_ranges = {
            "mbe": (Decimal("0"), Decimal("1")),
            "fx_volatility": (Decimal("0"), Decimal("0.10")),
            "political_delay": (Decimal("0"), Decimal("60")),
            "threshold_breach": (Decimal("0"), Decimal("1")),
            "trend_momentum": (Decimal("-1"), Decimal("1")),
        }

    # Bileşenleri normalize et
    mbe_norm = normalize_component(
        components.mbe_value,
        *normalization_ranges.get("mbe", (Decimal("0"), Decimal("1"))),
    )
    fx_norm = normalize_component(
        components.fx_volatility,
        *normalization_ranges.get("fx_volatility", (Decimal("0"), Decimal("0.10"))),
    )
    delay_norm = normalize_component(
        components.political_delay,
        *normalization_ranges.get("political_delay", (Decimal("0"), Decimal("60"))),
    )
    breach_norm = normalize_component(
        components.threshold_breach,
        *normalization_ranges.get("threshold_breach", (Decimal("0"), Decimal("1"))),
    )
    trend_norm = normalize_component(
        components.trend_momentum,
        *normalization_ranges.get("trend_momentum", (Decimal("-1"), Decimal("1"))),
    )

    # Ağırlıklı toplam
    composite = (
        weights["mbe"] * mbe_norm
        + weights["fx_volatility"] * fx_norm
        + weights["political_delay"] * delay_norm
        + weights["threshold_breach"] * breach_norm
        + weights["trend_momentum"] * trend_norm
    ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    # Clamp [0, 1]
    if composite < Decimal("0"):
        composite = Decimal("0")
    elif composite > Decimal("1"):
        composite = Decimal("1")

    # Sistem modunu belirle
    system_mode = _determine_system_mode(composite)

    # Ağırlık vektörünü string'e çevir (JSON uyumluluk)
    weight_vector = {k: str(v) for k, v in weights.items()}

    return RiskResult(
        composite_score=composite,
        mbe_component=mbe_norm,
        fx_volatility_component=fx_norm,
        political_delay_component=delay_norm,
        threshold_breach_component=breach_norm,
        trend_momentum_component=trend_norm,
        weight_vector=weight_vector,
        system_mode=system_mode,
    )


def check_threshold_breach(
    composite_score: Decimal,
    threshold_open: Decimal,
    threshold_close: Decimal,
    previous_alert_active: bool = False,
) -> Optional[dict]:
    """
    Risk skoru için eşik ihlali kontrolü yapar (hysteresis destekli).

    Args:
        composite_score: Mevcut bileşik risk skoru.
        threshold_open: Alarm açılış eşiği.
        threshold_close: Alarm kapanış eşiği.
        previous_alert_active: Önceki alarm aktif miydi?

    Returns:
        Eşik aşıldıysa alarm bilgi dict'i, yoksa None.
    """
    if not previous_alert_active:
        # Alarm kapalı — açılış eşiğini kontrol et
        if composite_score >= threshold_open:
            return {
                "action": "open",
                "composite_score": str(composite_score),
                "threshold": str(threshold_open),
            }
    else:
        # Alarm açık — kapanış eşiğini kontrol et
        if composite_score <= threshold_close:
            return {
                "action": "close",
                "composite_score": str(composite_score),
                "threshold": str(threshold_close),
            }
        # Hâlâ eşiğin üstünde — alarm devam eder
        return None

    return None


def apply_regime_modifier(
    threshold_open: Decimal,
    regime_modifier: dict[str, float] | None,
    active_regime_type: str | None,
) -> Decimal:
    """
    Rejim olayına göre eşik değerini modifiye eder.

    Rejim modifier, eşik değerini bir katsayıyla çarpar.
    Örneğin seçim döneminde eşik %85'e düşürülür (0.85 çarpanı).

    Args:
        threshold_open: Orijinal eşik açılış değeri.
        regime_modifier: Rejim tipi → çarpan eşlemesi.
        active_regime_type: Aktif rejim tipi (None ise modifier uygulanmaz).

    Returns:
        Modifiye edilmiş eşik değeri.
    """
    if regime_modifier is None or active_regime_type is None:
        return threshold_open

    modifier = regime_modifier.get(active_regime_type)
    if modifier is None:
        return threshold_open

    modifier_decimal = Decimal(str(modifier))
    modified = (threshold_open * modifier_decimal).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )

    logger.info(
        "Rejim modifier uygulandı: %s × %s = %s (rejim: %s)",
        threshold_open,
        modifier_decimal,
        modified,
        active_regime_type,
    )

    return modified


def _determine_system_mode(composite_score: Decimal) -> str:
    """
    Bileşik skora göre sistem modunu belirler.

    Args:
        composite_score: Bileşik risk skoru (0-1).

    Returns:
        Sistem modu: "normal", "high_alert" veya "crisis".
    """
    if composite_score >= Decimal("0.80"):
        return "crisis"
    if composite_score >= Decimal("0.60"):
        return "high_alert"
    return "normal"
