"""
Plotly grafik bilesenleri — v3 (v5 ML Gecis).
v1 ML fonksiyonlari kaldirildi, v5 gauge/history eklendi.
MBE/Risk fonksiyonlari korundu.
"""

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np

# ── Turkce Eslesme Tablolari ──────────────────────────────────────────────

RISK_COMP_TR = {
    "mbe_comp": "Maliyet Farki",
    "fx_comp": "Doviz Dalgalanmasi",
    "pol_comp": "Politik Donem",
    "trend_comp": "Fiyat Momentumu",
    "threshold_comp": "Esik Yakinligi",
}

YAKIT_TR = {"benzin": "BENZIN", "motorin": "MOTORIN", "lpg": "LPG"}

# ── Ortak Layout Ayarlari ─────────────────────────────────────────────────

_COMMON_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="white", family="sans-serif", size=13),
    modebar=dict(orientation="v", bgcolor="rgba(0,0,0,0)"),
)


def _base_layout(**kw):
    """Ortak layout + ozel parametreler."""
    layout = dict(_COMMON_LAYOUT)
    layout.update(kw)
    return layout



def _hex_to_rgba(hex_color, opacity=0.4):
    """Hex rengi rgba formatina cevir."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{opacity})"

# ══════════════════════════════════════════════════════════════════════════
# A) MBE GAUGE
# ══════════════════════════════════════════════════════════════════════════

def create_mbe_gauge(value, fuel_type):
    """MBE Gostergesi — gelistirilmis versiyon."""
    max_val = 2.0

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=round(value, 3),
        domain={"x": [0, 1], "y": [0.18, 1]},
        title={"text": f"⛽ {fuel_type.capitalize()} MBE (TL/L)",
               "font": {"size": 14}},
        number={"font": {"size": 28}, "suffix": " TL",
                "valueformat": "+.3f"},
        delta={"reference": 0.0, "valueformat": "+.2f",
               "increasing": {"color": "#22C55E"},
               "decreasing": {"color": "#EF4444"}},
        gauge={
            "axis": {
                "range": [-max_val, max_val],
                "tickwidth": 2,
                "tickcolor": "#6B7280",
                "tickvals": [-2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2],
                "tickfont": {"size": 11},
            },
            "bar": {"color": "rgba(255,255,255,0.85)", "thickness": 0.25},
            "bgcolor": "#1E1E1E",
            "steps": [
                {"range": [-max_val, -0.75], "color": "#DC2626"},
                {"range": [-0.75, -0.25], "color": "#F97316"},
                {"range": [-0.25, 0.25], "color": "#22C55E"},
                {"range": [0.25, 0.75], "color": "#F97316"},
                {"range": [0.75, max_val], "color": "#DC2626"},
            ],
            "threshold": {
                "line": {"color": "#FACC15", "width": 5},
                "thickness": 0.85,
                "value": value,
            },
        },
    ))

    # Gauge altina aciklama
    if value > 0.25:
        aciklama = "✅ Dagitici karli — zam riski dusuk"
        ann_color = "#22C55E"
    elif value < -0.25:
        aciklama = "⚠️ Dagitici zararda — zam riski yuksek"
        ann_color = "#EF4444"
    else:
        aciklama = "➡️ Denge bolgesinde — dikkatli takip edin"
        ann_color = "#F59E0B"

    fig.add_annotation(
        text=f"<b>{aciklama}</b>",
        xref="paper", yref="paper",
        x=0.5, y=-0.02,
        showarrow=False,
        font=dict(size=11, color=ann_color),
    )

    fig.update_layout(
        **_base_layout(
            height=400,
            margin=dict(l=20, r=20, t=60, b=50),
        )
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════
# B) TREND LINE (Alan Grafigi)
# ══════════════════════════════════════════════════════════════════════════

def create_trend_line(df: pd.DataFrame, x_col, y_col, title):
    """MBE Trend — alan grafigi, sifir cizgisi belirgin."""
    if df.empty:
        return go.Figure()

    fig = go.Figure()

    y_vals = df[y_col].values
    x_vals = df[x_col]

    # Pozitif alan (yesil)
    y_pos = [max(0, v) for v in y_vals]
    fig.add_trace(go.Scatter(
        x=x_vals, y=y_pos,
        fill="tozeroy", mode="lines",
        line=dict(color="rgba(34,197,94,0.7)", width=0),
        fillcolor="rgba(34,197,94,0.25)",
        name="Kar Bolgesi",
        showlegend=True,
        hoverinfo="skip",
    ))

    # Negatif alan (kirmizi)
    y_neg = [min(0, v) for v in y_vals]
    fig.add_trace(go.Scatter(
        x=x_vals, y=y_neg,
        fill="tozeroy", mode="lines",
        line=dict(color="rgba(239,68,68,0.7)", width=0),
        fillcolor="rgba(239,68,68,0.25)",
        name="Zarar Bolgesi",
        showlegend=True,
        hoverinfo="skip",
    ))

    # Ana cizgi
    fig.add_trace(go.Scatter(
        x=x_vals, y=y_vals,
        mode="lines+markers",
        name="MBE Degeri",
        line=dict(color="#FF6B35", width=3),
        marker=dict(size=4, color="#FF6B35"),
        hovertemplate="<b>%{x}</b><br>MBE: %{y:+.3f} TL/L<extra></extra>",
    ))

    # SMA cizgileri (solid, kalin)
    if "sma_5" in df.columns:
        fig.add_trace(go.Scatter(
            x=x_vals, y=df["sma_5"],
            name="SMA-5 (Kisa Vade)",
            line=dict(color="#00CC96", width=2),
            hovertemplate="SMA-5: %{y:.3f}<extra></extra>",
        ))

    if "sma_10" in df.columns:
        fig.add_trace(go.Scatter(
            x=x_vals, y=df["sma_10"],
            name="SMA-10 (Uzun Vade)",
            line=dict(color="#AB63FA", width=2),
            hovertemplate="SMA-10: %{y:.3f}<extra></extra>",
        ))

    # Sifir cizgisi (zam/kar siniri)
    fig.add_hline(
        y=0, line_width=2, line_dash="dash",
        line_color="#FACC15",
        annotation_text="Denge Noktasi (0)",
        annotation_font=dict(color="#FACC15", size=11),
        annotation_position="top left",
    )

    fig.update_layout(
        **_base_layout(
            xaxis_title="",
            yaxis_title="TL/L",
            hovermode="x unified",
            height=400,
            margin=dict(l=0, r=0, t=20, b=0),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02,
                xanchor="right", x=1, font=dict(size=11),
            ),
        )
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════
# C) RISK HEATMAP
# ══════════════════════════════════════════════════════════════════════════

def create_risk_heatmap(df: pd.DataFrame):
    """Risk Isi Haritasi — renkli, degerli."""
    if df.empty:
        return go.Figure()

    pivot_df = df.pivot(index="date", columns="fuel_type", values="score")

    # 0-1 -> 0-100 donusumu
    pivot_pct = pivot_df * 100

    # Y-eksen etiketlerini Turkcelestir
    col_map = {c: YAKIT_TR.get(c, c.upper()) for c in pivot_pct.columns}
    pivot_pct = pivot_pct.rename(columns=col_map)

    z_vals = pivot_pct.T.values
    y_labels = list(pivot_pct.columns)
    x_labels = [str(d) for d in pivot_pct.index]

    # Annotation metinleri
    annotations = []
    for i, row_label in enumerate(y_labels):
        for j, col_label in enumerate(x_labels):
            val = z_vals[i][j]
            txt_color = "white" if val > 50 else "#E5E7EB"
            annotations.append(dict(
                text=f"{val:.0f}",
                x=col_label, y=row_label,
                xref="x", yref="y",
                showarrow=False,
                font=dict(color=txt_color, size=10),
            ))

    # Ozel renk skalasi: yesil(0-30) -> sari(30-60) -> kirmizi(60-100)
    custom_colorscale = [
        [0.0, "#16A34A"],
        [0.3, "#22C55E"],
        [0.45, "#FACC15"],
        [0.6, "#F97316"],
        [0.8, "#EF4444"],
        [1.0, "#991B1B"],
    ]

    fig = go.Figure(go.Heatmap(
        z=z_vals,
        x=x_labels,
        y=y_labels,
        colorscale=custom_colorscale,
        zmin=0, zmax=100,
        colorbar=dict(
            title=dict(text="Risk Skoru (%)", font=dict(size=12)),
            tickvals=[0, 25, 50, 75, 100],
            ticktext=["0", "25", "50", "75", "100"],
            len=0.9,
        ),
        hovertemplate="<b>%{y}</b> | %{x}<br>Risk: %{z:.1f}%<extra></extra>",
    ))

    fig.update_layout(
        **_base_layout(
            height=350,
            margin=dict(l=10, r=10, t=30, b=100),
            xaxis=dict(
                tickangle=-45,
                title="Tarih",
                tickfont=dict(size=9),
                tickformat="%d %b",
                nticks=12,
                tickmode="auto",
            ),
            yaxis=dict(title="", tickfont=dict(size=13)),
            annotations=annotations,
        )
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════
# D) RISK BREAKDOWN (Stacked Area Chart)
# ══════════════════════════════════════════════════════════════════════════

def create_risk_breakdown(df: pd.DataFrame, fuel_type: str = "benzin"):
    """Risk Bilesenleri -- Bagimsiz Line Chart (tek yakit tipi). Her bilesen 0-100%."""
    if df.empty:
        return go.Figure()

    # Yakit tipine gore filtrele
    df_fuel = df[df["fuel_type"] == fuel_type].copy()
    if df_fuel.empty:
        fig = go.Figure()
        fig.add_annotation(
            text=f"{fuel_type.capitalize()} icin risk verisi bulunamadi",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=14, color="#9CA3AF"),
        )
        fig.update_layout(**_base_layout(height=400))
        return fig

    # Tarihe gore sirala
    df_fuel = df_fuel.sort_values("date")

    # Tarih parse
    try:
        date_vals = pd.to_datetime(df_fuel["date"])
    except Exception:
        date_vals = df_fuel["date"]

    fig = go.Figure()

    # Her bilesen bagimsiz cizgi
    components = [
        ("mbe_comp", "Maliyet Farki", "#636EFA"),
        ("fx_comp", "Doviz Dalgalanmasi", "#EF553B"),
        ("pol_comp", "Politik Donem", "#00CC96"),
        ("threshold_comp", "Esik Yakinligi", "#FFA15A"),
        ("trend_comp", "Fiyat Momentumu", "#AB63FA"),
    ]

    for col, name, color in components:
        if col in df_fuel.columns:
            pct_vals = df_fuel[col].fillna(0) * 100
            fig.add_trace(go.Scatter(
                x=date_vals,
                y=pct_vals,
                mode="lines",
                name=name,
                line=dict(width=2, color=color),
                hovertemplate=f"<b>{name}</b>: " + "%{y:.1f}%<extra></extra>",
            ))

    # Composit risk cizgisi (referans)
    if "score" in df_fuel.columns:
        composite_pct = df_fuel["score"].fillna(0) * 100
        fig.add_trace(go.Scatter(
            x=date_vals,
            y=composite_pct,
            mode="lines+markers",
            name="Toplam Risk",
            line=dict(color="white", width=2, dash="dot"),
            marker=dict(size=4, color="white"),
            hovertemplate="<b>Toplam Risk</b>: %{y:.1f}%<extra></extra>",
        ))

    fig.update_layout(
        **_base_layout(
            height=400,
            margin=dict(l=0, r=0, t=30, b=80),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02,
                xanchor="center", x=0.5, font=dict(size=10),
                bgcolor="rgba(0,0,0,0.3)",
            ),
            xaxis=dict(
                tickangle=-45,
                tickfont=dict(size=9),
                tickformat="%d %b",
                nticks=10,
            ),
            yaxis=dict(
                title="Risk Katkisi (%)",
                ticksuffix="%",
                range=[0, 100],
            ),
            hovermode="x unified",
        )
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════
# E) V5 PROBABILITY GAUGE (Yeni)
# ══════════════════════════════════════════════════════════════════════════

def create_v5_probability_gauge(probability, fuel_type, threshold=0.25):
    """v5 Fiyat Degisim Olasilik Gostergesi — yatay bar.

    Renkler:
      <20% yesil (sabit/dusuk risk)
      20-25% sari (belirsiz bolge)
      >25% kirmizi (degisim bekleniyor)
    Esik cizgisi: %25 (hibrit alarm esigi)
    """
    if probability is None:
        fig = go.Figure()
        fig.add_annotation(
            text="v5 olasilik verisi bulunamadi",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=14, color="#9CA3AF"),
        )
        fig.update_layout(**_base_layout(height=140))
        return fig

    prob_pct = probability * 100

    # Renk belirleme
    if prob_pct < 20:
        bar_color = "#22C55E"   # yesil — sabit
        status_text = "Sabit Bekleniyor"
    elif prob_pct < 25:
        bar_color = "#F59E0B"   # sari — belirsiz
        status_text = "Belirsiz Bolge"
    else:
        bar_color = "#EF4444"   # kirmizi — degisim
        status_text = "Degisim Bekleniyor"

    fig = go.Figure()

    # Arka plan bar (gri)
    fig.add_trace(go.Bar(
        y=["Olasilik"], x=[100],
        orientation="h",
        marker=dict(color="rgba(75,85,99,0.3)", line=dict(width=0)),
        showlegend=False,
        hoverinfo="skip",
    ))

    # Dolu bar (renkli)
    fig.add_trace(go.Bar(
        y=["Olasilik"], x=[prob_pct],
        orientation="h",
        marker=dict(
            color=bar_color,
            line=dict(color="#1F2937", width=1),
        ),
        showlegend=False,
        text=f"  %{prob_pct:.1f} — {status_text}",
        textposition="inside",
        textfont=dict(size=14, color="white", family="sans-serif"),
        hovertemplate=f"Fiyat Degisim Olasiligi: %{{x:.1f}}%<extra></extra>",
    ))

    # Esik cizgisi (%25 hibrit alarm)
    threshold_pct = threshold * 100
    fig.add_vline(
        x=threshold_pct, line_width=3, line_dash="dash",
        line_color="#FACC15",
        annotation_text=f"Alarm %{threshold_pct:.0f}",
        annotation_font=dict(color="#FACC15", size=11),
        annotation_position="top",
    )

    fig.update_layout(
        **_base_layout(
            barmode="overlay",
            xaxis=dict(
                range=[0, 100],
                showgrid=False,
                ticksuffix="%",
                tickvals=[0, 25, 50, 75, 100],
                tickfont=dict(size=10, color="#9CA3AF"),
            ),
            yaxis=dict(showticklabels=False),
            height=140,
            margin=dict(l=0, r=0, t=15, b=30),
            showlegend=False,
        )
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════
# F) V5 PREDICTION HISTORY (Yeni)
# ══════════════════════════════════════════════════════════════════════════

def create_regime_timeline(df: pd.DataFrame):
    """Rejim Zaman Cizelgesi — gelistirilmis."""
    if df.empty:
        return go.Figure()

    fig = go.Figure()

    for _, row in df.iterrows():
        rtype = str(row.get("type", "Normal"))
        color = REGIME_COLORS.get(rtype, "#6B7280")
        desc = row.get("desc", rtype)
        start = row["start"]
        end = row["end"]

        fig.add_trace(go.Bar(
            x=[(pd.Timestamp(end) - pd.Timestamp(start)).days or 1],
            y=[rtype],
            base=[start],
            orientation="h",
            marker=dict(color=color, line=dict(color="#1F2937", width=1)),
            name=rtype,
            showlegend=False,
            text=f"{rtype}",
            textposition="inside",
            textfont=dict(size=12, color="white"),
            hovertemplate=f"<b>{rtype}</b><br>{desc}<br>"
                          f"{start} → {end}<extra></extra>",
        ))

    fig.update_layout(
        **_base_layout(
            title=dict(text="Piyasa Rejimleri", font=dict(size=15)),
            xaxis_title="Tarih",
            yaxis_title="",
            showlegend=False,
            height=300,
            margin=dict(l=10, r=10, t=40, b=40),
            xaxis=dict(type="date"),
            barmode="overlay",
        )
    )
    return fig


def create_v5_prediction_history(df: pd.DataFrame, fuel_type: str = ""):
    """
    Predictor v5 tahmin gecmisi grafigi.

    Backfill ve gercek tahminleri ayri renk/stil ile gosterir.
    - Backfill (model_version == "v5-backfill"): kesikli cizgi, mor (#9333EA), opacity 0.6
    - Gercek (model_version != "v5-backfill"): duz cizgi, mavi (#3B82F6), opacity 1.0
    - first_event_amount bar chart: backfill icin acik renk
    - Esik cizgisi: %25 (hibrit alarm)
    """
    if df.empty:
        return go.Figure()

    fig = go.Figure()

    # model_version kolonu yoksa tum veriyi gercek say
    has_version = "model_version" in df.columns

    if has_version:
        df_backfill = df[df["model_version"] == "v5-backfill"].copy()
        df_real = df[df["model_version"] != "v5-backfill"].copy()
    else:
        df_backfill = pd.DataFrame()
        df_real = df.copy()

    # ── 1. Stage-1 Probability cizgileri ──

    # Backfill: kesikli mor cizgi
    if not df_backfill.empty and "stage1_probability" in df_backfill.columns:
        fig.add_trace(go.Scatter(
            x=df_backfill["date"],
            y=df_backfill["stage1_probability"],
            mode="lines",
            name="Backfill Simulasyon",
            line=dict(color="#9333EA", width=2, dash="dash"),
            opacity=0.6,
            hovertemplate=(
                "<b>%{x|%d %b}</b><br>"
                "Olasilik: %{y:.1%}<br>"
                "<i>(Backfill Simulasyon)</i>"
                "<extra></extra>"
            ),
        ))

    # Gercek: duz mavi cizgi
    if not df_real.empty and "stage1_probability" in df_real.columns:
        fig.add_trace(go.Scatter(
            x=df_real["date"],
            y=df_real["stage1_probability"],
            mode="lines+markers",
            name="Gercek Tahmin",
            line=dict(color="#3B82F6", width=2.5),
            marker=dict(size=5, color="#3B82F6"),
            opacity=1.0,
            hovertemplate=(
                "<b>%{x|%d %b}</b><br>"
                "Olasilik: %{y:.1%}<br>"
                "<i>(Gercek Tahmin)</i>"
                "<extra></extra>"
            ),
        ))

    # ── 2. first_event_amount bar chart ──

    # Backfill barlar: acik mor
    if not df_backfill.empty and "first_event_amount" in df_backfill.columns:
        df_bf_nonzero = df_backfill[df_backfill["first_event_amount"].abs() > 0.001]
        if not df_bf_nonzero.empty:
            colors_bf = [
                "rgba(239, 68, 68, 0.3)" if v > 0 else "rgba(34, 197, 94, 0.3)"
                for v in df_bf_nonzero["first_event_amount"]
            ]
            fig.add_trace(go.Bar(
                x=df_bf_nonzero["date"],
                y=df_bf_nonzero["first_event_amount"],
                name="Backfill Ilk Hareket",
                marker_color=colors_bf,
                yaxis="y2",
                hovertemplate=(
                    "<b>%{x|%d %b}</b><br>"
                    "Ilk Hareket: %{y:+.2f} TL<br>"
                    "<i>(Backfill)</i>"
                    "<extra></extra>"
                ),
                showlegend=False,
            ))

    # Gercek barlar: dolu renk
    if not df_real.empty and "first_event_amount" in df_real.columns:
        df_r_nonzero = df_real[df_real["first_event_amount"].abs() > 0.001]
        if not df_r_nonzero.empty:
            colors_real = [
                "rgba(239, 68, 68, 0.8)" if v > 0 else "rgba(34, 197, 94, 0.8)"
                for v in df_r_nonzero["first_event_amount"]
            ]
            fig.add_trace(go.Bar(
                x=df_r_nonzero["date"],
                y=df_r_nonzero["first_event_amount"],
                name="Ilk Hareket (TL)",
                marker_color=colors_real,
                yaxis="y2",
                hovertemplate=(
                    "<b>%{x|%d %b}</b><br>"
                    "Ilk Hareket: %{y:+.2f} TL<br>"
                    "<extra></extra>"
                ),
            ))

    # ── 3. Esik cizgileri ──

    # x eksen araligi
    all_dates = list(df["date"])
    x_range = [min(all_dates), max(all_dates)] if all_dates else [None, None]

    # %25 alarm esigi (hibrit alarm sistemi)
    fig.add_hline(
        y=0.25,
        line_dash="dot",
        line_color="#EF4444",
        line_width=1.5,
        annotation_text="Alarm %25",
        annotation_position="top right",
        annotation_font_size=10,
        annotation_font_color="#EF4444",
    )

    # ── 4. Alarm tetiklenen gunler (marker) ──
    if "alarm_triggered" in df.columns:
        df_alarm = df[df["alarm_triggered"] == True]
        if not df_alarm.empty:
            fig.add_trace(go.Scatter(
                x=df_alarm["date"],
                y=df_alarm["stage1_probability"],
                mode="markers",
                name="Alarm",
                marker=dict(
                    size=10,
                    color="#EF4444",
                    symbol="diamond",
                    line=dict(width=1, color="white"),
                ),
                hovertemplate=(
                    "<b>%{x|%d %b}</b><br>"
                    "ALARM: %{y:.1%}<br>"
                    "<extra></extra>"
                ),
            ))

    # ── 5. Layout ──

    title_suffix = f" — {fuel_type.capitalize()}" if fuel_type else ""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=f"v5 Tahmin Gecmisi{title_suffix}",
        xaxis_title="Tarih",
        yaxis=dict(
            title="Degisim Olasiligi",
            range=[0, 1],
            tickformat=".0%",
            side="left",
        ),
        yaxis2=dict(
            title="Ilk Hareket (TL)",
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        hovermode="x unified",
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11),
        ),
        height=420,
        bargap=0.3,
    )

    return fig

