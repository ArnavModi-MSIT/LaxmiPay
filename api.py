"""
api.py — FastAPI backend for LaxmiPay RFID Payment System
Improvements:
  - bcrypt password hashing (passlib)
  - JWT authentication for admin & customer endpoints
  - Admin credentials from environment variables
  - ESP endpoints protected by X-ESP-API-Key header
  - CORS restricted to configured origin
  - WAL mode on SQLite
  - Fixed velocity check (rolling 60-second window)
  - Card blocking (status column)
  - Idempotency key on /deduct to prevent double-charge
  - Daily spending limit per card
  - Merchant name stored per transaction
  - transaction_type column (debit / credit / topup)
  - Fraud thresholds from environment variables
  - /block-card and /unblock-card endpoints
  - /export/transactions/{rfid} CSV endpoint
"""

import os
import csv
import io
from datetime import datetime, timezone, timedelta

import sqlite3
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator
from passlib.context import CryptContext
from jose import JWTError, jwt

# ---------- Config (from environment) ----------
DB_PATH                 = os.environ.get("DB_PATH", "./Database.db")
SECRET_KEY              = os.environ.get("SECRET_KEY", "change-me-in-production-use-a-long-random-string")
JWT_ALGORITHM           = "HS256"
JWT_EXPIRE_MINUTES      = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))   # 8 hours

ADMIN_USERNAME          = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH     = os.environ.get("ADMIN_PASSWORD_HASH", "")          # bcrypt hash of admin password
ESP_API_KEY             = os.environ.get("ESP_API_KEY", "esp-secret-key-change-me")

FRAUD_VELOCITY_LIMIT    = int(os.environ.get("FRAUD_VELOCITY_LIMIT", "5"))    # max txns per 60s
FRAUD_AMOUNT_THRESHOLD  = int(os.environ.get("FRAUD_AMOUNT_THRESHOLD", "2000"))

ALLOWED_ORIGIN          = os.environ.get("ALLOWED_ORIGIN", "*")              # e.g. http://localhost:8501

