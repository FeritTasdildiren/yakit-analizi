"""
Yakıt Analizi Admin Dashboard.
"""

import streamlit as st
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

st.set_page_config(
    page_title="Yakıt Analizi",
    page_icon="⛽",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Global CSS ──────────────────────────────────────────────────────────
st.markdown('''
    <style>
    :root {
        --bg-color: #1F2937;
        --card-bg: #374151;
        --text-color: #F3F4F6;
        --risk-high: #EF4444;
        --risk-low: #22C55E;
        --risk-med: #F59E0B;
        --accent: #3B82F6;
    }
    .stApp { background-color: var(--bg-color); color: var(--text-color); }
    .info-box { background-color: rgba(59, 130, 246, 0.1); border-left: 4px solid var(--accent); padding: 1rem; margin-bottom: 1rem; border-radius: 4px; font-size: 0.9rem; }
    .info-title { font-weight: bold; color: var(--accent); display: block; margin-bottom: 0.5rem; }
    .kpi-card { background-color: var(--card-bg); padding: 1rem; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: center; border: 1px solid #4B5563; word-wrap: break-word; overflow-wrap: break-word; overflow: hidden; }
    .kpi-value { font-size: 1.5rem; font-weight: bold; margin: 0.3rem 0; }
    .kpi-label { font-size: 0.8rem; color: #9CA3AF; text-transform: uppercase; letter-spacing: 0.03em; }
    .badge { padding: 0.25rem 0.5rem; border-radius: 9999px; font-size: 0.75rem; font-weight: bold; }
    .badge-red { background-color: rgba(239, 68, 68, 0.2); color: #FCA5A5; }
    .badge-green { background-color: rgba(34, 197, 94, 0.2); color: #86EFAC; }
    .badge-amber { background-color: rgba(245, 158, 11, 0.2); color: #FDBA74; }
    </style>
''', unsafe_allow_html=True)


# Auth kontrolü — giriş yapılmadan hiçbir şey gösterilmez
from auth import check_auth, logout
check_auth()

# Sidebar'da çıkış butonu
with st.sidebar:
    st.markdown(f"👤 **{st.session_state.get('username', '')}**")
    if st.button("🚪 Çıkış Yap", use_container_width=True):
        logout()

st.title("⛽ Yakıt Analizi Sistemi")

st.markdown("""
### Hoş Geldiniz

Bu sistem, Türkiye akaryakıt piyasası için **yapay zeka destekli fiyat tahmin ve risk analizi** sunar.

**Modüller:**

- **📊 Genel Bakış:** Güncel MBE değerleri, trendler ve son fiyat değişimleri.
- **📈 ML Tahminler:** Makine öğrenmesi modellerinin zam/indirim tahminleri ve olasılıkları.
- **🔥 Risk Analizi:** Piyasa riskleri, eşik ihlalleri ve kriz durumu izleme.
- **👥 Kullanıcı Yönetimi:** Telegram bot kullanıcılarının onay ve yönetimi.
- **⚙️ Sistem:** Servis sağlığı ve teknik durum.

---
*Versiyon: 0.1.0*
""")

st.sidebar.success("Sol menüden bir modül seçiniz.")
