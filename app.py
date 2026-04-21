import streamlit as st
import requests

API_URL = "http://localhost:8000"

st.set_page_config(
    page_title="LaxmiPay",
    page_icon="💳",
    layout="centered",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.stApp { background: #0f0f13; color: #e8e8e8; }

.hero-title {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 2.6rem; font-weight: 600;
    color: #00e5a0; letter-spacing: -1px; margin-bottom: 0;
}
.hero-sub {
    font-size: 0.85rem; color: #666;
    letter-spacing: 3px; text-transform: uppercase; margin-top: 6px;
}
.status-pill {
    display: inline-block; padding: 3px 14px;
    border-radius: 999px; font-size: 0.78rem;
    font-family: 'IBM Plex Mono', monospace; margin-bottom: 1rem;
}
.status-online  { background: #0a2e1f; color: #00e5a0; border: 1px solid #00e5a0; }
.status-offline { background: #2e0a0a; color: #ff5c5c; border: 1px solid #ff5c5c; }
.info-card {
    background: #181820; border: 1px solid #2a2a35;
    border-radius: 12px; padding: 1.2rem 1.4rem; margin-bottom: 1rem;
}
.stButton > button {
    width: 100%; border-radius: 8px;
    background: #00e5a0; color: #0f0f13;
    font-weight: 600; font-family: 'IBM Plex Mono', monospace;
    border: none; padding: 0.6rem; transition: opacity 0.2s;
}
.stButton > button:hover { opacity: 0.85; }
.stTextInput input {
    background: #1a1a24 !important; border: 1px solid #2a2a35 !important;
    color: #e8e8e8 !important; border-radius: 8px !important;
}
[data-testid="stSidebar"] {
    background: #0d0d11 !important; border-right: 1px solid #1e1e28;
}
</style>
""", unsafe_allow_html=True)


def check_api():
    try:
        r = requests.get(f"{API_URL}/", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


api_online = check_api()
status_class = "status-online" if api_online else "status-offline"
status_text = "● API ONLINE" if api_online else "● API OFFLINE"

st.markdown('<div class="hero-title">LaxmiPay</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-sub">RFID Payment Management System</div>', unsafe_allow_html=True)
st.markdown(f'<span class="status-pill {status_class}">{status_text}</span>', unsafe_allow_html=True)
st.markdown("---")

with st.sidebar:
    st.markdown("**Navigation**")
    page = st.radio("", ["🏠 Home", "👤 Customer Portal", "🛠️ Admin Panel"], label_visibility="collapsed")
    st.markdown("---")
    st.markdown(f"**API:** `{API_URL}`")
    st.markdown("**Version:** `4.0.0`")
    if st.session_state.get("admin_token"):
        st.markdown("---")
        st.success("🔐 Admin logged in")
        if st.button("Logout"):
            st.session_state.pop("admin_token", None)
            st.rerun()


if page == "🏠 Home":
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""<div class="info-card"><b>💳 RFID Card Management</b><br>
        <span style="color:#888;font-size:0.85rem">Register cards, top up balances, set daily spending limits, block or unblock cards instantly.</span></div>""",
        unsafe_allow_html=True)
        st.markdown("""<div class="info-card"><b>🔐 Fraud Detection</b><br>
        <span style="color:#888;font-size:0.85rem">Velocity-based and high-value threshold checks automatically flag suspicious transactions.</span></div>""",
        unsafe_allow_html=True)
    with col2:
        st.markdown("""<div class="info-card"><b>📊 Real-time Analytics</b><br>
        <span style="color:#888;font-size:0.85rem">Daily volume charts, top spenders, flagged transaction overview, and full audit trail.</span></div>""",
        unsafe_allow_html=True)
        st.markdown("""<div class="info-card"><b>💸 Simulate Payments</b><br>
        <span style="color:#888;font-size:0.85rem">Process payments directly from the dashboard to demo the full payment lifecycle.</span></div>""",
        unsafe_allow_html=True)

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Open Customer Portal"):
            st.switch_page("pages/Customer_Dashboard.py")
    with c2:
        if st.button("Open Admin Panel"):
            st.switch_page("pages/Admin_Dashboard.py")


elif page == "👤 Customer Portal":
    st.subheader("👤 Customer Portal")
    st.info("View your balance, transaction history, and make payments.")
    if st.button("Open Customer Portal"):
        st.switch_page("pages/Customer_Dashboard.py")


elif page == "🛠️ Admin Panel":
    st.subheader("🛠️ Admin Login")

    if not api_online:
        st.error("⚠️ API server is offline. Run: `uvicorn api:app --reload`")
        st.stop()

    if st.session_state.get("admin_token"):
        st.success("Already logged in.")
        if st.button("Go to Admin Panel"):
            st.switch_page("pages/Admin_Dashboard.py")
    else:
        st.caption("Default credentials: `admin` / `admin123`")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Login"):
            if not username or not password:
                st.warning("Enter both username and password.")
            else:
                try:
                    res = requests.post(f"{API_URL}/authenticate/admin", json={"username": username, "password": password}, timeout=5)
                    if res.status_code == 200:
                        st.session_state["admin_token"] = res.json()["token"]
                        st.success("✅ Login successful!")
                        st.switch_page("pages/Admin_Dashboard.py")
                    else:
                        st.error("❌ Invalid credentials.")
                except requests.exceptions.ConnectionError:
                    st.error("⚠️ Cannot connect to API.")