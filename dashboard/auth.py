"""
Dashboard Authentication Module.
Cookie tabanlı kalıcı oturum — sayfa refresh'te session kaybolmaz.
"""

import streamlit as st
import hashlib
import hmac
import time
import json
import base64

# Kullanıcı bilgileri
_USERS = {
    "ferittd": None  # Hash başlangıçta hesaplanır
}

_SECRET_KEY = "yakit_analiz_dashboard_2026_secret"
_COOKIE_NAME = "yakit_auth"
_COOKIE_EXPIRY_DAYS = 7

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# Başlangıçta hash'i hesapla
_USERS["ferittd"] = _hash_password("Poyraz2306!?")


def _create_token(username: str) -> str:
    """Basit imzalı token oluştur."""
    payload = {
        "user": username,
        "exp": int(time.time()) + (_COOKIE_EXPIRY_DAYS * 86400)
    }
    data = base64.b64encode(json.dumps(payload).encode()).decode()
    sig = hashlib.sha256(f"{data}{_SECRET_KEY}".encode()).hexdigest()[:16]
    return f"{data}.{sig}"


def _verify_token(token: str) -> str | None:
    """Token'ı doğrula, geçerliyse username döndür."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        data, sig = parts
        expected_sig = hashlib.sha256(f"{data}{_SECRET_KEY}".encode()).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(base64.b64decode(data).decode())
        if payload.get("exp", 0) < time.time():
            return None
        return payload.get("user")
    except Exception:
        return None


def check_auth():
    """
    Session veya cookie'den auth kontrol eder.
    Giriş yapılmamışsa login formu gösterir ve st.stop() ile durur.
    """
    # 1. Session'da zaten giriş varsa devam
    if st.session_state.get("authenticated"):
        return True

    # 2. Cookie'den token kontrol et
    token = st.query_params.get("_auth_token", None)

    # Cookie alternatifi: session_state'e JavaScript ile yazılmış token
    if not token:
        token = st.session_state.get("_auth_cookie")

    if token:
        username = _verify_token(token)
        if username and username in _USERS:
            st.session_state["authenticated"] = True
            st.session_state["username"] = username
            return True

    # 3. LocalStorage'dan oku (component ile)
    _try_restore_from_storage()
    if st.session_state.get("authenticated"):
        return True

    # 4. Login formu göster
    _show_login_form()
    st.stop()
    return False


def _try_restore_from_storage():
    """localStorage'dan token okumayı dene."""
    if "_storage_checked" in st.session_state:
        return

    st.session_state["_storage_checked"] = True

    # Streamlit components ile localStorage okuma
    try:
        import extra_streamlit_components as stx
        cookie_manager = stx.CookieManager(key="yakit_cookie_mgr")
        token = cookie_manager.get(_COOKIE_NAME)
        if token:
            username = _verify_token(token)
            if username and username in _USERS:
                st.session_state["authenticated"] = True
                st.session_state["username"] = username
    except Exception:
        pass


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
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = username

                    # Cookie'ye yaz
                    token = _create_token(username)
                    try:
                        import extra_streamlit_components as stx
                        cookie_manager = stx.CookieManager(key="yakit_cookie_mgr_login")
                        cookie_manager.set(_COOKIE_NAME, token,
                                         expires_at=None,
                                         key="set_auth_cookie")
                    except Exception:
                        pass

                    st.session_state["_auth_cookie"] = token
                    st.rerun()
                else:
                    st.error("❌ Geçersiz kullanıcı adı veya şifre.")


def logout():
    """Çıkış yap."""
    st.session_state["authenticated"] = False
    st.session_state["username"] = None
    st.session_state["_auth_cookie"] = None
    st.session_state.pop("_storage_checked", None)

    try:
        import extra_streamlit_components as stx
        cookie_manager = stx.CookieManager(key="yakit_cookie_mgr_logout")
        cookie_manager.delete(_COOKIE_NAME, key="del_auth_cookie")
    except Exception:
        pass

    st.rerun()
