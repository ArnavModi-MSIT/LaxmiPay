# LaxmiPay — Secure RFID Contactless Payment System with JWT Authentication and Real-Time Fraud Detection
 
## Abstract
 
This project presents a production-hardened contactless payment system built on passive RFID technology, designed for deployment in environments such as college canteens, campus transit, or access-controlled facilities. The system integrates IoT hardware (ESP8266 + MFRC522) with a RESTful API backend (FastAPI + SQLite) and a multi-role web dashboard (Streamlit).
 
Authentication is token-based throughout: admin and customer sessions use signed JWT tokens, while ESP8266 hardware endpoints are protected by a shared API key. Passwords are stored as bcrypt hashes and all secrets are managed via environment variables — no credentials are hardcoded.
 
The fraud detection module operates as a pre-processing gate on every payment, applying a rolling 60-second velocity check and a configurable high-value threshold. Administrators can block or unblock individual cards in real time, set per-card daily spending limits, and export full transaction histories as CSV. Every admin action is recorded in a tamper-evident audit log.
 
The system is intentionally lightweight — no external ML services, no message brokers, deployable on a single machine or Raspberry Pi — while following security practices suitable for a real institutional deployment.
 
---
 
## System Architecture
 
```
┌──────────────────────────────────────────────────────────┐
│                      CLIENT LAYER                        │
│  ┌─────────────────────┐    ┌────────────────────────┐   │
│  │  Customer Dashboard  │    │   Admin Dashboard       │   │
│  │  (Balance + History) │    │  (Analytics + Audit)    │   │
│  └──────────┬──────────┘    └──────────┬─────────────┘   │
└─────────────┼──────────────────────────┼─────────────────┘
              │     HTTP/REST + JWT        │
┌─────────────▼──────────────────────────▼─────────────────┐
│                    API LAYER (FastAPI)                    │
│  /authenticate  /rfid  /transactions  /topup  /deduct    │
│  /block-card  /unblock-card  /spending-limit             │
│  /export/transactions  /analytics/summary  /audit-log    │
│                                                           │
│          ┌──────────────────────────────────────┐         │
│          │        Fraud Detection Engine        │         │
│          │  • Card status check (blocked?)      │         │
│          │  • Rolling 60s velocity check        │         │
│          │  • High-value threshold (₹2k)        │         │
│          │  • Daily spending limit enforcement  │         │
│          └──────────────────────────────────────┘         │
└───────────────────────────┬──────────────────────────────┘
                            │ SQLite (WAL mode)
┌───────────────────────────▼──────────────────────────────┐
│                       DATA LAYER                         │
│  RFIDTable | Transactions | UserAuth | AuditLog          │
└───────────────────────────────────────────────────────────┘
                            │ Hardware
┌───────────────────────────▼──────────────────────────────┐
│   ESP8266 + MFRC522 → POST /deduct (X-ESP-API-Key)       │
└────────────────────────────────────────────────────────────┘
```
 
---
 
## Features
 
| Feature | Description |
|---|---|
| **RFID Card Management** | Register, update, and view RFID cards with balance and ESP linkage |
| **QR Code Identity** | Each card has a downloadable QR code for customer-side verification |
| **Contactless Payment** | ESP8266 triggers `/deduct` on card tap; balance deducted atomically |
| **Top-Up** | Admin can add balance to any registered card |
| **JWT Authentication** | Admin and customer sessions are token-based; ESP endpoints use `X-ESP-API-Key` header |
| **Bcrypt Password Hashing** | Passwords stored as bcrypt hashes; legacy SHA-256 hashes auto-migrated on next login |
| **Fraud Detection** | Rolling 60-second velocity check + configurable high-value threshold; thresholds set via env vars |
| **Card Blocking** | Admin can block or unblock any card instantly (lost/stolen card handling) |
| **Daily Spending Limits** | Per-card configurable daily cap enforced at payment time |
| **Idempotency** | ESP8266 sends a unique `request_id`; duplicate requests are rejected to prevent double-charges |
| **Transaction Ledger** | Timestamped, immutable log with fraud flag and transaction type columns |
| **CSV Export** | Admin can download per-card or full transaction history as CSV |
| **Merchant Name** | Each transaction records the terminal/merchant name for readable history |
| **Audit Log** | Every admin action is recorded in a tamper-evident log |
| **Analytics Dashboard** | Daily volume chart, top spenders, flagged transaction rate |
| **WAL Mode** | SQLite runs in Write-Ahead Logging mode to prevent write conflicts from concurrent readers |
 
---
 
## Hardware Requirements
 
| Component | Purpose |
|---|---|
| ESP8266 (NodeMCU) | Wi-Fi microcontroller; sends RFID reads to the API |
| MFRC522 | SPI RFID reader module |
| RFID Cards/Tags | Passive 13.56 MHz Mifare cards |
| Power supply | 5V USB or 3.3V regulated supply |
 
