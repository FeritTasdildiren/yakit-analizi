import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from auth import check_auth, logout
check_auth()

import streamlit as st
import platform
import pandas as pd
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from dashboard.components.data_fetcher import get_system_status, get_latest_mbe
from src.config.settings import settings

st.title("⚙️ Sistem Durumu")

# --- Durum Kontrolleri ---
col1, col2, col3 = st.columns(3)

# 1. Veritabani
db_status = "Bilinmiyor"
db_color = "gray"
try:
    check = get_latest_mbe("benzin")
    if check:
        db_status = "BAĞLI ✅"
        db_color = "green"
    else:
        db_status = "BAĞLI (Veri Yok) ⚠️"
        db_color = "orange"
except Exception as e:
    db_status = f"HATA ❌ ({str(e)})"
    db_color = "red"

col1.markdown(f"### Veritabanı\n<h2 style='color:{db_color}'>{db_status}</h2>", unsafe_allow_html=True)

# 2. API / Circuit Breaker
api_status = get_system_status()
if api_status:
    cb_state = api_status.get("state", "UNKNOWN")
    cb_color = "green" if cb_state == "CLOSED" else "red" if cb_state == "OPEN" else "orange"

    col2.markdown(f"### Circuit Breaker\n<h2 style='color:{cb_color}'>{cb_state}</h2>", unsafe_allow_html=True)

    with col2.expander("Detaylar"):
        st.json(api_status)
else:
    col2.markdown("### API Durumu\n<h2 style='color:red'>ERİŞİLEMEZ ❌</h2>", unsafe_allow_html=True)
    col2.caption("Backend servisi çalışmıyor olabilir.")

# 3. Ortam
col3.markdown(f"### Ortam\n<h2>{platform.system()}</h2>", unsafe_allow_html=True)
col3.caption(f"Python: {platform.python_version()}")

st.divider()

# --- Konfigurasyon ---
st.subheader("🔧 Konfigürasyon Özeti")

safe_settings = {
    "DATABASE_URL": settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else "***",
    "REDIS_URL": settings.REDIS_URL,
    "DATA_FETCH_HOUR": settings.DATA_FETCH_HOUR,
    "BRENT_SOURCE": settings.BRENT_FALLBACK_SOURCE,
    "RETRY_COUNT": settings.RETRY_COUNT
}

st.json(safe_settings)

st.subheader("📋 Son Sistem Logları")
st.info("Log görüntüleme henüz aktif değil. Konsol çıktılarını kontrol edin.")
