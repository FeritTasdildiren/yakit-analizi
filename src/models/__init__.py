"""
Veritabanı modelleri.

Tüm SQLAlchemy model sınıfları burada import edilerek mapper registry'ye
kaydedilir. Bu sayede relationship() içindeki string referanslar
(ör: relationship("DailyMarketData")) doğru şekilde çözümlenir.
"""

from src.models.base import Base  # noqa: F401
from src.models.market_data import DailyMarketData  # noqa: F401
from src.models.tax_parameters import TaxParameter  # noqa: F401
from src.models.cost_base_snapshots import CostBaseSnapshot  # noqa: F401
from src.models.price_changes import PriceChange  # noqa: F401
from src.models.mbe_calculations import MBECalculation  # noqa: F401
from src.models.regime_events import RegimeEvent  # noqa: F401
from src.models.threshold_config import ThresholdConfig  # noqa: F401
from src.models.risk_scores import RiskScore  # noqa: F401
from src.models.political_delay_history import PoliticalDelayHistory  # noqa: F401
from src.models.alerts import Alert  # noqa: F401
from src.models.ml_predictions import MLPrediction  # noqa: F401
from src.models.users import TelegramUser  # noqa: F401

__all__ = [
    "Base",
    "DailyMarketData",
    "TaxParameter",
    "CostBaseSnapshot",
    "PriceChange",
    "MBECalculation",
    "RegimeEvent",
    "ThresholdConfig",
    "RiskScore",
    "PoliticalDelayHistory",
    "Alert",
    "MLPrediction",
    "TelegramUser",
]
