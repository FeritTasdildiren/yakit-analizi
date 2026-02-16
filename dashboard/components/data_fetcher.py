"""
Dashboard veri erisim katmani.
Veritabanindan async olarak veri ceker ve Streamlit icin sync wrapper saglar.
"""

import asyncio
import logging
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select, desc, func, update, text
from sqlalchemy.orm import selectinload

from src.models import (
    MBECalculation,
    RiskScore,
    MLPrediction,
    Alert,
    TelegramUser,
    PriceChange,
    DailyMarketData,
    ThresholdConfig,
    RegimeEvent
)
from src.config.settings import settings

logger = logging.getLogger(__name__)

# --- Async Engine ---
engine = create_async_engine(settings.DATABASE_URL, echo=False)

# --- Helpers ---
def to_float(val):
    """Decimal'i float'a cevirir."""
    if isinstance(val, Decimal):
        return float(val)
    return val

def _df_convert_decimals(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame icindeki Decimal kolonlari float'a cevirir."""
    for col in df.columns:
        # Check if column is object type which might hold Decimals
        if df[col].dtype == object:
            try:
                # Try converting one element to check
                if len(df) > 0 and isinstance(df[col].iloc[0], Decimal):
                    df[col] = df[col].apply(lambda x: float(x) if x is not None else None)
            except Exception:
                pass
    return df

# --- Async Data Fetchers ---

async def _fetch_latest_mbe(fuel_type: str):
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(MBECalculation)
            .where(MBECalculation.fuel_type == fuel_type)
            .order_by(desc(MBECalculation.trade_date))
            .limit(1)
        )
        return result.scalar_one_or_none()

async def _fetch_mbe_history(fuel_type: str, days: int):
    start_date = datetime.now().date() - timedelta(days=days)
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(MBECalculation)
            .where(
                MBECalculation.fuel_type == fuel_type,
                MBECalculation.trade_date >= start_date
            )
            .order_by(MBECalculation.trade_date)
        )
        data = result.scalars().all()
        return [
            {
                "date": d.trade_date,
                "mbe_value": to_float(d.mbe_value),
                "mbe_pct": to_float(d.mbe_pct),
                "sma_5": to_float(d.sma_5),
                "sma_10": to_float(d.sma_10),
                "trend": d.trend_direction,
                "fuel_type": d.fuel_type
            }
            for d in data
        ]

async def _fetch_latest_risk(fuel_type: str):
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(RiskScore)
            .where(RiskScore.fuel_type == fuel_type)
            .order_by(desc(RiskScore.trade_date))
            .limit(1)
        )
        return result.scalar_one_or_none()

async def _fetch_risk_history(days: int):
    start_date = datetime.now().date() - timedelta(days=days)
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(RiskScore)
            .where(RiskScore.trade_date >= start_date)
            .order_by(RiskScore.trade_date)
        )
        data = result.scalars().all()
        return [
            {
                "date": d.trade_date,
                "fuel_type": d.fuel_type,
                "score": to_float(d.composite_score),
                "mbe_comp": to_float(d.mbe_component),
                "fx_comp": to_float(d.fx_volatility_component),
                "pol_comp": to_float(d.political_delay_component),
                "trend_comp": to_float(d.trend_momentum_component),
                "threshold_comp": to_float(d.threshold_breach_component),
            }
            for d in data
        ]

async def _fetch_latest_prediction(fuel_type: str):
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(MLPrediction)
            .where(MLPrediction.fuel_type == fuel_type)
            .order_by(desc(MLPrediction.prediction_date))
            .limit(1)
        )
        return result.scalar_one_or_none()

async def _fetch_prediction_history(fuel_type: str, days: int):
    start_date = datetime.now().date() - timedelta(days=days)
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(MLPrediction)
            .where(
                MLPrediction.fuel_type == fuel_type,
                MLPrediction.prediction_date >= start_date
            )
            .order_by(MLPrediction.prediction_date)
        )
        data = result.scalars().all()
        # Gercek degisimleri de cekelim
        prices = await session.execute(
             select(PriceChange)
             .where(
                 PriceChange.fuel_type == fuel_type,
                 PriceChange.change_date >= start_date
             )
        )
        price_map = {p.change_date: to_float(p.change_amount) for p in prices.scalars().all()}
        
        return [
            {
                "date": d.prediction_date,
                "p_hike": to_float(d.probability_hike),
                "p_stable": to_float(d.probability_stable),
                "p_cut": to_float(d.probability_cut),
                "predicted": d.predicted_direction,
                "expected_change": to_float(d.expected_change_tl),
                "actual_change": price_map.get(d.prediction_date, 0.0)
            }
            for d in data
        ]

async def _fetch_alerts(limit: int = 50):
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(Alert)
            .order_by(desc(Alert.created_at))
            .limit(limit)
        )
        data = result.scalars().all()
        return [
            {
                "id": d.id,
                "date": d.created_at,
                "level": d.alert_level,
                "type": d.alert_type,
                "fuel": d.fuel_type,
                "message": d.message,
                "resolved": d.is_resolved
            }
            for d in data
        ]