# ---------- App ----------
app = FastAPI(
    title="LaxmiPay RFID Payment API",
    description="Secure RFID-based contactless payment system with fraud detection",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN] if ALLOWED_ORIGIN != "*" else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Auth helpers ----------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def _hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _verify_password(plain: str, hashed: str) -> bool:
    # Support legacy SHA-256 during migration
    import hashlib
    if hashed == hashlib.sha256(plain.encode()).hexdigest():
        return True
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def _create_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    return jwt.encode({"sub": subject, "role": role, "exp": expire}, SECRET_KEY, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def require_admin(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    payload = _decode_token(credentials.credentials)
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload


def require_customer_or_admin(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    payload = _decode_token(credentials.credentials)
    if payload.get("role") not in ("customer", "admin"):
        raise HTTPException(status_code=403, detail="Access denied")
    return payload


def require_esp_key(x_esp_api_key: str = Header(default="")):
    if x_esp_api_key != ESP_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid ESP API key")


# ---------- DB helper ----------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe for concurrent reads+writes
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _log_audit(conn, action: str, rfid: str, detail: str):
    conn.execute(
        "INSERT INTO AuditLog (action, rfid, detail, timestamp) VALUES (?, ?, ?, ?)",
        (action, rfid, detail, datetime.now(timezone.utc).isoformat()),
    )


# ---------- Pydantic models ----------
class UserAuthRequest(BaseModel):
    rfid: str
    password: str


class AdminAuthRequest(BaseModel):
    username: str
    password: str


class DeductRequest(BaseModel):
    rfid: str
    espid: str
    amount: int
    merchant_name: Optional[str] = "Unknown"
    idempotency_key: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v):
        if v <= 0:
            raise ValueError("Deduction amount must be positive")
        return v


class TopUpRequest(BaseModel):
    rfid: str
    amount: int

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v):
        if v <= 0:
            raise ValueError("Top-up amount must be positive")
        return v


class UpdateRFIDRequest(BaseModel):
    rfid: str
    espid: str
    transaction_amount: int
    merchant_name: Optional[str] = None

    @field_validator("transaction_amount")
    @classmethod
    def positive_amount(cls, v):
        if v < 0:
            raise ValueError("Transaction amount cannot be negative")
        return v


class SpendingLimitRequest(BaseModel):
    rfid: str
    daily_limit: int

    @field_validator("daily_limit")
    @classmethod
    def non_negative(cls, v):
        if v < 0:
            raise ValueError("Daily limit cannot be negative")
        return v


class BlockCardRequest(BaseModel):
    rfid: str
    reason: Optional[str] = "Admin action"


class TransactionResponse(BaseModel):
    rfid: str
    esp_id: str
    amount: int
    merchant_name: Optional[str] = None
    transaction_type: Optional[str] = None
    timestamp: Optional[str] = None
    flagged: Optional[bool] = False


# ---------- Fraud detection ----------
def _check_fraud(conn, rfid: str, amount: int) -> dict:
    """
    Two-factor fraud heuristic:
    1. Rolling velocity check — >FRAUD_VELOCITY_LIMIT debit transactions in last 60 seconds
    2. Amount check — single transaction exceeding FRAUD_AMOUNT_THRESHOLD
    """
    # Rolling 60-second window (fixed from original [:16] bug)
    sixty_seconds_ago = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()

    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM Transactions
           WHERE rfid = ? AND timestamp >= ? AND transaction_type = 'debit'""",
        (rfid, sixty_seconds_ago),
    ).fetchone()

    velocity = row["cnt"] if row else 0
    if velocity >= FRAUD_VELOCITY_LIMIT:
        return {"flagged": True, "reason": f"Velocity exceeded: {velocity} txns/60s"}

    if amount >= FRAUD_AMOUNT_THRESHOLD:
        return {"flagged": True, "reason": f"High-value transaction: ₹{amount}"}

    return {"flagged": False, "reason": ""}


def _check_daily_limit(conn, rfid: str, amount: int) -> bool:
    """Returns True if this transaction would exceed the card's daily limit."""
    card = conn.execute(
        "SELECT daily_limit FROM RFIDTable WHERE RFID = ?", (rfid,)
    ).fetchone()
    if not card or not card["daily_limit"]:
        return False  # no limit set

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    spent_today = conn.execute(
        """SELECT COALESCE(SUM(amount), 0) as total FROM Transactions
           WHERE rfid = ? AND transaction_type = 'debit' AND timestamp >= ?""",
        (rfid, today_start),
    ).fetchone()["total"]

    return (spent_today + amount) > card["daily_limit"]


# ---------- Endpoints ----------

@app.get("/")
def home():
    return {"message": "LaxmiPay API v3.0 running.", "docs": "/docs"}


# --- Auth ---

@app.post("/authenticate/customer")
def authenticate_customer(request: UserAuthRequest):
    with get_db() as conn:
        user = conn.execute(
            "SELECT Password FROM UserAuth WHERE RFID = ?", (request.rfid,)
        ).fetchone()
        if user and _verify_password(request.password, user["Password"]):
            token = _create_token(subject=request.rfid, role="customer")
            _log_audit(conn, "CUSTOMER_LOGIN", request.rfid, "Login successful")
            conn.commit()
            return {"status": "success", "token": token}
        raise HTTPException(status_code=401, detail="Invalid RFID or password")


@app.post("/authenticate/admin")
def authenticate_admin(request: AdminAuthRequest):
    if request.username != ADMIN_USERNAME:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # If ADMIN_PASSWORD_HASH is set in env, use bcrypt verification
    if ADMIN_PASSWORD_HASH:
        if not pwd_context.verify(request.password, ADMIN_PASSWORD_HASH):
            raise HTTPException(status_code=401, detail="Invalid credentials")
    else:
        # Fallback: plain comparison — only for local dev, never in production
        import hashlib
        plain_hash = os.environ.get("ADMIN_PASSWORD_PLAIN", "admin")
        if request.password != plain_hash:
            raise HTTPException(status_code=401, detail="Invalid credentials")

    token = _create_token(subject=request.username, role="admin")
    return {"status": "success", "token": token}


# --- Card info (requires customer or admin token) ---

@app.get("/rfid/{rfid}")
def get_rfid_details(rfid: str, auth=Depends(require_customer_or_admin)):
    with get_db() as conn:
        result = conn.execute(
            "SELECT Balance, ESPID, status, daily_limit, merchant_name FROM RFIDTable WHERE RFID = ?", (rfid,)
        ).fetchone()
        if result:
            return {
                "rfid": rfid,
                "balance": result["Balance"],
                "esp_id": result["ESPID"],
                "status": result["status"] or "active",
                "daily_limit": result["daily_limit"],
                "merchant_name": result["merchant_name"],
            }
        raise HTTPException(status_code=404, detail="RFID not found")


@app.get("/balance/{rfid}")
def get_balance(rfid: str, auth=Depends(require_customer_or_admin)):
    with get_db() as conn:
        result = conn.execute(
            "SELECT Balance, status FROM RFIDTable WHERE RFID = ?", (rfid,)
        ).fetchone()
        if result:
            return {"rfid": rfid, "balance": result["Balance"], "status": result["status"] or "active"}
        raise HTTPException(status_code=404, detail="RFID not found")


@app.get("/transactions/{rfid}", response_model=List[TransactionResponse])
def get_transactions(rfid: str, limit: int = Query(50, ge=1, le=500), auth=Depends(require_customer_or_admin)):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT rfid, esp_id, amount, merchant_name, transaction_type, timestamp, flagged
               FROM Transactions WHERE rfid = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (rfid, limit),
        ).fetchall()
        if rows:
            return [
                {
                    "rfid": r["rfid"],
                    "esp_id": r["esp_id"],
                    "amount": r["amount"],
                    "merchant_name": r["merchant_name"],
                    "transaction_type": r["transaction_type"],
                    "timestamp": r["timestamp"],
                    "flagged": bool(r["flagged"]),
                }
                for r in rows
            ]
        raise HTTPException(status_code=404, detail="No transactions found")


