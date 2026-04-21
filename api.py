import os
import csv
import io
from datetime import datetime, timezone, timedelta
import sqlite3
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator
from passlib.context import CryptContext
from jose import JWTError, jwt

DB_PATH = "./Database.db"
SECRET_KEY = "laxmipay-local-secret-key-2024"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 480

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

FRAUD_VELOCITY_LIMIT = 5
FRAUD_AMOUNT_THRESHOLD = 2000

app = FastAPI(title="LaxmiPay API", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def _hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _verify_password(plain: str, hashed: str) -> bool:
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


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _log_audit(conn, action: str, rfid: str, detail: str):
    conn.execute(
        "INSERT INTO AuditLog (action, rfid, detail, timestamp) VALUES (?, ?, ?, ?)",
        (action, rfid, detail, datetime.now(timezone.utc).isoformat()),
    )


class AdminAuthRequest(BaseModel):
    username: str
    password: str


class CustomerAuthRequest(BaseModel):
    rfid: str
    password: str


class DeductRequest(BaseModel):
    rfid: str
    amount: int
    merchant_name: Optional[str] = "Unknown"

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v


class TopUpRequest(BaseModel):
    rfid: str
    amount: int

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
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


class NewCardRequest(BaseModel):
    rfid: str
    initial_balance: int
    password: str
    merchant_name: Optional[str] = None
    daily_limit: Optional[int] = None

    @field_validator("initial_balance")
    @classmethod
    def non_negative(cls, v):
        if v < 0:
            raise ValueError("Balance cannot be negative")
        return v


def _check_fraud(conn, rfid: str, amount: int) -> dict:
    sixty_seconds_ago = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM Transactions WHERE rfid = ? AND timestamp >= ? AND transaction_type = 'debit'",
        (rfid, sixty_seconds_ago),
    ).fetchone()
    velocity = row["cnt"] if row else 0
    if velocity >= FRAUD_VELOCITY_LIMIT:
        return {"flagged": True, "reason": f"Velocity exceeded: {velocity} txns/60s"}
    if amount >= FRAUD_AMOUNT_THRESHOLD:
        return {"flagged": True, "reason": f"High-value transaction: ₹{amount}"}
    return {"flagged": False, "reason": ""}


def _check_daily_limit(conn, rfid: str, amount: int) -> bool:
    card = conn.execute("SELECT daily_limit FROM RFIDTable WHERE RFID = ?", (rfid,)).fetchone()
    if not card or not card["daily_limit"]:
        return False
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    spent_today = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM Transactions WHERE rfid = ? AND transaction_type = 'debit' AND timestamp >= ?",
        (rfid, today_start),
    ).fetchone()["total"]
    return (spent_today + amount) > card["daily_limit"]


@app.get("/")
def home():
    return {"message": "LaxmiPay API v4.0 running.", "docs": "/docs"}


@app.post("/authenticate/admin")
def authenticate_admin(request: AdminAuthRequest):
    if request.username != ADMIN_USERNAME or request.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = _create_token(subject=request.username, role="admin")
    return {"status": "success", "token": token}


@app.post("/authenticate/customer")
def authenticate_customer(request: CustomerAuthRequest):
    with get_db() as conn:
        user = conn.execute("SELECT Password FROM UserAuth WHERE RFID = ?", (request.rfid,)).fetchone()
        if user and _verify_password(request.password, user["Password"]):
            token = _create_token(subject=request.rfid, role="customer")
            _log_audit(conn, "CUSTOMER_LOGIN", request.rfid, "Login successful")
            conn.commit()
            return {"status": "success", "token": token}
        raise HTTPException(status_code=401, detail="Invalid RFID or password")


@app.get("/rfid/{rfid}")
def get_rfid_details(rfid: str, auth=Depends(require_customer_or_admin)):
    with get_db() as conn:
        result = conn.execute(
            "SELECT Balance, status, daily_limit, merchant_name FROM RFIDTable WHERE RFID = ?", (rfid,)
        ).fetchone()
        if result:
            return {
                "rfid": rfid,
                "balance": result["Balance"],
                "status": result["status"] or "active",
                "daily_limit": result["daily_limit"],
                "merchant_name": result["merchant_name"],
            }
        raise HTTPException(status_code=404, detail="RFID not found")


