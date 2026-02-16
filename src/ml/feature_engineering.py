"""
Feature Engineering Pipeline (Katman 4).

47+ feature'i 5 gruptan hesaplar. Tum hesaplamalar DB'den bagimsiz
pure function olarak calisir — girdi dict/DataFrame, cikti feature dict.

Feature Gruplari:
  1. MBE Ozellikleri (6 feature)
  2. Net Maliyet (NC) Ozellikleri (7 feature)
  3. Dis Piyasa Faktorleri (13 feature)
  4. Politik/Ekonomik Rejim (12 feature)
  5. Vergi & Maliyet (9 feature)

Kurallar:
  - Mevcut mbe_calculator.py fonksiyonlari import edilir, tekrar yazilmaz.
  - SMA yetersiz veri icin graceful degrade (mevcut ortalamayi kullan).
  - Tum feature'lar float olarak model'e girer.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.core.mbe_calculator import (
    _safe_decimal,
    calculate_nc_forward,
    calculate_sma,
    detect_trend,
    get_rho,
)

logger = logging.getLogger(__name__)

# --- Sabitler ---

# Feature isimleri (model egitiminde kullanilir)
FEATURE_NAMES: list[str] = [
    # Grup 1: MBE
    "mbe_value", "mbe_pct", "mbe_sma_5", "mbe_sma_10",
    "delta_mbe", "delta_mbe_3d",
    # Grup 2: NC
    "nc_forward", "nc_sma_3", "nc_sma_5", "nc_sma_7", "nc_sma_10",
    "nc_trend_increase", "nc_trend_decrease", "nc_trend_no_change",
    # Grup 3: Dis Piyasa
    "cif_usd_ton", "cif_lag_1", "cif_lag_3", "cif_lag_5",
    "fx_rate", "fx_lag_1", "fx_volatility_5d", "fx_volatility_10d",
    "fx_momentum_3d", "brent_usd_bbl", "brent_lag_1",
    "brent_volatility", "vix_equivalent",
    # Grup 4: Politik/Ekonomik Rejim
    "regime_normal", "regime_election", "regime_kur_shock", "regime_tax",
    "days_since_last_hike", "days_to_election",
    "is_holiday_period", "holiday_proximity_days",
    "political_tension_score", "geopolitical_score",
    "otv_change_proximity",
    "policy_uncertainty_index", "central_bank_signal",
    "parliamentary_session_active",
    # Grup 5: Vergi & Maliyet
    "otv_rate", "kdv_rate", "margin_total", "cost_base_snapshot",
    "implied_cif", "cost_gap_tl", "cost_gap_pct",
    "tax_bracket_change_flag", "effective_tax_rate",
]

# Toplam feature sayisi
TOTAL_FEATURE_COUNT = len(FEATURE_NAMES)


@dataclass
class FeatureRecord:
    """Tek bir gun icin hesaplanmis feature seti."""

    trade_date: str
    fuel_type: str
    features: dict[str, float] = field(default_factory=dict)
    missing_features: list[str] = field(default_factory=list)


# ────────────────────────────────────────────────────────────────────────────
#  Yardimci Fonksiyonlar
# ────────────────────────────────────────────────────────────────────────────


def _to_float(value: Any, default: float = 0.0) -> float:
    """Herhangi bir degeri guvenli sekilde float'a donusturur."""
    if value is None:
        return default
    try:
        if isinstance(value, Decimal):
            return float(value)
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_list_get(lst: list, idx: int, default: Any = None) -> Any:
    """Liste indeksine guvenli erisim."""
    try:
        return lst[idx]
    except (IndexError, TypeError):
        return default


def _compute_sma_float(series: list[float], window: int) -> float:
    """
    Float serisi icin SMA hesaplar.
    Yetersiz veri durumunda mevcut verilerin ortalamasini alir.
    """
    if not series:
        return 0.0
    actual_window = min(window, len(series))
    window_data = series[-actual_window:]
    return sum(window_data) / len(window_data)