### Wiring (ESP8266 ↔ MFRC522)
 
| MFRC522 Pin | ESP8266 Pin |
|---|---|
| SDA (SS) | D8 (GPIO15) |
| SCK | D5 (GPIO14) |
| MOSI | D7 (GPIO13) |
| MISO | D6 (GPIO12) |
| RST | D3 (GPIO0) |
| GND | GND |
| 3.3V | 3V3 |
 
---
 
## Fraud Detection Design
 
The fraud detection module operates as a **pre-processing gate** on every `/deduct` call. Four independent checks are applied in order:
 
### 1. Card Status Check
 
If the card's `status` is `blocked`, the transaction is **hard-rejected** immediately with a `403`. No balance is read or modified. Admins can toggle this from the dashboard for lost or stolen cards.
 
### 2. Rolling Velocity Check
 
A transaction is flagged and rejected if the same RFID card has been used **≥5 times (debit only) within a true rolling 60-second window**:
 
```python
from datetime import timedelta
one_min_ago = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
# COUNT debit transactions WHERE rfid = X AND timestamp >= one_min_ago
```
 
Top-ups are excluded from the velocity count. The threshold is configurable via `FRAUD_VELOCITY_LIMIT` in `.env`.
 
### 3. High-Value Threshold
 
Any single transaction meeting or exceeding `FRAUD_AMOUNT_THRESHOLD` (default: ₹2,000, configurable via env) is flagged and rejected.
 
### 4. Daily Limit Enforcement
 
If a deduction would cause the card's cumulative daily spend to exceed its configured `daily_limit`, the transaction is **hard-blocked**. Cards with `daily_limit = NULL` have no cap. Limits are set per-card from the Admin Dashboard.
 
Flagged transactions are recorded with `flagged = 1` in the `Transactions` table and visible in the Admin Dashboard under **Flagged Transactions**.
 
---
 
## Database Schema
 
```sql
-- Master card registry
CREATE TABLE RFIDTable (
    RFID                 INTEGER PRIMARY KEY,
    Balance              INTEGER NOT NULL DEFAULT 0,
    ESPID                INTEGER,
    "Transaction Amount" INTEGER,
    status               TEXT    NOT NULL DEFAULT 'active',  -- active | blocked
    daily_limit          INTEGER,                             -- NULL = no limit
    merchant_name        TEXT
);
 
-- Immutable transaction ledger
CREATE TABLE Transactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    rfid             TEXT    NOT NULL,
    esp_id           TEXT    NOT NULL,
    amount           INTEGER NOT NULL,
    merchant_name    TEXT,
    transaction_type TEXT    NOT NULL DEFAULT 'debit',  -- debit | topup
    timestamp        TEXT    NOT NULL,                  -- ISO 8601 UTC
    flagged          INTEGER NOT NULL DEFAULT 0,
    idempotency_key  TEXT    UNIQUE
);
 
-- Customer authentication
CREATE TABLE UserAuth (
    RFID     INTEGER PRIMARY KEY,
    Password TEXT NOT NULL              -- bcrypt hashed
);
 
-- Admin/system action trail
CREATE TABLE AuditLog (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_user TEXT    NOT NULL,
    action     TEXT    NOT NULL,
    target     TEXT,
    details    TEXT,
    timestamp  TEXT    NOT NULL
);
```
 
---
 
## API Reference
 
### Authentication
 
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/authenticate/customer` | None | Customer login → returns JWT |
| `POST` | `/authenticate/admin` | None | Admin login → returns JWT |
 
### Card Operations
 
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/` | None | Health check |
| `GET` | `/rfid/{rfid}` | Bearer JWT | Card details |
| `GET` | `/balance/{rfid}` | Bearer JWT | Balance + status |
| `GET` | `/transactions/{rfid}` | Bearer JWT | Transaction history |
| `GET` | `/rfid-list` | Admin JWT | All registered RFIDs |
| `POST` | `/deduct` | X-ESP-API-Key | Process payment (hardware endpoint) |
| `POST` | `/topup` | Admin JWT | Add balance to a card |
| `PUT` | `/update-rfid` | Admin JWT | Update card ESP/amount settings |
 
### Admin Operations
 
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/block-card` | Admin JWT | Block a card (lost/stolen) |
| `POST` | `/unblock-card` | Admin JWT | Unblock a card |
| `PUT` | `/spending-limit` | Admin JWT | Set per-card daily spending limit |
| `GET` | `/flagged-transactions` | Admin JWT | All flagged transactions |
| `GET` | `/export/transactions/{rfid}` | Admin JWT | Download per-card CSV |
| `GET` | `/export/transactions` | Admin JWT | Download all transactions CSV |
| `GET` | `/analytics/summary` | Admin JWT | System-wide analytics |
| `GET` | `/audit-log` | Admin JWT | Full admin action log |
 
Full interactive docs available at `http://localhost:8000/docs` (Swagger UI).
 
