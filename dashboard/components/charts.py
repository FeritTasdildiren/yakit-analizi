"""
Plotly grafik bilesenleri.
"""

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

def create_mbe_gauge(value, fuel_type):
    """MBE Gostergesi."""
    # Renk araliklari
    # Yesil: -0.25 ~ +0.25
    # Sari: ±0.25 ~ ±0.75
    # Kirmizi: ±0.75+
    
    max_val = 2.0
    
    fig = go.Figure(go.Indicator(
        mode = "gauge+number+delta",
        value = value,
        domain = {'x': [0, 1], 'y': [0, 1]},
        title = {'text': f"{fuel_type.capitalize()} MBE (TL/L)"},
        delta = {'reference': 0.0},
        gauge = {
            'axis': {'range': [-max_val, max_val], 'tickwidth': 1, 'tickcolor': "white"},
            'bar': {'color': "white", 'thickness': 0.1},
            'bgcolor': "#1E1E1E",
            'steps': [
                {'range': [-0.25, 0.25], 'color': "#00CC96"},  # Yesil
                {'range': [0.25, 0.75], 'color': "#FFA15A"},   # Sari (Pozitif)
                {'range': [-0.75, -0.25], 'color': "#FFA15A"}, # Sari (Negatif)
                {'range': [0.75, max_val], 'color': "#EF553B"}, # Kirmizi (Pozitif)
                {'range': [-max_val, -0.75], 'color': "#EF553B"} # Kirmizi (Negatif)
            ],
            'threshold': {
                'line': {'color': "white", 'width': 4},
                'thickness': 0.75,
                'value': value
            }
        }
    ))
    
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        font={'color': "white", 'family': "sans-serif"},
        height=300,
        margin=dict(l=20, r=20, t=50, b=20)
    )
    return fig

def create_trend_line(df: pd.DataFrame, x_col, y_col, title):
    """Trend cizgi grafigi."""
    if df.empty:
        return go.Figure()

    fig = px.line(df, x=x_col, y=y_col, title=title)
    fig.update_traces(line_color='#FF6B35', line_width=3)
    
    # SMA varsa ekle
    if 'sma_5' in df.columns:
        fig.add_trace(go.Scatter(x=df[x_col], y=df['sma_5'], name='SMA-5', line=dict(color='#00CC96', width=1, dash='dot')))
        
    if 'sma_10' in df.columns:
        fig.add_trace(go.Scatter(x=df[x_col], y=df['sma_10'], name='SMA-10', line=dict(color='#AB63FA', width=1, dash='dot')))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="",
        yaxis_title="TL/L",
        hovermode="x unified",
        margin=dict(l=0, r=0, t=30, b=0)
    )
    return fig

def create_risk_heatmap(df: pd.DataFrame):
    """Risk Isı Haritası (Heatmap)."""
    if df.empty:
        return go.Figure()
        
    # Pivot: Index=Date, Columns=FuelType, Values=RiskScore
    pivot_df = df.pivot(index='date', columns='fuel_type', values='score')
    
    fig = px.imshow(
        pivot_df.T, # Transpose for fuels on y-axis
        labels=dict(x="Tarih", y="Yakıt", color="Risk Skoru"),
        x=pivot_df.index,
        y=pivot_df.columns,
        color_continuous_scale="RdYlGn_r", # Green to Red (reversed)
        range_color=[0, 100]
    )
    
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=30, b=0),
        height=250
    )
    return fig

def create_risk_breakdown(df: pd.DataFrame):
    """Risk Bilesenleri (Stacked Bar)."""
    if df.empty:
        return go.Figure()
        
    # Sadece son gunu veya ortalamayi alabiliriz, burada zaman serisi bar chart yapiyoruz
    fig = go.Figure()
    
    # Her bilesen icin trace ekle
    components = {
        'mbe_comp': 'MBE',
        'fx_comp': 'Döviz',
        'pol_comp': 'Politik',
        'trend_comp': 'Trend',
        'threshold_comp': 'Eşik'
    }
    
    colors = ['#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A']
    
    for i, (col, name) in enumerate(components.items()):
        if col in df.columns:
            fig.add_trace(go.Bar(
                x=df['date'],
                y=df[col] * 100, # % olarak goster
                name=name,
                marker_color=colors[i % len(colors)]
            ))
            
    fig.update_layout(
        barmode='stack',
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title="Risk Bileşenleri (%)",
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig

def create_probability_bar(hike, stable, cut):
    """Tahmin Olasiliklari (Horizontal Bar)."""
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        y=['Tahmin'],
        x=[hike],
        name='Zam',
        orientation='h',
        marker=dict(color='#EF553B', line=dict(color='white', width=1))
    ))
    fig.add_trace(go.Bar(
        y=['Tahmin'],
        x=[stable],
        name='Sabit',
        orientation='h',
        marker=dict(color='#FFA15A', line=dict(color='white', width=1))
    ))
    fig.add_trace(go.Bar(
        y=['Tahmin'],
        x=[cut],
        name='İndirim',
        orientation='h',
        marker=dict(color='#00CC96', line=dict(color='white', width=1))
    ))
    
    fig.update_layout(
        barmode='stack',
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(range=[0, 1], showgrid=False, showticklabels=False),
        yaxis=dict(showticklabels=False),
        height=80,
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False
    )
    return fig

