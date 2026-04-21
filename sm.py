"""
sm.py — Database schema setup and seeding for LaxmiPay.

New columns vs v2:
  RFIDTable:   status (active/blocked), daily_limit, merchant_name
  Transactions: merchant_name, transaction_type (debit/credit/topup), idempotency_key

Run this script whenever you set up a fresh environment.
For an existing database it safely adds any missing columns via ALTER TABLE.
"""

import sqlite3
import random
import hashlib
from datetime import datetime, timezone, timedelta
from passlib.context import CryptContext

DB_PATH = "./Database.db"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _hash(password: str) -> str:
    return pwd_context.hash(password)


def create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ESPNumber (
            ESPID          INTEGER PRIMARY KEY AUTOINCREMENT,
            RFID           INTEGER NOT NULL,
            TransactionAmt INTEGER
        );

        CREATE TABLE IF NOT EXISTS RFIDTable (
            RFID                  INTEGER PRIMARY KEY,
            Balance               INTEGER NOT NULL DEFAULT 0,
            ESPID                 INTEGER,
            "Transaction Amount"  INTEGER,
            status                TEXT NOT NULL DEFAULT 'active',
            daily_limit           INTEGER,
            merchant_name         TEXT
        );

        CREATE TABLE IF NOT EXISTS UserAuth (
            RFID     INTEGER PRIMARY KEY,
            Password TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS Transactions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            rfid             TEXT    NOT NULL,
            esp_id           TEXT    NOT NULL,
            amount           INTEGER NOT NULL,
            merchant_name    TEXT,
            transaction_type TEXT    NOT NULL DEFAULT 'debit',
            timestamp        TEXT    NOT NULL,
            flagged          INTEGER NOT NULL DEFAULT 0,
            idempotency_key  TEXT    UNIQUE
        );

        CREATE TABLE IF NOT EXISTS AuditLog (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            action    TEXT NOT NULL,
            rfid      TEXT,
            detail    TEXT,
            timestamp TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_txn_rfid       ON Transactions(rfid);
        CREATE INDEX IF NOT EXISTS idx_txn_timestamp  ON Transactions(timestamp);
        CREATE INDEX IF NOT EXISTS idx_txn_type       ON Transactions(transaction_type);
        CREATE INDEX IF NOT EXISTS idx_txn_idem       ON Transactions(idempotency_key);
        CREATE INDEX IF NOT EXISTS idx_audit_rfid     ON AuditLog(rfid);
    """)
    conn.commit()
    print("✅ Tables created.")


def migrate_existing(conn):
    """Safely add new columns to an existing database without data loss."""
    migrations = [
        ("RFIDTable",    "status",           "TEXT NOT NULL DEFAULT 'active'"),
        ("RFIDTable",    "daily_limit",       "INTEGER"),
        ("RFIDTable",    "merchant_name",     "TEXT"),
        ("Transactions", "merchant_name",     "TEXT"),
        ("Transactions", "transaction_type",  "TEXT NOT NULL DEFAULT 'debit'"),
        ("Transactions", "idempotency_key",   "TEXT"),
    ]
    for table, col, col_def in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
            conn.commit()
            print(f"  ➕ Migrated: {table}.{col}")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                pass  # already exists, skip
            else:
                raise

    # Add unique index on idempotency_key if not already present
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_txn_idem ON Transactions(idempotency_key)")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    print("✅ Migration complete.")


def insert_dummy_data(conn):
    rfid_numbers = random.sample(range(1000, 9999), 20)
    esp_ids      = [f"ESP{i:02d}" for i in range(1, 6)]
    merchants    = ["Main Canteen", "North Block Cafe", "Library Kiosk", "Sports Canteen", "Vending Machine"]

    for rfid in rfid_numbers:
        balance   = random.randint(200, 8000)
        txn_amt   = random.randint(10, 500)
        password  = _hash(f"pass{rfid}")
        merchant  = random.choice(merchants)
        d_limit   = random.choice([None, None, 500, 1000, 2000])  # 40% have a limit
        conn.execute(
            'INSERT OR IGNORE INTO RFIDTable (RFID, Balance, ESPID, "Transaction Amount", status, daily_limit, merchant_name)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?)',
            (rfid, balance, None, txn_amt, "active", d_limit, merchant),
        )
        conn.execute(
            "INSERT OR IGNORE INTO UserAuth (RFID, Password) VALUES (?, ?)",
            (rfid, password),
        )

    for rfid in rfid_numbers:
        for _ in range(random.randint(1, 3)):
            conn.execute(
                "INSERT INTO ESPNumber (RFID, TransactionAmt) VALUES (?, ?)",
                (rfid, random.randint(10, 500)),
            )

    now = datetime.now(timezone.utc)
    for _ in range(250):
        rfid    = str(random.choice(rfid_numbers))
        esp     = random.choice(esp_ids)
        merchant = random.choice(merchants)
        amount  = random.randint(10, 600)
        days_ago = random.uniform(0, 14)
        ts      = (now - timedelta(days=days_ago)).isoformat()
        flagged = 0
        txn_type = "debit"

        if random.random() < 0.05:
            amount  = random.randint(2000, 5000)
            flagged = 1
        elif random.random() < 0.03:
            flagged = 1

        conn.execute(
            """INSERT INTO Transactions (rfid, esp_id, amount, merchant_name, transaction_type, timestamp, flagged)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rfid, esp, amount, merchant, txn_type, ts, flagged),
        )

    # Top-up events
    for rfid in random.sample(rfid_numbers, 8):
        ts = (now - timedelta(days=random.uniform(0, 7))).isoformat()
        conn.execute(
            """INSERT INTO Transactions (rfid, esp_id, amount, merchant_name, transaction_type, timestamp, flagged)
               VALUES (?, 'TOPUP', ?, 'Top-Up', 'topup', ?, 0)""",
            (str(rfid), random.randint(500, 2000), ts),
        )

    # Seed audit log
    for rfid in random.sample(rfid_numbers, 5):
        conn.execute(
            "INSERT INTO AuditLog (action, rfid, detail, timestamp) VALUES (?, ?, ?, ?)",
            ("SYSTEM_INIT", str(rfid), "Card registered during setup", now.isoformat()),
        )

    conn.commit()
    print("✅ Dummy data inserted.")
    print("\nSample credentials (RFID → password):")
    for rfid in rfid_numbers[:5]:
        print(f"  RFID {rfid}  →  pass{rfid}")


def print_admin_hash():
    """Helper: print bcrypt hash for your admin password to put in .env"""
    import getpass
    try:
        pw = getpass.getpass("Enter admin password to hash (for .env): ")
        print(f"\nADMIN_PASSWORD_HASH={pwd_context.hash(pw)}\n")
    except Exception:
        pass


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    create_tables(conn)
    migrate_existing(conn)
    insert_dummy_data(conn)
    conn.close()
    print("\n✅ Database ready at", DB_PATH)
    print_admin_hash()
