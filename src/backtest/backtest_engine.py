"""
Backtest Motoru — MBE ve Risk uctan uca dogrulama.

Sentetik veri uzerinde Katman 2 (MBE) ve Katman 3 (Risk/Esik) motorlarini
calistirir. DB bagimliligi YOK — tum hesaplamalar in-memory.

TUM parasal degerler Decimal. Float YASAK.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from src.core.mbe_calculator import (
    MBEResult,
    CostSnapshot,
    _safe_decimal,
    calculate_nc_forward,
    calculate_nc_base_from_pump,
    calculate_sma,
    calculate_full_mbe,
    calculate_cost_snapshot,
    get_regime_config,
    get_rho,
    PRECISION,
)
from src.core.risk_engine import (
    RiskComponents,
    RiskResult,
    calculate_risk_score,
    check_threshold_breach,
)
from src.core.political_delay_tracker import (
    DelayTracker,
    DelayState,
    DelayTransition,
    update_tracker,
)
from src.core.threshold_manager import (
    DEFAULT_THRESHOLDS,
    check_hysteresis,
)
from src.backtest.synthetic_data import (
    SyntheticDay,
    get_all_scenarios,
    DEFAULT_MARGIN,
)

logger = logging.getLogger(__name__)


# --- Sonuc Veri Yapilari ---


@dataclass
class DailyMBERecord:
    """Bir gunluk MBE backtest sonucu."""

    date: date
    fuel_type: str
    cif_usd_ton: Decimal
    fx_rate: Decimal
    pump_price_tl: Decimal
    nc_forward: Decimal
    nc_base: Decimal
    mbe_value: Decimal
    mbe_pct: Decimal
    sma_window: int
    trend_direction: str
    regime: int
    cost_snapshot: CostSnapshot
    is_price_change: bool
    change_direction: str


@dataclass
class DailyRiskRecord:
    """Bir gunluk Risk backtest sonucu."""

    date: date
    fuel_type: str
    composite_score: Decimal
    mbe_component: Decimal
    fx_volatility_component: Decimal
    political_delay_component: Decimal
    threshold_breach_component: Decimal
    trend_momentum_component: Decimal
    system_mode: str
    delay_state: str
    delay_days: int
    alert_triggered: bool
    alert_action: str | None
    is_price_change: bool


@dataclass
class BacktestMBEResult:
    """MBE backtest toplam sonucu."""

    scenario_name: str
    fuel_type: str
    total_days: int
    daily_records: list[DailyMBERecord] = field(default_factory=list)
    price_changes: int = 0
    max_mbe: Decimal = Decimal("0")
    min_mbe: Decimal = Decimal("0")
    avg_mbe: Decimal = Decimal("0")


@dataclass
class BacktestRiskResult:
    """Risk backtest toplam sonucu."""

    scenario_name: str
    fuel_type: str
    total_days: int
    daily_records: list[DailyRiskRecord] = field(default_factory=list)
    total_alerts: int = 0
    max_risk_score: Decimal = Decimal("0")
    avg_risk_score: Decimal = Decimal("0")
    delay_events: int = 0


@dataclass
class ScenarioBacktestResult:
    """Tek senaryo icin tam backtest sonucu."""

    scenario_name: str
    fuel_type: str
    mbe_result: BacktestMBEResult
    risk_result: BacktestRiskResult


@dataclass
class FullBacktestReport:
    """Tum senaryolar x tum yakitlar icin tam rapor."""

    results: list[ScenarioBacktestResult] = field(default_factory=list)
    run_date: date | None = None


# --- MBE Backtest ---


def run_mbe_backtest(
    scenario: list[SyntheticDay],
    fuel_type: str,
    scenario_name: str = "unnamed",
) -> BacktestMBEResult:
    """
    MBE backtest: Sentetik veri uzerinde gunluk MBE hesaplama.

    Her gun:
    1. NC_forward hesapla
    2. NC_base: Son zam gunundeki pompa fiyatindan ters hesapla
    3. SMA, MBE, cost snapshot, trend, delta hesapla
    4. Zam gunlerinde nc_base guncelle

    Args:
        scenario: SyntheticDay listesi.
        fuel_type: Yakit tipi.
        scenario_name: Senaryo adi.

    Returns:
        BacktestMBEResult.
    """
    if not scenario:
        raise ValueError("Senaryo verisi bos olamaz")

    rho = get_rho(fuel_type)
    result = BacktestMBEResult(
        scenario_name=scenario_name,
        fuel_type=fuel_type,
        total_days=len(scenario),
    )

    # NC_forward serisi (pencere icin birikim)
    nc_forward_history: list[Decimal] = []

    # Son zam bilgisi — ilk gun icin baslangic nc_base
    first_day = scenario[0]
    regime_config = get_regime_config(first_day.regime)
    current_nc_base = calculate_nc_base_from_pump(
        pump_price=first_day.pump_price_tl,
        otv=first_day.otv_fixed_tl,
        kdv=first_day.kdv_rate,
        m_total=regime_config.m_total,
    )

    previous_mbe: Decimal | None = None
    mbe_history: list[Decimal] = []
    price_change_count = 0

    for i, day in enumerate(scenario):
        regime_config = get_regime_config(day.regime)

        # NC_forward hesapla
        nc_forward = calculate_nc_forward(
            cif_usd_ton=day.cif_usd_ton,
            fx_rate=day.fx_rate,
            rho=rho,
        )
        nc_forward_history.append(nc_forward)

        # Zam gunu: nc_base guncelle (yeni pompa fiyatindan reverse-engineer)
        if day.is_price_change:
            current_nc_base = calculate_nc_base_from_pump(
                pump_price=day.pump_price_tl,
                otv=day.otv_fixed_tl,
                kdv=day.kdv_rate,
                m_total=regime_config.m_total,
            )
            price_change_count += 1

        # MBE hesapla (full)
        mbe_3_days_ago = mbe_history[-3] if len(mbe_history) >= 3 else None

        mbe_result = calculate_full_mbe(
            nc_forward_series=nc_forward_history,
            nc_base=current_nc_base,
            regime=day.regime,
            previous_mbe=previous_mbe,
            mbe_3_days_ago=mbe_3_days_ago,
        )

        mbe_history.append(mbe_result.mbe_value)
        previous_mbe = mbe_result.mbe_value

        # Cost snapshot
        cost_snap = calculate_cost_snapshot(
            cif_usd_ton=day.cif_usd_ton,
            fx_rate=day.fx_rate,
            pump_price=day.pump_price_tl,
            otv_fixed_tl=day.otv_fixed_tl,
            kdv_rate=day.kdv_rate,
            rho=rho,
            m_total=regime_config.m_total,
        )

        # Daily record
        record = DailyMBERecord(
            date=day.date,
            fuel_type=fuel_type,
            cif_usd_ton=day.cif_usd_ton,
            fx_rate=day.fx_rate,
            pump_price_tl=day.pump_price_tl,
            nc_forward=nc_forward,
            nc_base=current_nc_base,
            mbe_value=mbe_result.mbe_value,
            mbe_pct=mbe_result.mbe_pct,
            sma_window=mbe_result.sma_window,
            trend_direction=mbe_result.trend_direction,
            regime=day.regime,
            cost_snapshot=cost_snap,
            is_price_change=day.is_price_change,
            change_direction=day.change_direction,
        )
        result.daily_records.append(record)

    # Ozet metrikleri hesapla
    result.price_changes = price_change_count
    if mbe_history:
        result.max_mbe = max(mbe_history)
        result.min_mbe = min(mbe_history)
        total = sum(mbe_history)
        count = Decimal(str(len(mbe_history)))
        result.avg_mbe = (total / count).quantize(PRECISION, rounding=ROUND_HALF_UP)

    logger.info(
        "MBE backtest tamamlandi: senaryo=%s, yakit=%s, gun=%d, zam=%d, "
        "max_mbe=%s, min_mbe=%s",
        scenario_name,
        fuel_type,
        len(scenario),
        price_change_count,
        result.max_mbe,
        result.min_mbe,
    )

    return result


# --- Risk Backtest ---


def run_risk_backtest(
    mbe_results: BacktestMBEResult,
    scenario: list[SyntheticDay],
    fuel_type: str,
    scenario_name: str = "unnamed",
) -> BacktestRiskResult:
    """
    Risk backtest: MBE sonuclari uzerinde risk skoru, esik, alert hesaplama.

    Her gun:
    1. FX volatility (son 5 gun std) hesapla
    2. Politik gecikme state machine guncelle
    3. Risk skoru hesapla
    4. Esik kontrolu + alert

    Args:
        mbe_results: MBE backtest sonuclari.
        scenario: Orijinal senaryo verisi.
        fuel_type: Yakit tipi.
        scenario_name: Senaryo adi.

    Returns:
        BacktestRiskResult.
    """
    if not mbe_results.daily_records:
        raise ValueError("MBE sonuclari bos olamaz")

    result = BacktestRiskResult(
        scenario_name=scenario_name,
        fuel_type=fuel_type,
        total_days=len(mbe_results.daily_records),
    )

    # FX gecmisi (volatilite hesabi icin)
    fx_history: list[Decimal] = []

    # Politik gecikme tracker
    delay_tracker = DelayTracker()

    # Alert durumu (hysteresis icin)
    alert_active = False

    # MBE esik degeri (warning seviyesi)
    mbe_threshold_open = Decimal("0.50")

    # Risk esik degerleri
    risk_threshold_open = Decimal("0.60")
    risk_threshold_close = Decimal("0.45")

    total_alerts = 0
    delay_events = 0
    risk_scores: list[Decimal] = []

    for i, (mbe_rec, day) in enumerate(
        zip(mbe_results.daily_records, scenario)
    ):
        # FX volatility: son 5 gunun standart sapmasi
        fx_history.append(day.fx_rate)
        fx_vol = _calculate_fx_volatility(fx_history, window=5)

        # Politik gecikme state machine
        transition = update_tracker(
            tracker=delay_tracker,
            current_mbe=abs(mbe_rec.mbe_value),
            threshold=mbe_threshold_open,
            current_date=day.date.isoformat(),
            price_changed=day.is_price_change,
            partial_change=False,
            regime_type=_regime_to_type(day.regime),
        )

        if transition.should_create_record:
            delay_events += 1

        # Terminal durumlardan IDLE'a don (sonraki cycle icin)
        if delay_tracker.state in (
            DelayState.CLOSED,
            DelayState.ABSORBED,
            DelayState.PARTIAL_CLOSE,
        ):
            # Reset icin bir dummy update
            delay_tracker.state = DelayState.IDLE
            delay_tracker.below_threshold_streak = 0
            delay_tracker.current_delay_days = 0

        # Trend momentum: MBE'nin son 3 gunluk degisim yonu
        trend_momentum = _calculate_trend_momentum(
            mbe_results.daily_records, i
        )

        # Threshold breach bilesen degeri
        # MBE threshold'u asmissa 1, degilse 0
        threshold_breach_val = (
            Decimal("1") if abs(mbe_rec.mbe_value) >= mbe_threshold_open else Decimal("0")
        )

        # Risk skoru hesapla
        components = RiskComponents(
            mbe_value=abs(mbe_rec.mbe_value),
            fx_volatility=fx_vol,
            political_delay=Decimal(str(delay_tracker.current_delay_days)),
            threshold_breach=threshold_breach_val,
            trend_momentum=trend_momentum,
        )

        risk_result = calculate_risk_score(components)
        risk_scores.append(risk_result.composite_score)

        # Alert kontrol (hysteresis)
        alert_triggered = False
        alert_action: str | None = None

        breach = check_threshold_breach(
            composite_score=risk_result.composite_score,
            threshold_open=risk_threshold_open,
            threshold_close=risk_threshold_close,
            previous_alert_active=alert_active,
        )

        if breach is not None:
            alert_triggered = True
            alert_action = breach["action"]
            if alert_action == "open":
                alert_active = True
                total_alerts += 1
            elif alert_action == "close":
                alert_active = False

        # Daily record
        record = DailyRiskRecord(
            date=mbe_rec.date,
            fuel_type=fuel_type,
            composite_score=risk_result.composite_score,
            mbe_component=risk_result.mbe_component,
            fx_volatility_component=risk_result.fx_volatility_component,
            political_delay_component=risk_result.political_delay_component,
            threshold_breach_component=risk_result.threshold_breach_component,
            trend_momentum_component=risk_result.trend_momentum_component,
            system_mode=risk_result.system_mode,
            delay_state=delay_tracker.state.value,
            delay_days=delay_tracker.current_delay_days,
            alert_triggered=alert_triggered,
            alert_action=alert_action,
            is_price_change=day.is_price_change,
        )
        result.daily_records.append(record)

    # Ozet metrikleri
    result.total_alerts = total_alerts
    result.delay_events = delay_events
    if risk_scores:
        result.max_risk_score = max(risk_scores)
        total = sum(risk_scores)
        count = Decimal(str(len(risk_scores)))
        result.avg_risk_score = (total / count).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )

    logger.info(
        "Risk backtest tamamlandi: senaryo=%s, yakit=%s, gun=%d, "
        "alert=%d, max_risk=%s, gecikme_olayi=%d",
        scenario_name,
        fuel_type,
        result.total_days,
        total_alerts,
        result.max_risk_score,
        delay_events,
    )

    return result


# --- Tam Backtest ---


def run_full_backtest(
    fuel_types: list[str] | None = None,
    scenarios: dict[str, list[SyntheticDay]] | None = None,
) -> FullBacktestReport:
    """
    Tum senaryolar x tum yakitlar icin tam backtest.

    Args:
        fuel_types: Yakit tipleri listesi. None ise ["benzin", "motorin"].
        scenarios: Senaryo dict'i. None ise otomatik uretilir.

    Returns:
        FullBacktestReport.
    """
    if fuel_types is None:
        fuel_types = ["benzin", "motorin"]

    report = FullBacktestReport(run_date=date.today())

    for ft in fuel_types:
        if scenarios is not None:
            ft_scenarios = scenarios
        else:
            ft_scenarios = get_all_scenarios(fuel_type=ft)

        for scenario_name, scenario_data in ft_scenarios.items():
            # MBE backtest
            mbe_result = run_mbe_backtest(
                scenario=scenario_data,
                fuel_type=ft,
                scenario_name=scenario_name,
            )

            # Risk backtest
            risk_result = run_risk_backtest(
                mbe_results=mbe_result,
                scenario=scenario_data,
                fuel_type=ft,
                scenario_name=scenario_name,
            )

            report.results.append(
                ScenarioBacktestResult(
                    scenario_name=scenario_name,
                    fuel_type=ft,
                    mbe_result=mbe_result,
                    risk_result=risk_result,
                )
            )

    logger.info(
        "Tam backtest tamamlandi: %d senaryo x yakit kombinasyonu",
        len(report.results),
    )

    return report


# --- Yardimci Fonksiyonlar ---


def _calculate_fx_volatility(
    fx_history: list[Decimal],
    window: int = 5,
) -> Decimal:
    """
    FX volatilite: Son 'window' gunun standart sapmasi.

    Args:
        fx_history: FX degerleri gecmisi.
        window: Pencere genisligi.

    Returns:
        Standart sapma (Decimal).
    """
    if len(fx_history) < 2:
        return Decimal("0")

    # Son window kadar veri al
    data = fx_history[-window:]

    if len(data) < 2:
        return Decimal("0")

    # Ortalama
    count = Decimal(str(len(data)))
    mean = sum(data) / count

    # Varyans
    squared_diffs = [(x - mean) ** 2 for x in data]
    variance = sum(squared_diffs) / count

    # Standart sapma (Newton yontemiyle karekök)
    std = _decimal_sqrt(variance)

    return std.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _decimal_sqrt(value: Decimal, precision: int = 16) -> Decimal:
    """
    Decimal karekök hesaplar (Newton-Raphson yontemi).

    Args:
        value: Karekoku alinacak deger.
        precision: Iterasyon sayisi.

    Returns:
        Karekok degeri (Decimal).
    """
    if value < Decimal("0"):
        raise ValueError("Negatif degerin karekoku alinamaz")
    if value == Decimal("0"):
        return Decimal("0")

    # Baslangic tahmini
    guess = value / Decimal("2")
    for _ in range(precision):
        guess = (guess + value / guess) / Decimal("2")

    return guess.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _calculate_trend_momentum(
    mbe_records: list[DailyMBERecord],
    current_index: int,
    lookback: int = 3,
) -> Decimal:
    """
    Trend momentum: MBE'nin son 'lookback' gunluk degisim yonu.

    Deger [-1, 1] arasinda:
    - Artis trendi: +1
    - Azalis trendi: -1
    - Degisim yok: 0

    Gercek deger: (mbe_son - mbe_ilk) / abs(mbe_ilk) seklinde normalize edilir.
    Sinir degerleri [-1, 1]'e clamp edilir.

    Args:
        mbe_records: MBE gunluk kayitlari.
        current_index: Mevcut gun indeksi.
        lookback: Kac gun geriye bakacagi.

    Returns:
        Trend momentum degeri (Decimal).
    """
    if current_index < 1:
        return Decimal("0")

    start_idx = max(0, current_index - lookback)
    start_mbe = mbe_records[start_idx].mbe_value
    current_mbe = mbe_records[current_index].mbe_value

    if start_mbe == Decimal("0"):
        if current_mbe > Decimal("0"):
            return Decimal("1")
        elif current_mbe < Decimal("0"):
            return Decimal("-1")
        return Decimal("0")

    momentum = (current_mbe - start_mbe) / abs(start_mbe)

    # Clamp [-1, 1]
    if momentum > Decimal("1"):
        momentum = Decimal("1")
    elif momentum < Decimal("-1"):
        momentum = Decimal("-1")

    return momentum.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _regime_to_type(regime: int) -> str | None:
    """Rejim kodunu string tipe cevirir."""
    mapping = {
        0: None,  # Normal — ozel tip yok
        1: "election",
        2: "fx_shock",
        3: "tax_adjustment",
    }
    return mapping.get(regime)
