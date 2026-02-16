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

# --- Arama ---
search_query = st.text_input(
    "🔍 Kullanıcı Ara",
    placeholder="Ad, kullanıcı adı veya telefon numarası ile arayın...",
    key="user_search",
)

def filter_users(df, query):
    if not query or not query.strip():
        return df
    q = query.strip().lower()
    mask = (
        df['name'].fillna('').str.lower().str.contains(q, regex=False)
        | df['username'].fillna('').str.lower().str.contains(q, regex=False)
        | df['phone'].fillna('').str.contains(q, regex=False)
        | df['id'].astype(str).str.contains(q, regex=False)
    )
    return df[mask]

filtered_df = filter_users(users_df, search_query)

if search_query and filtered_df.empty:
    st.warning(f"\"{search_query}\" ile eşleşen kullanıcı bulunamadı.")
    st.stop()

if search_query:
    st.caption(f"{len(filtered_df)} sonuç bulundu.")

# --- Helper: kullanici satiri render ---
def render_user_row(row, actions):
    col_info, *action_cols = st.columns([4] + [1] * len(actions))
    
    with col_info:
        name = row.get('name', '') or ''
        username = row.get('username', '') or ''
        phone = row.get('phone', '') or ''
        display = f"**{name}** (@{username})" if username else f"**{name}**"
        if phone:
            display += f" — {phone}"
        st.markdown(display)
    
    for i, (label, key_prefix, action_fn) in enumerate(actions):
        with action_cols[i]:
            if st.button(label, key=f"{key_prefix}_{row['id']}"):
                action_fn(row)

def do_approve(row):
    try:
        resp = requests.post(
            f"{API_BASE}/users/{row['id']}/approve",
            json={"approved_by": "dashboard_admin"},
            timeout=10,
        )
        if resp.status_code == 200:
            st.success("Onaylandı! Bildirim gönderildi.")
            get_telegram_users_df.clear()
            st.rerun()
        else:
            st.error(f"Hata: {resp.status_code}")
    except Exception as e:
        st.error(f"API hatası: {e}")

def do_reject(row):
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

def do_revoke(row):
    try:
        resp = requests.post(
            f"{API_BASE}/users/{row['id']}/reject",
            json={"reason": "Admin tarafından askıya alındı"},
            timeout=10,
        )
        if resp.status_code == 200:
            st.warning("Askıya alındı.")
            get_telegram_users_df.clear()
            st.rerun()
        else:
            st.error(f"Hata: {resp.status_code}")
    except Exception as e:
        st.error(f"API hatası: {e}")

def do_reactivate(row):
    try:
        resp = requests.post(
            f"{API_BASE}/users/{row['id']}/approve",
            json={"approved_by": "dashboard_admin"},
            timeout=10,
        )
        if resp.status_code == 200:
            st.success("Tekrar aktif ve onaylı.")
            get_telegram_users_df.clear()
            st.rerun()
        else:
            st.error(f"Hata: {resp.status_code}")
    except Exception as e:
        st.error(f"API hatası: {e}")

# --- Onay Bekleyenler ---
pending_df = filtered_df[(filtered_df['approved'] == False) & (filtered_df['active'] == True)]
if not pending_df.empty:
    st.subheader(f"⏳ Onay Bekleyen ({len(pending_df)})")
    for _, row in pending_df.iterrows():
        render_user_row(row, [
            ("✅ Onayla", "approve", do_approve),
            ("❌ Reddet", "reject", do_reject),
        ])
    st.divider()

# --- Onaylanmis & Aktif ---
approved_df = filtered_df[(filtered_df['approved'] == True) & (filtered_df['active'] == True)]
if not approved_df.empty:
    st.subheader(f"✅ Onaylı ({len(approved_df)})")
    for _, row in approved_df.iterrows():
        render_user_row(row, [
            ("🚫 Askıya Al", "revoke", do_revoke),
        ])
    st.divider()

# --- Pasif ---
inactive_df = filtered_df[filtered_df['active'] == False]
if not inactive_df.empty:
    st.subheader(f"🔴 Pasif ({len(inactive_df)})")
    for _, row in inactive_df.iterrows():
        render_user_row(row, [
            ("🔄 Aktif Et", "reactivate", do_reactivate),
        ])
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
