"""
Backtest Performans Metrikleri ve Go/No-Go Rapor Jeneratoru.

Metrikler:
    - Capture Rate: Zam oncesi alarm orani (hedef >= 0.70)
    - False Alarm Rate: Yanlis alarm orani (hedef <= 0.40)
    - Early Warning Days: Ortalama onceden uyari suresi (hedef 1-7 gun)
    - Cost Gap Accuracy: Maliyet ayristirma dogrulugu (hedef std < 3.0 TRY/L)

TUM parasal degerler Decimal. Float YASAK.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass

from src.backtest.backtest_engine import (
    BacktestMBEResult,
    BacktestRiskResult,
    DailyMBERecord,
    DailyRiskRecord,
    FullBacktestReport,
    ScenarioBacktestResult,
    _decimal_sqrt,
)

logger = logging.getLogger(__name__)

# --- Go/No-Go Esik Degerleri ---

CAPTURE_RATE_THRESHOLD = Decimal("0.70")
FALSE_ALARM_RATE_THRESHOLD = Decimal("0.40")
EARLY_WARNING_MIN_DAYS = 1
EARLY_WARNING_MAX_DAYS = 7
COST_GAP_STD_THRESHOLD = Decimal("3.0")


# --- Veri Yapilari ---


@dataclass
class MetricsResult:
    """Tek senaryo icin metrik sonuclari."""

    scenario_name: str
    fuel_type: str
    capture_rate: Decimal
    false_alarm_rate: Decimal
    early_warning_days: Decimal
    cost_gap_mean: Decimal
    cost_gap_std: Decimal
    capture_rate_pass: bool
    false_alarm_rate_pass: bool
    early_warning_pass: bool
    cost_gap_pass: bool
    go_decision: bool


@dataclass
class FullMetricsReport:
    """Tum senaryolar icin metrik raporu."""

    scenario_metrics: list[MetricsResult]
    overall_go: bool
    report_markdown: str
    run_date: date


# --- Metrik Hesaplama Fonksiyonlari ---


def calculate_capture_rate(
    risk_records: list[DailyRiskRecord],
    mbe_records: list[DailyMBERecord],
    window: int = 7,
) -> Decimal:
    """
    Capture Rate: Fiyat degisikligi oncesi alert orani.

    Tum fiyat degisiklik gunlerini bulur. Her biri icin onceki 'window'
    gun icinde en az bir alert (open) tetiklenmis mi kontrol eder.

    capture_rate = yakalanan_zamlar / toplam_zamlar

    Args:
        risk_records: Risk backtest gunluk kayitlari.
        mbe_records: MBE backtest gunluk kayitlari.
        window: Alert penceresi (gun).

    Returns:
        Capture rate [0, 1] (Decimal).
    """
    # Fiyat degisiklik gunlerini bul
    change_indices = [
        i for i, rec in enumerate(mbe_records) if rec.is_price_change
    ]

    if not change_indices:
        return Decimal("1")  # Zam yoksa %100 capture (vakuum)

    captured = 0

    for change_idx in change_indices:
        # Onceki window gun icinde alert var mi?
        window_start = max(0, change_idx - window)
        window_records = risk_records[window_start:change_idx]

        has_alert = any(
            rec.alert_triggered and rec.alert_action == "open"
            for rec in window_records
        )

        if has_alert:
            captured += 1

    total = len(change_indices)
    rate = (Decimal(str(captured)) / Decimal(str(total))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )

    logger.info(
        "Capture rate: %d/%d = %s (pencere=%d gun)",
        captured,
        total,
        rate,
        window,
    )

    return rate


def calculate_false_alarm_rate(
    risk_records: list[DailyRiskRecord],
    mbe_records: list[DailyMBERecord],
    window: int = 7,
) -> Decimal:
    """
    False Alarm Rate: Fiyat degisikligi gelmeyen alert orani.

    Tum alert (open) gunlerini bulur. Her biri icin sonraki 'window'
    gun icinde fiyat degisikligi var mi kontrol eder.

    false_alarm_rate = yanlis_alarmlar / toplam_alarmlar

    Args:
        risk_records: Risk backtest gunluk kayitlari.
        mbe_records: MBE backtest gunluk kayitlari.
        window: Dogrulama penceresi (gun).

    Returns:
        False alarm rate [0, 1] (Decimal).
    """
    # Alert gunlerini bul
    alert_indices = [
        i
        for i, rec in enumerate(risk_records)
        if rec.alert_triggered and rec.alert_action == "open"
    ]

    if not alert_indices:
        return Decimal("0")  # Alert yoksa false alarm da yok

    false_alarms = 0

    for alert_idx in alert_indices:
        # Sonraki window gun icinde fiyat degisikligi var mi?
        window_end = min(len(mbe_records), alert_idx + window + 1)
        window_records = mbe_records[alert_idx:window_end]

        has_change = any(rec.is_price_change for rec in window_records)

        if not has_change:
            false_alarms += 1

    total = len(alert_indices)
    rate = (Decimal(str(false_alarms)) / Decimal(str(total))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )

    logger.info(
        "False alarm rate: %d/%d = %s (pencere=%d gun)",
        false_alarms,
        total,
        rate,
        window,
    )

    return rate


def calculate_early_warning_days(
    risk_records: list[DailyRiskRecord],
    mbe_records: list[DailyMBERecord],
) -> Decimal:
    """
    Early Warning Days: Alert ile fiyat degisikligi arasindaki ortalama gun.

    Her fiyat degisikligi icin en yakin onceki alert'i bulur ve
    aradaki gun sayisini hesaplar. Ortalama alir.

    Args:
        risk_records: Risk backtest gunluk kayitlari.
        mbe_records: MBE backtest gunluk kayitlari.

    Returns:
        Ortalama erken uyari gun sayisi (Decimal).
    """
    # Fiyat degisiklik indeksleri
    change_indices = [
        i for i, rec in enumerate(mbe_records) if rec.is_price_change
    ]

    # Alert indeksleri
    alert_indices = [
        i
        for i, rec in enumerate(risk_records)
        if rec.alert_triggered and rec.alert_action == "open"
    ]

    if not change_indices or not alert_indices:
        return Decimal("0")

    warning_days: list[int] = []

    for change_idx in change_indices:
        # En yakin onceki alert'i bul
        preceding_alerts = [a for a in alert_indices if a < change_idx]
        if preceding_alerts:
            closest_alert = max(preceding_alerts)
            days_before = change_idx - closest_alert
            warning_days.append(days_before)

    if not warning_days:
        return Decimal("0")

    total = Decimal(str(sum(warning_days)))
    count = Decimal(str(len(warning_days)))

    avg = (total / count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    logger.info(
        "Early warning days: ortalama=%s, ornekler=%s",
        avg,
        warning_days,
    )

    return avg


def calculate_cost_gap_accuracy(
    mbe_records: list[DailyMBERecord],
) -> tuple[Decimal, Decimal]:
    """
    Maliyet ayristirma dogrulugu: Cost gap mean ve std.

    Args:
        mbe_records: MBE backtest gunluk kayitlari.

    Returns:
        (mean_gap, std_gap) tuple'i (Decimal).
    """
    gaps = [abs(rec.cost_snapshot.cost_gap_tl) for rec in mbe_records]

    if not gaps:
        return Decimal("0"), Decimal("0")

    count = Decimal(str(len(gaps)))
    mean_gap = (sum(gaps) / count).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )

    if len(gaps) < 2:
        return mean_gap, Decimal("0")

    # Standart sapma
    squared_diffs = [(g - mean_gap) ** 2 for g in gaps]
    variance = sum(squared_diffs) / count
    std_gap = _decimal_sqrt(variance)

    return mean_gap, std_gap.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# --- Senaryo Metrikleri ---


def evaluate_scenario(
    scenario_result: ScenarioBacktestResult,
) -> MetricsResult:
    """
    Tek senaryo icin tum metrikleri hesaplar ve Go/No-Go karar verir.

    Args:
        scenario_result: Senaryo backtest sonucu.

    Returns:
        MetricsResult.
    """
    mbe_recs = scenario_result.mbe_result.daily_records
    risk_recs = scenario_result.risk_result.daily_records

    # Metrikleri hesapla
    capture = calculate_capture_rate(risk_recs, mbe_recs)
    false_alarm = calculate_false_alarm_rate(risk_recs, mbe_recs)
    early_warn = calculate_early_warning_days(risk_recs, mbe_recs)
    cost_mean, cost_std = calculate_cost_gap_accuracy(mbe_recs)

    # Go/No-Go kontrolleri
    capture_pass = capture >= CAPTURE_RATE_THRESHOLD
    false_alarm_pass = false_alarm <= FALSE_ALARM_RATE_THRESHOLD
    early_warn_pass = (
        Decimal(str(EARLY_WARNING_MIN_DAYS)) <= early_warn <= Decimal(str(EARLY_WARNING_MAX_DAYS))
        if early_warn > Decimal("0")
        else True  # Uyari yoksa (zam yoksa) pass
    )
    cost_pass = cost_std < COST_GAP_STD_THRESHOLD

    go = capture_pass and false_alarm_pass and early_warn_pass and cost_pass

    return MetricsResult(
        scenario_name=scenario_result.scenario_name,
        fuel_type=scenario_result.fuel_type,
        capture_rate=capture,
        false_alarm_rate=false_alarm,
        early_warning_days=early_warn,
        cost_gap_mean=cost_mean,
        cost_gap_std=cost_std,
        capture_rate_pass=capture_pass,
        false_alarm_rate_pass=false_alarm_pass,
        early_warning_pass=early_warn_pass,
        cost_gap_pass=cost_pass,
        go_decision=go,
    )


# --- Rapor Jeneratoru ---


def generate_backtest_report(
    full_report: FullBacktestReport,
) -> FullMetricsReport:
    """
    Tam backtest raporu olusturur: Metrikler + Markdown + Go/No-Go karar.

    Args:
        full_report: FullBacktestReport.

    Returns:
        FullMetricsReport.
    """
    scenario_metrics: list[MetricsResult] = []

    for result in full_report.results:
        metrics = evaluate_scenario(result)
        scenario_metrics.append(metrics)

    # Overall Go: Tum senaryolar pass etmeli
    overall_go = all(m.go_decision for m in scenario_metrics) if scenario_metrics else False

    # Markdown rapor olustur
    md = _build_markdown_report(scenario_metrics, overall_go, full_report.run_date)

    return FullMetricsReport(
        scenario_metrics=scenario_metrics,
        overall_go=overall_go,
        report_markdown=md,
        run_date=full_report.run_date or date.today(),
    )


def _build_markdown_report(
    metrics: list[MetricsResult],
    overall_go: bool,
    run_date: date | None,
) -> str:
    """Markdown formatinda backtest raporu olusturur."""
    decision = "GO" if overall_go else "NO-GO"
    decision_emoji = "BASARILI" if overall_go else "BASARISIZ"

    lines = [
        "# Backtest Raporu — Deterministik Cekirdek Dogrulama",
        "",
        f"**Tarih:** {run_date or date.today()}",
        f"**Karar:** **{decision}** ({decision_emoji})",
        "",
        "---",
        "",
        "## Go/No-Go Kriterleri",
        "",
        "| Metrik | Esik | Durum |",
        "|--------|------|-------|",
        f"| Capture Rate | >= {CAPTURE_RATE_THRESHOLD} | {'GECTI' if all(m.capture_rate_pass for m in metrics) else 'KALDI'} |",
        f"| False Alarm Rate | <= {FALSE_ALARM_RATE_THRESHOLD} | {'GECTI' if all(m.false_alarm_rate_pass for m in metrics) else 'KALDI'} |",
        f"| Early Warning | {EARLY_WARNING_MIN_DAYS}-{EARLY_WARNING_MAX_DAYS} gun | {'GECTI' if all(m.early_warning_pass for m in metrics) else 'KALDI'} |",
        f"| Cost Gap Std | < {COST_GAP_STD_THRESHOLD} TRY/L | {'GECTI' if all(m.cost_gap_pass for m in metrics) else 'KALDI'} |",
        "",
        "---",
        "",
        "## Senaryo Detaylari",
        "",
    ]

    for m in metrics:
        pass_fail = "GECTI" if m.go_decision else "KALDI"
        lines.extend([
            f"### {m.scenario_name} ({m.fuel_type}) — {pass_fail}",
            "",
            "| Metrik | Deger | Esik | Sonuc |",
            "|--------|-------|------|-------|",
            f"| Capture Rate | {m.capture_rate} | >= {CAPTURE_RATE_THRESHOLD} | {'GECTI' if m.capture_rate_pass else 'KALDI'} |",
            f"| False Alarm Rate | {m.false_alarm_rate} | <= {FALSE_ALARM_RATE_THRESHOLD} | {'GECTI' if m.false_alarm_rate_pass else 'KALDI'} |",
            f"| Early Warning Days | {m.early_warning_days} | {EARLY_WARNING_MIN_DAYS}-{EARLY_WARNING_MAX_DAYS} | {'GECTI' if m.early_warning_pass else 'KALDI'} |",
            f"| Cost Gap Mean | {m.cost_gap_mean} TRY/L | - | - |",
            f"| Cost Gap Std | {m.cost_gap_std} TRY/L | < {COST_GAP_STD_THRESHOLD} | {'GECTI' if m.cost_gap_pass else 'KALDI'} |",
            "",
        ])

    lines.extend([
        "---",
        "",
        "## Sonuc",
        "",
    ])

    if overall_go:
        lines.extend([
            f"**{decision}** — Tum senaryolar tum kriterleri karsiladi.",
            "Katman 4 (ML) gecisine hazir.",
        ])
    else:
        failed = [m for m in metrics if not m.go_decision]
        lines.append(f"**{decision}** — {len(failed)} senaryo kriterlerden gecemedi:")
        for m in failed:
            reasons = []
            if not m.capture_rate_pass:
                reasons.append(f"Capture Rate ({m.capture_rate} < {CAPTURE_RATE_THRESHOLD})")
            if not m.false_alarm_rate_pass:
                reasons.append(f"False Alarm Rate ({m.false_alarm_rate} > {FALSE_ALARM_RATE_THRESHOLD})")
            if not m.early_warning_pass:
                reasons.append(f"Early Warning ({m.early_warning_days} gun)")
            if not m.cost_gap_pass:
                reasons.append(f"Cost Gap Std ({m.cost_gap_std} >= {COST_GAP_STD_THRESHOLD})")
            lines.append(f"- **{m.scenario_name}/{m.fuel_type}**: {', '.join(reasons)}")

        lines.extend([
            "",
            "Katman 4 (ML) gecisi icin once bu sorunlarin giderilmesi gerekir.",
        ])

    return "\n".join(lines)
