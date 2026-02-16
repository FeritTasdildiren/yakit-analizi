"""
Yakıt Analizi Admin Dashboard.
"""

import streamlit as st
import sys
import os

# Proje kok dizinini path'e ekle (module importlari icin)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

st.set_page_config(
    page_title="Yakıt Analizi",
    page_icon="⛽",
    layout="wide",
    initial_sidebar_state="expanded"
)

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
*Geliştirici: Gemini Agent*
*Versiyon: 0.1.0*
""")

st.sidebar.success("Sol menüden bir modül seçiniz.")