@app.get("/rfid-list")
def get_rfid_list(auth=Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT RFID, Balance, status, daily_limit, merchant_name FROM RFIDTable ORDER BY RFID"
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


@app.get("/transactions/{rfid}")
def get_transactions(rfid: str, limit: int = Query(50, ge=1, le=500), auth=Depends(require_customer_or_admin)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT rfid, amount, merchant_name, transaction_type, timestamp, flagged FROM Transactions WHERE rfid = ? ORDER BY timestamp DESC LIMIT ?",
            (rfid, limit),
        ).fetchall()
        return [
            {
                "rfid": r["rfid"],
                "amount": r["amount"],
                "merchant_name": r["merchant_name"],
                "transaction_type": r["transaction_type"],
                "timestamp": r["timestamp"],
                "flagged": bool(r["flagged"]),
            }
            for r in rows
        ]


@app.post("/pay")
def process_payment(request: DeductRequest, auth=Depends(require_customer_or_admin)):
    with get_db() as conn:
        row = conn.execute("SELECT Balance, status FROM RFIDTable WHERE RFID = ?", (request.rfid,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="RFID not found")
        if (row["status"] or "active") == "blocked":
            raise HTTPException(status_code=403, detail="Card is blocked")
        if row["Balance"] < request.amount:
            raise HTTPException(status_code=400, detail="Insufficient balance")
        if _check_daily_limit(conn, request.rfid, request.amount):
            raise HTTPException(status_code=400, detail="Daily spending limit exceeded")

        fraud = _check_fraud(conn, request.rfid, request.amount)
        flagged = fraud["flagged"]
        new_balance = row["Balance"] - request.amount

        conn.execute("UPDATE RFIDTable SET Balance = ? WHERE RFID = ?", (new_balance, request.rfid))
        conn.execute(
            "INSERT INTO Transactions (rfid, amount, merchant_name, transaction_type, timestamp, flagged) VALUES (?, ?, ?, 'debit', ?, ?)",
            (request.rfid, request.amount, request.merchant_name, datetime.now(timezone.utc).isoformat(), int(flagged)),
        )
        _log_audit(conn, "DEDUCT_FLAGGED" if flagged else "DEDUCT", request.rfid, f"₹{request.amount} at {request.merchant_name}")
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
        existing = conn.execute("SELECT Balance FROM RFIDTable WHERE RFID = ?", (request.rfid,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="RFID not found")
        new_balance = existing["Balance"] + request.amount
        conn.execute("UPDATE RFIDTable SET Balance = ? WHERE RFID = ?", (new_balance, request.rfid))
        conn.execute(
            "INSERT INTO Transactions (rfid, amount, merchant_name, transaction_type, timestamp, flagged) VALUES (?, ?, 'Top-Up', 'topup', ?, 0)",
            (request.rfid, request.amount, datetime.now(timezone.utc).isoformat()),
        )
        _log_audit(conn, "TOPUP", request.rfid, f"₹{request.amount} topped up")
        conn.commit()
        return {"status": "success", "rfid": request.rfid, "new_balance": new_balance}


@app.post("/cards")
def add_card(request: NewCardRequest, auth=Depends(require_admin)):
    with get_db() as conn:
        existing = conn.execute("SELECT RFID FROM RFIDTable WHERE RFID = ?", (request.rfid,)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="RFID already registered")
        conn.execute(
            "INSERT INTO RFIDTable (RFID, Balance, status, daily_limit, merchant_name) VALUES (?, ?, 'active', ?, ?)",
            (request.rfid, request.initial_balance, request.daily_limit, request.merchant_name),
        )
        conn.execute(
            "INSERT INTO UserAuth (RFID, Password) VALUES (?, ?)",
            (request.rfid, _hash_password(request.password)),
        )
        _log_audit(conn, "CARD_ADDED", request.rfid, f"New card registered, balance ₹{request.initial_balance}")
        conn.commit()
        return {"status": "success", "rfid": request.rfid}


@app.post("/block-card")
def block_card(request: BlockCardRequest, auth=Depends(require_admin)):
    with get_db() as conn:
        existing = conn.execute("SELECT status FROM RFIDTable WHERE RFID = ?", (request.rfid,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="RFID not found")
        conn.execute("UPDATE RFIDTable SET status = 'blocked' WHERE RFID = ?", (request.rfid,))
        _log_audit(conn, "BLOCK_CARD", request.rfid, f"Blocked: {request.reason}")
        conn.commit()
        return {"status": "success", "message": f"Card {request.rfid} blocked"}


@app.post("/unblock-card")
def unblock_card(request: BlockCardRequest, auth=Depends(require_admin)):
    with get_db() as conn:
        existing = conn.execute("SELECT status FROM RFIDTable WHERE RFID = ?", (request.rfid,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="RFID not found")
        conn.execute("UPDATE RFIDTable SET status = 'active' WHERE RFID = ?", (request.rfid,))
        _log_audit(conn, "UNBLOCK_CARD", request.rfid, f"Unblocked: {request.reason}")
        conn.commit()
        return {"status": "success", "message": f"Card {request.rfid} unblocked"}


@app.put("/spending-limit")
def set_spending_limit(request: SpendingLimitRequest, auth=Depends(require_admin)):
    with get_db() as conn:
        existing = conn.execute("SELECT RFID FROM RFIDTable WHERE RFID = ?", (request.rfid,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="RFID not found")
        conn.execute(
            "UPDATE RFIDTable SET daily_limit = ? WHERE RFID = ?",
            (request.daily_limit if request.daily_limit > 0 else None, request.rfid),
        )
        _log_audit(conn, "SET_LIMIT", request.rfid, f"Daily limit set to ₹{request.daily_limit}")
        conn.commit()
        return {"status": "success", "rfid": request.rfid, "daily_limit": request.daily_limit}


@app.get("/analytics/summary")
def analytics_summary(auth=Depends(require_admin)):
    with get_db() as conn:
        total_balance = conn.execute("SELECT COALESCE(SUM(Balance), 0) as total FROM RFIDTable").fetchone()["total"]
        txn_stats = conn.execute(
            "SELECT COUNT(*) as count, COALESCE(SUM(amount), 0) as volume, COALESCE(AVG(amount), 0) as avg_amount, SUM(flagged) as flagged_count FROM Transactions WHERE transaction_type = 'debit'"
        ).fetchone()
        top_spenders = conn.execute(
            "SELECT rfid, SUM(amount) as total_spent FROM Transactions WHERE transaction_type = 'debit' GROUP BY rfid ORDER BY total_spent DESC LIMIT 5"
        ).fetchall()
        daily_volume = conn.execute(
            "SELECT substr(timestamp, 1, 10) as day, SUM(amount) as volume FROM Transactions WHERE transaction_type = 'debit' GROUP BY day ORDER BY day DESC LIMIT 14"
        ).fetchall()
        blocked_count = conn.execute("SELECT COUNT(*) as cnt FROM RFIDTable WHERE status = 'blocked'").fetchone()["cnt"]
        total_cards = conn.execute("SELECT COUNT(*) as cnt FROM RFIDTable").fetchone()["cnt"]

        return {
            "total_balance_in_circulation": total_balance,
            "transaction_count": txn_stats["count"],
            "transaction_volume": txn_stats["volume"],
            "avg_transaction_amount": round(txn_stats["avg_amount"], 2),
            "flagged_transactions": txn_stats["flagged_count"],
            "blocked_cards": blocked_count,
            "total_cards": total_cards,
            "top_spenders": [{"rfid": r["rfid"], "total_spent": r["total_spent"]} for r in top_spenders],
            "daily_volume": [{"day": r["day"], "volume": r["volume"]} for r in daily_volume],
        }


@app.get("/flagged-transactions")
def get_flagged_transactions(limit: int = Query(100, ge=1, le=500), auth=Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, rfid, merchant_name, amount, timestamp FROM Transactions WHERE flagged = 1 ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/audit-log")
def get_audit_log(limit: int = Query(100, ge=1, le=1000), auth=Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT action, rfid, detail, timestamp FROM AuditLog ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/export/transactions")
def export_all_transactions_csv(limit: int = Query(1000, ge=1, le=10000), auth=Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT rfid, merchant_name, transaction_type, amount, timestamp, flagged FROM Transactions ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["rfid", "merchant_name", "transaction_type", "amount", "timestamp", "flagged"])
    writer.writeheader()
    for r in rows:
        writer.writerow(dict(r))
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=all_transactions.csv"})


@app.get("/export/transactions/{rfid}")
def export_card_transactions_csv(rfid: str, limit: int = Query(500, ge=1, le=5000), auth=Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT rfid, merchant_name, transaction_type, amount, timestamp, flagged FROM Transactions WHERE rfid = ? ORDER BY timestamp DESC LIMIT ?",
            (rfid, limit),
        ).fetchall()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["rfid", "merchant_name", "transaction_type", "amount", "timestamp", "flagged"])
    writer.writeheader()
    for r in rows:
        writer.writerow(dict(r))
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=transactions_{rfid}.csv"})