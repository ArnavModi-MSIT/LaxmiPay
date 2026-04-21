"""
qr.py — QR Code generation utility for the RFID Payment System.

Usage:
  python qr.py <rfid>                    # Single QR code
  python qr.py --batch                   # Batch-generate for all RFIDs in DB
  python qr.py --batch --out ./qr_codes  # Specify output directory
"""

import qrcode
import sys
import os
import argparse
import sqlite3
from cryptography.fernet import Fernet


DB_PATH = "./Database.db"
ENCRYPTION_KEY = b"z1cXRBEAIY301GjtQOzr2xx1iygts7K_QSAeuQTtJ3o="
cipher = Fernet(ENCRYPTION_KEY)


def encrypt_data(data: str) -> str:
    """Encrypt data and return as string."""
    encrypted = cipher.encrypt(data.encode())
    return encrypted.decode('utf-8')


def generate_qr(data: str, filename: str = "qr_code.png") -> str:
    """Generate a single QR code PNG. Returns the saved filepath."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(filename)
    return filename


def batch_generate(out_dir: str = "./qr_codes"):
    """Generate QR codes for all RFIDs in the database."""
    os.makedirs(out_dir, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT RFID FROM RFIDTable").fetchall()
    conn.close()

    if not rows:
        print("⚠️  No RFIDs found in database. Run sm.py first.")
        return

    for (rfid,) in rows:
        data = f"{rfid}:pass{rfid}"
        encrypted = encrypt_data(data)
        path = os.path.join(out_dir, f"rfid_{rfid}.png")
        generate_qr(encrypted, path)

    print(f"✅ Generated {len(rows)} encrypted QR codes → {out_dir}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RFID QR Code Generator")
    parser.add_argument("rfid", nargs="?", help="Single RFID to generate QR for")
    parser.add_argument("--batch", action="store_true", help="Generate QR codes for all RFIDs in DB")
    parser.add_argument("--out", default="./qr_codes", help="Output directory for batch mode")
    args = parser.parse_args()

    if args.batch:
        batch_generate(args.out)
    elif args.rfid:
        data = f"{args.rfid}:pass{args.rfid}"
        encrypted = encrypt_data(data)
        path = generate_qr(encrypted, f"rfid_{args.rfid}.png")
        print(f"✅ QR code saved: {path}")
    else:
        parser.print_help()