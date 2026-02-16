import pytest
import pandas as pd
import plotly.graph_objects as go
from unittest.mock import MagicMock, patch

from dashboard.components.charts import (
    create_mbe_gauge,
    create_trend_line,
    create_risk_heatmap,
    create_probability_bar
)
from dashboard.components.data_fetcher import get_latest_mbe

# --- Charts Tests ---

def test_create_mbe_gauge():
    fig = create_mbe_gauge(1.5, "benzin")
    assert isinstance(fig, go.Figure)
    # Title is in the indicator trace, not layout
    assert fig.data[0].title.text == "Benzin MBE (TL/L)"

def test_create_trend_line():
    df = pd.DataFrame({
        "date": pd.date_range(start="2023-01-01", periods=10),
        "mbe_value": range(10),
        "sma_5": range(10),
        "sma_10": range(10)
    })
    fig = create_trend_line(df, "date", "mbe_value", "Test Trend")
    assert isinstance(fig, go.Figure)
    assert fig.layout.title.text == "Test Trend"

def test_create_risk_heatmap():
    df = pd.DataFrame({
        "date": pd.date_range(start="2023-01-01", periods=5),
        "fuel_type": ["benzin"]*5,
        "score": [10, 20, 30, 40, 50]
    })
    fig = create_risk_heatmap(df)
    assert isinstance(fig, go.Figure)

def test_create_probability_bar():
    fig = create_probability_bar(0.7, 0.2, 0.1)
    assert isinstance(fig, go.Figure)
    # Check data
    assert fig.data[0].x[0] == 0.7
    assert fig.data[1].x[0] == 0.2

# --- Data Fetcher Tests ---

@patch("dashboard.components.data_fetcher.asyncio.run")
def test_get_latest_mbe(mock_run):
    # Mock return value of async function
    mock_data = MagicMock()
    mock_data.mbe_value = 1.23
    mock_data.mbe_pct = 12.3
    mock_data.trend_direction = "increase"
    mock_data.regime = 0
    
    mock_run.return_value = mock_data
    
    result = get_latest_mbe("benzin")
    
    assert result is not None
    assert result["value"] == 1.23
    assert result["trend"] == "increase"
    
    # Test empty return
    mock_run.return_value = None
    result_empty = get_latest_mbe("motorin")
    assert result_empty is None
