import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from auth import check_auth, logout
check_auth()

import streamlit as st
import pandas as pd

# Path setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dashboard.components.data_fetcher import (
    get_risk_history_df,
    get_alerts_df,
    get_regime_timeline,
    get_latest_risk_score,
    get_latest_mbe,
)
from dashboard.components.charts import (
    create_risk_heatmap,
    create_risk_breakdown,
    create_regime_timeline,
)


st.title("🔥 Risk Analizi")

# Veri Çekme
risk_history = get_risk_history_df(days=30)
alerts_df = get_alerts_df(limit=50)
regime_df = get_regime_timeline()
current_risk_b = get_latest_risk_score("benzin")
current_risk_m = get_latest_risk_score("motorin")
current_risk_l = get_latest_risk_score("lpg")


# KPI Kartları (HTML/CSS)
def render_risk_kpi(label, score, mbe_value=None):
    pct = score * 100 if score else 0
    if pct > 60:
        color = "#EF4444"
        badge = '<span class="badge badge-red">Yüksek</span>'
    elif pct > 30:
        color = "#F59E0B"
        badge = '<span class="badge badge-amber">Orta</span>'
    else:
        color = "#22C55E"
        badge = '<span class="badge badge-green">Düşük</span>'
    # MBE yon bilgisi
    direction_html = ""
    if mbe_value is not None:
        if mbe_value > 0.1:
            direction_html = '<div style="font-size:0.8rem;color:#EF4444;margin-top:4px;">📈 Zam Baskısı</div>'
        elif mbe_value < -0.1:
            direction_html = '<div style="font-size:0.8rem;color:#22C55E;margin-top:4px;">📉 İndirim Olasılığı</div>'
        else:
            direction_html = '<div style="font-size:0.8rem;color:#9CA3AF;margin-top:4px;">➡️ Nötr</div>'
    return (
        '<div class="kpi-card">'
        f'<div class="kpi-label">{label} Risk Skoru</div>'
        f'<div class="kpi-value" style="color:{color}">{pct:.1f}%</div>'
        f'{badge}'
        f'{direction_html}'
        '</div>'
    )


c1, c2, c3 = st.columns(3)
score_b = current_risk_b["score"] if current_risk_b else 0
score_m = current_risk_m["score"] if current_risk_m else 0
score_l = current_risk_l["score"] if current_risk_l else 0

# MBE yon bilgisi icin degerler
mbe_b = get_latest_mbe("benzin")
mbe_m = get_latest_mbe("motorin")
mbe_l = get_latest_mbe("lpg")
mbe_val_b = mbe_b["value"] if mbe_b else None
mbe_val_m = mbe_m["value"] if mbe_m else None
mbe_val_l = mbe_l["value"] if mbe_l else None

c1.markdown(render_risk_kpi("Benzin", score_b, mbe_val_b), unsafe_allow_html=True)
c2.markdown(render_risk_kpi("Motorin", score_m, mbe_val_m), unsafe_allow_html=True)
c3.markdown(render_risk_kpi("LPG", score_l, mbe_val_l), unsafe_allow_html=True)

st.divider()

# Risk Heatmap & Breakdown
st.subheader("Risk Isı Haritası (30 Gün)")
if not risk_history.empty:
    fig_heat = create_risk_heatmap(risk_history)
    st.plotly_chart(fig_heat, use_container_width=True, config={"displayModeBar": False}, key="risk_heatmap")
else:
    st.info("Risk geçmişi bulunamadı.")

st.subheader("Risk Bileşenleri")
st.caption("Her bileşen bağımsız 0-100% arası. Maliyet Farkı: MBE büyüklüğü, Döviz: kur dalgalanması, Politik: son zamdan geçen süre, Eşik: kritik seviyeye yakınlık, Momentum: fiyat trendi.")
if not risk_history.empty:
    tab_b, tab_m, tab_l = st.tabs(["⛽ Benzin", "🛢️ Motorin", "🔥 LPG"])
    with tab_b:
        fig_b = create_risk_breakdown(risk_history, fuel_type="benzin")
        st.plotly_chart(fig_b, use_container_width=True, config={"displayModeBar": False}, key="risk_break_benzin")
    with tab_m:
        fig_m = create_risk_breakdown(risk_history, fuel_type="motorin")
        st.plotly_chart(fig_m, use_container_width=True, config={"displayModeBar": False}, key="risk_break_motorin")
    with tab_l:
        fig_l = create_risk_breakdown(risk_history, fuel_type="lpg")
        st.plotly_chart(fig_l, use_container_width=True, config={"displayModeBar": False}, key="risk_break_lpg")
else:
    st.info("Risk bileşen verisi yok.")

# Risk Bileşenleri Açıklama Kartları
st.markdown(
    '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin:1rem 0;">'
    '<div class="kpi-card" style="text-align:left;padding:1rem;">'
    '<div style="font-weight:bold;color:#636EFA;margin-bottom:0.3rem;">📊 Maliyet Farkı</div>'
    '<div style="font-size:0.85rem;color:#9CA3AF;">Pompa fiyatı ile maliyet arasındaki fark ne kadar büyükse risk o kadar yüksek.</div></div>'
    '<div class="kpi-card" style="text-align:left;padding:1rem;">'
    '<div style="font-weight:bold;color:#EF553B;margin-bottom:0.3rem;">💱 Döviz Dalgalanması</div>'
    '<div style="font-size:0.85rem;color:#9CA3AF;">USD/TRY kurundaki ani değişimler maliyet baskısı yaratır.</div></div>'
    '<div class="kpi-card" style="text-align:left;padding:1rem;">'
    '<div style="font-weight:bold;color:#00CC96;margin-bottom:0.3rem;">🏛️ Politik Dönem</div>'
    '<div style="font-size:0.85rem;color:#9CA3AF;">Seçim, bayram gibi dönemlerde zam ertelenme eğilimi.</div></div>'
    '<div class="kpi-card" style="text-align:left;padding:1rem;">'
    '<div style="font-weight:bold;color:#AB63FA;margin-bottom:0.3rem;">📈 Fiyat Momentumu</div>'
    '<div style="font-size:0.85rem;color:#9CA3AF;">Son dönemdeki fiyat hareketlerinin yönü ve hızı.</div></div>'
    '<div class="kpi-card" style="text-align:left;padding:1rem;">'
    '<div style="font-weight:bold;color:#FFA15A;margin-bottom:0.3rem;">🎯 Eşik Yakınlığı</div>'
    '<div style="font-size:0.85rem;color:#9CA3AF;">Kritik fiyat eşiklerine olan mesafe — yakınsa zam tetiklenebilir.</div></div>'
    '</div>',
    unsafe_allow_html=True,
)

st.divider()

# Rejim Timeline
st.subheader("Piyasa Rejimleri")
st.caption("📅 Piyasa rejimi zaman cizelgesi: Mavi=Normal, Kirmizi=Yukselis, Yesil=Dusus, Sari=Volatil donemler.")
if not regime_df.empty:
    fig_regime = create_regime_timeline(regime_df)
    st.plotly_chart(fig_regime, use_container_width=True, config={"displayModeBar": False}, key="risk_regime_timeline")
else:
    st.info("Rejim kaydı bulunamadı (Varsayılan: Normal).")

st.divider()

# Aktif Alertler
st.subheader("⚠️ Sistem Alarmları")

if not alerts_df.empty:
    def highlight_level(val):
        color = "red" if val == "critical" else "orange" if val == "warning" else "blue"
        return f"color: {color}; font-weight: bold"

    st.dataframe(
        alerts_df.style.map(highlight_level, subset=["level"]),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.success("Aktif alarm yok.")