@app.get("/rfid-list")
def get_rfid_list(auth=Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT RFID, Balance, status, daily_limit, merchant_name FROM RFIDTable"
        ).fetchall()
        return [
            {
                "rfid": r["RFID"],
                "balance": r["Balance"],
                "status": r["status"] or "active",
                "daily_limit": r["daily_limit"],
                "merchant_name": r["merchant_name"],
            }
            for r in rows
        ]


# --- Payments (ESP endpoints, protected by API key) ---

@app.post("/deduct")
def deduct_balance(request: DeductRequest, _=Depends(require_esp_key)):
    """Process a payment. Called by ESP8266 on card tap."""
    with get_db() as conn:
        # Idempotency check — reject duplicate request IDs
        if request.idempotency_key:
            existing = conn.execute(
                "SELECT id FROM Transactions WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing:
                return {"status": "duplicate", "message": "Transaction already processed"}

        row = conn.execute(
            "SELECT Balance, status FROM RFIDTable WHERE RFID = ?", (request.rfid,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="RFID not found")
        if (row["status"] or "active") == "blocked":
            raise HTTPException(status_code=403, detail="Card is blocked")
        if row["Balance"] < request.amount:
            raise HTTPException(status_code=400, detail="Insufficient balance")

        # Daily limit check
        if _check_daily_limit(conn, request.rfid, request.amount):
            raise HTTPException(status_code=400, detail="Daily spending limit exceeded")

        fraud = _check_fraud(conn, request.rfid, request.amount)
        flagged = fraud["flagged"]

        new_balance = row["Balance"] - request.amount
        conn.execute(
            "UPDATE RFIDTable SET Balance = ? WHERE RFID = ?",
            (new_balance, request.rfid),
        )
        conn.execute(
            """INSERT INTO Transactions
               (rfid, esp_id, amount, merchant_name, transaction_type, timestamp, flagged, idempotency_key)
               VALUES (?, ?, ?, ?, 'debit', ?, ?, ?)""",
            (
                request.rfid,
                request.espid,
                request.amount,
                request.merchant_name,
                datetime.now(timezone.utc).isoformat(),
                int(flagged),
                request.idempotency_key,
            ),
        )
        _log_audit(
            conn,
            "DEDUCT_FLAGGED" if flagged else "DEDUCT",
            request.rfid,
            f"₹{request.amount} at {request.merchant_name} via {request.espid}. Fraud: {fraud['reason'] or 'None'}",
        )
        conn.commit()

        return {
            "status": "success",
            "rfid": request.rfid,
            "amount_deducted": request.amount,
            "new_balance": new_balance,
            "flagged": flagged,
            "fraud_reason": fraud["reason"],
        }


@app.post("/topup")
def top_up_balance(request: TopUpRequest, auth=Depends(require_admin)):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT Balance FROM RFIDTable WHERE RFID = ?", (request.rfid,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="RFID not found")

        new_balance = existing["Balance"] + request.amount
        conn.execute(
            "UPDATE RFIDTable SET Balance = ? WHERE RFID = ?",
            (new_balance, request.rfid),
        )
        conn.execute(
            """INSERT INTO Transactions
               (rfid, esp_id, amount, merchant_name, transaction_type, timestamp, flagged)
               VALUES (?, 'TOPUP', ?, 'Top-Up', 'topup', ?, 0)""",
            (request.rfid, request.amount, datetime.now(timezone.utc).isoformat()),
        )
        _log_audit(conn, "TOPUP", request.rfid, f"₹{request.amount} topped up")
        conn.commit()

        return {"status": "success", "rfid": request.rfid, "new_balance": new_balance}


# --- Card management (admin only) ---

@app.put("/update-rfid")
def update_rfid(request: UpdateRFIDRequest, auth=Depends(require_admin)):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM RFIDTable WHERE RFID = ?", (request.rfid,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="RFID not found")

        conn.execute(
            'UPDATE RFIDTable SET ESPID = ?, "Transaction Amount" = ?, merchant_name = ? WHERE RFID = ?',
            (request.espid, request.transaction_amount, request.merchant_name, request.rfid),
        )
        _log_audit(conn, "UPDATE_RFID", request.rfid, f"Linked to ESP {request.espid}")
        conn.commit()
        return {"status": "success", "message": "RFID updated successfully"}


@app.post("/block-card")
def block_card(request: BlockCardRequest, auth=Depends(require_admin)):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT status FROM RFIDTable WHERE RFID = ?", (request.rfid,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="RFID not found")
        conn.execute(
            "UPDATE RFIDTable SET status = 'blocked' WHERE RFID = ?", (request.rfid,)
        )
        _log_audit(conn, "BLOCK_CARD", request.rfid, f"Card blocked: {request.reason}")
        conn.commit()
        return {"status": "success", "message": f"Card {request.rfid} blocked"}


@app.post("/unblock-card")
def unblock_card(request: BlockCardRequest, auth=Depends(require_admin)):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT status FROM RFIDTable WHERE RFID = ?", (request.rfid,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="RFID not found")
        conn.execute(
            "UPDATE RFIDTable SET status = 'active' WHERE RFID = ?", (request.rfid,)
        )
        _log_audit(conn, "UNBLOCK_CARD", request.rfid, f"Card unblocked: {request.reason}")
        conn.commit()
        return {"status": "success", "message": f"Card {request.rfid} unblocked"}


@app.put("/spending-limit")
def set_spending_limit(request: SpendingLimitRequest, auth=Depends(require_admin)):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT RFID FROM RFIDTable WHERE RFID = ?", (request.rfid,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="RFID not found")
        conn.execute(
            "UPDATE RFIDTable SET daily_limit = ? WHERE RFID = ?",
            (request.daily_limit if request.daily_limit > 0 else None, request.rfid),
        )
        _log_audit(conn, "SET_LIMIT", request.rfid, f"Daily limit set to ₹{request.daily_limit}")
        conn.commit()
        return {"status": "success", "rfid": request.rfid, "daily_limit": request.daily_limit}


# --- Export ---

@app.get("/export/transactions/{rfid}")
def export_transactions_csv(
    rfid: str,
    limit: int = Query(500, ge=1, le=5000),
    auth=Depends(require_admin),
):
    """Download transaction history for a card as CSV."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT rfid, esp_id, merchant_name, transaction_type, amount, timestamp, flagged
               FROM Transactions WHERE rfid = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (rfid, limit),
        ).fetchall()

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["rfid", "esp_id", "merchant_name", "transaction_type", "amount", "timestamp", "flagged"],
    )
    writer.writeheader()
    for r in rows:
        writer.writerow(dict(r))

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=transactions_{rfid}.csv"},
    )


@app.get("/export/transactions")
def export_all_transactions_csv(
    limit: int = Query(1000, ge=1, le=10000),
    auth=Depends(require_admin),
):
    """Download all transactions as CSV (admin only)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT rfid, esp_id, merchant_name, transaction_type, amount, timestamp, flagged
               FROM Transactions ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        ).fetchall()

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["rfid", "esp_id", "merchant_name", "transaction_type", "amount", "timestamp", "flagged"],
    )
    writer.writeheader()
    for r in rows:
        writer.writerow(dict(r))

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=all_transactions.csv"},
    )


