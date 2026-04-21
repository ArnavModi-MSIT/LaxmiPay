# 💳 LaxmiPay — RFID Payment Management System

A modern RFID card payment management system with real-time analytics, fraud detection, and secure QR-based authentication.

---

## ✨ Features

- **🔐 Secure QR-Based Login**: Encrypted QR codes for instant authentication (no password entry needed)
- **💳 RFID Card Management**: Register, top-up, block/unblock cards, set spending limits
- **📊 Real-time Analytics**: Dashboard with transaction volumes, top spenders, and fraud rate monitoring
- **🚨 Fraud Detection**: Velocity-based and high-value transaction flagging
- **👥 Dual Portals**: Separate Admin and Customer dashboards
- **📋 Audit Trail**: Complete transaction history and system logs
- **💾 CSV Export**: Download transaction data for reporting

---

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python)
- **Frontend**: Streamlit (Python)
- **Database**: SQLite3
- **Authentication**: JWT tokens
- **Encryption**: Fernet (symmetric encryption for QR codes)
- **Password Hashing**: PBKDF2-SHA256

---

## 📋 Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Virtual environment (recommended)

---

## 📦 Installation

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/LaxmiPay.git
cd LaxmiPay
```

### 2. Create & Activate Virtual Environment
```bash
# Windows
python -m venv .venv
.venv\Scripts\Activate.ps1

# macOS/Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Initialize Database
```bash
python sm.py
```
This creates:
- SQLite database with sample RFIDs
- 20 user accounts with demo data
- Encrypted QR codes in `./qr_codes/` folder

---

## 🚀 Quick Start

### Terminal 1: Start API Server
```bash
uvicorn api:app --reload
```
- API running on: **http://localhost:8000**
- API docs: **http://localhost:8000/docs** (interactive)

### Terminal 2: Start Frontend App
```bash
streamlit run app.py
```
- App running on: **http://localhost:8501**
- Browser opens automatically

---

## 👤 Login Credentials

### Admin Panel
```
Username: admin
Password: admin123
```
Access: Main app → Sidebar → "🛠️ Admin Panel"

### Customer Portal
**Option 1: QR Code Scan (Recommended)**
- Navigate to `./qr_codes/` folder
- Save any `rfid_*.png` on your phone
- In app: "👤 Customer Portal" → "📷 Scan QR Code"
- Instant login - no password needed!

**Option 2: Manual Login**
- RFID: `4220` (or any from sample data)
- Password: `pass4220` (format: `pass{RFID}`)

**Demo Credentials:**
```
RFID: 4220  → Password: pass4220
RFID: 7653  → Password: pass7653
RFID: 3744  → Password: pass3744
RFID: 5225  → Password: pass5225
RFID: 7594  → Password: pass7594
```

---

## 📁 Project Structure

```
LaxmiPay/
├── README.md                   # This file
├── requirements.txt            # Python dependencies
├── Database.db                 # SQLite database
│
├── api.py                      # FastAPI backend
│   ├── Authentication endpoints
│   ├── RFID management
│   ├── Transaction processing
│   ├── Analytics & fraud detection
│   └── Audit logging
│
├── app.py                      # Streamlit main app
│   ├── Home page
│   ├── Customer portal link
│   └── Admin login
│
├── sm.py                       # Database setup & initialization
│   ├── Create tables
│   ├── Generate sample data
│   └── Hash passwords
│
├── qr.py                       # QR code generator
│   ├── Single QR generation
│   └── Batch generation with encryption
│
├── pages/
│   ├── Admin_Dashboard.py      # Admin panel
│   │   ├── Analytics overview
│   │   ├── Card manager
│   │   ├── Payment simulator
│   │   ├── Flagged transactions
│   │   └── Audit logs
│   │
│   └── Customer_Dashboard.py   # Customer portal
│       ├── Balance display
│       ├── Transaction history
│       ├── QR/manual login
│       ├── Payment interface
│       └── Profile management
│
├── qr_codes/                   # Generated QR codes (encrypted)
│   ├── rfid_4220.png
│   ├── rfid_7653.png
│   └── ...
│
└── .venv/                      # Virtual environment
```

---

## 🔑 Key Endpoints

### Authentication
- `POST /authenticate/admin` - Admin login
- `POST /authenticate/customer` - Customer login

### RFID Management
- `GET /rfid/{rfid}` - Get card details
- `POST /rfid/register` - Register new card
- `PUT /rfid/{rfid}` - Update card (balance, limit, status)

### Transactions
- `POST /process-payment` - Process payment
- `GET /transactions/{rfid}` - Get user transactions

### Analytics
- `GET /analytics/summary` - Dashboard metrics
- `GET /flagged-transactions` - Fraud alerts

### Export
- `GET /export/transactions` - Download all transactions
- `GET /export/transactions/{rfid}` - Download user transactions

---

## 🔐 Security Features

1. **Encrypted QR Codes**: Fernet symmetric encryption
   - QR data appears as gibberish when scanned externally
   - Only app can decrypt with correct key

2. **JWT Authentication**: 
   - Tokens expire after 8 hours
   - Role-based access control (Admin/Customer)

