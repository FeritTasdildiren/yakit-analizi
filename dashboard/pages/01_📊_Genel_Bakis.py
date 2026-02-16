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
    get_latest_mbe,
    get_mbe_history,
    get_latest_risk_score,
    get_latest_prediction,
    get_price_changes_df,
    get_telegram_users_df
)
from dashboard.components.charts import create_mbe_gauge, create_trend_line


st.title("📊 Genel Bakış")

# --- Yakit Turu Filtresi ---
# Kullanici hangi yakit turlerini gormek istedigini secebilir
YAKIT_TURLERI = ["benzin", "motorin", "lpg"]
secili_yakitlar = st.multiselect(
    "Yakıt Türü Filtresi",
    options=YAKIT_TURLERI,
    default=YAKIT_TURLERI,
    format_func=lambda x: x.upper() if x == "lpg" else x.capitalize(),
)

# --- Veri Cekme ---
# Her secili yakit turu icin veri cek
mbe_data: dict = {}
hist_data: dict = {}
risk_data: dict = {}
pred_data: dict = {}

for yt in secili_yakitlar:
    mbe_data[yt] = get_latest_mbe(yt)
    hist_data[yt] = get_mbe_history(yt, 30)
    risk_data[yt] = get_latest_risk_score(yt)
    pred_data[yt] = get_latest_prediction(yt)

# Kullanici Sayisi
users_df = get_telegram_users_df(status="active")
active_user_count = len(users_df) if not users_df.empty else 0

# --- KPI Kartlari ---
# Dinamik kolon sayisi: secili yakit + risk + ML + kullanici = len(secili) + 3
kpi_cols = st.columns(len(secili_yakitlar) + 3)

# Helper for KPI display
def display_kpi(col, label, value, delta=None, delta_color="normal"):
    col.metric(label, value, delta, delta_color=delta_color)

# Yakit bazli MBE KPI'lari
YAKIT_ETIKET = {"benzin": "Benzin", "motorin": "Motorin", "lpg": "LPG"}
for i, yt in enumerate(secili_yakitlar):
    mbe = mbe_data.get(yt)
    val = mbe["value"] if mbe else 0.0
    trend = mbe["trend"] if mbe else "-"
    display_kpi(kpi_cols[i], f"{YAKIT_ETIKET[yt]} MBE", f"{val:+.2f} TL", trend, "off")

# Risk Skoru (tum secili yakitlarin maksimumu)
risk_values = [
    risk_data[yt]["score"] for yt in secili_yakitlar
    if risk_data.get(yt) is not None
]
risk_max = max(risk_values) if risk_values else 0.0
risk_col_idx = len(secili_yakitlar)
display_kpi(
    kpi_cols[risk_col_idx],
    "Risk Skoru",
    f"{risk_max:.0f}/100",
    "⚠️" if risk_max > 60 else "✅",
    "inverse",
)

# ML Durum (herhangi bir yakit icin tahmin varsa "Hazir")
ml_hazir = any(pred_data.get(yt) is not None for yt in secili_yakitlar)
ml_status = "Hazır" if ml_hazir else "Bekliyor"
display_kpi(kpi_cols[risk_col_idx + 1], "ML Durum", ml_status, "v1.0")

# Aktif Kullanici
display_kpi(kpi_cols[risk_col_idx + 2], "Aktif Kullanıcı", str(active_user_count), "👥")

st.divider()

# --- MBE Gosterge ve Trend ---
# Secili yakit sayisina gore dinamik kolon olustur
if secili_yakitlar:
    cols = st.columns(len(secili_yakitlar))

    for i, yt in enumerate(secili_yakitlar):
        etiket = YAKIT_ETIKET[yt]
        # LPG icin farkli ikon kullan
        ikon = "🔥" if yt == "lpg" else "⛽"

        with cols[i]:
            st.subheader(f"{ikon} {etiket} Analizi")
            mbe = mbe_data.get(yt)
            hist = hist_data.get(yt, pd.DataFrame())

            if mbe:
                fig_gauge = create_mbe_gauge(mbe["value"], etiket)
                st.plotly_chart(fig_gauge, use_container_width=True)

            if isinstance(hist, pd.DataFrame) and not hist.empty:
                fig_trend = create_trend_line(
                    hist, "date", "mbe_value",
                    f"{etiket} MBE Trendi (30 Gün)",
                )
                st.plotly_chart(fig_trend, use_container_width=True)
else:
    st.info("Lütfen en az bir yakıt türü seçin.")

st.divider()

# --- Son Fiyat Degisimleri ---
st.subheader("📝 Son Fiyat Değişimleri")
changes_df = get_price_changes_df(limit=10)

if not changes_df.empty:
    # Secili yakitlara gore filtrele (eger fuel kolonu varsa)
    if "fuel" in changes_df.columns and secili_yakitlar:
        changes_filtered = changes_df[changes_df["fuel"].isin(secili_yakitlar)]
    else:
        changes_filtered = changes_df

    if not changes_filtered.empty:
        # Renklendirme fonksiyonu
        def color_direction(val):
            color = 'red' if val == 'increase' else 'green' if val == 'decrease' else 'white'
            return f'color: {color}'

        # Display table with formatting
        st.dataframe(
            changes_filtered.style.map(color_direction, subset=['dir'])
            .format({"amount": "{:.2f} TL"}),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Seçili yakıt türleri için fiyat değişikliği kaydı yok.")
else:
    st.info("Henüz fiyat değişikliği kaydı yok.")