def _compute_std_float(series: list[float]) -> float:
    """Float serisi icin standart sapma hesaplar."""
    if len(series) < 2:
        return 0.0
    n = len(series)
    mean = sum(series) / n
    variance = sum((x - mean) ** 2 for x in series) / (n - 1)
    return math.sqrt(variance)


def _compute_momentum(series: list[float], period: int) -> float:
    """Momentum hesaplar: son deger - N gun onceki deger."""
    if len(series) < period + 1:
        if len(series) >= 2:
            return series[-1] - series[0]
        return 0.0
    return series[-1] - series[-(period + 1)]


# ────────────────────────────────────────────────────────────────────────────
#  Grup 1: MBE Ozellikleri (6 feature)
# ────────────────────────────────────────────────────────────────────────────


def compute_mbe_features(
    mbe_value: float,
    mbe_pct: float,
    mbe_history: list[float] | None = None,
    previous_mbe: float | None = None,
    mbe_3_days_ago: float | None = None,
) -> dict[str, float]:
    """
    MBE ozelliklerini hesaplar.

    Args:
        mbe_value: Gunluk MBE degeri (TL/L).
        mbe_pct: MBE yuzdesel formu (%).
        mbe_history: Gecmis MBE degerleri (en eski -> en yeni).
        previous_mbe: Bir onceki gunun MBE degeri.
        mbe_3_days_ago: 3 gun onceki MBE degeri.

    Returns:
        6 adet MBE feature iceren dict.
    """
    history = mbe_history or []

    # SMA hesaplamalari — yeterli veri yoksa graceful degrade
    mbe_sma_5 = _compute_sma_float(history, 5) if history else mbe_value
    mbe_sma_10 = _compute_sma_float(history, 10) if history else mbe_value

    # Delta hesaplamalari
    delta_mbe = (mbe_value - previous_mbe) if previous_mbe is not None else 0.0
    delta_mbe_3d = (mbe_value - mbe_3_days_ago) if mbe_3_days_ago is not None else 0.0

    return {
        "mbe_value": mbe_value,
        "mbe_pct": mbe_pct,
        "mbe_sma_5": mbe_sma_5,
        "mbe_sma_10": mbe_sma_10,
        "delta_mbe": delta_mbe,
        "delta_mbe_3d": delta_mbe_3d,
    }


# ────────────────────────────────────────────────────────────────────────────
#  Grup 2: Net Maliyet (NC) Ozellikleri (7 feature)
# ────────────────────────────────────────────────────────────────────────────


def compute_nc_features(
    cif_usd_ton: float,
    fx_rate: float,
    fuel_type: str = "motorin",
    nc_history: list[float] | None = None,
) -> dict[str, float]:
    """
    Net Maliyet (NC) ozelliklerini hesaplar.

    Args:
        cif_usd_ton: CIF Akdeniz fiyati (USD/ton).
        fx_rate: USD/TRY doviz kuru.
        fuel_type: Yakit tipi (yogunluk sabiti icin).
        nc_history: Gecmis NC_forward degerleri.

    Returns:
        7 adet NC feature iceren dict.
    """
    # NC forward hesapla — mbe_calculator'dan import
    try:
        rho = get_rho(fuel_type)
        nc_fwd_decimal = calculate_nc_forward(cif_usd_ton, fx_rate, rho)
        nc_forward = float(nc_fwd_decimal)
    except (ValueError, ZeroDivisionError):
        nc_forward = 0.0

    history = nc_history or []

    # SMA hesaplamalari
    nc_sma_3 = _compute_sma_float(history, 3) if history else nc_forward
    nc_sma_5 = _compute_sma_float(history, 5) if history else nc_forward
    nc_sma_7 = _compute_sma_float(history, 7) if history else nc_forward
    nc_sma_10 = _compute_sma_float(history, 10) if history else nc_forward

    # Trend yonu — one-hot encoding
    trend = "no_change"
    if len(history) >= 3:
        decimal_history = [Decimal(str(v)) for v in history[-3:]]
        trend = detect_trend(decimal_history, lookback=3)

    nc_trend_increase = 1.0 if trend == "increase" else 0.0
    nc_trend_decrease = 1.0 if trend == "decrease" else 0.0
    nc_trend_no_change = 1.0 if trend == "no_change" else 0.0

    return {
        "nc_forward": nc_forward,
        "nc_sma_3": nc_sma_3,
        "nc_sma_5": nc_sma_5,
        "nc_sma_7": nc_sma_7,
        "nc_sma_10": nc_sma_10,
        "nc_trend_increase": nc_trend_increase,
        "nc_trend_decrease": nc_trend_decrease,
        "nc_trend_no_change": nc_trend_no_change,
    }


