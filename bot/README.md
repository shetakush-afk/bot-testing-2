# 🚀 Python Telegram Subscription & UPI Payment Bot + Web Admin Panel

Yeh ek complete production-ready **Telegram Subscription & Dynamic UPI Payment Bot** hai, jisme **Domain Web Admin Dashboard** bhi shamil hai.

---

## 🔥 Features Summary

### 1. 🎬 Demo & Welcome Flow
- `/start` command dene par sabse pehle 4-5 demo videos ke links show hote hain.
- Post-demo custom welcome message aur Subscription Plans Inline Buttons dikhte hain (Name aur Price ke sath).

### 2. 💳 Auto Dynamic UPI QR Generation
- Selected plan par click karte hi instantly **dynamic UPI QR Code Image** generate hoti hai (`upi://pay?pa=...`).
- Image ke sath **"✅ Maine Payment Kar Diya"** ka Inline Button hota hai.

### 3. 🛡️ Payment Verification & Admin Approval Workflow
- User **"✅ Maine Payment Kar Diya"** par click karta hai.
- Step 1: User 12-digit **UTR / Transaction ID** enter karta hai.
- Step 2: User **Payment Screenshot Photo** upload karta hai.
- Step 3: Details Admin ke Telegram DM par auto-forward ho jati hain (User Info, Plan, UTR, Screenshot, aur **Inline Approve / Reject Buttons**).
- **Approval Action:** Admin jab approve karta hai, toh bot automatically Customer ke DM par Private Telegram Channel ka **One-Time Invite Link** bhej deta hai!

### 4. 🌐 Domain Web Admin Panel
- Access from your custom domain: `https://yourdomain.com` (e.g. `http://localhost:5000`).
- Secure Password Login system.
- Live Analytics Cards (Total Revenue, Pending Approvals, Total Approved, Total Rejected).
- Payments Table: User Info, Plan, UTR ID, Screenshot Modal Preview, Approve & Reject Buttons.
- Live Web Settings Manager:
  - UPI ID & Admin Name edit karne ka form.
  - Post-Demo Welcome Message update karne ka form.
  - Channel ID set karne ka form.
  - Subscription Plans Add/Edit/Delete karne ka form.

### 5. ⚡ Admin Telegram Bot Commands
- `/setupi <new_upi>` - Runtime par UPI ID badalne ke liye.
- `/setmessage <new_message>` - Welcome message update karne ke liye.
- `/setplan <id> <name> <price>` - New plan add ya edit karne ke liye.
- `/botconfig` - Current active configuration dekhne ke liye.

---

## 🛠️ Requirements & Installation

### Step 1: Navigate to Project Directory
```bash
cd bot
```

### Step 2: Install Python Dependencies
Terminal mein execute karein:
```bash
pip install -r requirements.txt
```

---

## ⚙️ Environment Configuration (`.env`)

Apne project directory me `.env` file banayein (`.env.example` file se copy karein):

```env
# Telegram Bot Token (@BotFather se lein)
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz123456

# Admin Telegram User ID (@userinfobot se lein)
ADMIN_ID=123456789

# Private Telegram Channel ID (e.g. -100123456789)
CHANNEL_ID=-100123456789

# Web Dashboard Port
PORT=5000

# Web Session Secret Key
SECRET_KEY=super_secret_admin_key_998877
```

---

## 🚀 Running the Bot & Web Panel

Command run karein:
```bash
python app.py
```

Console Output:
```
🌐 [WEB DASHBOARD] Starting Admin Web Panel on http://0.0.0.0:5000
🤖 [BOT ENGINE] Initializing python-telegram-bot...
🚀 [READY] Telegram Bot & Web Admin Panel are running concurrently!
👉 Web Panel URL: http://localhost:5000
```

---

## 🌐 Deploying on Custom Domain (Nginx + VPS)

Agar aap Web Panel ko apne domain par host karna chahte hain (e.g. `https://admin.yourdomain.com`):

### 1. Nginx Reverse Proxy Setup:
`/etc/nginx/sites-available/admin_panel`:
```nginx
server {
    server_name admin.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 2. SSL Certificate (Certbot):
```bash
sudo certbot --nginx -d admin.yourdomain.com
```

### 3. Systemd Service (Background Service):
`/etc/systemd/system/telegrambot.service`:
```ini
[Unit]
Description=Telegram Bot & Web Admin Panel
After=network.target

[Service]
User=root
WorkingDirectory=/path/to/bot
ExecStart=/usr/bin/python3 /path/to/bot/app.py
Restart=always

[Install]
WantedBy=multi-user.target
```
Enable & Start:
```bash
sudo systemctl enable telegrambot
sudo systemctl start telegrambot
```

---

## 🔐 Default Credentials
- **Web Admin Password:** `admin123pass` (Aap `config.json` mein change kar sakte hain).

---

## 📝 Notes
- Private Telegram Channel mein Bot ko **Administrator** banayein aur **"Invite Users via Link"** permission enable karein.
