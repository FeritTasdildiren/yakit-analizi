"""
Backtest API endpoint'leri.

Backtest calistirma, rapor sorgulama ve senaryo listeleme.
Tum endpoint'ler /api/v1/backtest prefix'i altindadir.

DB bagimliligi YOK — tum islemler in-memory.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.backtest.synthetic_data import (
    get_all_scenarios,
    list_scenarios,
    generate_normal_scenario,
    generate_fx_shock_scenario,
    generate_election_scenario,
)
from src.backtest.backtest_engine import (
    run_mbe_backtest,
    run_risk_backtest,
    run_full_backtest,
    FullBacktestReport,
    ScenarioBacktestResult,
)
from src.backtest.metrics import (
    generate_backtest_report,
    evaluate_scenario,
    FullMetricsReport,
    MetricsResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/backtest", tags=["Backtest"])

# --- In-Memory Cache ---
# Son backtest sonucunu hafizada tutar (DB yok)
_last_report: FullMetricsReport | None = None


# --- Pydantic Modelleri ---


class ScenarioInfo(BaseModel):
    """Senaryo bilgi schemasi."""

    name: str
    description: str
    days: str
    price_changes: str


class ScenarioListResponse(BaseModel):
    """Senaryo listesi yaniti."""

    count: int
    scenarios: list[ScenarioInfo]


class BacktestRunRequest(BaseModel):
    """Backtest calistirma istegi."""

    fuel_types: list[str] = Field(
        default=["benzin", "motorin"],
        description="Yakit tipleri listesi",
    )
    scenarios: list[str] | None = Field(
        default=None,
        description="Senaryo adlari (None = tumu)",
    )


class ScenarioMetricResponse(BaseModel):
    """Tek senaryo metrik yaniti."""

    scenario_name: str
    fuel_type: str
    capture_rate: str
    false_alarm_rate: str
    early_warning_days: str
    cost_gap_mean: str
    cost_gap_std: str
    capture_rate_pass: bool
    false_alarm_rate_pass: bool
    early_warning_pass: bool
    cost_gap_pass: bool
    go_decision: bool


class BacktestRunResponse(BaseModel):
    """Backtest calistirma yaniti."""

    overall_go: bool
    decision: str
    run_date: str
    scenario_count: int
    scenario_metrics: list[ScenarioMetricResponse]
    report_markdown: str


class BacktestReportResponse(BaseModel):
    """Son backtest raporu yaniti."""

    available: bool
    report: BacktestRunResponse | None = None


# --- Endpoint'ler ---


@router.get(
    "/scenarios",
    response_model=ScenarioListResponse,
    summary="Mevcut senaryo listesi",
)
async def get_scenarios() -> ScenarioListResponse:
    """Kullanilabilir backtest senaryolarini listeler."""
    scenarios = list_scenarios()
    return ScenarioListResponse(
        count=len(scenarios),
        scenarios=[ScenarioInfo(**s) for s in scenarios],
    )


@router.post(
    "/run",
    response_model=BacktestRunResponse,
    summary="Backtest calistir",
)
async def run_backtest(
    payload: BacktestRunRequest | None = None,
) -> BacktestRunResponse:
    """
    Backtest pipeline'ini calistirir.

    Sentetik veri uzerinde MBE ve Risk motorlarini uctan uca test eder.
    Sonuclari metriklere gore degerlendirir ve Go/No-Go karari verir.
    """
    global _last_report

    if payload is None:
        payload = BacktestRunRequest()

    # Yakit tipi dogrulama
    valid_fuels = {"benzin", "motorin", "lpg"}
    for ft in payload.fuel_types:
        if ft not in valid_fuels:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Gecersiz yakit tipi: '{ft}'. Gecerli: {valid_fuels}",
            )

    try:
        # Tam backtest calistir
        full_report = run_full_backtest(
            fuel_types=payload.fuel_types,
        )

        # Metrik raporu olustur
        metrics_report = generate_backtest_report(full_report)
        _last_report = metrics_report

        # Yanit olustur
        decision = "GO" if metrics_report.overall_go else "NO-GO"

        scenario_responses = []
        for m in metrics_report.scenario_metrics:
            scenario_responses.append(
                ScenarioMetricResponse(
                    scenario_name=m.scenario_name,
                    fuel_type=m.fuel_type,
                    capture_rate=str(m.capture_rate),
                    false_alarm_rate=str(m.false_alarm_rate),
                    early_warning_days=str(m.early_warning_days),
                    cost_gap_mean=str(m.cost_gap_mean),
                    cost_gap_std=str(m.cost_gap_std),
                    capture_rate_pass=m.capture_rate_pass,
                    false_alarm_rate_pass=m.false_alarm_rate_pass,
                    early_warning_pass=m.early_warning_pass,
                    cost_gap_pass=m.cost_gap_pass,
                    go_decision=m.go_decision,
                )
            )

        return BacktestRunResponse(
            overall_go=metrics_report.overall_go,
            decision=decision,
            run_date=str(metrics_report.run_date),
            scenario_count=len(scenario_responses),
            scenario_metrics=scenario_responses,
            report_markdown=metrics_report.report_markdown,
        )

    except Exception as e:
        logger.exception("Backtest calistirma hatasi")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backtest calistirma hatasi: {str(e)}",
        )


@router.get(
    "/report",
    response_model=BacktestReportResponse,
    summary="Son backtest raporu",
)
async def get_report() -> BacktestReportResponse:
    """Son calistirilan backtest raporunu dondurur."""
    if _last_report is None:
        return BacktestReportResponse(available=False)

    decision = "GO" if _last_report.overall_go else "NO-GO"

    scenario_responses = []
    for m in _last_report.scenario_metrics:
        scenario_responses.append(
            ScenarioMetricResponse(
                scenario_name=m.scenario_name,
                fuel_type=m.fuel_type,
                capture_rate=str(m.capture_rate),
                false_alarm_rate=str(m.false_alarm_rate),
                early_warning_days=str(m.early_warning_days),
                cost_gap_mean=str(m.cost_gap_mean),
                cost_gap_std=str(m.cost_gap_std),
                capture_rate_pass=m.capture_rate_pass,
                false_alarm_rate_pass=m.false_alarm_rate_pass,
                early_warning_pass=m.early_warning_pass,
                cost_gap_pass=m.cost_gap_pass,
                go_decision=m.go_decision,
            )
        )

    return BacktestReportResponse(
        available=True,
        report=BacktestRunResponse(
            overall_go=_last_report.overall_go,
            decision=decision,
            run_date=str(_last_report.run_date),
            scenario_count=len(scenario_responses),
            scenario_metrics=scenario_responses,
            report_markdown=_last_report.report_markdown,
        ),
    )
