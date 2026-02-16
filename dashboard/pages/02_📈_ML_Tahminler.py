import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from auth import check_auth, logout
check_auth()

import streamlit as st
import sys
import os
import pandas as pd

# Path setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from dashboard.components.data_fetcher import (
    get_latest_prediction, 
    get_prediction_history_df
)
from dashboard.components.charts import (
    create_probability_bar, 
    create_shap_chart, 
    create_prediction_history
)


st.title("📈 ML Tahmin Analizi")

# --- Veri Cekme ---
pred_benzin = get_latest_prediction("benzin")
hist_benzin = get_prediction_history_df("benzin", 30)

pred_motorin = get_latest_prediction("motorin")
hist_motorin = get_prediction_history_df("motorin", 30)

# --- Helper Function ---
def render_prediction_card(fuel_type, data, history_df):
    if not data:
        st.warning(f"{fuel_type.capitalize()} için tahmin verisi bulunamadı.")
        return

    # Kart Basligi
    direction_map = {
        "hike": ("ZAM", "red", "⬆️"),
        "cut": ("İNDİRİM", "green", "⬇️"),
        "stable": ("SABİT", "orange", "➡️")
    }
    
    direction, color, icon = direction_map.get(data["direction"], ("BİLİNMİYOR", "gray", "❓"))
    prob = max(data["prob_hike"], data["prob_stable"], data["prob_cut"])
    
    st.markdown(f"""
    <div style="padding: 20px; border-radius: 10px; background-color: #262730; margin-bottom: 20px;">
        <h3 style="color: {color}; margin-top: 0;">{icon} {fuel_type.capitalize()}: {direction} (%{prob*100:.1f})</h3>
        <p>Beklenen Değişim: <b>{data['expected_change'] if data['expected_change'] else '-'} TL</b></p>
        <p style="font-size: 0.8em; color: #888;">Model: {data['model']} | Tarih: {data['date']}</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Olasilik Bar
    st.subheader("Olasılık Dağılımı")
    fig_prob = create_probability_bar(data["prob_hike"], data["prob_stable"], data["prob_cut"])
    st.plotly_chart(fig_prob, use_container_width=True, config={'displayModeBar': False})
    
    # SHAP
    st.subheader("Etkileyen Faktörler (SHAP)")
    if data["shap"]:
        fig_shap = create_shap_chart(data["shap"])
        st.plotly_chart(fig_shap, use_container_width=True, config={'displayModeBar': False})
    else:
        st.info("SHAP açıklaması mevcut değil.")
        
    # Gecmis
    st.subheader("Tahmin Geçmişi (30 Gün)")
    if not history_df.empty:
        fig_hist = create_prediction_history(history_df, f"{fuel_type.capitalize()} Tahmin Geçmişi")
        st.plotly_chart(fig_hist, use_container_width=True)
    else:
        st.info("Geçmiş veri yok.")

# --- Layout ---
tab1, tab2 = st.tabs(["⛽ Benzin", "⛽ Motorin"])

with tab1:
    render_prediction_card("benzin", pred_benzin, hist_benzin)

with tab2:
    render_prediction_card("motorin", pred_motorin, hist_motorin)
