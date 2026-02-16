"""
Dashboard Authentication Module.
Query param token ile kalici oturum — sayfa refresh'te session kaybolmaz.
"""

import streamlit as st
import hashlib
import hmac
import time
import json
import base64

_USERS = {
    "ferittd": None
}

_SECRET_KEY = "yakit_analiz_dashboard_2026_secret"
_TOKEN_EXPIRY_DAYS = 7


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

_USERS["ferittd"] = _hash_password("Poyraz2306!?")


def _create_token(username: str) -> str:
    payload = {
        "user": username,
        "exp": int(time.time()) + (_TOKEN_EXPIRY_DAYS * 86400)
    }
    data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hashlib.sha256(f"{data}{_SECRET_KEY}".encode()).hexdigest()[:16]
    return f"{data}.{sig}"


def _verify_token(token: str) -> str | None:
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        data, sig = parts
        expected_sig = hashlib.sha256(f"{data}{_SECRET_KEY}".encode()).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(data).decode())
        if payload.get("exp", 0) < time.time():
            return None
        return payload.get("user")
    except Exception:
        return None


def check_auth():
    # 1. Session'da zaten giris varsa devam
    if st.session_state.get("authenticated"):
        return True

    # 2. URL query param'dan token kontrol et
    token = st.query_params.get("token")
    if token:
        username = _verify_token(token)
        if username and username in _USERS:
            st.session_state["authenticated"] = True
            st.session_state["username"] = username
            st.session_state["_auth_token"] = token
            return True

    # 3. Login formu goster
    _show_login_form()
    st.stop()
    return False


def _show_login_form():
    st.markdown("""
    <style>
    [data-testid="stSidebar"] {display: none;}
    [data-testid="stSidebarNav"] {display: none;}
    header {display: none;}
    </style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div style='text-align: center; padding: 2rem 0;'>
            <h1>⛽ Yakıt Analizi</h1>
            <p style='color: #888;'>Yönetim Paneli</p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            username = st.text_input("Kullanıcı Adı", placeholder="Kullanıcı adınızı giriniz")
            password = st.text_input("Şifre", type="password", placeholder="Şifrenizi giriniz")
            submit = st.form_submit_button("Giriş Yap", use_container_width=True)

            if submit:
                if username in _USERS and hmac.compare_digest(
                    _hash_password(password), _USERS[username]
                ):
                    token = _create_token(username)
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = username
                    st.session_state["_auth_token"] = token
                    # Token'i URL'ye ekle — refresh'te korunur
                    st.query_params["token"] = token
                    st.rerun()
                else:
                    st.error("❌ Geçersiz kullanıcı adı veya şifre.")


def logout():
    st.session_state["authenticated"] = False
    st.session_state["username"] = None
    st.session_state["_auth_token"] = None
    if "token" in st.query_params:
        del st.query_params["token"]
    st.rerun()
