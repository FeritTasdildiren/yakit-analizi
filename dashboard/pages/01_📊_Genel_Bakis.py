import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from auth import check_auth, logout
check_auth()

import streamlit as st
import pandas as pd

# Path setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dashboard.components.data_fetcher import (
    get_latest_mbe,
    get_mbe_history,
    get_latest_risk_score,
    get_latest_prediction_v5,
    get_price_changes_df,
    get_telegram_users_df,
)
from dashboard.components.charts import create_mbe_gauge, create_trend_line


st.title("📊 Genel Bakış")

# Bilgi Kutusu
st.markdown(
    '<div class="info-box">'
    '<span class="info-title">ℹ️ Terimler Sözlüğü</span><br>'
    '<b>MBE (Maliyet Baz Etkisi):</b> Pompa fiyatı ile maliyet arasındaki fark. '
    'Pozitif (+) ise hammadde maliyeti yükselîyor (zam baskısı), '
    'Negatif (-) ise hammadde maliyeti düşüyor (indirim olasılığı).<br>'
    '<b>Risk Skoru:</b> 0-100 arası risk göstergesi. '
    'Yüksek skor = Yüksek fiyat değişimi ihtimali. MBE yönüne göre zam veya indirim olabilir.<br>'
    '<b>ML v5:</b> Binary fiyat degisim tahmini — degisim olacak mi? (0-100% olasilik)'
    '</div>',
    unsafe_allow_html=True,
)

# Yakıt Türü Filtresi
YAKIT_TURLERI = ["benzin", "motorin", "lpg"]
secili_yakitlar = st.multiselect(
    "Yakıt Türü Filtresi",
    options=YAKIT_TURLERI,
    default=YAKIT_TURLERI,
    format_func=lambda x: x.upper() if x == "lpg" else x.capitalize(),
)

# Veri Çekme
mbe_data: dict = {}
hist_data: dict = {}
risk_data: dict = {}
pred_v5_data: dict = {}

for yt in secili_yakitlar:
    mbe_data[yt] = get_latest_mbe(yt)
    hist_data[yt] = get_mbe_history(yt, 30)
    risk_data[yt] = get_latest_risk_score(yt)
    pred_v5_data[yt] = get_latest_prediction_v5(yt)

users_df = get_telegram_users_df(status="active")
active_user_count = len(users_df) if not users_df.empty else 0

# KPI Kartları (HTML/CSS)
YAKIT_ETIKET = {"benzin": "Benzin", "motorin": "Motorin", "lpg": "LPG"}
TREND_TR = {"increase": "Zam", "decrease": "İndirim", "stable": "Sabit"}


def render_kpi_card(label, value, sub="", color="#F3F4F6"):
    return (
        '<div class="kpi-card">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value" style="color:{color}">{value}</div>'
        f'<div style="font-size:0.8rem;color:#9CA3AF">{sub}</div>'
        '</div>'
    )


kpi_cols = st.columns(len(secili_yakitlar) + 3)

for i, yt in enumerate(secili_yakitlar):
    mbe = mbe_data.get(yt)
    val = mbe["value"] if mbe else 0.0
    trend_raw = mbe["trend"] if mbe else "-"
    trend = TREND_TR.get(trend_raw, trend_raw)
    color = "#22C55E" if val > 0 else "#EF4444" if val < 0 else "#F3F4F6"
    kpi_cols[i].markdown(
        render_kpi_card(f"{YAKIT_ETIKET[yt]} MBE", f"{val:+.2f} TL", trend, color),
        unsafe_allow_html=True,
    )

# Risk Skoru
risk_items = [
    (yt, risk_data[yt]["score"])
    for yt in secili_yakitlar
    if risk_data.get(yt) is not None
]
if risk_items:
    max_fuel, risk_max = max(risk_items, key=lambda x: x[1])
    risk_pct = risk_max * 100
    fuel_label = YAKIT_ETIKET[max_fuel]
else:
    risk_pct = 0.0
    fuel_label = "-"
