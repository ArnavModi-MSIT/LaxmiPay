import streamlit as st
import requests
import pandas as pd

API_URL = "http://localhost:8000"

st.set_page_config(page_title="LaxmiPay Admin", page_icon="🛠️", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');
html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.stApp { background: #0f0f13; color: #e8e8e8; }
div[data-testid="metric-container"] { background: #181820; border: 1px solid #2a2a35; border-radius: 12px; padding: 0.8rem; }
[data-testid="stSidebar"] { background: #0d0d11 !important; border-right: 1px solid #1e1e28; }
.stButton > button { border-radius: 8px; font-family: 'IBM Plex Mono', monospace; }
.stTextInput input { background: #1a1a24 !important; border: 1px solid #2a2a35 !important; color: #e8e8e8 !important; border-radius: 8px !important; }
.stNumberInput input { background: #1a1a24 !important; border: 1px solid #2a2a35 !important; color: #e8e8e8 !important; border-radius: 8px !important; }
.stSelectbox > div > div { background: #1a1a24 !important; border: 1px solid #2a2a35 !important; }
</style>
""", unsafe_allow_html=True)

token = st.session_state.get("admin_token")
if not token:
    st.error("🔒 Please log in from the home page first.")
    if st.button("Go to Login"):
        st.switch_page("app.py")
    st.stop()

HEADERS = {"Authorization": f"Bearer {token}"}


def api_get(path, **kwargs):
    try:
        r = requests.get(f"{API_URL}{path}", headers=HEADERS, timeout=10, **kwargs)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            st.session_state.pop("admin_token", None)
            st.error("Session expired. Please log in again.")
            st.stop()
        st.error(f"API error: {e}")
        return None
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None


def api_post(path, json_body):
    try:
        r = requests.post(f"{API_URL}{path}", headers=HEADERS, json=json_body, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        detail = e.response.json().get("detail", str(e)) if e.response else str(e)
        st.error(f"Error: {detail}")
        return None
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None


def api_put(path, json_body):
    try:
        r = requests.put(f"{API_URL}{path}", headers=HEADERS, json=json_body, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        detail = e.response.json().get("detail", str(e)) if e.response else str(e)
        st.error(f"Error: {detail}")
        return None
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None


with st.sidebar:
    st.markdown("### 🛠️ Admin Panel")
    section = st.radio(
        "Section",
        ["📊 Analytics", "💳 Card Manager", "💸 Simulate Payment", "🚨 Flagged", "📋 Audit Log"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    if st.button("🚪 Logout"):
        st.session_state.pop("admin_token", None)
        st.switch_page("app.py")


if section == "📊 Analytics":
    st.title("📊 Analytics Overview")

    data = api_get("/analytics/summary")
    if not data:
        st.stop()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("💰 In Circulation", f"₹{data['total_balance_in_circulation']:,}")
    c2.metric("📦 Transactions",   f"{data['transaction_count']:,}")
    c3.metric("💸 Total Volume",   f"₹{data['transaction_volume']:,}")
    c4.metric("🚨 Flagged",        f"{data['flagged_transactions']}")
    c5.metric("🔒 Blocked Cards",  f"{data['blocked_cards']} / {data['total_cards']}")

    st.markdown("---")
    col_l, col_r = st.columns([3, 2])

    with col_l:
        st.subheader("Daily Transaction Volume (last 14 days)")
        if data["daily_volume"]:
            df_vol = pd.DataFrame(data["daily_volume"])
            df_vol["day"] = pd.to_datetime(df_vol["day"])
            df_vol = df_vol.sort_values("day").set_index("day")
            st.area_chart(df_vol["volume"], color="#00e5a0")
        else:
            st.info("No transaction data yet.")

    with col_r:
        st.subheader("Top 5 Spenders")
        if data["top_spenders"]:
            df_top = pd.DataFrame(data["top_spenders"])
            df_top.columns = ["RFID", "Total Spent (₹)"]
            df_top = df_top.sort_values("Total Spent (₹)", ascending=True)
            st.bar_chart(df_top.set_index("RFID"), color="#00e5a0")
        else:
            st.info("No spending data yet.")

    st.markdown("---")
    fraud_pct = round(data["flagged_transactions"] / data["transaction_count"] * 100, 2) if data["transaction_count"] > 0 else 0
    c1, c2 = st.columns([1, 2])
    c1.metric("Fraud Rate", f"{fraud_pct}%")
    with c2:
        st.markdown(f"""
**Active detection rules:**
- Velocity check — flags >5 transactions within 60 seconds from same RFID
- High-value check — flags single transactions ≥ ₹2,000

Current fraud rate: `{fraud_pct}%` of total transactions
        """)

    st.markdown("---")
    st.subheader("📥 Export")
    if st.button("Download all transactions as CSV"):
        try:
            r = requests.get(f"{API_URL}/export/transactions", headers=HEADERS, timeout=30)
            r.raise_for_status()
            st.download_button("💾 Save CSV", data=r.content, file_name="all_transactions.csv", mime="text/csv")
        except Exception as e:
            st.error(f"Export failed: {e}")


elif section == "💳 Card Manager":
    st.title("💳 Card Manager")

    tab_list, tab_new = st.tabs(["Manage Existing Cards", "Add New Card"])

    with tab_list:
        cards = api_get("/rfid-list")
        if not cards:
            st.info("No cards registered.")
            st.stop()

        df = pd.DataFrame(cards)
        df["status"] = df["status"].fillna("active")
        df["daily_limit"] = df["daily_limit"].fillna(0).astype(int)

        a, b, c = st.columns(3)
        a.metric("Total Cards", len(df))
        b.metric("Active", (df["status"] == "active").sum())
        c.metric("Blocked", (df["status"] == "blocked").sum())

        st.markdown("---")
        st.subheader("All Cards")
        disp = df.copy()
        disp["status"] = disp["status"].apply(lambda s: "🟢 Active" if s == "active" else "🔴 Blocked")
        disp["balance"] = disp["balance"].apply(lambda x: f"₹{x:,}")
        disp["daily_limit"] = disp["daily_limit"].apply(lambda x: f"₹{x:,}" if x > 0 else "No limit")
        disp.columns = ["RFID", "Balance", "Status", "Daily Limit", "Merchant"]
        st.dataframe(disp, use_container_width=True, hide_index=True)

        st.markdown("---")
        rfid_options = df["rfid"].astype(str).tolist()
        selected_rfid = st.selectbox("Select card to manage", rfid_options)
        row = df[df["rfid"].astype(str) == selected_rfid].iloc[0]

        st.markdown(
            f"**Status:** {'🟢 Active' if row['status'] == 'active' else '🔴 Blocked'}  "
            f"| **Balance:** ₹{row['balance']:,}  "
            f"| **Daily limit:** {'₹' + str(int(row['daily_limit'])) if row['daily_limit'] > 0 else 'None'}"
        )

        op1, op2, op3 = st.columns(3)

        with op1:
            st.markdown("#### 🔒 Block / Unblock")
            reason = st.text_input("Reason", value="Admin action", key="block_reason")
            if row["status"] == "active":
                if st.button("🔴 Block Card", type="primary"):
                    res = api_post("/block-card", {"rfid": selected_rfid, "reason": reason})
                    if res:
                        st.success(f"Card {selected_rfid} blocked.")
                        st.rerun()
            else:
                if st.button("🟢 Unblock Card", type="primary"):
                    res = api_post("/unblock-card", {"rfid": selected_rfid, "reason": reason})
                    if res:
                        st.success(f"Card {selected_rfid} unblocked.")
                        st.rerun()

        with op2:
            st.markdown("#### 💸 Daily Limit")
            new_limit = st.number_input(
                "Set limit (₹, 0 = none)",
                min_value=0, max_value=50000,
                value=int(row["daily_limit"]) if row["daily_limit"] > 0 else 0,
                step=100, key="new_limit"
            )
            if st.button("✅ Save Limit"):
                res = api_put("/spending-limit", {"rfid": selected_rfid, "daily_limit": new_limit})
                if res:
                    st.success(f"Limit set to ₹{new_limit:,}")
                    st.rerun()

        with op3:
            st.markdown("#### ➕ Top-Up")
            topup_amount = st.number_input("Amount (₹)", min_value=1, max_value=100000, value=500, step=100, key="topup_amt")
            if st.button("💰 Add Balance"):
                res = api_post("/topup", {"rfid": selected_rfid, "amount": topup_amount})
                if res:
                    st.success(f"₹{topup_amount:,} added. New balance: ₹{res['new_balance']:,}")
                    st.rerun()

        st.markdown("---")
        st.subheader(f"Transaction History — {selected_rfid}")
        txns = api_get(f"/transactions/{selected_rfid}?limit=50")
        if txns:
            df_txns = pd.DataFrame(txns)
            df_txns["flagged"] = df_txns["flagged"].apply(lambda x: "🚨 Yes" if x else "—")
            df_txns["amount"] = df_txns["amount"].apply(lambda x: f"₹{x:,}")
            st.dataframe(
                df_txns[["timestamp", "transaction_type", "merchant_name", "amount", "flagged"]],
                use_container_width=True, hide_index=True
            )
            try:
                r = requests.get(f"{API_URL}/export/transactions/{selected_rfid}", headers=HEADERS, timeout=30)
                r.raise_for_status()
                st.download_button(f"📥 Export CSV", data=r.content, file_name=f"transactions_{selected_rfid}.csv", mime="text/csv")
            except Exception:
                pass
        else:
            st.info("No transactions found for this card.")

    with tab_new:
        st.subheader("Register New Card")
        with st.form("new_card_form"):
            new_rfid = st.text_input("RFID Number")
            new_password = st.text_input("Password for cardholder", type="password")
            init_balance = st.number_input("Initial Balance (₹)", min_value=0, max_value=100000, value=1000, step=100)
            new_merchant = st.text_input("Merchant / Location (optional)")
            new_limit = st.number_input("Daily Limit (₹, 0 = none)", min_value=0, max_value=50000, value=0, step=100)
            submitted = st.form_submit_button("✅ Register Card")

        if submitted:
            if not new_rfid or not new_password:
                st.warning("RFID and password are required.")
            else:
                res = api_post("/cards", {
                    "rfid": new_rfid,
                    "password": new_password,
                    "initial_balance": init_balance,
                    "merchant_name": new_merchant or None,
                    "daily_limit": new_limit if new_limit > 0 else None,
                })
                if res:
                    st.success(f"Card {new_rfid} registered with balance ₹{init_balance:,}.")


elif section == "💸 Simulate Payment":
    st.title("💸 Simulate Payment")
    st.info("Use this to demonstrate the full payment flow — simulates a customer tapping their card at a merchant terminal.")

    cards = api_get("/rfid-list")
    if not cards:
        st.stop()

    rfid_options = [c["rfid"] for c in cards if c["status"] == "active"]
    merchants = ["Main Canteen", "North Block Cafe", "Library Kiosk", "Sports Canteen", "Vending Machine", "East Wing Cafe", "Bookstore"]

    col1, col2 = st.columns(2)
    with col1:
        selected_rfid = st.selectbox("Select RFID (active cards only)", rfid_options)
        selected_merchant = st.selectbox("Merchant", merchants)
        payment_amount = st.number_input("Payment Amount (₹)", min_value=1, max_value=10000, value=100, step=10)

    with col2:
        if selected_rfid:
            card_info = next((c for c in cards if c["rfid"] == selected_rfid), None)
            if card_info:
                st.markdown("**Card Details**")
                st.metric("Current Balance", f"₹{card_info['balance']:,}")
                if card_info.get("daily_limit"):
                    st.metric("Daily Limit", f"₹{card_info['daily_limit']:,}")
                else:
                    st.caption("No daily limit set")

    st.markdown("---")
    if st.button("⚡ Process Payment", type="primary"):
        res = api_post("/pay", {
            "rfid": selected_rfid,
            "amount": payment_amount,
            "merchant_name": selected_merchant,
        })
        if res:
            if res.get("flagged"):
                st.warning(f"⚠️ Payment processed but **flagged**: {res['fraud_reason']}")
            else:
                st.success(f"✅ Payment of ₹{payment_amount:,} processed at {selected_merchant}.")
            col_a, col_b = st.columns(2)
            col_a.metric("Amount Deducted", f"₹{res['amount_deducted']:,}")
            col_b.metric("New Balance", f"₹{res['new_balance']:,}")

    st.markdown("---")
    st.subheader("Recent Transactions")
    if selected_rfid:
        txns = api_get(f"/transactions/{selected_rfid}?limit=10")
        if txns:
            df = pd.DataFrame(txns)
            df["flagged"] = df["flagged"].apply(lambda x: "🚨" if x else "✅")
            df["amount"] = df["amount"].apply(lambda x: f"₹{x:,}")
            st.dataframe(df[["timestamp", "transaction_type", "merchant_name", "amount", "flagged"]], use_container_width=True, hide_index=True)


elif section == "🚨 Flagged":
    st.title("🚨 Flagged Transactions")
    st.info("These transactions were flagged by the fraud engine but were still processed. Review and block cards if needed.")

    flagged = api_get("/flagged-transactions?limit=200")
    if not flagged:
        st.success("No flagged transactions.")
        st.stop()

    df = pd.DataFrame(flagged)
    df["amount"] = df["amount"].apply(lambda x: f"₹{x:,}")
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Quick Block")
    rfid_to_block = st.text_input("Enter RFID to block")
    block_reason = st.text_input("Reason", value="Flagged transaction review")
    if st.button("🔴 Block Card"):
        if rfid_to_block:
            res = api_post("/block-card", {"rfid": rfid_to_block, "reason": block_reason})
            if res:
                st.success(f"Card {rfid_to_block} blocked.")
        else:
            st.warning("Enter an RFID.")


elif section == "📋 Audit Log":
    st.title("📋 Audit Log")

    limit = st.slider("Number of entries", 50, 1000, 200, step=50)
    logs = api_get(f"/audit-log?limit={limit}")

    if not logs:
        st.info("No audit log entries.")
        st.stop()

    df = pd.DataFrame(logs)
    df.columns = ["Action", "RFID", "Detail", "Timestamp"]

    action_types = ["All"] + sorted(df["Action"].unique().tolist())
    selected_action = st.selectbox("Filter by action", action_types)
    if selected_action != "All":
        df = df[df["Action"] == selected_action]

    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"Showing {len(df)} entries")