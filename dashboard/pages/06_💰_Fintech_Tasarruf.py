import streamlit as st
import pandas as pd
import sys
import os

# Add project root to sys.path to allow imports from src and dashboard
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from dashboard.components.data_fetcher import get_latest_mbe

# Sayfa Ayarları
st.set_page_config(
    page_title="Fintech & Tasarruf",
    page_icon="💰",
    layout="wide"
)

st.title("💰 Fintech & Yakıt Tasarrufu")
st.markdown("Yakıt harcamalarınızı optimize edin ve bütçenizi koruyun.")

# --- 1. TASARRUF HESAPLAYICI ---
st.header("🧮 Yakıt Tasarruf Hesaplayıcı")

col_calc1, col_calc2 = st.columns([1, 2])

with col_calc1:
    st.subheader("Parametreler")
    
    # Kullanıcı Girişleri
    fuel_type = st.selectbox(
        "Yakıt Türü",
        ["Benzin", "Motorin", "LPG"],
        index=0
    )
    
    monthly_km = st.slider(
        "Aylık Mesafe (km)",
        min_value=500,
        max_value=5000,
        value=1500,
        step=100
    )
    
    consumption = st.slider(
        "Ortalama Tüketim (lt/100km)",
        min_value=4.0,
        max_value=15.0,
        value=7.5,
        step=0.1
    )
    
    # Varsayılan fiyatlar (Kullanıcı değiştirebilir)
    default_prices = {"Benzin": 43.0, "Motorin": 43.0, "LPG": 25.0}
    current_price = st.number_input(
        "Güncel Pompa Fiyatı (TL)",
        min_value=10.0,
        max_value=100.0,
        value=default_prices.get(fuel_type, 40.0),
        step=0.1
    )

with col_calc2:
    st.subheader("Maliyet Analizi")
    
    # Hesaplamalar
    monthly_liters = (monthly_km / 100) * consumption
    monthly_cost = monthly_liters * current_price
    yearly_cost = monthly_cost * 12
    daily_cost = monthly_cost / 30
    
    # Metriklerin Gösterimi
    m1, m2, m3 = st.columns(3)
    
    m1.metric("Aylık Maliyet", f"{monthly_cost:,.2f} TL")
    m2.metric("Yıllık Maliyet", f"{yearly_cost:,.2f} TL")
    m3.metric("Günlük Ortalama", f"{daily_cost:,.2f} TL")
    
    st.info(f"Ayda yaklaşık **{monthly_liters:.1f} litre** yakıt tüketiyorsunuz.")

st.divider()

# --- 2. AKILLI TANKLAMA ÖNERİSİ ---
st.header("🧠 Akıllı Tanklama Önerisi")

# Seçilen yakıt türüne göre MBE verisini çek
# API 'benzin' veya 'motorin' bekliyor (küçük harf). LPG için şu an veri yoksa handle etmeliyiz.
api_fuel_type = fuel_type.lower()
if api_fuel_type == "lpg":
    mbe_data = None # LPG için MBE verisi olmayabilir
else:
    try:
        mbe_data = get_latest_mbe(api_fuel_type)
    except Exception as e:
        st.error(f"Veri alınırken hata oluştu: {e}")
        mbe_data = None

col_advice1, col_advice2 = st.columns([2, 1])

with col_advice1:
    if mbe_data:
        mbe_val = mbe_data.get('value', 0)
        
        # MBE Değerine Göre Mantık
        if mbe_val > 1.5: # Pozitif ve yüksek -> Zam beklentisi
            st.error(f"⚠️ **ZAM BEKLENTİSİ!** (MBE: {mbe_val:+.2f} TL)")
            st.markdown("Piyasa verileri fiyatların yükseleceğini işaret ediyor. Deponuzu **bugün doldurmanız** tavsiye edilir.")
        elif mbe_val < -1.5: # Negatif -> İndirim beklentisi
            st.success(f"✅ **İNDİRİM BEKLENTİSİ!** (MBE: {mbe_val:+.2f} TL)")
            st.markdown("Piyasa verileri fiyatların düşebileceğini işaret ediyor. Acil değilse **beklemeniz** tavsiye edilir.")
        else: # Nötr
            st.info(f"⚖️ **FİYATLAR STABİL** (MBE: {mbe_val:+.2f} TL)")
            st.markdown("Önemli bir fiyat değişikliği beklenmiyor. İhtiyacınız kadar alabilirsiniz.")
            
        st.caption(f"*Veri Kaynağı: Piyasa Başabaş Noktası (MBE) Analizi - Trend: {mbe_data.get('trend', '-') }*")
        
    elif api_fuel_type == "lpg":
         st.warning("LPG için şu an aktif piyasa analizi bulunmamaktadır.")
    else:
        st.warning("Piyasa verisi şu an alınamıyor. Lütfen daha sonra tekrar deneyiniz.")

with col_advice2:
    st.markdown("#### Nasıl Çalışır?")
    st.markdown("""
    **MBE (Piyasa Başabaş Noktası)**, uluslararası petrol fiyatları ve döviz kurlarını analiz ederek 
    gerçek maliyet ile pompa fiyatı arasındaki farkı hesaplar.
    """)

st.divider()

# --- 3. YAKIT KARTI KARŞILAŞTIRMA ---
st.header("💳 Yakıt Kartı Avantajları")

card_data = {
    "Kart Adı": ["Opet Worldcard", "Shell ClubSmart", "BP Miles&Smiles", "Total Enerji Kart", "Petrol Ofisi MaxiPuan"],
    "İndirim Oranı": ["%3 - %5", "Puan Bazlı", "Mil Kazanımı", "%2 - %3", "Puan Bazlı"],
    "Puan/Ödül": ["Worldpuan", "Smart Puan", "THY Mil", "Yakıt Puan", "MaxiPuan"],
    "Özel Avantajlar": [
        "Kampanyalarda ek puan", 
        "Market alışverişlerinde puan", 
        "Uçuş mili kazanımı", 
        "Mobil ödeme kolaylığı", 
        "Anlaşmalı banka avantajları"
    ]
}

df_cards = pd.DataFrame(card_data)
st.dataframe(df_cards, use_container_width=True, hide_index=True)

st.divider()

# --- 4. TASARRUF İPUÇLARI ---
st.header("💡 Akıllı Sürüş ve Tasarruf İpuçları")

with st.expander("Daha Az Yakıt İçin 6 Altın Kural", expanded=True):
    st.markdown("""
    1. **Lastik Basıncını Kontrol Edin:** Düşük lastik basıncı sürtünmeyi artırır ve yakıt tüketimini %5'e kadar yükseltebilir.
    2. **Gereksiz Yüklerden Kurtulun:** Araçtaki her fazladan 50 kg yük, yakıt tüketimini %1-2 artırır.
    3. **Ani Hızlanmadan Kaçının:** Agresif sürüş (ani fren ve gaz), yakıt tüketimini şehir içinde %20, otoyolda %30 artırır.
    4. **Klimayı Akıllıca Kullanın:** Düşük hızlarda camları açmak, yüksek hızlarda (80+ km/s) klimayı kullanmak daha verimlidir.
    5. **Bakımları İhmal Etmeyin:** Hava filtresi, bujiler ve yağ değişiminin zamanında yapılması motor verimliliğini korur.
    6. **Motoru Rölantide Isıtmayın:** Yeni nesil araçlarda hareket halindeyken motor daha hızlı ve verimli ısınır. 1 dakikadan fazla bekleyecekseniz kontağı kapatın.
    """)

st.markdown("---")
st.caption("© 2026 Yakıt Analizi Sistemi - Fintech Modülü")
