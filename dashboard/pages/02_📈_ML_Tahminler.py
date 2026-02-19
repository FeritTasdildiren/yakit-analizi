import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from auth import check_auth, logout
check_auth()

import streamlit as st
import pandas as pd

# Path setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dashboard.components.data_fetcher import (
    get_latest_prediction_v5,
    get_prediction_v5_history_df,
)
from dashboard.components.charts import (
    create_v5_probability_gauge,
    create_v5_prediction_history,
)


st.title("📈 ML Tahmin Analizi")

st.markdown(
    '<div class="info-box">'
    '<span class="info-title">ℹ️ v5 ML Predictor</span><br>'
    '<b>Fiyat Degisim Olasiligi:</b> Binary siniflandirma — fiyat degisecek mi? '
    '0-100% arasinda kalibre edilmis olasilik.<br>'
    '<b>Ilk Hareket:</b> Model degisim ongoruyorsa, beklenen ilk hareket tutari ve yonu.<br>'
    '<b>3 Gun Net:</b> 3 gunluk kumulatif net fiyat etkisi (artis/dusus).<br>'
    '<b>Alarm Esigi:</b> %25 uzerinde degisim bekleniyor sinyali (hibrit alarm: ML + deterministik + anomali).'
    '</div>',
    unsafe_allow_html=True,
)

# ── Yardimci Sabitler ──────────────────────────────────────────────────

_EVENT_TYPE_TR = {
    "artis": ("ZAM", "#EF4444", "⬆️"),
    "dusus": ("INDIRIM", "#22C55E", "⬇️"),
}

_FUEL_ICONS = {"benzin": "⛽", "motorin": "⛽", "lpg": "🔥"}


# ── v5 Render Fonksiyonlari ────────────────────────────────────────────

def render_v5_card(fuel_type, v5_data):
    """v5 tahmin kartini render eder (HTML/CSS)."""
    if not v5_data:
        st.info(f"{fuel_type.capitalize()} icin v5 tahmin verisi bulunamadi.")
        return

    prob = v5_data.get("stage1_probability")
    prob_pct = prob * 100 if prob is not None else 0

    first_type = v5_data.get("first_event_type")
    first_amount = v5_data.get("first_event_amount")
    net_amount = v5_data.get("net_amount_3d")

    event_label, event_color, event_icon = _EVENT_TYPE_TR.get(
        first_type, ("SABIT", "#F59E0B", "➡️")
    )

    alarm_triggered = v5_data.get("alarm_triggered", False)
    alarm_msg = v5_data.get("alarm_message", "")

    first_str = f"{abs(first_amount):.2f} TL/L" if first_amount else "-"
    net_str = f"{abs(net_amount):.2f} TL/L" if net_amount else "-"
    net_dir = ""
    if net_amount:
        net_dir = " (artis)" if net_amount > 0 else " (dusus)"

    calib = v5_data.get("calibration_method", "raw")
    run_date = v5_data.get("date", "-")

    st.markdown(
        f'<div style="padding:1.5rem;border-radius:10px;background-color:#1E293B;'
        f'margin-bottom:1.5rem;border-left:5px solid {event_color};">'
        f'<h3 style="color:{event_color};margin-top:0;">'
        f'{event_icon} {fuel_type.capitalize()}: {event_label}</h3>'
        f'<div style="display:flex;gap:2rem;flex-wrap:wrap;">'
        f'<div><span style="color:#9CA3AF;font-size:0.85rem;">Olasilik (Kalibre)</span>'
        f'<div style="font-size:1.5rem;font-weight:bold;color:{event_color}">%{prob_pct:.1f}</div></div>'
        f'<div><span style="color:#9CA3AF;font-size:0.85rem;">Ilk Hareket</span>'
        f'<div style="font-size:1.2rem;font-weight:bold;">{first_str}</div></div>'
        f'<div><span style="color:#9CA3AF;font-size:0.85rem;">3 Gun Net</span>'
        f'<div style="font-size:1.2rem;font-weight:bold;">{net_str}{net_dir}</div></div>'
        f'<div><span style="color:#9CA3AF;font-size:0.85rem;">Kalibrasyon</span>'
        f'<div style="font-size:1rem;">{calib}</div></div>'
        f'<div><span style="color:#9CA3AF;font-size:0.85rem;">Tarih</span>'
        f'<div style="font-size:1rem;">{run_date}</div></div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # Alarm mesaji (varsa)
    if alarm_triggered and alarm_msg:
        if "Alarm" in alarm_msg:
            alarm_color = "#EF4444"
        elif "Uyar" in alarm_msg:
            alarm_color = "#F59E0B"
        else:
            alarm_color = "#3B82F6"
        st.markdown(
            f'<div style="padding:1rem;border-radius:8px;'
            f'background-color:rgba(239,68,68,0.1);border:1px solid {alarm_color};'
            f'margin-bottom:1rem;">'
            f'<strong style="color:{alarm_color};">🔔 Alarm:</strong> '
            f'{alarm_msg}</div>',
            unsafe_allow_html=True,
        )


def render_v5_tab(fuel_type):
    """Tek yakit turu icin tam v5 tab icerigini render eder."""

    # 1) Veri cek
    v5_data = get_latest_prediction_v5(fuel_type)
    v5_history = get_prediction_v5_history_df(fuel_type, 60)

    # 2) Ana tahmin karti
    render_v5_card(fuel_type, v5_data)

    # 3) Olasilik gauge
    st.subheader("Fiyat Degisim Olasiligi")
    prob = v5_data.get("stage1_probability") if v5_data else None
    fig_gauge = create_v5_probability_gauge(prob, fuel_type)
    st.plotly_chart(
        fig_gauge,
        use_container_width=True,
        config={"displayModeBar": False},
        key=f"{fuel_type}_v5_prob_gauge",
    )

    # 4) Tahmin gecmisi
    hist_count = len(v5_history) if isinstance(v5_history, pd.DataFrame) and not v5_history.empty else 0
    st.subheader(f"Tahmin Gecmisi ({hist_count} Kayit)")
    if hist_count > 0 and hist_count < 3:
        st.info("📊 Backfill verileri dahil. Kesikli cizgi=simulasyon, duz cizgi=gercek tahmin.")
    fig_hist = create_v5_prediction_history(v5_history, fuel_type)
    st.plotly_chart(
        fig_hist,
        use_container_width=True,
        config={"displayModeBar": False},
        key=f"{fuel_type}_v5_pred_history",
    )


# ── Sayfa Layout ───────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs(["⛽ Benzin", "⛽ Motorin", "🔥 LPG"])

with tab1:
    render_v5_tab("benzin")

with tab2:
    render_v5_tab("motorin")

with tab3:
    render_v5_tab("lpg")