# ────────────────────────────────────────────────────────────────────────────
#  Grup 3: Dis Piyasa Faktorleri (13 feature)
# ────────────────────────────────────────────────────────────────────────────


def compute_external_market_features(
    cif_usd_ton: float,
    fx_rate: float,
    brent_usd_bbl: float,
    cif_history: list[float] | None = None,
    fx_history: list[float] | None = None,
    brent_history: list[float] | None = None,
) -> dict[str, float]:
    """
    Dis piyasa faktorlerini hesaplar.

    Args:
        cif_usd_ton: CIF Akdeniz fiyati (USD/ton).
        fx_rate: USD/TRY doviz kuru.
        brent_usd_bbl: Brent ham petrol (USD/bbl).
        cif_history: Gecmis CIF fiyatlari.
        fx_history: Gecmis FX kurlari.
        brent_history: Gecmis Brent fiyatlari.

    Returns:
        13 adet dis piyasa feature iceren dict.
    """
    cif_hist = cif_history or []
    fx_hist = fx_history or []
    brent_hist = brent_history or []

    # CIF lag'lar
    cif_lag_1 = _safe_list_get(cif_hist, -2, cif_usd_ton) if len(cif_hist) >= 2 else cif_usd_ton
    cif_lag_3 = _safe_list_get(cif_hist, -4, cif_usd_ton) if len(cif_hist) >= 4 else cif_usd_ton
    cif_lag_5 = _safe_list_get(cif_hist, -6, cif_usd_ton) if len(cif_hist) >= 6 else cif_usd_ton

    # FX lag ve volatilite
    fx_lag_1 = _safe_list_get(fx_hist, -2, fx_rate) if len(fx_hist) >= 2 else fx_rate

    fx_volatility_5d = _compute_std_float(fx_hist[-5:]) if len(fx_hist) >= 5 else 0.0
    fx_volatility_10d = _compute_std_float(fx_hist[-10:]) if len(fx_hist) >= 10 else 0.0

    fx_momentum_3d = _compute_momentum(fx_hist, 3) if fx_hist else 0.0

    # Brent lag ve volatilite
    brent_lag_1 = (
        _safe_list_get(brent_hist, -2, brent_usd_bbl)
        if len(brent_hist) >= 2
        else brent_usd_bbl
    )
    brent_volatility = _compute_std_float(brent_hist[-10:]) if len(brent_hist) >= 5 else 0.0

    # VIX equivalent — emtia volatilite proxy (Brent + FX volatilitenin kombinasyonu)
    vix_equivalent = (brent_volatility + fx_volatility_5d * 10) / 2.0

    return {
        "cif_usd_ton": cif_usd_ton,
        "cif_lag_1": _to_float(cif_lag_1, cif_usd_ton),
        "cif_lag_3": _to_float(cif_lag_3, cif_usd_ton),
        "cif_lag_5": _to_float(cif_lag_5, cif_usd_ton),
        "fx_rate": fx_rate,
        "fx_lag_1": _to_float(fx_lag_1, fx_rate),
        "fx_volatility_5d": fx_volatility_5d,
        "fx_volatility_10d": fx_volatility_10d,
        "fx_momentum_3d": fx_momentum_3d,
        "brent_usd_bbl": brent_usd_bbl,
        "brent_lag_1": _to_float(brent_lag_1, brent_usd_bbl),
        "brent_volatility": brent_volatility,
        "vix_equivalent": vix_equivalent,
    }


