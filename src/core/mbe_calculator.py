"""
MBE (Maliyet Baz Etkisi) Hesaplama Motoru.

Delta bazli MBE formulu:
    MBE_t = SMA_w[(CIF_i * FX_i) / rho] - SMA_w[(CIF_j * FX_j) / rho]
    burada i = {t-w+1,...,t} (bugun), j = {t_last-w+1,...,t_last} (son zam gunu)

Rejim bazli SMA pencere genislikleri:
    - Rejim 0 (Normal): w=5, M_total=1.20 TRY/L
    - Rejim 1 (Secim): w=7, M_total=1.00 TRY/L
    - Rejim 2 (Kur Soku): w=3, M_total=1.50 TRY/L
    - Rejim 3 (Vergi Ayarlama): w=5, M_total=1.20 TRY/L

rho (ton -> litre):
    Benzin = 1180, Motorin = 1190, LPG = 1750

TUM PARASAL HESAPLAMALAR Decimal ILE YAPILIR. Float YASAK.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import NamedTuple

logger = logging.getLogger(__name__)


# --- Sabitler ---

# Yogunluk sabitleri (ton -> litre donusumu)
RHO: dict[str, Decimal] = {
    "benzin": Decimal("1180"),
    "motorin": Decimal("1190"),
    "lpg": Decimal("1750"),
}

# Rejim parametreleri: (sma_window, m_total)
REGIME_PARAMS: dict[int, tuple[int, Decimal]] = {
    0: (5, Decimal("1.20")),   # Normal
    1: (7, Decimal("1.00")),   # Secim
    2: (3, Decimal("1.50")),   # Kur Soku
    3: (5, Decimal("1.20")),   # Vergi Ayarlama
}

# Varsayilan yuvarlatma hassasiyeti
PRECISION = Decimal("0.00000001")  # 8 ondalik


# --- Yardimci Fonksiyonlar ---


def _safe_decimal(value: int | float | str | Decimal | None) -> Decimal:
    """
    Herhangi bir numerik degeri guvenli sekilde Decimal'e donusturur.

    Float -> str -> Decimal yoluyla kayipsiz donusum saglar.

    Args:
        value: Donusturulecek deger.

    Returns:
        Decimal degeri.

    Raises:
        ValueError: value None veya donusturulemez ise.
    """
    if value is None:
        raise ValueError("Decimal'e donusturulemez: None deger")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"Decimal'e donusturulemez: {value!r}") from e


# --- Veri Yapilari ---


class RegimeConfig(NamedTuple):
    """Rejim konfigurasyonu."""
    window: int
    m_total: Decimal


@dataclass
class CostSnapshot:
    """Maliyet ayristirma snapshot sonucu."""
    cif_component_tl: Decimal
    otv_component_tl: Decimal
    kdv_component_tl: Decimal
    margin_component_tl: Decimal
    theoretical_cost_tl: Decimal
    actual_pump_price_tl: Decimal
    implied_cif_usd_ton: Decimal | None
    cost_gap_tl: Decimal
    cost_gap_pct: Decimal


@dataclass
class MBEResult:
    """MBE hesaplama sonucu."""
    nc_forward: Decimal
    nc_base: Decimal
    mbe_value: Decimal
    mbe_pct: Decimal
    sma_5: Decimal | None = None
    sma_10: Decimal | None = None
    delta_mbe: Decimal | None = None
    delta_mbe_3: Decimal | None = None
    trend_direction: str = "no_change"
    regime: int = 0
    sma_window: int = 5


# --- Hesaplama Fonksiyonlari ---


def calculate_nc_forward(
    cif_usd_ton: Decimal | int | float | str,
    fx_rate: Decimal | int | float | str,
    rho: Decimal | int | float | str,
) -> Decimal:
    """
    NC_forward (Net Cost Forward) hesaplar.

    NC_forward = (CIF * FX) / rho

    Args:
        cif_usd_ton: CIF Akdeniz fiyati (USD/ton).
        fx_rate: USD/TRY doviz kuru.
        rho: Yogunluk sabiti (ton -> litre).

    Returns:
        NC_forward degeri (TL/litre).

    Raises:
        ValueError: Gecersiz veya sifir rho degeri.
        ZeroDivisionError: rho sifir ise.
    """
    cif = _safe_decimal(cif_usd_ton)
    fx = _safe_decimal(fx_rate)
    r = _safe_decimal(rho)

    if r == Decimal("0"):
        raise ZeroDivisionError("rho (yogunluk sabiti) sifir olamaz")

    result = (cif * fx) / r
    return result.quantize(PRECISION, rounding=ROUND_HALF_UP)


def calculate_nc_base_from_pump(
    pump_price: Decimal | int | float | str,
    otv: Decimal | int | float | str,
    kdv: Decimal | int | float | str,
    m_total: Decimal | int | float | str,
) -> Decimal:
    """
    NC_base: Pompa fiyatindan ters hesaplama ile net maliyet cikarir.

    NC_base = (pump_price - m_total) / (1 + kdv) - otv

    Args:
        pump_price: Pompa fiyati TL/litre.
        otv: OTV sabit tutar TL/litre.
        kdv: KDV orani (0-1 arasi, or: 0.18).
        m_total: Toplam marj TL/litre.

    Returns:
        NC_base degeri (TL/litre).

    Raises:
        ZeroDivisionError: (1 + kdv) sifir ise.
    """
    pp = _safe_decimal(pump_price)
    o = _safe_decimal(otv)
    k = _safe_decimal(kdv)
    m = _safe_decimal(m_total)

    denominator = Decimal("1") + k
    if denominator == Decimal("0"):
        raise ZeroDivisionError("(1 + kdv) sifir olamaz — kdv = -1 gecersiz")

    result = (pp - m) / denominator - o
    return result.quantize(PRECISION, rounding=ROUND_HALF_UP)


def calculate_sma(
    series: list[Decimal],
    window: int,
) -> list[Decimal]:
    """
    Basit hareketli ortalama (Simple Moving Average) hesaplar.

    Her indeks icin, o indekse kadar (dahil) window kadar elemani ortalar.
    Yetersiz veri durumunda mevcut verilerin ortalamasi alinir.

    Args:
        series: Decimal degerlerden olusan seri.
        window: Pencere genisligi.

    Returns:
        SMA degerlerinden olusan liste (series ile ayni uzunlukta).

    Raises:
        ValueError: window < 1 veya series bos ise.
    """
    if window < 1:
        raise ValueError(f"SMA pencere genisligi en az 1 olmalidir, verilen: {window}")
    if not series:
        raise ValueError("SMA hesabi icin en az 1 veri noktasi gerekli")

    result: list[Decimal] = []
    for i in range(len(series)):
        # Pencere baslangiç indeksi (0'dan kucuk olamaz)
        start = max(0, i - window + 1)
        window_data = series[start : i + 1]
        count = Decimal(str(len(window_data)))
        total = sum(window_data)
        avg = (total / count).quantize(PRECISION, rounding=ROUND_HALF_UP)
        result.append(avg)

    return result


def calculate_mbe(
    nc_forward_series: list[Decimal],
    nc_base_sma: Decimal,
    window: int,
) -> Decimal:
    """
    MBE (Maliyet Baz Etkisi) degerini hesaplar.

    MBE = SMA_w(NC_forward_series) - nc_base_sma

    Args:
        nc_forward_series: Son w gun icin NC_forward degerleri.
        nc_base_sma: Son zam tarihindeki NC_base SMA degeri.
        window: SMA pencere genisligi.

    Returns:
        MBE degeri (TL/litre).

    Raises:
        ValueError: nc_forward_series bos ise.
    """
    if not nc_forward_series:
        raise ValueError("MBE hesabi icin en az 1 NC_forward degeri gerekli")

    sma_values = calculate_sma(nc_forward_series, window)
    # Son SMA degeri = guncel SMA
    current_sma = sma_values[-1]

    mbe = current_sma - nc_base_sma
    return mbe.quantize(PRECISION, rounding=ROUND_HALF_UP)


def calculate_cost_snapshot(
    cif_usd_ton: Decimal | int | float | str,
    fx_rate: Decimal | int | float | str,
    pump_price: Decimal | int | float | str,
    otv_fixed_tl: Decimal | int | float | str,
    kdv_rate: Decimal | int | float | str,
    rho: Decimal | int | float | str,
    m_total: Decimal | int | float | str,
) -> CostSnapshot:
    """
    Gunluk maliyet ayristirma snapshot'i hesaplar.

    Bilesenleri hesaplar:
    1. CIF bileseni = (CIF * FX) / rho
    2. OTV bileseni = otv_fixed_tl
    3. Teorik maliyet = (CIF_bileseni + OTV) * (1 + KDV) + marj
    4. KDV bileseni = (CIF_bileseni + OTV) * KDV
    5. Maliyet farki = gercek_pompa - teorik_maliyet

    Args:
        cif_usd_ton: CIF Akdeniz fiyati (USD/ton).
        fx_rate: USD/TRY doviz kuru.
        pump_price: Gercek pompa fiyati (TL/litre).
        otv_fixed_tl: OTV sabit tutar (TL/litre).
        kdv_rate: KDV orani (0-1 arasi).
        rho: Yogunluk sabiti.
        m_total: Toplam marj (TL/litre).

    Returns:
        CostSnapshot nesnesi.
    """
    cif = _safe_decimal(cif_usd_ton)
    fx = _safe_decimal(fx_rate)
    pp = _safe_decimal(pump_price)
    otv = _safe_decimal(otv_fixed_tl)
    kdv = _safe_decimal(kdv_rate)
    r = _safe_decimal(rho)
    m = _safe_decimal(m_total)

    # CIF bileseni (TL/litre)
    cif_component = calculate_nc_forward(cif, fx, r)

    # OTV bileseni
    otv_component = otv

    # KDV bileseni
    kdv_component = ((cif_component + otv) * kdv).quantize(PRECISION, rounding=ROUND_HALF_UP)

    # Marj bileseni
    margin_component = m

    # Teorik maliyet = (CIF + OTV) * (1 + KDV) + marj
    theoretical = ((cif_component + otv) * (Decimal("1") + kdv) + m).quantize(
        PRECISION, rounding=ROUND_HALF_UP
    )

    # Ima edilen CIF (ters hesaplama)
    # implied_cif = NC_base * rho / FX
    implied_cif: Decimal | None = None
    if fx > Decimal("0") and r > Decimal("0"):
        nc_base = calculate_nc_base_from_pump(pp, otv, kdv, m)
        implied_cif = ((nc_base * r) / fx).quantize(PRECISION, rounding=ROUND_HALF_UP)

    # Maliyet farki
    cost_gap = (pp - theoretical).quantize(PRECISION, rounding=ROUND_HALF_UP)

    # Maliyet farki yuzdesi
    if theoretical != Decimal("0"):
        cost_gap_pct = ((cost_gap / theoretical) * Decimal("100")).quantize(
            PRECISION, rounding=ROUND_HALF_UP
        )
    else:
        cost_gap_pct = Decimal("0")

    return CostSnapshot(
        cif_component_tl=cif_component,
        otv_component_tl=otv_component,
        kdv_component_tl=kdv_component,
        margin_component_tl=margin_component,
        theoretical_cost_tl=theoretical,
        actual_pump_price_tl=pp,
        implied_cif_usd_ton=implied_cif,
        cost_gap_tl=cost_gap,
        cost_gap_pct=cost_gap_pct,
    )


def detect_trend(
    sma_series: list[Decimal],
    lookback: int = 3,
) -> str:
    """
    SMA serisinin son 'lookback' degerine bakarak trend yonunu tespit eder.

    Kurallar:
    - Son deger > ilk deger (lookback icinde) -> 'increase'
    - Son deger < ilk deger (lookback icinde) -> 'decrease'
    - Aksi halde -> 'no_change'

    Args:
        sma_series: SMA degerlerinden olusan seri.
        lookback: Kac gune bakarak trend belirlenecegi.

    Returns:
        Trend yonu: 'increase', 'decrease', 'no_change'
    """
    if not sma_series or len(sma_series) < 2:
        return "no_change"

    # Lookback penceresi
    actual_lookback = min(lookback, len(sma_series))
    start_val = sma_series[-actual_lookback]
    end_val = sma_series[-1]

    if end_val > start_val:
        return "increase"
    elif end_val < start_val:
        return "decrease"
    else:
        return "no_change"


def get_regime_config(regime: int) -> RegimeConfig:
    """
    Rejim koduna gore konfigurasyonu dondurur.

    Args:
        regime: Rejim kodu (0-3).

    Returns:
        RegimeConfig (window, m_total).

    Raises:
        ValueError: Gecersiz rejim kodu.
    """
    if regime not in REGIME_PARAMS:
        raise ValueError(
            f"Gecersiz rejim kodu: {regime}. "
            f"Gecerli kodlar: {list(REGIME_PARAMS.keys())}"
        )
    window, m_total = REGIME_PARAMS[regime]
    return RegimeConfig(window=window, m_total=m_total)


def get_rho(fuel_type: str) -> Decimal:
    """
    Yakit tipine gore yogunluk sabitini dondurur.

    Args:
        fuel_type: Yakit tipi ('benzin', 'motorin', 'lpg').

    Returns:
        Yogunluk sabiti (Decimal).

    Raises:
        ValueError: Gecersiz yakit tipi.
    """
    if fuel_type not in RHO:
        raise ValueError(
            f"Gecersiz yakit tipi: '{fuel_type}'. "
            f"Gecerli tipler: {list(RHO.keys())}"
        )
    return RHO[fuel_type]


def calculate_full_mbe(
    nc_forward_series: list[Decimal],
    nc_base: Decimal,
    regime: int = 0,
    previous_mbe: Decimal | None = None,
    mbe_3_days_ago: Decimal | None = None,
) -> MBEResult:
    """
    Tam MBE hesaplama paketi — tum turetilmis metrikleri uretir.

    Args:
        nc_forward_series: NC_forward degerleri serisi (en eski -> en yeni).
        nc_base: NC_base degeri (son zam tarihinden).
        regime: Aktif rejim kodu (0-3).
        previous_mbe: Bir onceki gunun MBE degeri (delta hesabi icin).
        mbe_3_days_ago: 3 gun onceki MBE degeri (delta_3 hesabi icin).

    Returns:
        MBEResult nesnesi.
    """
    config = get_regime_config(regime)
    window = config.window

    if not nc_forward_series:
        raise ValueError("NC_forward serisi bos olamaz")

    # Son NC_forward degeri
    nc_fwd = nc_forward_series[-1]

    # SMA hesaplamalari
    sma_all = calculate_sma(nc_forward_series, window)
    current_sma = sma_all[-1]

    # 5 ve 10 gunluk SMA
    sma_5_vals = calculate_sma(nc_forward_series, 5)
    sma_5 = sma_5_vals[-1] if len(nc_forward_series) >= 1 else None

    sma_10_vals = calculate_sma(nc_forward_series, 10)
    sma_10 = sma_10_vals[-1] if len(nc_forward_series) >= 1 else None

    # MBE hesaplama
    mbe_value = (current_sma - nc_base).quantize(PRECISION, rounding=ROUND_HALF_UP)

    # MBE yuzdesi
    if nc_base != Decimal("0"):
        mbe_pct = ((mbe_value / nc_base) * Decimal("100")).quantize(
            PRECISION, rounding=ROUND_HALF_UP
        )
    else:
        mbe_pct = Decimal("0")

    # Delta MBE
    delta_mbe: Decimal | None = None
    if previous_mbe is not None:
        delta_mbe = (mbe_value - previous_mbe).quantize(PRECISION, rounding=ROUND_HALF_UP)

    delta_mbe_3: Decimal | None = None
    if mbe_3_days_ago is not None:
        delta_mbe_3 = (mbe_value - mbe_3_days_ago).quantize(PRECISION, rounding=ROUND_HALF_UP)

    # Trend
    trend_direction = detect_trend(sma_all, lookback=3)

    return MBEResult(
        nc_forward=nc_fwd,
        nc_base=nc_base,
        mbe_value=mbe_value,
        mbe_pct=mbe_pct,
        sma_5=sma_5,
        sma_10=sma_10,
        delta_mbe=delta_mbe,
        delta_mbe_3=delta_mbe_3,
        trend_direction=trend_direction,
        regime=regime,
        sma_window=window,
    )
