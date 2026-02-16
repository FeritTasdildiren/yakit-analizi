import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from auth import check_auth, logout
check_auth()

import streamlit as st
import pandas as pd
import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from dashboard.components.data_fetcher import get_telegram_users_df

API_BASE = "http://localhost:8100/api/v1/telegram"

st.title("👥 Kullanıcı Yönetimi")

# --- Veri Cekme ---
users_df = get_telegram_users_df(status="all")

if users_df.empty:
    st.info("Kayıtlı kullanıcı yok.")
    st.stop()

# --- Istatistikler ---
total = len(users_df)
approved_active = len(users_df[(users_df['approved'] == True) & (users_df['active'] == True)])
pending = len(users_df[(users_df['approved'] == False) & (users_df['active'] == True)])
inactive = len(users_df[users_df['active'] == False])

c1, c2, c3, c4 = st.columns(4)
c1.metric("Toplam", total)
c2.metric("Onaylı & Aktif", approved_active)
c3.metric("Onay Bekliyor", pending, delta_color="inverse")
c4.metric("Pasif", inactive)

st.divider()

# --- Onay Bekleyenler ---
pending_df = users_df[(users_df['approved'] == False) & (users_df['active'] == True)]
if not pending_df.empty:
    st.subheader("⏳ Onay Bekleyen Kullanıcılar")

    for idx, row in pending_df.iterrows():
        col_info, col_approve, col_reject = st.columns([4, 1, 1])

        with col_info:
            name = row.get('name', '') or ''
            username = row.get('username', '') or ''
            phone = row.get('phone', '') or ''
            display = f"**{name}** (@{username})" if username else f"**{name}**"
            st.markdown(f"{display} — {phone}")

        with col_approve:
            if st.button("✅ Onayla", key=f"approve_{row['id']}"):
                try:
                    resp = requests.post(
                        f"{API_BASE}/users/{row['id']}/approve",
                        json={"approved_by": "dashboard_admin"},
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        st.success("Onaylandı! Kullanıcıya bildirim gönderildi.")
                        get_telegram_users_df.clear()
                        st.rerun()
                    else:
                        st.error(f"Hata: {resp.status_code}")
                except Exception as e:
                    st.error(f"API hatası: {e}")

        with col_reject:
            if st.button("❌ Reddet", key=f"reject_{row['id']}"):
                try:
                    resp = requests.post(
                        f"{API_BASE}/users/{row['id']}/reject",
                        json={},
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        st.warning("Reddedildi.")
                        get_telegram_users_df.clear()
                        st.rerun()
                    else:
                        st.error(f"Hata: {resp.status_code}")
                except Exception as e:
                    st.error(f"API hatası: {e}")

    st.divider()

# --- Onaylanmis & Aktif Kullanicilar ---
approved_df = users_df[(users_df['approved'] == True) & (users_df['active'] == True)]
if not approved_df.empty:
    st.subheader("✅ Onaylı Kullanıcılar")

    for idx, row in approved_df.iterrows():
        col_info, col_revoke = st.columns([5, 1])

        with col_info:
            name = row.get('name', '') or ''
            username = row.get('username', '') or ''
            phone = row.get('phone', '') or ''
            display = f"**{name}** (@{username})" if username else f"**{name}**"
            st.markdown(f"{display} — {phone}")

        with col_revoke:
            if st.button("🚫 Askıya Al", key=f"revoke_{row['id']}"):
                try:
                    resp = requests.post(
                        f"{API_BASE}/users/{row['id']}/reject",
                        json={"reason": "Admin tarafından askıya alındı"},
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        st.warning("Kullanıcı askıya alındı.")
                        get_telegram_users_df.clear()
                        st.rerun()
                    else:
                        st.error(f"Hata: {resp.status_code}")
                except Exception as e:
                    st.error(f"API hatası: {e}")

    st.divider()

# --- Pasif Kullanicilar ---
inactive_df = users_df[users_df['active'] == False]
if not inactive_df.empty:
    st.subheader("🔴 Pasif Kullanıcılar")

    for idx, row in inactive_df.iterrows():
        col_info, col_reactivate = st.columns([5, 1])

        with col_info:
            name = row.get('name', '') or ''
            username = row.get('username', '') or ''
            approved_status = "(eski onaylı)" if row.get('approved') else "(onaysız)"
            st.markdown(f"**{name}** (@{username}) {approved_status}")

        with col_reactivate:
            if st.button("🔄 Aktif Et", key=f"reactivate_{row['id']}"):
                try:
                    resp = requests.post(
                        f"{API_BASE}/users/{row['id']}/approve",
                        json={"approved_by": "dashboard_admin"},
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        st.success("Kullanıcı tekrar aktif ve onaylı.")
                        get_telegram_users_df.clear()
                        st.rerun()
                    else:
                        st.error(f"Hata: {resp.status_code}")
                except Exception as e:
                    st.error(f"API hatası: {e}")

    st.divider()

# --- Toplu Mesaj ---
st.subheader("📢 Toplu Mesaj Gönder")
st.caption("Tüm onaylı ve aktif kullanıcılara Telegram mesajı gönderir.")

with st.form("broadcast_form"):
    msg = st.text_area("Mesaj İçeriği", placeholder="Tüm onaylı kullanıcılara gönderilecek mesaj...")
    submitted = st.form_submit_button("📤 Gönder", type="primary")

    if submitted and msg:
        try:
            resp = requests.post(
                f"{API_BASE}/broadcast",
                json={"message": msg},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                st.success(
                    f"✅ Mesaj gönderildi! "
                    f"Başarılı: {data.get('sent', 0)}, "
                    f"Başarısız: {data.get('failed', 0)}, "
                    f"Toplam: {data.get('total', 0)}"
                )
            else:
                st.error(f"Hata: {resp.status_code} — {resp.text}")
        except Exception as e:
            st.error(f"API hatası: {e}")
    elif submitted:
        st.error("Mesaj içeriği boş olamaz.")
