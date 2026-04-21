import streamlit as st
import requests
import pandas as pd
from datetime import date
from cryptography.fernet import Fernet

API_URL = "http://localhost:8000"

# Encryption key (must match qr.py)
ENCRYPTION_KEY = b"z1cXRBEAIY301GjtQOzr2xx1iygts7K_QSAeuQTtJ3o="
cipher = Fernet(ENCRYPTION_KEY)

st.set_page_config(page_title="LaxmiPay", page_icon="💳", layout="centered")

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
    font-size: 3rem; font-weight: 600; color: #00e5a0;
}
.balance-label { font-size: 0.78rem; color: #888; letter-spacing: 2px; text-transform: uppercase; }
.rfid-tag { font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; color: #555; margin-top: 0.4rem; }

.blocked-card {
    background: #2e0a0a; border: 1px solid #ff5c5c;
    border-radius: 16px; padding: 1.5rem; text-align: center;
    color: #ff5c5c; margin-bottom: 1.5rem;
}
.scan-hint {
    background: #0d1a14; border: 1px dashed #00e5a0;
    border-radius: 12px; padding: 1rem 1.2rem;
    color: #00e5a0; font-size: 0.85rem;
    font-family: 'IBM Plex Mono', monospace;
    margin-bottom: 1rem; text-align: center;
}
.rfid-badge {
    display: inline-block;
    background: #0a2e1f; border: 1px solid #00e5a0;
    border-radius: 8px; padding: 0.4rem 1rem;
    font-family: 'IBM Plex Mono', monospace;
    color: #00e5a0; font-size: 1rem;
    margin: 0.5rem 0 1rem 0;
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
.stNumberInput input {
    background: #1a1a24 !important; border: 1px solid #2a2a35 !important;
    color: #e8e8e8 !important; border-radius: 8px !important;
}
div[data-testid="metric-container"] {
    background: #181820; border: 1px solid #2a2a35;
    border-radius: 12px; padding: 0.8rem;
}
[data-testid="stSidebar"] { background: #0d0d11 !important; border-right: 1px solid #1e1e28; }

/* Style the camera widget */
[data-testid="stCameraInput"] label { color: #888 !important; }
[data-testid="stCameraInput"] button {
    background: #00e5a0 !important; color: #0f0f13 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    border-radius: 8px !important; font-weight: 600 !important;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────

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


def api_post(path, token, json_body):
    try:
        r = requests.post(f"{API_URL}{path}", headers={"Authorization": f"Bearer {token}"}, json=json_body, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        detail = e.response.json().get("detail", str(e)) if e.response else str(e)
        st.error(f"Error: {detail}")
        return None
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None


def decrypt_qr_data(encrypted_data: str) -> str:
    """Decrypt encrypted QR code data. Returns decrypted string or None on failure."""
    try:
        decrypted = cipher.decrypt(encrypted_data.encode())
        return decrypted.decode('utf-8')
    except Exception:
        return None


def decode_qr_from_image(img_bytes):
    """
    Decode a QR code from raw image bytes.
    Tries pyzbar first, then falls back to OpenCV.
    Returns the decoded string or None.
    """
    from PIL import Image
    import io as _io
    img = Image.open(_io.BytesIO(img_bytes)).convert("RGB")

    # ── Attempt 1: pyzbar (fastest, most reliable) ──────────────────────────
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
        results = pyzbar_decode(img)
        if results:
            return results[0].data.decode("utf-8").strip()
    except ImportError:
        pass  # pyzbar not installed, try opencv

    # ── Attempt 2: OpenCV QRCodeDetector ─────────────────────────────────────
    try:
        import cv2
        import numpy as np
        cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        detector = cv2.QRCodeDetector()
        value, _, _ = detector.detectAndDecode(cv_img)
        if value:
            return value.strip()
    except ImportError:
        pass

    return None


def do_login(rfid: str, password: str) -> bool:
    """Call the API, store token+rfid on success. Returns True on success."""
    try:
        res = requests.post(
            f"{API_URL}/authenticate/customer",
            json={"rfid": rfid, "password": password},
            timeout=5,
        )
        if res.status_code == 200:
            st.session_state["customer_token"] = res.json()["token"]
            st.session_state["customer_rfid"] = rfid
            return True
        return False
    except requests.exceptions.ConnectionError:
        st.error("⚠️ Cannot connect to API. Make sure `uvicorn api:app --reload` is running.")
        return False


# ─────────────────────────────────────────────
# LOGIN SCREEN
# ─────────────────────────────────────────────

if not st.session_state.get("customer_token"):

    st.markdown("## 💳 LaxmiPay — Customer Portal")
    st.markdown("---")

    tab_manual, tab_qr = st.tabs(["🔑 Password Login", "📷 Scan QR Code"])

    # ── Manual login ──────────────────────────────────────────────────────────
    with tab_manual:
        st.markdown("")
        rfid_manual = st.text_input("RFID Number", key="manual_rfid")
        password_manual = st.text_input("Password", type="password", key="manual_pass")

        if st.button("Login", key="manual_login_btn"):
            if not rfid_manual or not password_manual:
                st.warning("Enter both RFID and password.")
            elif do_login(rfid_manual.strip(), password_manual):
                st.success("✅ Login successful!")
                st.rerun()
            else:
                st.error("❌ Invalid RFID or password.")

        st.markdown("---")
        st.caption("Demo: use any RFID from sm.py output with password `pass{RFID}`, or scan QR code for instant login")

    # ── QR scan login ─────────────────────────────────────────────────────────
    with tab_qr:
        st.markdown("")

        # If we already decoded an RFID from the camera, skip straight to password entry
        if st.session_state.get("qr_scanned_rfid"):
            scanned = st.session_state["qr_scanned_rfid"]
            st.success(f"✅ QR code detected!")
            st.markdown(f'<div class="rfid-badge">RFID: {scanned}</div>', unsafe_allow_html=True)

            password_qr = st.text_input("Enter your password to confirm", type="password", key="qr_pass")

            col_login, col_rescan = st.columns(2)
            with col_login:
                if st.button("🔓 Login", key="qr_login_btn"):
                    if not password_qr:
                        st.warning("Enter your password.")
                    elif do_login(scanned, password_qr):
                        st.session_state.pop("qr_scanned_rfid", None)
                        st.success("✅ Login successful!")
                        st.rerun()
                    else:
                        st.error("❌ Incorrect password.")
            with col_rescan:
                if st.button("🔄 Scan Again", key="qr_rescan_btn"):
                    st.session_state.pop("qr_scanned_rfid", None)
                    st.rerun()

        else:
            st.markdown(
                '<div class="scan-hint">📱 Hold your RFID QR code in front of the camera,<br>'
                'and login instantly without password!</div>',
                unsafe_allow_html=True,
            )

            img_file = st.camera_input(
                "Point your camera at the QR code",
                key="qr_camera",
                label_visibility="collapsed",
            )

            if img_file is not None:
                raw_bytes = img_file.getvalue()
                with st.spinner("Decoding QR code…"):
                    result = decode_qr_from_image(raw_bytes)

                if result:
                    # Try to decrypt
                    decrypted = decrypt_qr_data(result)
                    
                    if decrypted and ":" in decrypted:
                        # Successfully decrypted and contains rfid:password
                        rfid, password = decrypted.split(":", 1)
                        rfid = rfid.strip()
                        password = password.strip()
                        if do_login(rfid, password):
                            st.success("✅ Login successful via QR code!")
                            st.rerun()
                        else:
                            st.error("❌ Invalid QR code or credentials.")
                    elif ":" in result:
                        # Not encrypted, but contains rfid:password (legacy)
                        rfid, password = result.split(":", 1)
                        rfid = rfid.strip()
                        password = password.strip()
                        if do_login(rfid, password):
                            st.success("✅ Login successful via QR code!")
                            st.rerun()
                        else:
                            st.error("❌ Invalid QR code or credentials.")
                    else:
                        # Just RFID, ask for password (legacy)
                        st.session_state["qr_scanned_rfid"] = result
                        st.rerun()
                else:
                    st.error(
                        "⚠️ No QR code detected. Make sure the code is in focus and well-lit, then try again."
                    )
                    st.caption(
                        "If this keeps failing, install pyzbar for better detection: "
                        "`pip install pyzbar`"
                    )

        st.markdown("---")
        st.caption("QR codes are generated by `qr.py`. Run `python qr.py --batch` to generate all.")

    st.stop()


# ─────────────────────────────────────────────
# AUTHENTICATED DASHBOARD
# ─────────────────────────────────────────────

token = st.session_state["customer_token"]
rfid  = st.session_state["customer_rfid"]

with st.sidebar:
    st.markdown(f"**RFID:** `{rfid}`")
    if st.button("🚪 Logout"):
        st.session_state.pop("customer_token", None)
        st.session_state.pop("customer_rfid", None)
        st.session_state.pop("qr_scanned_rfid", None)
        st.rerun()

card = api_get(f"/rfid/{rfid}", token)
if not card:
    st.stop()

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

txns_data = api_get(f"/transactions/{rfid}?limit=500", token)
txns = txns_data if txns_data else []

today_str = date.today().isoformat()
today_spent = sum(
    t["amount"] for t in txns
    if t.get("transaction_type") == "debit" and t.get("timestamp", "").startswith(today_str)
)

daily_limit = card.get("daily_limit") or 0

st.subheader("📅 Today's Spending")
if daily_limit > 0:
    progress  = min(today_spent / daily_limit, 1.0)
    remaining = max(daily_limit - today_spent, 0)
    c1, c2, c3 = st.columns(3)
    c1.metric("Spent today", f"₹{today_spent:,}")
    c2.metric("Daily limit", f"₹{daily_limit:,}")
    c3.metric("Remaining",   f"₹{remaining:,}")
    st.progress(progress, text=f"{progress*100:.0f}% of daily limit used")
else:
    st.metric("Spent today", f"₹{today_spent:,}")
    st.caption("No daily limit on this card.")


if card.get("status") != "blocked":
    st.markdown("---")
    st.subheader("⚡ Make a Payment")

    merchants = ["Main Canteen", "North Block Cafe", "Library Kiosk",
                 "Sports Canteen", "Vending Machine", "East Wing Cafe", "Bookstore"]
    col1, col2 = st.columns(2)
    with col1:
        merchant = st.selectbox("Merchant", merchants)
    with col2:
        amount = st.number_input(
            "Amount (₹)", min_value=1, max_value=card["balance"],
            value=min(100, card["balance"]), step=10,
        )

    if st.button("💳 Pay Now"):
        res = api_post("/pay", token, {"rfid": rfid, "amount": amount, "merchant_name": merchant})
        if res:
            if res.get("flagged"):
                st.warning(f"⚠️ Payment processed but flagged: {res['fraud_reason']}")
            else:
                st.success(f"✅ ₹{amount:,} paid to {merchant}")
            st.metric("New Balance", f"₹{res['new_balance']:,}")
            st.rerun()


st.markdown("---")
st.subheader("📜 Transaction History")

if not txns:
    st.info("No transactions found.")
else:
    df = pd.DataFrame(txns)

    f1, f2 = st.columns(2)
    with f1:
        type_filter = st.selectbox("Filter by type", ["All", "debit", "topup"])
    with f2:
        flag_filter = st.checkbox("Show only flagged")

    if type_filter != "All":
        df = df[df["transaction_type"] == type_filter]
    if flag_filter:
        df = df[df["flagged"] == True]

    if df.empty:
        st.info("No transactions match the filter.")
    else:
        df["flagged_display"]  = df["flagged"].apply(lambda x: "🚨" if x else "")
        df["amount_display"]   = df.apply(
            lambda r: f"{'−' if r['transaction_type'] == 'debit' else '+'} ₹{r['amount']:,}", axis=1
        )
        show = df[["timestamp", "transaction_type", "merchant_name", "amount_display", "flagged_display"]].copy()
        show.columns = ["Date & Time", "Type", "Merchant", "Amount", "⚑"]
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.caption(f"Showing {len(df)} transactions")