# ────────────────────────────────────────────────────────────────────────────
#  Grup 4: Politik / Ekonomik Rejim (12 feature)
# ────────────────────────────────────────────────────────────────────────────


def compute_regime_features(
    regime: int = 0,
    days_since_last_hike: int = 0,
    days_to_election: int = 365,
    is_holiday_period: bool = False,
    holiday_proximity_days: int = 30,
    political_tension_score: float = 0.0,
    geopolitical_score: float = 0.0,
    otv_change_proximity: int = 90,
    policy_uncertainty_index: float = 0.5,
    central_bank_signal: float = 0.0,
    parliamentary_session_active: bool = True,
) -> dict[str, float]:
    """
    Politik/ekonomik rejim ozelliklerini hesaplar.

    Args:
        regime: Aktif rejim kodu (0=Normal, 1=Secim, 2=Kur Soku, 3=Vergi).
        days_since_last_hike: Son zamdan bu yana gecen gun.
        days_to_election: Bir sonraki secime kalan gun.
        is_holiday_period: Bayram donemi mi?
        holiday_proximity_days: En yakin bayrama gun sayisi.
        political_tension_score: Siyasi gerilim skoru (0-1).
        geopolitical_score: Jeopolitik risk skoru (0-1).
        otv_change_proximity: Son OTV degisiminden gecen gun.
        policy_uncertainty_index: Politika belirsizligi endeksi (0-1).
        central_bank_signal: Merkez bankasi sinyali (-1 ile 1 arasi).
        parliamentary_session_active: Meclis oturumu aktif mi?

    Returns:
        12 adet rejim feature iceren dict.
    """
    # Rejim one-hot encoding
    regime_normal = 1.0 if regime == 0 else 0.0
    regime_election = 1.0 if regime == 1 else 0.0
    regime_kur_shock = 1.0 if regime == 2 else 0.0
    regime_tax = 1.0 if regime == 3 else 0.0

    return {
        "regime_normal": regime_normal,
        "regime_election": regime_election,
        "regime_kur_shock": regime_kur_shock,
        "regime_tax": regime_tax,
        "days_since_last_hike": float(days_since_last_hike),
        "days_to_election": float(days_to_election),
        "is_holiday_period": 1.0 if is_holiday_period else 0.0,
        "holiday_proximity_days": float(holiday_proximity_days),
        "political_tension_score": political_tension_score,
        "geopolitical_score": geopolitical_score,
        "otv_change_proximity": float(otv_change_proximity),
        "policy_uncertainty_index": policy_uncertainty_index,
        "central_bank_signal": central_bank_signal,
        "parliamentary_session_active": 1.0 if parliamentary_session_active else 0.0,
    }


# ────────────────────────────────────────────────────────────────────────────
#  Grup 5: Vergi & Maliyet (9 feature)
# ────────────────────────────────────────────────────────────────────────────


