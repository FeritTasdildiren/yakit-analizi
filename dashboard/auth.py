"""
Dashboard Authentication Module.
Cookie + query param token ile kalici oturum — sayfa refresh'te session kaybolmaz.
Streamlit st.context.cookies ile HTTP cookie okunur, JavaScript ile yazilir.
"""

import streamlit as st
# st.html() kullaniliyor (iframe DEGIL, dogrudan DOM enjeksiyonu)
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
_COOKIE_NAME = "yakit_auth_token"


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


def _set_cookie_js(token: str):
    """JavaScript ile browser cookie set eder."""
    max_age = _TOKEN_EXPIRY_DAYS * 86400
    js = f"""
    <script>
    document.cookie = "{_COOKIE_NAME}={token}; path=/; max-age={max_age}; SameSite=Lax";
    </script>
    """
    st.html(js, unsafe_allow_javascript=True)


def _clear_cookie_js():
    """JavaScript ile browser cookie siler."""
    js = f"""
    <script>
    document.cookie = "{_COOKIE_NAME}=; path=/; max-age=0; SameSite=Lax";
    </script>
    """
    st.html(js, unsafe_allow_javascript=True)


def _get_cookie_token() -> str | None:
    """st.context.cookies ile HTTP cookie'den token okur."""
    try:
        cookies = st.context.cookies
        return cookies.get(_COOKIE_NAME)
    except Exception:
        return None


def check_auth():
    # 1. Session'da zaten giris varsa devam
    if st.session_state.get("authenticated"):
        # Cookie'set bekliyorsa (login sonrasi rerun durumu) -> cookie'yi yaz
        if st.session_state.get("_pending_cookie"):
            _set_cookie_js(st.session_state["_pending_cookie"])
            st.session_state["_pending_cookie"] = None
        return True

    # 2. HTTP Cookie'den token kontrol et (en guvenilir — refresh'te korunur)
    cookie_token = _get_cookie_token()
    if cookie_token:
        username = _verify_token(cookie_token)
        if username and username in _USERS:
            st.session_state["authenticated"] = True
            st.session_state["username"] = username
            st.session_state["_auth_token"] = cookie_token
            return True

    # 3. URL query param'dan token kontrol et (fallback)
    token = st.query_params.get("token")
    if token:
        username = _verify_token(token)
        if username and username in _USERS:
            st.session_state["authenticated"] = True
            st.session_state["username"] = username
            st.session_state["_auth_token"] = token
            # Cookie'ye de yaz (gelecek refresh'ler icin)
            st.session_state["_pending_cookie"] = token
            _set_cookie_js(token)
            return True

    # 4. Login formu goster
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
                    # Cookie yazimi rerun sonrasina ertele
                    st.session_state["_pending_cookie"] = token
                    # Query params'a da yaz (fallback)
                    st.query_params["token"] = token
                    st.rerun()
                else:
                    st.error("❌ Geçersiz kullanıcı adı veya şifre.")


def logout():
    st.session_state["authenticated"] = False
    st.session_state["username"] = None
    st.session_state["_auth_token"] = None
    st.session_state["_pending_cookie"] = None
    # Cookie sil + sayfa redirect (rerun yerine JS kullan -- rerun st.html() render etmeden calisir)
    if "token" in st.query_params:
        del st.query_params["token"]
    js = f'''<script>
    document.cookie = "{_COOKIE_NAME}=; path=/; max-age=0; SameSite=Lax";
    window.location.href = window.location.pathname;
    </script>'''
    st.html(js, unsafe_allow_javascript=True)
    st.stop()
