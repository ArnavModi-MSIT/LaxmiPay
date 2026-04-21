"""
Customer_Dashboard.py — LaxmiPay customer portal
Features:
  - Login with RFID + password → receives JWT token
  - Balance display with card status indicator
  - Transaction history with type, merchant, and fraud flag
  - Daily spending summary vs. limit
  - QR code scan for RFID lookup
"""

import os
import streamlit as st
import requests
import pandas as pd
from datetime import datetime, date

API_URL = os.environ.get("API_URL", "http://localhost:8000")

st.set_page_config(page_title="LaxmiPay Customer", page_icon="💳", layout="centered")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');
html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.stApp { background: #0f0f13; color: #e8e8e8; }
.balance-card {
    background: linear-gradient(135deg, #0a2e1f 0%, #0d1a14 100%);
    border: 1px solid #00e5a0; border-radius: 16px;
    padding: 2rem; text-align: center; margin-bottom: 1.5rem;
}
.balance-amount {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 2.8rem; font-weight: 600; color: #00e5a0;
}
.balance-label { font-size: 0.8rem; color: #888; letter-spacing: 2px; text-transform: uppercase; }
.rfid-tag {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.85rem; color: #555; margin-top: 0.5rem;
}
.blocked-card {
    background: #2e0a0a; border: 1px solid #ff5c5c;
    border-radius: 16px; padding: 1.5rem; text-align: center;
    color: #ff5c5c; margin-bottom: 1.5rem;
}
.stButton > button {
    width: 100%; border-radius: 8px; background: #00e5a0;
    color: #0f0f13; font-weight: 600; font-family: 'IBM Plex Mono', monospace;
    border: none; padding: 0.6rem; transition: opacity 0.2s;
}
.stButton > button:hover { opacity: 0.85; }
.stTextInput input {
    background: #1a1a24 !important; border: 1px solid #2a2a35 !important;
    color: #e8e8e8 !important; border-radius: 8px !important;
}
</style>
""", unsafe_allow_html=True)


def api_get(path, token):
    try:
        r = requests.get(f"{API_URL}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code in (401, 403):
            st.session_state.pop("customer_token", None)
            st.session_state.pop("customer_rfid", None)
            st.error("Session expired. Please log in again.")
            st.rerun()
        st.error(f"API error: {e}")
        return None
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None


# ---- Login ----
if not st.session_state.get("customer_token"):
    st.markdown("## 👤 Customer Login")
    st.markdown("Enter your RFID number and password to view your account.")

    rfid     = st.text_input("RFID Number")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if not rfid or not password:
            st.warning("Please enter both RFID and password.")
        else:
            try:
                res = requests.post(
                    f"{API_URL}/authenticate/customer",
                    json={"rfid": rfid, "password": password},
                    timeout=5,
                )
                if res.status_code == 200:
                    st.session_state["customer_token"] = res.json()["token"]
                    st.session_state["customer_rfid"]  = rfid
                    st.rerun()
                else:
                    st.error("❌ Invalid RFID or password.")
            except requests.exceptions.ConnectionError:
                st.error("⚠️ Cannot connect to API.")

    st.markdown("---")
    st.caption("Your password was provided by your administrator when your card was registered.")
    st.stop()


# ---- Logged in ----
token = st.session_state["customer_token"]
rfid  = st.session_state["customer_rfid"]

with st.sidebar:
    st.markdown(f"**Logged in as:** `{rfid}`")
    if st.button("🚪 Logout"):
        st.session_state.pop("customer_token", None)
        st.session_state.pop("customer_rfid", None)
        st.rerun()

# Fetch card details
card = api_get(f"/rfid/{rfid}", token)
if not card:
    st.stop()

# ---- Balance card ----
if card.get("status") == "blocked":
    st.markdown("""<div class="blocked-card">
        <b style="font-size:1.2rem">🔴 Card Blocked</b><br>
        <span style="font-size:0.9rem">Your card has been blocked. Please contact the administrator.</span>
    </div>""", unsafe_allow_html=True)
else:
    st.markdown(f"""
    <div class="balance-card">
        <div class="balance-label">Available Balance</div>
        <div class="balance-amount">₹{card['balance']:,}</div>
        <div class="rfid-tag">RFID: {rfid}</div>
    </div>
    """, unsafe_allow_html=True)

# ---- Spending summary ----
st.subheader("📅 Today's spending")
txns_data = api_get(f"/transactions/{rfid}?limit=500", token)
txns = txns_data if txns_data else []

today_str = date.today().isoformat()
today_spent = sum(
    t["amount"] for t in txns
    if t.get("transaction_type") == "debit" and t.get("timestamp", "").startswith(today_str)
)

daily_limit = card.get("daily_limit") or 0

if daily_limit > 0:
    progress = min(today_spent / daily_limit, 1.0)
    remaining = max(daily_limit - today_spent, 0)
    col1, col2, col3 = st.columns(3)
    col1.metric("Spent today", f"₹{today_spent:,}")
    col2.metric("Daily limit", f"₹{daily_limit:,}")
    col3.metric("Remaining", f"₹{remaining:,}")
    st.progress(progress, text=f"{progress*100:.0f}% of daily limit used")
else:
    st.metric("Spent today", f"₹{today_spent:,}")
    st.caption("No daily limit set on this card.")

# ---- Transaction history ----
st.markdown("---")
st.subheader("📜 Transaction history")

if not txns:
    st.info("No transactions found.")
else:
    df = pd.DataFrame(txns)

    # Filter controls
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        type_filter = st.selectbox("Filter by type", ["All", "debit", "topup"])
    with filter_col2:
        flag_filter = st.checkbox("Show only flagged")

    if type_filter != "All":
        df = df[df["transaction_type"] == type_filter]
    if flag_filter:
        df = df[df["flagged"] == True]

    if df.empty:
        st.info("No transactions match the filter.")
    else:
        df["flagged_display"] = df["flagged"].apply(lambda x: "🚨" if x else "")
        df["amount_display"]  = df.apply(
            lambda r: f"{'−' if r['transaction_type']=='debit' else '+'} ₹{r['amount']:,}",
            axis=1,
        )
        show_cols = {
            "timestamp":          "Date & Time",
            "transaction_type":   "Type",
            "merchant_name":      "Merchant",
            "amount_display":     "Amount",
            "esp_id":             "Terminal",
            "flagged_display":    "⚑",
        }
        display_df = df[list(show_cols.keys())].copy()
        display_df.columns = list(show_cols.values())
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        st.caption(f"Showing {len(df)} transactions")