def compute_tax_cost_features(
    otv_rate: float,
    kdv_rate: float,
    margin_total: float,
    cost_base_snapshot: float,
    implied_cif: float | None = None,
    cost_gap_tl: float = 0.0,
    cost_gap_pct: float = 0.0,
    tax_bracket_change_flag: bool = False,
    effective_tax_rate: float | None = None,
    pump_price: float | None = None,
) -> dict[str, float]:
    """
    Vergi ve maliyet ozelliklerini hesaplar.

    Args:
        otv_rate: OTV orani veya sabit tutar (TL/L).
        kdv_rate: KDV orani (orn: 0.20).
        margin_total: Toplam marj (TL/L).
        cost_base_snapshot: Maliyet bazi (TL/L).
        implied_cif: Ima edilen CIF (USD/ton).
        cost_gap_tl: Maliyet farki (TL).
        cost_gap_pct: Maliyet farki yuzdesi.
        tax_bracket_change_flag: OTV degisim flag.
        effective_tax_rate: Etkin vergi orani.
        pump_price: Pompa fiyati (etkin vergi hesabi icin).

    Returns:
        9 adet vergi/maliyet feature iceren dict.
    """
    # Etkin vergi orani hesapla (yoksa tahmini)
    if effective_tax_rate is None and pump_price and pump_price > 0:
        tax_portion = otv_rate + (cost_base_snapshot + otv_rate) * kdv_rate
        effective_tax_rate = tax_portion / pump_price if pump_price > 0 else 0.0
    elif effective_tax_rate is None:
        effective_tax_rate = 0.0

    return {
        "otv_rate": otv_rate,
        "kdv_rate": kdv_rate,
        "margin_total": margin_total,
        "cost_base_snapshot": cost_base_snapshot,
        "implied_cif": _to_float(implied_cif, 0.0),
        "cost_gap_tl": cost_gap_tl,
        "cost_gap_pct": cost_gap_pct,
        "tax_bracket_change_flag": 1.0 if tax_bracket_change_flag else 0.0,
        "effective_tax_rate": effective_tax_rate,
    }


# ────────────────────────────────────────────────────────────────────────────
#  Ana Feature Hesaplama — Tum Gruplari Birlestir
# ────────────────────────────────────────────────────────────────────────────