def create_shap_chart(shap_data: dict):
    """SHAP Feature Importance."""
    if not shap_data:
        return go.Figure()
        
    # shap_data: {"feature_name": value, ...} or list of dicts
    # Eger dict ise
    if isinstance(shap_data, dict):
        features = list(shap_data.keys())
        values = list(shap_data.values())
    elif isinstance(shap_data, list):
         # list of {feature: val} ? No, prompt says top_features in JSONB.
         # Assume format: {"feature1": 0.1, "feature2": -0.05}
         # Or list of {"feature": "name", "value": 0.1}
         # Let's handle generic dict for now as that's most common in JSONB
         return go.Figure()

    # Sort by absolute value
    sorted_indices = sorted(range(len(values)), key=lambda k: abs(values[k]))
    features = [features[i] for i in sorted_indices]
    values = [values[i] for i in sorted_indices]
    
    colors = ['#EF553B' if v > 0 else '#00CC96' for v in values]
    
    fig = go.Figure(go.Bar(
        x=values,
        y=features,
        orientation='h',
        marker_color=colors
    ))
    
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title="Etkileyen Faktörler (SHAP)",
        margin=dict(l=0, r=0, t=30, b=0),
        height=300
    )
    return fig

def create_prediction_history(df: pd.DataFrame, title="Tahmin Geçmişi"):
    """Tahmin Gecmisi (Olasiliklar)."""
    if df.empty:
        return go.Figure()

    fig = go.Figure()
    
    # Olasiliklar (Area chart)
    fig.add_trace(go.Scatter(
        x=df['date'], y=df['p_hike'],
        mode='lines',
        name='Zam Olasılığı',
        line=dict(color='#EF553B', width=2),
        stackgroup='one'
    ))
    fig.add_trace(go.Scatter(
        x=df['date'], y=df['p_stable'],
        mode='lines',
        name='Sabit Olasılığı',
        line=dict(color='#FFA15A', width=2),
        stackgroup='one'
    ))
    # Cut olasiligi genelde dusuktur ama ekleyelim
    fig.add_trace(go.Scatter(
        x=df['date'], y=df['p_cut'],
        mode='lines',
        name='İndirim Olasılığı',
        line=dict(color='#00CC96', width=2),
        stackgroup='one'
    ))
    
    # Gercek degisimler (Scatter points)
    # Sadece degisim olan gunleri filtrele
    changes = df[df['actual_change'] != 0]
    if not changes.empty:
        fig.add_trace(go.Scatter(
            x=changes['date'], 
            y=[0.5] * len(changes), # Ortaya koy
            mode='markers',
            name='Gerçek Değişim',
            marker=dict(
                size=10,
                color=['red' if x > 0 else 'green' for x in changes['actual_change']],
                symbol=['triangle-up' if x > 0 else 'triangle-down' for x in changes['actual_change']]
            )
        ))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=title,
        xaxis_title="Tarih",
        yaxis_title="Olasılık",
        yaxis=dict(range=[0, 1]),
        hovermode="x unified",
        margin=dict(l=0, r=0, t=30, b=0)
    )
    return fig

def create_regime_timeline(df: pd.DataFrame):
    """Rejim Zaman Cizelgesi."""
    if df.empty:
        return go.Figure()
        
    fig = px.timeline(
        df, 
        x_start="start", 
        x_end="end", 
        y="type", 
        color="type",
        hover_data=["desc"]
    )
    
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title="Piyasa Rejimleri",
        xaxis_title="Tarih",
        yaxis_title="Rejim Tipi",
        showlegend=False,
        height=200,
        margin=dict(l=0, r=0, t=30, b=0)
    )
    return fig