risk_color = "#EF4444" if risk_pct > 60 else "#F59E0B" if risk_pct > 30 else "#22C55E"
risk_icon = "⚠️" if risk_pct > 60 else "✅"
risk_sub = f"{risk_icon} {fuel_label}"
idx = len(secili_yakitlar)
kpi_cols[idx].markdown(
    render_kpi_card("Risk Skoru", f"{risk_pct:.0f}/100", risk_sub, risk_color),
    unsafe_allow_html=True,
)

# ML v5 Durumu
ml_v5_hazir = any(pred_v5_data.get(yt) is not None for yt in secili_yakitlar)
ml_status = "Hazır" if ml_v5_hazir else "Bekliyor"
ml_color = "#22C55E" if ml_v5_hazir else "#F59E0B"
kpi_cols[idx + 1].markdown(
    render_kpi_card("ML Durum", ml_status, "v5", ml_color),
    unsafe_allow_html=True,
)

# Aktif Kullanıcı
kpi_cols[idx + 2].markdown(
    render_kpi_card("Aktif Kullanıcı", str(active_user_count), "👥"),
    unsafe_allow_html=True,
)

st.divider()

# MBE Gösterge ve Trend
if secili_yakitlar:
    cols = st.columns(len(secili_yakitlar))

    for i, yt in enumerate(secili_yakitlar):
        etiket = YAKIT_ETIKET[yt]
        ikon = "🔥" if yt == "lpg" else "⛽"

        with cols[i]:
            st.markdown(f"**{ikon} {etiket}**")
            mbe = mbe_data.get(yt)
            hist = hist_data.get(yt, pd.DataFrame())

            if mbe:
                fig_gauge = create_mbe_gauge(mbe["value"], etiket)
                st.plotly_chart(
                    fig_gauge,
                    use_container_width=True,
                    config={"displayModeBar": False},
                    key=f"genel_{yt}_mbe_gauge",
                )

            if isinstance(hist, pd.DataFrame) and not hist.empty:
                fig_trend = create_trend_line(
                    hist, "date", "mbe_value",
                    f"{etiket} MBE Trendi (30 Gun)",
                )
                st.plotly_chart(
                    fig_trend,
                    use_container_width=True,
                    config={"displayModeBar": False},
                    key=f"genel_{yt}_mbe_trend",
                )
else:
    st.info("Lütfen en az bir yakıt türü seçin.")

st.divider()

# Son Fiyat Değişimleri
st.subheader("📝 Son Fiyat Değişimleri")
changes_df = get_price_changes_df(limit=10)

DIR_TR = {"increase": "Zam", "decrease": "İndirim", "stable": "Sabit"}
HEADER_TR = {
    "fuel": "Yakıt",
    "date": "Tarih",
    "dir": "Yön",
    "amount": "Tutar",
    "old_price": "Eski Fiyat",
    "new_price": "Yeni Fiyat",
}

if not changes_df.empty:
    if "fuel" in changes_df.columns and secili_yakitlar:
        changes_filtered = changes_df[changes_df["fuel"].isin(secili_yakitlar)]
    else:
        changes_filtered = changes_df

    if not changes_filtered.empty:
        if "dir" in changes_filtered.columns:
            changes_filtered = changes_filtered.copy()
            changes_filtered["dir"] = changes_filtered["dir"].map(DIR_TR).fillna(
                changes_filtered["dir"]
            )

        display_df = changes_filtered.rename(
            columns={k: v for k, v in HEADER_TR.items() if k in changes_filtered.columns}
        )

        def color_direction(val):
            color = "red" if val == "Zam" else "green" if val == "İndirim" else "white"
            return f"color: {color}"

        dir_col = "Yön" if "Yön" in display_df.columns else "dir"
        fmt = {}
        if "Tutar" in display_df.columns:
            fmt["Tutar"] = "{:.2f} TL"
        elif "amount" in display_df.columns:
            fmt["amount"] = "{:.2f} TL"

        st.dataframe(
            display_df.style.map(color_direction, subset=[dir_col]).format(fmt),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Seçili yakıt türleri için fiyat değişikliği kaydı yok.")
else:
    st.info("Henüz fiyat değişikliği kaydı yok.")
