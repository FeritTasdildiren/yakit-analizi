import streamlit as st
import sys
import os
import pandas as pd

# Path setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from dashboard.components.data_fetcher import (
    get_risk_history_df,
    get_alerts_df,
    get_regime_timeline,
    get_latest_risk_score
)
from dashboard.components.charts import (
    create_risk_heatmap,
    create_risk_breakdown,
    create_regime_timeline
)

st.set_page_config(page_title="Risk Analizi", page_icon="🔥", layout="wide")

st.title("🔥 Risk Analizi")

# --- Veri Cekme ---
risk_history = get_risk_history_df(days=30)
alerts_df = get_alerts_df(limit=50)
regime_df = get_regime_timeline()
current_risk_b = get_latest_risk_score("benzin")
current_risk_m = get_latest_risk_score("motorin")

# --- Risk Skoru KPI ---
c1, c2 = st.columns(2)
score_b = current_risk_b["score"] if current_risk_b else 0
score_m = current_risk_m["score"] if current_risk_m else 0

c1.metric("Benzin Risk Skoru", f"{score_b:.1f}", delta_color="inverse")
c2.metric("Motorin Risk Skoru", f"{score_m:.1f}", delta_color="inverse")

st.divider()

# --- Risk Heatmap & Breakdown ---
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Risk Isı Haritası (30 Gün)")
    if not risk_history.empty:
        fig_heat = create_risk_heatmap(risk_history)
        st.plotly_chart(fig_heat, use_container_width=True)
    else:
        st.info("Risk geçmişi bulunamadı.")

with col2:
    st.subheader("Risk Bileşenleri")
    if not risk_history.empty:
        # Sadece son gunu gosterelim veya stack bar time series
        fig_break = create_risk_breakdown(risk_history)
        st.plotly_chart(fig_break, use_container_width=True)
    else:
        st.info("Risk bileşen verisi yok.")

st.divider()

# --- Rejim Timeline ---
st.subheader("Piyasa Rejimleri")
if not regime_df.empty:
    fig_regime = create_regime_timeline(regime_df)
    st.plotly_chart(fig_regime, use_container_width=True)
else:
    st.info("Rejim kaydı bulunamadı (Varsayılan: Normal).")

st.divider()

# --- Aktif Alertler ---
st.subheader("⚠️ Sistem Alarmları")

if not alerts_df.empty:
    # Renklendirme
    def highlight_level(val):
        color = 'red' if val == 'critical' else 'orange' if val == 'warning' else 'blue'
        return f'color: {color}; font-weight: bold'
    
    st.dataframe(
        alerts_df.style.map(highlight_level, subset=['level']),
        use_container_width=True,
        hide_index=True
    )
else:
    st.success("Aktif alarm yok.")
