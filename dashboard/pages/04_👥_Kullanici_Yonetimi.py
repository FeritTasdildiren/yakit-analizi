import streamlit as st
import sys
import os
import pandas as pd

# Path setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from dashboard.components.data_fetcher import (
    get_telegram_users_df,
    approve_user
)

st.set_page_config(page_title="Kullanıcı Yönetimi", page_icon="👥", layout="wide")

st.title("👥 Kullanıcı Yönetimi")

# --- Veri Cekme ---
# Cache'i bypass etmek icin belki session_state kullanabiliriz ama 
# data_fetcher'da cache suresi kisa (10s).
users_df = get_telegram_users_df(status="all")

if users_df.empty:
    st.info("Kayıtlı kullanıcı yok.")
    st.stop()

# --- Istatistikler ---
total = len(users_df)
approved = len(users_df[users_df['approved'] == True])
pending = len(users_df[users_df['approved'] == False])

c1, c2, c3 = st.columns(3)
c1.metric("Toplam Kullanıcı", total)
c2.metric("Onaylı", approved, delta_color="normal")
c3.metric("Bekleyen", pending, delta_color="inverse")

st.divider()

# --- Editor ---
st.subheader("Kullanıcı Listesi ve Onay")

# Duzenlenebilir DataFrame
# ID'yi index yapalim ki degisiklikleri takip edebilelim
users_df['approved'] = users_df['approved'].astype(bool)
edited_df = st.data_editor(
    users_df,
    column_config={
        "approved": st.column_config.CheckboxColumn(
            "Onay Durumu",
            help="Kullanıcıyı onaylamak için işaretleyin",
            default=False,
        ),
        "id": st.column_config.TextColumn("Telegram ID", disabled=True),
        "username": st.column_config.TextColumn("Kullanıcı Adı", disabled=True),
        "name": st.column_config.TextColumn("Ad Soyad", disabled=True),
        "phone": st.column_config.TextColumn("Telefon", disabled=True),
        "created_at": st.column_config.DatetimeColumn("Kayıt Tarihi", disabled=True, format="D MMM YYYY, HH:mm"),
        "active": st.column_config.CheckboxColumn("Aktif", disabled=True)
    },
    disabled=["id", "username", "name", "phone", "created_at", "active"],
    hide_index=True,
    use_container_width=True,
    key="user_editor"
)

# --- Kaydet ---
if st.button("Değişiklikleri Kaydet", type="primary"):
    # Degisiklikleri bul
    # edited_df ile users_df karsilastir
    # users_df cached oldugu icin orijinal hali duruyor (eger data_editor key degismezse)
    
    # ID uzerinden karsilastir (sorting riskini onlemek icin)
    original_status = users_df.set_index('id')['approved'].to_dict()
    
    changes = 0
    for index, row in edited_df.iterrows():
        uid = row['id']
        new_status = row['approved']
        old_status = original_status.get(uid)
        
        if old_status is not None and new_status != old_status:
            # Degisiklik var
            approve_user(str(uid), new_status)
            changes += 1
            
    if changes > 0:
        st.success(f"{changes} kullanıcı güncellendi.")
        # Cache'i temizle ve sayfayi yenile
        get_telegram_users_df.clear()
        st.rerun()
    else:
        st.info("Değişiklik yapılmadı.")

st.divider()

# --- Toplu Mesaj ---
st.subheader("📢 Toplu Mesaj Gönder")
with st.form("broadcast_form"):
    msg = st.text_area("Mesaj İçeriği", placeholder="Tüm onaylı kullanıcılara gönderilecek mesaj...")
    submitted = st.form_submit_button("Gönder")
    
    if submitted and msg:
        # TODO: Implement broadcast logic (API Call)
        st.warning("Bu özellik henüz aktif değil (API entegrasyonu bekleniyor).")
    elif submitted:
        st.error("Mesaj içeriği boş olamaz.")
