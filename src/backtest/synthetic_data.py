"""
Sentetik Turkiye Akaryakit Piyasasi Veri Jeneratoru.

3 senaryo ile gercekci piyasa verisi uretir:
    - Normal: Brent yavas artis, 2-3 zam, 1 indirim
    - FX Soku: Ani %10 kur sicramasi, hizli + gecikmis zam
    - Secim: MBE yukselir ama 15-20 gun zam gelmez, sonra buyuk zam

DB bagimliligi YOK — tamami in-memory.
TUM parasal degerler Decimal. Float YASAK.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

logger = logging.getLogger(__name__)

# --- Sabitler ---

# OTV sabit tutarlar (TL/litre)
OTV_BENZIN = Decimal("2.4835")
OTV_MOTORIN = Decimal("2.1079")

# KDV orani
KDV_RATE = Decimal("0.20")

# Yogunluk sabitleri (ton -> litre)
RHO_BENZIN = Decimal("1180")
RHO_MOTORIN = Decimal("1190")

# Varsayilan marj (TL/litre)
DEFAULT_MARGIN = Decimal("1.20")

# Seed sabiti (deterministik random walk icin)
SEED_SALT = "yakit-analizi-backtest-v1"


# --- Veri Yapilari ---


@dataclass(frozen=True)
class SyntheticDay:
    """Bir gunluk sentetik piyasa verisi."""

    date: date
    fuel_type: str
    cif_usd_ton: Decimal
    fx_rate: Decimal
    pump_price_tl: Decimal
    otv_fixed_tl: Decimal
    kdv_rate: Decimal
    is_price_change: bool
    change_direction: str  # "up", "down", "none"
    change_amount_tl: Decimal
    regime: int  # 0=normal, 1=secim, 2=kur_soku, 3=vergi


# --- Deterministik Random Walk Yardimcilari ---


def _deterministic_hash(seed: str, day_index: int, component: str) -> Decimal:
    """
    Deterministik pseudo-random deger uretir (0-1 arasi).

    Ayni seed + day_index + component icin her zaman ayni degeri dondurur.
    """
    data = f"{SEED_SALT}:{seed}:{day_index}:{component}"
    h = hashlib.sha256(data.encode()).hexdigest()
    # Hash'in ilk 8 hex karakterini [0, 1) araligina map et
    int_val = int(h[:8], 16)
    max_val = 0xFFFFFFFF
    return (Decimal(str(int_val)) / Decimal(str(max_val))).quantize(
        Decimal("0.00000001"), rounding=ROUND_HALF_UP
    )


def _random_walk_step(
    current: Decimal,
    drift: Decimal,
    volatility: Decimal,
    seed: str,
    day_index: int,
    component: str,
) -> Decimal:
    """
    Deterministik random walk adimi.

    new_value = current + drift + volatility * (2 * rand - 1)

    rand [0,1) araliginda deterministik pseudo-random deger.
    (2 * rand - 1) ile [-1, 1) araligina map edilir.
    """
    rand = _deterministic_hash(seed, day_index, component)
    noise = volatility * (Decimal("2") * rand - Decimal("1"))
    new_value = current + drift + noise
    return new_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _calculate_pump_price(
    cif_usd_ton: Decimal,
    fx_rate: Decimal,
    rho: Decimal,
    otv: Decimal,
    kdv: Decimal,
    margin: Decimal,
) -> Decimal:
    """
    Teorik pompa fiyati hesaplar.

    pump = (CIF * FX / rho + OTV) * (1 + KDV) + margin
    """
    nc = (cif_usd_ton * fx_rate / rho).quantize(
        Decimal("0.00000001"), rounding=ROUND_HALF_UP
    )
    pump = (nc + otv) * (Decimal("1") + kdv) + margin
    return pump.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --- Senaryo Jeneratorleri ---


def generate_normal_scenario(
    days: int = 90,
    fuel_type: str = "benzin",
    start_date: date | None = None,
) -> list[SyntheticDay]:
    """
    Normal piyasa senaryosu: Brent yavas artis, 2-3 zam, 1 indirim.

    Args:
        days: Senaryo gun sayisi.
        fuel_type: Yakit tipi (benzin veya motorin).
        start_date: Baslangic tarihi.

    Returns:
        SyntheticDay listesi.
    """
    if start_date is None:
        start_date = date(2026, 1, 1)

    otv = OTV_BENZIN if fuel_type == "benzin" else OTV_MOTORIN
    rho = RHO_BENZIN if fuel_type == "benzin" else RHO_MOTORIN
    seed = f"normal-{fuel_type}"

    # Baslangic degerleri
    cif = Decimal("680.00")  # USD/ton
    fx = Decimal("36.50")  # USD/TRY

    # Pompa fiyati baslangici
    pump = _calculate_pump_price(cif, fx, rho, otv, KDV_RATE, DEFAULT_MARGIN)

    # Zam gunleri: gun 25, 50, 72 (2 zam + 1 indirim gun 82)
    price_change_days = {
        25: (Decimal("1.50"), "up"),
        50: (Decimal("2.00"), "up"),
        72: (Decimal("1.80"), "up"),
        82: (Decimal("-0.80"), "down"),
    }

    result: list[SyntheticDay] = []

    for i in range(days):
        current_date = start_date + timedelta(days=i)

        # CIF: yavas artis trendi (drift +0.30/gun, vol 2.0)
        cif = _random_walk_step(cif, Decimal("0.30"), Decimal("2.00"), seed, i, "cif")
        cif = max(cif, Decimal("500.00"))  # Alt sinir

        # FX: cok yavas artis (drift +0.005/gun, vol 0.10)
        fx = _random_walk_step(fx, Decimal("0.005"), Decimal("0.10"), seed, i, "fx")
        fx = max(fx, Decimal("30.00"))  # Alt sinir

        # Fiyat degisikligi kontrol
        is_change = i in price_change_days
        change_amount = Decimal("0")
        change_dir = "none"

        if is_change:
            change_amount, change_dir = price_change_days[i]
            pump = pump + change_amount
        # Pump fiyati zam/indirim disinda degismez (gercekci)

        result.append(
            SyntheticDay(
                date=current_date,
                fuel_type=fuel_type,
                cif_usd_ton=cif,
                fx_rate=fx,
                pump_price_tl=pump,
                otv_fixed_tl=otv,
                kdv_rate=KDV_RATE,
                is_price_change=is_change,
                change_direction=change_dir,
                change_amount_tl=change_amount,
                regime=0,  # Normal rejim
            )
        )

    logger.info(
        "Normal senaryo uretildi: %d gun, %d fiyat degisikligi",
        days,
        sum(1 for d in result if d.is_price_change),
    )
    return result


def generate_fx_shock_scenario(
    days: int = 60,
    fuel_type: str = "benzin",
    start_date: date | None = None,
) -> list[SyntheticDay]:
    """
    FX sok senaryosu: Ani %10 kur sicramasi, hizli + gecikmis zam.

    Gun 15'te kur %10 sicar. Gun 18'de hizli kucuk zam, gun 30'da buyuk zam.
    Rejim gun 15'te kur_soku (2) olur, gun 40'ta normale doner.

    Args:
        days: Senaryo gun sayisi.
        fuel_type: Yakit tipi.
        start_date: Baslangic tarihi.

    Returns:
        SyntheticDay listesi.
    """
    if start_date is None:
        start_date = date(2026, 1, 1)

    otv = OTV_BENZIN if fuel_type == "benzin" else OTV_MOTORIN
    rho = RHO_BENZIN if fuel_type == "benzin" else RHO_MOTORIN
    seed = f"fx_shock-{fuel_type}"

    cif = Decimal("700.00")
    fx = Decimal("36.00")

    pump = _calculate_pump_price(cif, fx, rho, otv, KDV_RATE, DEFAULT_MARGIN)

    # Gun 15: FX shock
    # Gun 18: Hizli kucuk zam
    # Gun 30: Buyuk zam
    price_change_days = {
        18: (Decimal("1.20"), "up"),
        30: (Decimal("3.50"), "up"),
    }

    result: list[SyntheticDay] = []

    for i in range(days):
        current_date = start_date + timedelta(days=i)

        # CIF: hafif artis
        cif = _random_walk_step(cif, Decimal("0.20"), Decimal("1.50"), seed, i, "cif")
        cif = max(cif, Decimal("550.00"))

        # FX: gun 15'te ani %10 sicrma
        if i == 15:
            fx = (fx * Decimal("1.10")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            drift = Decimal("0.003") if i < 15 else Decimal("0.01")
            vol = Decimal("0.08") if i < 15 else Decimal("0.15")
            fx = _random_walk_step(fx, drift, vol, seed, i, "fx")
            fx = max(fx, Decimal("30.00"))

        # Rejim: gun 15-40 arasi kur_soku
        regime = 2 if 15 <= i < 40 else 0

        # Fiyat degisikligi
        is_change = i in price_change_days
        change_amount = Decimal("0")
        change_dir = "none"

        if is_change:
            change_amount, change_dir = price_change_days[i]
            pump = pump + change_amount

        result.append(
            SyntheticDay(
                date=current_date,
                fuel_type=fuel_type,
                cif_usd_ton=cif,
                fx_rate=fx,
                pump_price_tl=pump,
                otv_fixed_tl=otv,
                kdv_rate=KDV_RATE,
                is_price_change=is_change,
                change_direction=change_dir,
                change_amount_tl=change_amount,
                regime=regime,
            )
        )

    logger.info(
        "FX sok senaryosu uretildi: %d gun, sok gunu=15, zamlar=[18, 30]",
        days,
    )
    return result


def generate_election_scenario(
    days: int = 60,
    fuel_type: str = "benzin",
    start_date: date | None = None,
) -> list[SyntheticDay]:
    """
    Secim senaryosu: MBE yukselir ama 15-20 gun zam gelmez, sonra buyuk zam.

    Secim donemi: gun 0-45. CIF ve FX yukselir, pompa sabit kalir.
    Gun 40'ta buyuk zam (4.50 TL). Secim rejimi (1) gun 0-45 arasi.

    Args:
        days: Senaryo gun sayisi.
        fuel_type: Yakit tipi.
        start_date: Baslangic tarihi.

    Returns:
        SyntheticDay listesi.
    """
    if start_date is None:
        start_date = date(2026, 1, 1)

    otv = OTV_BENZIN if fuel_type == "benzin" else OTV_MOTORIN
    rho = RHO_BENZIN if fuel_type == "benzin" else RHO_MOTORIN
    seed = f"election-{fuel_type}"

    cif = Decimal("690.00")
    fx = Decimal("36.00")

    pump = _calculate_pump_price(cif, fx, rho, otv, KDV_RATE, DEFAULT_MARGIN)

    # Sadece gun 40'ta buyuk zam
    price_change_days = {
        40: (Decimal("4.50"), "up"),
    }

    result: list[SyntheticDay] = []

    for i in range(days):
        current_date = start_date + timedelta(days=i)

        # CIF: artis trendi (secim doneminde de artar)
        cif = _random_walk_step(cif, Decimal("0.50"), Decimal("2.50"), seed, i, "cif")
        cif = max(cif, Decimal("550.00"))

        # FX: yavas artis
        fx = _random_walk_step(fx, Decimal("0.01"), Decimal("0.12"), seed, i, "fx")
        fx = max(fx, Decimal("30.00"))

        # Rejim: secim donemi gun 0-45
        regime = 1 if i < 45 else 0

        # Fiyat degisikligi
        is_change = i in price_change_days
        change_amount = Decimal("0")
        change_dir = "none"

        if is_change:
            change_amount, change_dir = price_change_days[i]
            pump = pump + change_amount

        result.append(
            SyntheticDay(
                date=current_date,
                fuel_type=fuel_type,
                cif_usd_ton=cif,
                fx_rate=fx,
                pump_price_tl=pump,
                otv_fixed_tl=otv,
                kdv_rate=KDV_RATE,
                is_price_change=is_change,
                change_direction=change_dir,
                change_amount_tl=change_amount,
                regime=regime,
            )
        )

    logger.info(
        "Secim senaryosu uretildi: %d gun, secim donemi=0-45, zam gunu=40",
        days,
    )
    return result


def get_all_scenarios(
    fuel_type: str = "benzin",
) -> dict[str, list[SyntheticDay]]:
    """
    Tum senaryolari uretir.

    Args:
        fuel_type: Yakit tipi.

    Returns:
        Senaryo adi -> SyntheticDay listesi eslemesi.
    """
    return {
        "normal": generate_normal_scenario(fuel_type=fuel_type),
        "fx_shock": generate_fx_shock_scenario(fuel_type=fuel_type),
        "election": generate_election_scenario(fuel_type=fuel_type),
    }


def list_scenarios() -> list[dict[str, str]]:
    """
    Mevcut senaryo listesini dondurur.

    Returns:
        Senaryo bilgi dict'leri.
    """
    return [
        {
            "name": "normal",
            "description": "Normal piyasa: Brent yavas artis, 2-3 zam, 1 indirim (90 gun)",
            "days": "90",
            "price_changes": "4",
        },
        {
            "name": "fx_shock",
            "description": "FX sok: Ani %10 kur sicramasi, hizli + gecikmis zam (60 gun)",
            "days": "60",
            "price_changes": "2",
        },
        {
            "name": "election",
            "description": "Secim: MBE yukselir, 40 gun zam gelmez, sonra buyuk zam (60 gun)",
            "days": "60",
            "price_changes": "1",
        },
    ]