3. **Password Hashing**: 
   - PBKDF2-SHA256 algorithm
   - Passwords never stored in plaintext

4. **Audit Logging**: 
   - All actions tracked with timestamps
   - Complete transaction history

5. **Fraud Detection**:
   - Velocity checks: 5+ transactions in 60 seconds
   - High-value alerts: Transactions ≥ ₹2,000

---

## 📊 Admin Dashboard Features

### 📈 Analytics Section
- Total balance in circulation
- Transaction count & volume
- Average transaction amount
- Flagged transactions count
- Blocked cards overview
- Daily volume chart (14 days)
- Top 5 spenders
- Fraud rate percentage

### 💳 Card Manager
- Register new RFID cards
- Top-up balance
- Set daily spending limits
- Block/unblock cards
- Bulk operations

### 💸 Payment Simulator
- Simulate customer payments
- Test fraud detection
- Generate transaction data

### 🚨 Flagged Transactions
- View all suspicious transactions
- Review high-value purchases
- Velocity check violations

### 📋 Audit Log
- Complete system activity
- User login/logout events
- Card management history
- Transaction records

---

## 💡 Usage Workflow

### First Time Setup
1. Run `python sm.py` to create database
2. Run `python qr.py --batch` to generate QR codes
3. Start API: `uvicorn api:app --reload`
4. Start App: `streamlit run app.py`

### Admin Tasks
1. Log in with `admin` / `admin123`
2. View analytics and metrics
3. Manage RFID cards
4. Monitor flagged transactions
5. Export transaction data

### Customer Tasks
1. Scan QR code for instant login
   - Or use manual login (RFID + password)
2. View account balance
3. Check transaction history
4. Make payments

---

## 🛠️ Advanced Usage

### Generate Single QR Code
```bash
python qr.py 4220
```

### Regenerate All QR Codes
```bash
python qr.py --batch --out ./qr_codes
```

### Access API Docs
Open: **http://localhost:8000/docs**
- Interactive API documentation
- Try out endpoints directly

---

## 📝 Database Schema

### RFIDTable
- `RFID` (Primary Key): Card identifier
- `Balance`: Current card balance
- `status`: 'active' or 'blocked'
- `daily_limit`: Optional spending limit
- `merchant_name`: Associated merchant

### UserAuth
- `RFID`: Card identifier
- `Password`: Hashed password

### Transactions
- `id`: Transaction ID
- `rfid`: Card used
- `amount`: Transaction amount
- `merchant_name`: Where transaction occurred
- `transaction_type`: 'debit' or 'topup'
- `timestamp`: When transaction happened
- `flagged`: Fraud flag (0/1)

### AuditLog
- `id`: Log entry ID
- `action`: Type of action
- `rfid`: Related card (if any)
- `detail`: Action details
- `timestamp`: When it happened

---

## ⚙️ Configuration

### Fraud Detection Limits
Edit in `api.py`:
```python
FRAUD_VELOCITY_LIMIT = 5          # Transactions per 60 seconds
FRAUD_AMOUNT_THRESHOLD = 2000     # Amount in rupees
```

### JWT Settings
Edit in `api.py`:
```python
JWT_EXPIRE_MINUTES = 480          # 8 hours
SECRET_KEY = "your-secret-key"
```

### Encryption Key
Located in `qr.py` and `pages/Customer_Dashboard.py`:
```python
ENCRYPTION_KEY = b"z1cXRBEAIY301GjtQOzr2xx1iygts7K_QSAeuQTtJ3o="
```

---

## 🐛 Troubleshooting

### "API server is offline"
- Ensure `uvicorn api:app --reload` is running in Terminal 1
- Check if port 8000 is available

### "QR code not detected"
- Ensure good lighting and focus
- Try moving camera closer
- Install pyzbar: `pip install pyzbar`

### "Invalid credentials" during login
- Verify RFID and password format
- Run `python sm.py` to reset database
- Check demo credentials above

### Database locked
- Close all Streamlit tabs
- Restart both API and app servers

---

## 📄 Requirements

```
fastapi==0.104.1
uvicorn==0.24.0
streamlit==1.28.1
requests==2.31.0
pandas==2.1.3
pydantic==2.5.0
passlib==1.7.4
python-jose==3.3.0
cryptography==41.0.7
qrcode==7.4.2
pillow==10.1.0
pyzbar==0.1.9
opencv-python==4.8.1.78
```

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see LICENSE file for details.

---

## 👨‍💼 Support

For issues, questions, or suggestions:
1. Check existing GitHub issues
2. Create a new issue with detailed description
3. Include error messages and screenshots if applicable

---

## 🚀 Future Enhancements

- [ ] Mobile app for iOS/Android
- [ ] Multi-user admin accounts
- [ ] Merchant integration
- [ ] Recurring payments
- [ ] Email notifications
- [ ] SMS OTP verification
- [ ] Advanced reporting & analytics
- [ ] Machine learning fraud detection

---

**Made with ❤️ for secure RFID payments**

*Version: 4.0.0 | Last Updated: April 2026*