async def _fetch_telegram_users(status: str = "all"):
    async with AsyncSession(engine) as session:
        query = select(TelegramUser).order_by(desc(TelegramUser.created_at))
        if status == "pending":
            query = query.where(TelegramUser.is_approved == False)
        elif status == "approved":
            query = query.where(TelegramUser.is_approved == True)
        
        result = await session.execute(query)
        data = result.scalars().all()
        return [
            {
                "id": str(d.telegram_id),
                "username": d.username,
                "name": f"{d.first_name or ''} {d.last_name or ''}".strip(),
                "phone": d.phone_number,
                "approved": d.is_approved,
                "active": d.is_active,
                "created_at": d.created_at
            }
            for d in data
        ]

async def _update_telegram_user(user_id: int, approved: bool):
    async with AsyncSession(engine) as session:
        await session.execute(
            update(TelegramUser)
            .where(TelegramUser.telegram_id == user_id)
            .values(is_approved=approved, updated_at=datetime.now())
        )
        await session.commit()

async def _fetch_regime_events():
    async with AsyncSession(engine) as session:
        result = await session.execute(select(RegimeEvent).order_by(RegimeEvent.start_date))
        data = result.scalars().all()
        return [
            {
                "start": d.start_date,
                "end": d.end_date,
                "type": d.regime_type,
                "desc": d.description
            }
            for d in data
        ]

async def _fetch_price_changes(limit: int = 10):
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(PriceChange)
            .order_by(desc(PriceChange.change_date))
            .limit(limit)
        )
        data = result.scalars().all()
        return [
            {
                "date": d.change_date,
                "fuel": d.fuel_type,
                "dir": d.direction,
                "amount": to_float(d.change_amount)
            }
            for d in data
        ]

# --- Streamlit Cache Wrappers ---

@st.cache_data(ttl=60)
def get_latest_mbe(fuel_type: str):
    data = asyncio.run(_fetch_latest_mbe(fuel_type))
    if data:
        return {
            "value": to_float(data.mbe_value),
            "pct": to_float(data.mbe_pct),
            "trend": data.trend_direction,
            "regime": data.regime
        }
    return None

@st.cache_data(ttl=300)
def get_mbe_history(fuel_type: str, days: int = 60):
    data = asyncio.run(_fetch_mbe_history(fuel_type, days))
    return pd.DataFrame(data)

@st.cache_data(ttl=60)
def get_latest_risk_score(fuel_type: str):
    data = asyncio.run(_fetch_latest_risk(fuel_type))
    if data:
        return {
            "score": to_float(data.composite_score),
            "mode": data.system_mode
        }
    return None

@st.cache_data(ttl=300)
def get_risk_history_df(days: int = 30):
    data = asyncio.run(_fetch_risk_history(days))
    return pd.DataFrame(data)

@st.cache_data(ttl=60)
def get_latest_prediction(fuel_type: str):
    data = asyncio.run(_fetch_latest_prediction(fuel_type))
    if data:
        return {
            "direction": data.predicted_direction,
            "prob_hike": to_float(data.probability_hike),
            "prob_stable": to_float(data.probability_stable),
            "expected_change": to_float(data.expected_change_tl),
            "model": data.model_version,
            "date": data.prediction_date,
            "shap": data.shap_top_features
        }
    return None

@st.cache_data(ttl=300)
def get_prediction_history_df(fuel_type: str, days: int = 30):
    data = asyncio.run(_fetch_prediction_history(fuel_type, days))
    return pd.DataFrame(data)

@st.cache_data(ttl=60)
def get_alerts_df(limit: int = 50):
    data = asyncio.run(_fetch_alerts(limit))
    return pd.DataFrame(data)

@st.cache_data(ttl=60)
def get_price_changes_df(limit: int = 10):
    data = asyncio.run(_fetch_price_changes(limit))
    return pd.DataFrame(data)

@st.cache_data(ttl=3600)
def get_regime_timeline():
    data = asyncio.run(_fetch_regime_events())
    return pd.DataFrame(data)

# Users (No cache for admin actions usually, but fetch can be cached briefly)
@st.cache_data(ttl=10) 
def get_telegram_users_df(status: str = "all"):
    data = asyncio.run(_fetch_telegram_users(status))
    return pd.DataFrame(data)

def approve_user(user_id: str, approved: bool):
    """Admin action: Kullaniciyi onayla/reddet."""
    # user_id str gelebilir, int'e cevir
    uid = int(user_id)
    asyncio.run(_update_telegram_user(uid, approved))
    # Clear cache
    get_telegram_users_df.clear()

def get_system_status():
    """Circuit breaker status from API."""
    try:
        # Localhost varsayimi — config'den de alinabilir ama dashboard genelde ayni makinede
        resp = requests.get("http://localhost:8000/api/v1/ml/health", timeout=2)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None
