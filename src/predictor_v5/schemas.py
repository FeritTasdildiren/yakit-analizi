from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict

class PredictionV5Result(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_date: date
    fuel_type: str
    stage1_probability: Decimal
    first_event_direction: Optional[int] = None
    first_event_amount: Optional[Decimal] = None
    first_event_type: Optional[str] = None
    net_amount_3d: Optional[Decimal] = None
    alarm_triggered: bool = False
    alarm_suppressed: bool = False
    suppression_reason: Optional[str] = None
    alarm_message: Optional[str] = None
    model_version: Optional[str] = None
    calibration_method: Optional[str] = None

class FeatureSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_date: date
    fuel_type: str
    features: Dict[str, float]
    feature_version: Optional[str] = None

class BacktestFoldMetrics(BaseModel):
    fold_idx: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float
    avg_precision: float
    brier_score: float

class BacktestMetrics(BaseModel):
    folds: List[BacktestFoldMetrics]
    mean_accuracy: float
    mean_roc_auc: float
    mean_f1: float

class AlarmState(BaseModel):
    is_alarm: bool
    message: str
    probability: float
    suppressed: bool
    reason: Optional[str] = None