### Request Headers
 
```
# Customer / Admin endpoints
Authorization: Bearer <jwt_token>
 
# ESP8266 hardware endpoint
X-ESP-API-Key: <esp_api_key_from_env>
```
 
---
 
## Setup & Running
 
### Prerequisites
 
- Python 3.10 or higher
- Arduino IDE with ESP8266 board support (for hardware flashing)
### 1. Install dependencies
 
```bash
pip install -r requirements.txt
```
 
### 2. Configure environment
 
```bash
cp .env.example .env
# Edit .env and fill in:
#   SECRET_KEY            — random string for JWT signing
#                           python -c "import secrets; print(secrets.token_hex(32))"
#   ADMIN_USERNAME        — your admin username
#   ADMIN_PASSWORD_HASH   — bcrypt hash of your admin password (see step 3)
#   ESP_API_KEY           — shared secret for ESP8266 hardware requests
#   ALLOWED_ORIGIN        — your Streamlit URL (e.g. http://localhost:8501)
#   FRAUD_VELOCITY_LIMIT  — max debit transactions per 60s before flag (default: 5)
#   FRAUD_AMOUNT_THRESHOLD — single transaction flag threshold in ₹ (default: 2000)
```
 
### 3. Generate admin password hash (run once)
 
```bash
python sm.py
# Follow the prompt — paste the printed bcrypt hash into ADMIN_PASSWORD_HASH in .env
```
 
### 4. Initialize / migrate database
 
```bash
python sm.py
# Safe to run on an existing database — adds new columns without data loss
```
 
### 5. Start API server
 
```bash
uvicorn api:app --reload --port 8000
```
 
### 6. Start Streamlit app (separate terminal)
 
```bash
streamlit run app.py
```
 
### 7. Update ESP8266 Arduino sketch
 
Add this header to every HTTP request in your `.ino` file:
 
```cpp
http.addHeader("X-ESP-API-Key", "your-esp-secret-key-from-env");
```
 
### 8. Generate QR codes
 
```bash
# Single RFID
python qr.py 1234
 
# All RFIDs in database
python qr.py --batch --out ./qr_codes
```
 
---
 
## Project Structure
 
```
LaxmiPay/
├── api.py                     # FastAPI backend — all endpoints, auth, fraud logic
├── sm.py                      # DB setup, migration, bcrypt password utility
├── app.py                     # Streamlit entry point — login, session, JWT storage
├── qr.py                      # QR code generation utility (unchanged)
├── pages/
│   ├── Admin_Dashboard.py     # Admin view — block cards, limits, export, audit log
│   └── Customer_Dashboard.py  # Customer view — balance, spending, transaction history
├── .env.example               # Environment variable template (copy to .env)
├── requirements.txt           # Python dependencies
├── .gitignore                 # Excludes Database.db and .env
└── README.md
```
 
---
 
## Security Notes
 
- Admin credentials are loaded from environment variables (`ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`). Never use default or weak values in production.
- Customer and admin sessions use **JWT tokens** (HS256). Token expiry is configurable via `ACCESS_TOKEN_EXPIRE_MINUTES` in `.env`.
- ESP8266 hardware endpoints are protected by the `X-ESP-API-Key` header. Set a strong random key in `.env` and add it to your Arduino sketch.
- Customer passwords are stored as **bcrypt hashes**. Legacy SHA-256 hashes are auto-verified and migrated on next login.
- `Database.db` is excluded from version control via `.gitignore`. Never commit it — it contains user balances and transaction history.
- Set `ALLOWED_ORIGIN` in `.env` to your Streamlit app's exact URL in production. Do not leave CORS open (`*`) outside local development.
- Enable HTTPS via a reverse proxy (nginx or Caddy) before any public or institutional deployment.
- Fraud thresholds (`FRAUD_VELOCITY_LIMIT`, `FRAUD_AMOUNT_THRESHOLD`) are environment variables — tune them without redeploying.
---
 
## Future Work
 
- Replace SQLite with PostgreSQL for concurrent multi-reader deployments
- SMS/email alert via Twilio or `smtplib` when a transaction is flagged (makes fraud detection actionable rather than just logged)
- ML-based anomaly detection (Isolation Forest) as an additional fraud heuristic layer
- Deploy on Raspberry Pi as edge gateway with MQTT for ESP8266 communication
- PIN-based confirmation for high-value transactions on the ESP hardware side
---
 
## References
 
1. Want, R. (2006). An Introduction to RFID Technology. *IEEE Pervasive Computing*, 5(1), 25–33.
2. Bhattacharyya, R. et al. (2010). RFID-based System for Automated Contactless Payment. *IEEE RFID Conference*.
3. FastAPI Documentation — https://fastapi.tiangolo.com
4. Streamlit Documentation — https://docs.streamlit.io
 
## License
 
MIT License. See `LICENSE` for details.
