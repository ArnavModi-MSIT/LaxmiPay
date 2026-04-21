"""
Admin_Dashboard.py — LaxmiPay admin panel
Features:
  - Analytics overview (daily volume chart, top spenders, flagged rate)
  - RFID card manager (block/unblock, set daily limit, top-up)
  - Flagged transaction review
  - Audit log
  - CSV export (per-card and all transactions)
"""

import os
import streamlit as st
import requests
import pandas as pd

API_URL = os.environ.get("API_URL", "http://localhost:8000")

st.set_page_config(page_title="LaxmiPay Admin", page_icon="🛠️", layout="wide")

# ---- Auth guard ----
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
        st.error(f"API error: {e.response.json().get('detail', str(e))}")
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
        st.error(f"API error: {e.response.json().get('detail', str(e))}")
        return None
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None


# ---- Sidebar ----
with st.sidebar:
    st.markdown("### 🛠️ Admin Panel")
    tab_choice = st.radio(
        "Section",
        ["📊 Analytics", "💳 Card Manager", "🚨 Flagged Transactions", "📋 Audit Log"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    if st.button("🚪 Logout"):
        st.session_state.pop("admin_token", None)
        st.switch_page("app.py")


# ==== ANALYTICS ====
if tab_choice == "📊 Analytics":
    st.title("📊 Analytics Overview")

    data = api_get("/analytics/summary")
    if not data:
        st.stop()

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("💰 Balance in Circulation", f"₹{data['total_balance_in_circulation']:,}")
    col2.metric("📦 Total Transactions",     f"{data['transaction_count']:,}")
    col3.metric("💸 Total Volume",           f"₹{data['transaction_volume']:,}")
    col4.metric("🚨 Flagged",               f"{data['flagged_transactions']}")
    col5.metric("🔒 Blocked Cards",         f"{data['blocked_cards']}")

    st.markdown("---")
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Daily transaction volume (last 14 days)")
        if data["daily_volume"]:
            df_vol = pd.DataFrame(data["daily_volume"]).set_index("day")
            st.bar_chart(df_vol["volume"])
        else:
            st.info("No transaction data yet.")

    with c2:
        st.subheader("Top 5 spenders")
        if data["top_spenders"]:
            df_top = pd.DataFrame(data["top_spenders"])
            df_top.columns = ["RFID", "Total Spent (₹)"]
            st.dataframe(df_top, use_container_width=True, hide_index=True)
        else:
            st.info("No data yet.")

    st.markdown("---")
    st.subheader("📥 Export all transactions")
    if st.button("Download all transactions CSV"):
        try:
            r = requests.get(f"{API_URL}/export/transactions", headers=HEADERS, timeout=30)
            r.raise_for_status()
            st.download_button(
                "💾 Save CSV",
                data=r.content,
                file_name="all_transactions.csv",
                mime="text/csv",
            )
        except Exception as e:
            st.error(f"Export failed: {e}")


# ==== CARD MANAGER ====
elif tab_choice == "💳 Card Manager":
    st.title("💳 Card Manager")

    cards = api_get("/rfid-list")
    if not cards:
        st.info("No cards registered.")
        st.stop()

    df = pd.DataFrame(cards)
    df["status"] = df["status"].fillna("active")
    df["daily_limit"] = df["daily_limit"].fillna(0).astype(int)

    # ---- Summary stats ----
    active_count  = (df["status"] == "active").sum()
    blocked_count = (df["status"] == "blocked").sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Cards", len(df))
    c2.metric("Active",  active_count)
    c3.metric("Blocked", blocked_count)

    st.markdown("---")

    # ---- Card table with color coding ----
    st.subheader("All registered cards")

    def status_badge(s):
        return "🟢 active" if s == "active" else "🔴 blocked"

    display_df = df.copy()
    display_df["status"] = display_df["status"].apply(status_badge)
    display_df["balance"] = display_df["balance"].apply(lambda x: f"₹{x:,}")
    display_df["daily_limit"] = display_df["daily_limit"].apply(
        lambda x: f"₹{x:,}" if x > 0 else "No limit"
    )
    display_df.columns = ["RFID", "Balance", "ESP ID", "Status", "Daily Limit", "Merchant"]
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ---- Operations ----
    rfid_options = df["rfid"].astype(str).tolist()
    selected_rfid = st.selectbox("Select a card to manage", rfid_options)
    selected_row  = df[df["rfid"].astype(str) == selected_rfid].iloc[0]

    st.markdown(f"**Current status:** {'🟢 Active' if selected_row['status'] == 'active' else '🔴 Blocked'}  "
                f"| **Balance:** ₹{selected_row['balance']:,}  "
                f"| **Daily limit:** {'₹' + str(selected_row['daily_limit']) if selected_row['daily_limit'] > 0 else 'None'}")

    op_col1, op_col2, op_col3 = st.columns(3)

    with op_col1:
        st.markdown("#### 🔒 Block / Unblock")
        reason = st.text_input("Reason", value="Lost or stolen card", key="block_reason")
        if selected_row["status"] == "active":
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

    with op_col2:
        st.markdown("#### 💸 Daily Spending Limit")
        new_limit = st.number_input(
            "Set daily limit (₹, 0 = no limit)",
            min_value=0,
            max_value=50000,
            value=int(selected_row["daily_limit"]) if selected_row["daily_limit"] > 0 else 0,
            step=100,
            key="new_limit",
        )
        if st.button("✅ Save Limit"):
            res = api_put("/spending-limit", {"rfid": selected_rfid, "daily_limit": new_limit})
            if res:
                st.success(f"Daily limit set to ₹{new_limit:,}")
                st.rerun()

    with op_col3:
        st.markdown("#### ➕ Top-Up Balance")
        topup_amount = st.number_input("Amount (₹)", min_value=1, max_value=100000, value=500, step=100, key="topup_amt")
        if st.button("💰 Add Balance"):
            res = api_post("/topup", {"rfid": selected_rfid, "amount": topup_amount})
            if res:
                st.success(f"₹{topup_amount:,} added. New balance: ₹{res['new_balance']:,}")
                st.rerun()

    st.markdown("---")
    st.subheader("📜 Transaction history for selected card")
    txns = api_get(f"/transactions/{selected_rfid}?limit=50")
    if txns:
        df_txns = pd.DataFrame(txns)
        df_txns["flagged"] = df_txns["flagged"].apply(lambda x: "🚨 Yes" if x else "—")
        df_txns["amount"]  = df_txns["amount"].apply(lambda x: f"₹{x:,}")
        st.dataframe(df_txns[["timestamp", "transaction_type", "merchant_name", "amount", "esp_id", "flagged"]],
                     use_container_width=True, hide_index=True)

        # CSV export for this card
        try:
            r = requests.get(f"{API_URL}/export/transactions/{selected_rfid}", headers=HEADERS, timeout=30)
            r.raise_for_status()
            st.download_button(
                f"📥 Export RFID {selected_rfid} history as CSV",
                data=r.content,
                file_name=f"transactions_{selected_rfid}.csv",
                mime="text/csv",
            )
        except Exception:
            pass
    else:
        st.info("No transactions found for this card.")


# ==== FLAGGED TRANSACTIONS ====
elif tab_choice == "🚨 Flagged Transactions":
    st.title("🚨 Flagged Transactions")
    st.info("These transactions were flagged by the fraud engine. They were processed normally — review and take action if needed (e.g., block the card).")

    flagged = api_get("/flagged-transactions?limit=200")
    if not flagged:
        st.success("No flagged transactions found.")
        st.stop()

    df = pd.DataFrame(flagged)
    df["amount"] = df["amount"].apply(lambda x: f"₹{x:,}")
    df.columns = ["ID", "RFID", "ESP ID", "Merchant", "Amount", "Timestamp"]
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Quick block a card from this view")
    rfid_to_block = st.text_input("Enter RFID to block")
    block_reason  = st.text_input("Reason", value="Flagged transaction review")
    if st.button("🔴 Block this card"):
        if rfid_to_block:
            res = api_post("/block-card", {"rfid": rfid_to_block, "reason": block_reason})
            if res:
                st.success(f"Card {rfid_to_block} blocked successfully.")
        else:
            st.warning("Enter an RFID number.")


# ==== AUDIT LOG ====
elif tab_choice == "📋 Audit Log":
    st.title("📋 Audit Log")

    limit = st.slider("Number of entries", 50, 1000, 200, step=50)
    logs  = api_get(f"/audit-log?limit={limit}")

    if not logs:
        st.info("No audit logs found.")
        st.stop()

    df = pd.DataFrame(logs)
    df.columns = ["Action", "RFID", "Detail", "Timestamp"]

    # Filter by action type
    action_types = ["All"] + sorted(df["Action"].unique().tolist())
    selected_action = st.selectbox("Filter by action", action_types)
    if selected_action != "All":
        df = df[df["Action"] == selected_action]

    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"Showing {len(df)} entries")
