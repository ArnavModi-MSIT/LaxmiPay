from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
from pydantic import BaseModel, field_validator
from typing import List, Optional
from datetime import datetime, timezone
import hashlib
import hmac
import os
from dotenv import load_dotenv

load_dotenv()  # loads .env into os.environ

app = FastAPI(
    title="RFID Payment API",
    description="Secure RFID-based contactless payment system with fraud detection",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.getenv("DB_PATH", "./Database.db")
FRAUD_VELOCITY_LIMIT = int(os.getenv("FRAUD_VELOCITY_LIMIT", "5"))
FRAUD_AMOUNT_THRESHOLD = int(os.getenv("FRAUD_AMOUNT_THRESHOLD", "2000"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

# ---------- DB Helper ----------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _log_audit(conn, action: str, rfid: str, detail: str):
    conn.execute(
        "INSERT INTO AuditLog (action, rfid, detail, timestamp) VALUES (?, ?, ?, ?)",
        (action, rfid, detail, datetime.now(timezone.utc).isoformat()),
    )


# ---------- Models ----------

class UserAuthRequest(BaseModel):
    rfid: str
    password: str

class AdminAuthRequest(BaseModel):
    username: str
    password: str

class TransactionResponse(BaseModel):
    rfid: str
    esp_id: str
    amount: int
    timestamp: Optional[str] = None
    flagged: Optional[bool] = False

class UpdateRFIDRequest(BaseModel):
    rfid: str
    espid: str
    transaction_amount: int

    @field_validator("transaction_amount")
    @classmethod
    def positive_amount(cls, v):
        if v < 0:
            raise ValueError("Transaction amount cannot be negative")
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

class DeductRequest(BaseModel):
    rfid: str
    espid: str
    amount: int

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v):
        if v <= 0:
            raise ValueError("Deduction amount must be positive")
        return v


# ---------- Fraud Detection ----------

def _check_fraud(conn, rfid: str, amount: int) -> dict:
    """
    Two-factor fraud heuristic:
      1. Velocity check  — >5 transactions in the last 60 seconds
      2. Amount check    — single transaction exceeding threshold
    Returns {"flagged": bool, "reason": str}
    """
    one_min_ago = datetime.now(timezone.utc).replace(microsecond=0).isoformat()[:16]
    rows = conn.execute(
        "SELECT COUNT(*) as cnt FROM Transactions WHERE rfid = ? AND timestamp >= ?",
        (rfid, one_min_ago),
    ).fetchone()
    velocity = rows["cnt"] if rows else 0

    if velocity >= FRAUD_VELOCITY_LIMIT:
        return {"flagged": True, "reason": f"Velocity exceeded: {velocity} txns/min"}
    if amount >= FRAUD_AMOUNT_THRESHOLD:
        return {"flagged": True, "reason": f"High-value transaction: ₹{amount}"}
    return {"flagged": False, "reason": ""}


# ---------- Endpoints ----------

@app.get("/")
def home():
    return {"message": "RFID Payment API v2.0 is running.", "docs": "/docs"}


@app.post("/authenticate/customer")
def authenticate_customer(request: UserAuthRequest):
    with get_db() as conn:
        try:
            user = conn.execute(
                "SELECT Password FROM UserAuth WHERE RFID = ?", (request.rfid,)
            ).fetchone()
            if user:
                stored = user["Password"]
                # Support both plain (legacy) and hashed passwords
                if stored == request.password or stored == _hash_password(request.password):
                    _log_audit(conn, "CUSTOMER_LOGIN", request.rfid, "Login successful")
                    conn.commit()
                    return {"status": "success", "message": "Login successful"}
            raise HTTPException(status_code=401, detail="Invalid RFID or Password")
        except sqlite3.Error as e:
            raise HTTPException(status_code=500, detail=f"Database error: {e}")


@app.post("/authenticate/admin")
def authenticate_admin(request: AdminAuthRequest):
    if request.username == ADMIN_USERNAME and request.password == ADMIN_PASSWORD:
        return {"status": "success", "message": "Admin login successful"}
    raise HTTPException(status_code=401, detail="Invalid admin credentials")


@app.get("/rfid/{rfid}")
def get_rfid_details(rfid: str):
    with get_db() as conn:
        try:
            result = conn.execute(
                "SELECT Balance, ESPID FROM RFIDTable WHERE RFID = ?", (rfid,)
            ).fetchone()
            if result:
                return {"rfid": rfid, "balance": result["Balance"], "esp_id": result["ESPID"]}
            raise HTTPException(status_code=404, detail="RFID not found")
        except sqlite3.Error as e:
            raise HTTPException(status_code=500, detail=f"Database error: {e}")


@app.get("/balance/{rfid}")
def get_balance(rfid: str):
    with get_db() as conn:
        try:
            result = conn.execute(
                "SELECT Balance FROM RFIDTable WHERE RFID = ?", (rfid,)
            ).fetchone()
            if result:
                return {"rfid": rfid, "balance": result["Balance"]}
            raise HTTPException(status_code=404, detail="RFID not found")
        except sqlite3.Error as e:
            raise HTTPException(status_code=500, detail=f"Database error: {e}")


@app.get("/transactions/{rfid}", response_model=List[TransactionResponse])
def get_transactions(rfid: str, limit: int = Query(50, ge=1, le=500)):
    with get_db() as conn:
        try:
            rows = conn.execute(
                """SELECT rfid, esp_id, amount, timestamp, flagged
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
                        "timestamp": r["timestamp"],
                        "flagged": bool(r["flagged"]),
                    }
                    for r in rows
                ]
            raise HTTPException(status_code=404, detail="No transactions found")
        except sqlite3.Error as e:
            raise HTTPException(status_code=500, detail=f"Database error: {e}")


@app.get("/rfid-list")
def get_rfid_list():
    with get_db() as conn:
        try:
            rows = conn.execute("SELECT DISTINCT RFID FROM RFIDTable").fetchall()
            return {"rfids": [r["RFID"] for r in rows]}
        except sqlite3.Error as e:
            raise HTTPException(status_code=500, detail=f"Database error: {e}")


@app.post("/deduct")
def deduct_balance(request: DeductRequest):
    """
    Process a payment deduction from an RFID card.
    Includes fraud detection before processing.
    """
    with get_db() as conn:
        try:
            row = conn.execute(
                "SELECT Balance FROM RFIDTable WHERE RFID = ?", (request.rfid,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="RFID not found")

            fraud = _check_fraud(conn, request.rfid, request.amount)
            flagged = fraud["flagged"]

            if row["Balance"] < request.amount:
                raise HTTPException(status_code=400, detail="Insufficient balance")

            new_balance = row["Balance"] - request.amount
            conn.execute(
                "UPDATE RFIDTable SET Balance = ? WHERE RFID = ?",
                (new_balance, request.rfid),
            )
            conn.execute(
                """INSERT INTO Transactions (rfid, esp_id, amount, timestamp, flagged)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    request.rfid,
                    request.espid,
                    request.amount,
                    datetime.now(timezone.utc).isoformat(),
                    int(flagged),
                ),
            )
            _log_audit(
                conn,
                "DEDUCT" if not flagged else "DEDUCT_FLAGGED",
                request.rfid,
                f"₹{request.amount} deducted via ESP {request.espid}. Fraud: {fraud['reason'] or 'None'}",
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
        except sqlite3.Error as e:
            raise HTTPException(status_code=500, detail=f"Database error: {e}")


@app.post("/topup")
def top_up_balance(request: TopUpRequest):
    with get_db() as conn:
        try:
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
                """INSERT INTO Transactions (rfid, esp_id, amount, timestamp, flagged)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    request.rfid,
                    "TOPUP",
                    request.amount,
                    datetime.now(timezone.utc).isoformat(),
                    0,
                ),
            )
            _log_audit(conn, "TOPUP", request.rfid, f"₹{request.amount} topped up")
            conn.commit()
            return {"status": "success", "rfid": request.rfid, "new_balance": new_balance}
        except sqlite3.Error as e:
            raise HTTPException(status_code=500, detail=f"Database error: {e}")


@app.put("/update-rfid")
def update_rfid(request: UpdateRFIDRequest):
    with get_db() as conn:
        try:
            existing = conn.execute(
                "SELECT * FROM RFIDTable WHERE RFID = ?", (request.rfid,)
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="RFID not found")
            conn.execute(
                'UPDATE RFIDTable SET ESPID = ?, "Transaction Amount" = ? WHERE RFID = ?',
                (request.espid, request.transaction_amount, request.rfid),
            )
            _log_audit(conn, "UPDATE_RFID", request.rfid, f"Linked to ESP {request.espid}")
            conn.commit()
            return {"status": "success", "message": "RFID updated successfully"}
        except sqlite3.Error as e:
            raise HTTPException(status_code=500, detail=f"Database error: {e}")


@app.get("/analytics/summary")
def analytics_summary():
    """
    System-wide analytics: total balance in circulation, transaction volume,
    flagged transaction count, top spending RFIDs.
    """
    with get_db() as conn:
        try:
            total_balance = conn.execute(
                "SELECT COALESCE(SUM(Balance), 0) as total FROM RFIDTable"
            ).fetchone()["total"]

            txn_stats = conn.execute(
                """SELECT COUNT(*) as count,
                          COALESCE(SUM(amount), 0) as volume,
                          COALESCE(AVG(amount), 0) as avg_amount,
                          SUM(flagged) as flagged_count
                   FROM Transactions WHERE esp_id != 'TOPUP'"""
            ).fetchone()

            top_spenders = conn.execute(
                """SELECT rfid, SUM(amount) as total_spent
                   FROM Transactions WHERE esp_id != 'TOPUP'
                   GROUP BY rfid ORDER BY total_spent DESC LIMIT 5"""
            ).fetchall()

            daily_volume = conn.execute(
                """SELECT substr(timestamp, 1, 10) as day, SUM(amount) as volume
                   FROM Transactions WHERE esp_id != 'TOPUP'
                   GROUP BY day ORDER BY day DESC LIMIT 14"""
            ).fetchall()

            return {
                "total_balance_in_circulation": total_balance,
                "transaction_count": txn_stats["count"],
                "transaction_volume": txn_stats["volume"],
                "avg_transaction_amount": round(txn_stats["avg_amount"], 2),
                "flagged_transactions": txn_stats["flagged_count"],
                "top_spenders": [{"rfid": r["rfid"], "total_spent": r["total_spent"]} for r in top_spenders],
                "daily_volume": [{"day": r["day"], "volume": r["volume"]} for r in daily_volume],
            }
        except sqlite3.Error as e:
            raise HTTPException(status_code=500, detail=f"Database error: {e}")


@app.get("/audit-log")
def get_audit_log(limit: int = Query(100, ge=1, le=1000)):
    with get_db() as conn:
        try:
            rows = conn.execute(
                "SELECT action, rfid, detail, timestamp FROM AuditLog ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            raise HTTPException(status_code=500, detail=f"Database error: {e}")


@app.get("/transaction-amount/{espid}/{rfid}")
def get_transaction_amount(espid: str, rfid: str):
    with get_db() as conn:
        try:
            result = conn.execute(
                "SELECT TransactionAmt FROM ESPNumber WHERE ESPID = ? AND RFID = ?",
                (espid, rfid),
            ).fetchone()
            if result:
                return {"espid": espid, "rfid": rfid, "transaction_amount": result["TransactionAmt"]}
            raise HTTPException(status_code=404, detail="No transaction found")
        except sqlite3.Error as e:
            raise HTTPException(status_code=500, detail=f"Database error: {e}")