def compute_all_features(
    *,
    trade_date: str,
    fuel_type: str,
    # MBE gruplari
    mbe_value: float,
    mbe_pct: float,
    mbe_history: list[float] | None = None,
    previous_mbe: float | None = None,
    mbe_3_days_ago: float | None = None,
    # NC gruplari
    cif_usd_ton: float,
    fx_rate: float,
    nc_history: list[float] | None = None,
    # Dis piyasa
    brent_usd_bbl: float = 0.0,
    cif_history: list[float] | None = None,
    fx_history: list[float] | None = None,
    brent_history: list[float] | None = None,
    # Rejim
    regime: int = 0,
    days_since_last_hike: int = 0,
    days_to_election: int = 365,
    is_holiday_period: bool = False,
    holiday_proximity_days: int = 30,
    political_tension_score: float = 0.0,
    geopolitical_score: float = 0.0,
    otv_change_proximity: int = 90,
    policy_uncertainty_index: float = 0.5,
    central_bank_signal: float = 0.0,
    parliamentary_session_active: bool = True,
    # Vergi & maliyet
    otv_rate: float = 0.0,
    kdv_rate: float = 0.20,
    margin_total: float = 1.20,
    cost_base_snapshot: float = 0.0,
    implied_cif: float | None = None,
    cost_gap_tl: float = 0.0,
    cost_gap_pct: float = 0.0,
    tax_bracket_change_flag: bool = False,
    effective_tax_rate: float | None = None,
    pump_price: float | None = None,
) -> FeatureRecord:
    """
    Tum feature gruplarini hesaplayip birlestiren ana fonksiyon.

    DB'den bagimsiz, pure function. Girdi parametrelerini alir,
    47+ feature iceren FeatureRecord dondurur.

    Returns:
        FeatureRecord — hesaplanmis feature seti.
    """
    features: dict[str, float] = {}
    missing: list[str] = []

    # Grup 1: MBE
    try:
        mbe_feats = compute_mbe_features(
            mbe_value=mbe_value,
            mbe_pct=mbe_pct,
            mbe_history=mbe_history,
            previous_mbe=previous_mbe,
            mbe_3_days_ago=mbe_3_days_ago,
        )
        features.update(mbe_feats)
    except Exception as exc:
        logger.warning("MBE feature hesaplama hatasi: %s", exc)
        for name in FEATURE_NAMES[:6]:
            features[name] = 0.0
            missing.append(name)

    # Grup 2: NC
    try:
        nc_feats = compute_nc_features(
            cif_usd_ton=cif_usd_ton,
            fx_rate=fx_rate,
            fuel_type=fuel_type,
            nc_history=nc_history,
        )
        features.update(nc_feats)
    except Exception as exc:
        logger.warning("NC feature hesaplama hatasi: %s", exc)
        for name in FEATURE_NAMES[6:14]:
            features[name] = 0.0
            missing.append(name)

    # Grup 3: Dis Piyasa
    try:
        ext_feats = compute_external_market_features(
            cif_usd_ton=cif_usd_ton,
            fx_rate=fx_rate,
            brent_usd_bbl=brent_usd_bbl,
            cif_history=cif_history,
            fx_history=fx_history,
            brent_history=brent_history,
        )
        features.update(ext_feats)
    except Exception as exc:
        logger.warning("Dis piyasa feature hesaplama hatasi: %s", exc)
        for name in FEATURE_NAMES[14:27]:
            features[name] = 0.0
            missing.append(name)

    # Grup 4: Rejim
    try:
        regime_feats = compute_regime_features(
            regime=regime,
            days_since_last_hike=days_since_last_hike,
            days_to_election=days_to_election,
            is_holiday_period=is_holiday_period,
            holiday_proximity_days=holiday_proximity_days,
            political_tension_score=political_tension_score,
            geopolitical_score=geopolitical_score,
            otv_change_proximity=otv_change_proximity,
            policy_uncertainty_index=policy_uncertainty_index,
            central_bank_signal=central_bank_signal,
            parliamentary_session_active=parliamentary_session_active,
        )
        features.update(regime_feats)
    except Exception as exc:
        logger.warning("Rejim feature hesaplama hatasi: %s", exc)
        for name in FEATURE_NAMES[27:41]:
            features[name] = 0.0
            missing.append(name)

    # Grup 5: Vergi & Maliyet
    try:
        tax_feats = compute_tax_cost_features(
            otv_rate=otv_rate,
            kdv_rate=kdv_rate,
            margin_total=margin_total,
            cost_base_snapshot=cost_base_snapshot,
            implied_cif=implied_cif,
            cost_gap_tl=cost_gap_tl,
            cost_gap_pct=cost_gap_pct,
            tax_bracket_change_flag=tax_bracket_change_flag,
            effective_tax_rate=effective_tax_rate,
            pump_price=pump_price,
        )
        features.update(tax_feats)
    except Exception as exc:
        logger.warning("Vergi/maliyet feature hesaplama hatasi: %s", exc)
        for name in FEATURE_NAMES[41:]:
            features[name] = 0.0
            missing.append(name)

    return FeatureRecord(
        trade_date=trade_date,
        fuel_type=fuel_type,
        features=features,
        missing_features=missing,
    )


def features_to_array(record: FeatureRecord) -> list[float]:
    """
    FeatureRecord'u sabit sirali float listesine donusturur.

    Model'e girecek feature vektoru, FEATURE_NAMES sirasina gore duzenlenir.
    Eksik feature'lar 0.0 ile doldurulur.

    Args:
        record: Hesaplanmis feature kaydi.

    Returns:
        FEATURE_NAMES sirasinda float listesi.
    """
    return [record.features.get(name, 0.0) for name in FEATURE_NAMES]


def features_dict_to_array(features: dict[str, float]) -> list[float]:
    """
    Feature dict'ini sabit sirali float listesine donusturur.

    Args:
        features: Feature adi -> deger eslesmesi.

    Returns:
        FEATURE_NAMES sirasinda float listesi.
    """
    return [features.get(name, 0.0) for name in FEATURE_NAMES]