# --- Analytics & audit ---

@app.get("/analytics/summary")
def analytics_summary(auth=Depends(require_admin)):
    with get_db() as conn:
        total_balance = conn.execute(
            "SELECT COALESCE(SUM(Balance), 0) as total FROM RFIDTable"
        ).fetchone()["total"]

        txn_stats = conn.execute(
            """SELECT COUNT(*) as count,
                      COALESCE(SUM(amount), 0) as volume,
                      COALESCE(AVG(amount), 0) as avg_amount,
                      SUM(flagged) as flagged_count
               FROM Transactions WHERE transaction_type = 'debit'"""
        ).fetchone()

        top_spenders = conn.execute(
            """SELECT rfid, SUM(amount) as total_spent
               FROM Transactions WHERE transaction_type = 'debit'
               GROUP BY rfid ORDER BY total_spent DESC LIMIT 5"""
        ).fetchall()

        daily_volume = conn.execute(
            """SELECT substr(timestamp, 1, 10) as day, SUM(amount) as volume
               FROM Transactions WHERE transaction_type = 'debit'
               GROUP BY day ORDER BY day DESC LIMIT 14"""
        ).fetchall()

        blocked_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM RFIDTable WHERE status = 'blocked'"
        ).fetchone()["cnt"]

        return {
            "total_balance_in_circulation": total_balance,
            "transaction_count": txn_stats["count"],
            "transaction_volume": txn_stats["volume"],
            "avg_transaction_amount": round(txn_stats["avg_amount"], 2),
            "flagged_transactions": txn_stats["flagged_count"],
            "blocked_cards": blocked_count,
            "top_spenders": [{"rfid": r["rfid"], "total_spent": r["total_spent"]} for r in top_spenders],
            "daily_volume": [{"day": r["day"], "volume": r["volume"]} for r in daily_volume],
        }


@app.get("/audit-log")
def get_audit_log(limit: int = Query(100, ge=1, le=1000), auth=Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT action, rfid, detail, timestamp FROM AuditLog ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/flagged-transactions")
def get_flagged_transactions(limit: int = Query(100, ge=1, le=500), auth=Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, rfid, esp_id, merchant_name, amount, timestamp
               FROM Transactions WHERE flagged = 1
               ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/transaction-amount/{espid}/{rfid}")
def get_transaction_amount(espid: str, rfid: str, _=Depends(require_esp_key)):
    with get_db() as conn:
        result = conn.execute(
            "SELECT TransactionAmt FROM ESPNumber WHERE ESPID = ? AND RFID = ?",
            (espid, rfid),
        ).fetchone()
        if result:
            return {"espid": espid, "rfid": rfid, "transaction_amount": result["TransactionAmt"]}
        raise HTTPException(status_code=404, detail="No transaction found")
