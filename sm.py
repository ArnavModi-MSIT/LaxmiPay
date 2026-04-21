import sqlite3
import random
from datetime import datetime, timezone, timedelta
from passlib.context import CryptContext

DB_PATH = "./Database.db"
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS RFIDTable (
            RFID        TEXT PRIMARY KEY,
            Balance     INTEGER NOT NULL DEFAULT 0,
            status      TEXT NOT NULL DEFAULT 'active',
            daily_limit INTEGER,
            merchant_name TEXT
        );

        CREATE TABLE IF NOT EXISTS UserAuth (
            RFID     TEXT PRIMARY KEY,
            Password TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS Transactions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            rfid             TEXT    NOT NULL,
            amount           INTEGER NOT NULL,
            merchant_name    TEXT,
            transaction_type TEXT    NOT NULL DEFAULT 'debit',
            timestamp        TEXT    NOT NULL,
            flagged          INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS AuditLog (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            action    TEXT NOT NULL,
            rfid      TEXT,
            detail    TEXT,
            timestamp TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_txn_rfid      ON Transactions(rfid);
        CREATE INDEX IF NOT EXISTS idx_txn_timestamp ON Transactions(timestamp);
        CREATE INDEX IF NOT EXISTS idx_txn_type      ON Transactions(transaction_type);
    """)
    conn.commit()


def insert_dummy_data(conn):
    rfid_numbers = [str(r) for r in random.sample(range(1000, 9999), 20)]
    merchants = ["Main Canteen", "North Block Cafe", "Library Kiosk", "Sports Canteen", "Vending Machine", "East Wing Cafe", "Bookstore"]

    for rfid in rfid_numbers:
        balance = random.randint(200, 8000)
        password = pwd_context.hash(f"pass{rfid}")
        merchant = random.choice(merchants)
        d_limit = random.choice([None, None, 500, 1000, 2000])
        conn.execute(
            "INSERT OR IGNORE INTO RFIDTable (RFID, Balance, status, daily_limit, merchant_name) VALUES (?, ?, 'active', ?, ?)",
            (rfid, balance, d_limit, merchant),
        )
        conn.execute(
            "INSERT OR IGNORE INTO UserAuth (RFID, Password) VALUES (?, ?)",
            (rfid, password),
        )

    now = datetime.now(timezone.utc)
    for _ in range(300):
        rfid = random.choice(rfid_numbers)
        merchant = random.choice(merchants)
        amount = random.randint(10, 600)
        days_ago = random.uniform(0, 14)
        ts = (now - timedelta(days=days_ago)).isoformat()
        flagged = 0
        if random.random() < 0.05:
            amount = random.randint(2000, 5000)
            flagged = 1
        elif random.random() < 0.03:
            flagged = 1
        conn.execute(
            "INSERT INTO Transactions (rfid, amount, merchant_name, transaction_type, timestamp, flagged) VALUES (?, ?, ?, 'debit', ?, ?)",
            (rfid, amount, merchant, ts, flagged),
        )

    for rfid in random.sample(rfid_numbers, 8):
        ts = (now - timedelta(days=random.uniform(0, 7))).isoformat()
        conn.execute(
            "INSERT INTO Transactions (rfid, amount, merchant_name, transaction_type, timestamp, flagged) VALUES (?, ?, 'Top-Up', 'topup', ?, 0)",
            (rfid, random.randint(500, 2000), ts),
        )

    for rfid in random.sample(rfid_numbers, 5):
        conn.execute(
            "INSERT INTO AuditLog (action, rfid, detail, timestamp) VALUES (?, ?, ?, ?)",
            ("SYSTEM_INIT", rfid, "Card registered during setup", now.isoformat()),
        )

    conn.commit()
    print("\nSample login credentials:")
    for rfid in rfid_numbers[:5]:
        print(f"  RFID: {rfid}  |  Password: pass{rfid}")
    print("\nAdmin credentials:")
    print("  Username: admin  |  Password: admin123")


if __name__ == "__main__":
    import os
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print("Removed existing database.")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    create_tables(conn)
    insert_dummy_data(conn)
    conn.close()
    print(f"\nDatabase ready at {DB_PATH}")