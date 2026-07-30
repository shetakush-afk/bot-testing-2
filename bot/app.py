import os
import sys
import json
import io
import time
import datetime
import asyncio
import threading
from pathlib import Path
from dotenv import load_dotenv

# Flask imports for Web Admin Panel
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory

# Telegram imports (python-telegram-bot v20+)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# QR Code & Image imports
import qrcode
from PIL import Image

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) if os.getenv("ADMIN_ID") else 0
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
PORT = int(os.getenv("PORT", "5000"))
SECRET_KEY = os.getenv("SECRET_KEY", "secret_admin_key_123")

# Directory setup
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
DEMO_UPLOADS_DIR = UPLOADS_DIR / "demo_videos"
DEMO_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Conversation states
WAITING_UTR, WAITING_SCREENSHOT = range(2)

# Global bot application instance reference
bot_app = None
loop = None

# --- CONFIG MANAGEMENT HELPERS ---
config_lock = threading.Lock()

def load_config():
    with config_lock:
        if not CONFIG_PATH.exists():
            default_config = {
                "upi_id": "admin@upi",
                "admin_name": "VIP Admin",
                "welcome_message": "🚀 *Welcome to Exclusive VIP Membership!*\n\nApne manpasand plan ko select karein.",
                "demo_videos": [
                    "🎬 *Demo Video 1: Channel Overview*\nhttps://t.me/demo/1",
                    "🎬 *Demo Video 2: Earnings & Proof*\nhttps://t.me/demo/2"
                ],
                "plans": [
                    {"id": "1", "name": "1 Month VIP Access", "price": 199},
                    {"id": "2", "name": "3 Months VIP Access", "price": 499},
                    {"id": "3", "name": "1 Year VIP Access", "price": 999},
                    {"id": "4", "name": "Lifetime VIP Access", "price": 1999}
                ],
                "channel_id": CHANNEL_ID or "-100123456789",
                "admin_password": "admin123pass",
                "payments": {}
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            return default_config
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

def save_config(data):
    with config_lock:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

# --- UPI QR CODE GENERATOR ---
def generate_upi_qr(upi_id, admin_name, amount, plan_name):
    """
    Generates dynamic UPI link and converts into a QR Code PNG in memory BytesIO.
    UPI URI Format: upi://pay?pa=<UPI_ID>&pn=<NAME>&am=<AMOUNT>&cu=INR&tn=<NOTE>
    """
    note = f"Payment for {plan_name}".replace(" ", "%20")
    clean_name = admin_name.replace(" ", "%20")
    upi_url = f"upi://pay?pa={upi_id}&pn={clean_name}&am={amount}&cu=INR&tn={note}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(upi_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    bio.name = 'upi_qr.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio, upi_url

# --- TELEGRAM BOT HANDLERS ---

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start command: Sends actual demo video files, post-demo message, and subscription plan buttons."""
    config = load_config()
    chat_id = update.effective_chat.id

    # 1. Send Demo Video Files
    demo_videos = config.get("demo_videos", [])
    if demo_videos:
        await update.message.reply_text("✨ *WELCOME! Sending Demo Videos...*", parse_mode="Markdown")
        
        for index, vid in enumerate(demo_videos):
            if isinstance(vid, dict):
                title = vid.get("title", f"🎬 Demo Video #{index + 1}")
                file_id = vid.get("file_id")
                file_path_rel = vid.get("file_path")
                abs_video_path = BASE_DIR / file_path_rel if file_path_rel else None

                sent = False
                # 1. Try sending via cached Telegram file_id (ultra-fast)
                if file_id:
                    try:
                        await context.bot.send_video(chat_id=chat_id, video=file_id, caption=title)
                        sent = True
                    except Exception as e:
                        print(f"[WARNING] Cached file_id failed, fallback to file upload: {e}")

                # 2. If file_id missing or failed, send local file and cache file_id
                if not sent and abs_video_path and abs_video_path.exists():
                    try:
                        with open(abs_video_path, "rb") as vfile:
                            msg = await context.bot.send_video(chat_id=chat_id, video=vfile, caption=title)
                            if msg.video:
                                vid["file_id"] = msg.video.file_id
                                save_config(config)
                        sent = True
                    except Exception as e:
                        print(f"[ERROR] Failed sending local video file: {e}")

                if not sent:
                    await update.message.reply_text(f"🎬 *{title}*", parse_mode="Markdown")
            elif isinstance(vid, str):
                await update.message.reply_text(vid, parse_mode="Markdown", disable_web_page_preview=False)

    # 2. Show Welcome Message & Subscription Plans
    welcome_text = config.get("welcome_message", "Select a subscription plan below:")

    keyboard = []
    for plan in config.get("plans", []):
        btn_text = f"⭐ {plan['name']} - ₹{plan['price']}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"select_plan_{plan['id']}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)

async def plan_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered when a user clicks a plan inline button. Generates & sends dynamic UPI QR code."""
    query = update.callback_query
    await query.answer()

    plan_id = query.data.replace("select_plan_", "")
    config = load_config()

    selected_plan = next((p for p in config.get("plans", []) if str(p["id"]) == str(plan_id)), None)
    if not selected_plan:
        await query.edit_message_text("❌ Selected plan was not found. Kripya `/start` karke firse try karein.")
        return

    # Save selected plan in user_data for conversation flow
    context.user_data["selected_plan"] = selected_plan

    # Generate UPI QR Code image
    upi_id = config.get("upi_id", "admin@upi")
    admin_name = config.get("admin_name", "VIP Admin")
    price = selected_plan["price"]
    plan_name = selected_plan["name"]

    qr_stream, upi_url = generate_upi_qr(upi_id, admin_name, price, plan_name)

    caption = (
        f"💳 *AUTOMATIC UPI PAYMENT QR CODE*\n\n"
        f"📌 *Selected Plan:* {plan_name}\n"
        f"💰 *Amount to Pay:* ₹{price}\n"
        f"🏦 *UPI ID:* `{upi_id}`\n\n"
        f"👇 *Instructions:*\n"
        f"1. Above QR code ko Google Pay, PhonePe, Paytm ya kisi bhi UPI app se scan karke **₹{price}** pay karein.\n"
        f"2. Payment successfully complete hone ke baad niche **'✅ Maine Payment Kar Diya'** button par click karein."
    )

    keyboard = [
        [InlineKeyboardButton("✅ Maine Payment Kar Diya", callback_data=f"paid_{plan_id}")],
        [InlineKeyboardButton("🔙 Back to Plans", callback_data="back_to_plans")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.reply_photo(photo=qr_stream, caption=caption, parse_mode="Markdown", reply_markup=reply_markup)

async def back_to_plans_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Navigates user back to plan selection menu."""
    query = update.callback_query
    await query.answer()
    config = load_config()

    keyboard = []
    for plan in config.get("plans", []):
        btn_text = f"⭐ {plan['name']} - ₹{plan['price']}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"select_plan_{plan['id']}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(config.get("welcome_message", "Select a plan:"), parse_mode="Markdown", reply_markup=reply_markup)

# --- CONVERSATION HANDLERS FOR PAYMENT VERIFICATION ---

async def payment_done_clicked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 1: User clicks 'Maine Payment Kar Diya'. Ask for 12-digit UTR / Txn ID."""
    query = update.callback_query
    await query.answer()

    plan_id = query.data.replace("paid_", "")
    config = load_config()
    selected_plan = next((p for p in config.get("plans", []) if str(p["id"]) == str(plan_id)), context.user_data.get("selected_plan"))

    if not selected_plan:
        await query.message.reply_text("❌ Session expired. Kripya `/start` se start karein.")
        return ConversationHandler.END

    context.user_data["selected_plan"] = selected_plan

    await query.message.reply_text(
        "📝 *PAYMENT VERIFICATION - STEP 1/2*\n\n"
        "Kripya apna **12-Digit UTR Number / Transaction ID** yahan chat me reply karein:\n"
        "_(Example: 324567890123)_",
        parse_mode="Markdown"
    )
    return WAITING_UTR

async def receive_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 2: Saves UTR and asks user for Screenshot Photo."""
    utr_input = update.message.text.strip()

    if len(utr_input) < 6:
        await update.message.reply_text("⚠️ Kripya sahi UTR / Transaction ID bhejien. Firse type karein:")
        return WAITING_UTR

    context.user_data["utr"] = utr_input

    await update.message.reply_text(
        "📸 *PAYMENT VERIFICATION - STEP 2/2*\n\n"
        "Bahut badiya! Ab kripya apne Payment ka **Screenshot Photo** is chat me upload karein.",
        parse_mode="Markdown"
    )
    return WAITING_SCREENSHOT

async def receive_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 3: Saves photo, records payment in config.json, and forwards to Admin on Telegram & Web."""
    if not update.message.photo:
        await update.message.reply_text("⚠️ Kripya payment ka Photo Screenshot upload karein.")
        return WAITING_SCREENSHOT

    user = update.effective_user
    photo = update.message.photo[-1] # Highest resolution photo
    file_id = photo.file_id

    # Download photo locally for Web Dashboard display
    file = await context.bot.get_file(file_id)
    file_name = f"pay_{user.id}_{int(time.time())}.jpg"
    photo_path = UPLOADS_DIR / file_name
    await file.download_to_drive(photo_path)

    selected_plan = context.user_data.get("selected_plan", {"name": "VIP Subscription", "price": 0})
    utr = context.user_data.get("utr", "N/A")
    payment_id = f"PAY_{int(time.time())}_{user.id}"

    timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Store record in config.json
    config = load_config()
    payment_record = {
        "payment_id": payment_id,
        "user_id": user.id,
        "user_name": user.full_name,
        "username": user.username or "",
        "plan_name": selected_plan.get("name"),
        "price": selected_plan.get("price"),
        "utr": utr,
        "photo_file_id": file_id,
        "photo_path": f"/uploads/{file_name}",
        "status": "PENDING",
        "timestamp": timestamp_str
    }
    config["payments"][payment_id] = payment_record
    save_config(config)

    # Notify Customer
    await update.message.reply_text(
        "⏳ *Aapka Payment Verification Under Process Hai!*\n\n"
        "Aapki UTR aur Screenshot details Admin ko bhej di gayi hain. "
        "Verification complete hote hi aapko automatic Private Channel ka Invite Link mil jayega. Thank you!",
        parse_mode="Markdown"
    )

    # Forward to Telegram Admin ID if configured
    current_admin_id = ADMIN_ID or config.get("admin_id")
    if current_admin_id:
        try:
            admin_msg = (
                f"🚨 *NEW PAYMENT APPROVAL REQUIRED*\n\n"
                f"👤 *User:* {user.full_name} (@{user.username or 'N/A'})\n"
                f"🆔 *User ID:* `{user.id}`\n"
                f"⭐ *Plan:* {selected_plan.get('name')}\n"
                f"💰 *Price:* ₹{selected_plan.get('price')}\n"
                f"🔢 *UTR:* `{utr}`\n"
                f"📅 *Time:* {timestamp_str}\n"
            )
            keyboard = [
                [
                    InlineKeyboardButton("✅ Approve & Send Link", callback_data=f"tg_approve_{payment_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"tg_reject_{payment_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Send photo with caption to Admin Telegram DM
            with open(photo_path, "rb") as photo_bytes:
                await context.bot.send_photo(
                    chat_id=current_admin_id,
                    photo=photo_bytes,
                    caption=admin_msg,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
        except Exception as e:
            print(f"[ERROR] Forwarding payment to Admin ID failed: {e}")

    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Payment process cancelled. Kripya `/start` se firse start karein.")
    return ConversationHandler.END

# --- ADMIN ACTION CALLBACKS (TELEGRAM INLINE BUTTONS) ---

async def admin_decision_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    config = load_config()

    if data.startswith("tg_approve_"):
        payment_id = data.replace("tg_approve_", "")
        success, msg = await process_approval(payment_id, context.bot)
        if success:
            await query.edit_message_caption(caption=query.message.caption + f"\n\n✅ *APPROVED BY ADMIN ON TELEGRAM*", parse_mode="Markdown")
        else:
            await query.message.reply_text(f"⚠️ Approval Error: {msg}")

    elif data.startswith("tg_reject_"):
        payment_id = data.replace("tg_reject_", "")
        success, msg = await process_rejection(payment_id, context.bot)
        if success:
            await query.edit_message_caption(caption=query.message.caption + f"\n\n❌ *REJECTED BY ADMIN ON TELEGRAM*", parse_mode="Markdown")
        else:
            await query.message.reply_text(f"⚠️ Rejection Error: {msg}")

# --- HELPER FUNCTIONS FOR APPROVAL / REJECTION ---

async def process_approval(payment_id, bot_instance):
    """Marks payment APPROVED, generates one-time Channel Invite Link, and DMs Customer."""
    config = load_config()
    payment = config["payments"].get(payment_id)
    if not payment:
        return False, "Payment ID not found"

    if payment["status"] == "APPROVED":
        return False, "Already Approved"

    user_id = payment["user_id"]
    channel_id = config.get("channel_id", CHANNEL_ID)
    course_link = config.get("course_link")

    invite_link = course_link if (course_link and course_link.strip()) else None
    if not invite_link:
        try:
            # Generate dynamic channel invite link with member_limit=1
            link_obj = await bot_instance.create_chat_invite_link(chat_id=channel_id, member_limit=1)
            invite_link = link_obj.invite_link
        except Exception as e:
            print(f"[WARNING] Could not create channel invite link automatically: {e}")
            invite_link = f"Contact Admin for Access (Channel ID: {channel_id})"

    # Update Payment Record
    payment["status"] = "APPROVED"
    payment["approved_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_config(config)

    # DM User on Telegram
    user_msg = (
        f"🎉 *CONGRATULATIONS! YOUR PAYMENT HAS BEEN APPROVED!*\n\n"
        f"⭐ *Plan Activated:* {payment['plan_name']}\n"
        f"💳 *UTR Verified:* `{payment['utr']}`\n\n"
        f"👇 *Click below link to join Private VIP Channel:*\n"
        f"🔗 [JOIN VIP CHANNEL]({invite_link})\n\n"
        f"_(Note: Yeh invite link ek baar usable hai.)_"
    )
    try:
        await bot_instance.send_message(chat_id=user_id, text=user_msg, parse_mode="Markdown", disable_web_page_preview=False)
    except Exception as e:
        print(f"[ERROR] Could not DM user {user_id}: {e}")

    return True, "Approved successfully"

async def process_rejection(payment_id, bot_instance):
    """Marks payment REJECTED and DMs Customer."""
    config = load_config()
    payment = config["payments"].get(payment_id)
    if not payment:
        return False, "Payment ID not found"

    payment["status"] = "REJECTED"
    save_config(config)

    user_id = payment["user_id"]
    user_msg = (
        f"❌ *PAYMENT REJECTED*\n\n"
        f"Aapka payment verification reject kar diya gaya hai.\n"
        f"📌 *UTR:* `{payment['utr']}`\n\n"
        f"Kripya correct UTR ID aur valid screenshot ke sath firse try karein ya support se contact karein."
    )
    try:
        await bot_instance.send_message(chat_id=user_id, text=user_msg, parse_mode="Markdown")
    except Exception as e:
        print(f"[ERROR] Could not DM user {user_id}: {e}")

    return True, "Rejected successfully"

# --- TELEGRAM BOT ADMIN COMMANDS ---

async def set_upi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin Command: /setupi <new_upi>"""
    if update.effective_user.id != ADMIN_ID and ADMIN_ID != 0:
        return
    if not context.args:
        await update.message.reply_text("Usage: `/setupi newupi@bank`", parse_mode="Markdown")
        return
    new_upi = context.args[0]
    config = load_config()
    config["upi_id"] = new_upi
    save_config(config)
    await update.message.reply_text(f"✅ UPI ID successfully updated to: `{new_upi}`", parse_mode="Markdown")

async def set_message_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin Command: /setmessage <new_message>"""
    if update.effective_user.id != ADMIN_ID and ADMIN_ID != 0:
        return
    if not context.args:
        await update.message.reply_text("Usage: `/setmessage New welcome message text...`", parse_mode="Markdown")
        return
    new_msg = " ".join(context.args)
    config = load_config()
    config["welcome_message"] = new_msg
    save_config(config)
    await update.message.reply_text("✅ Post-demo Welcome Message updated successfully!")

async def set_plan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin Command: /setplan <id> <name> <price>"""
    if update.effective_user.id != ADMIN_ID and ADMIN_ID != 0:
        return
    if len(context.args) < 3:
        await update.message.reply_text("Usage: `/setplan 1 '1 Month Access' 199`", parse_mode="Markdown")
        return
    plan_id = context.args[0]
    price = int(context.args[-1])
    plan_name = " ".join(context.args[1:-1]).replace("'", "").replace('"', '')

    config = load_config()
    plans = config.get("plans", [])

    # Check if plan already exists -> update, else add
    existing = next((p for p in plans if str(p["id"]) == str(plan_id)), None)
    if existing:
        existing["name"] = plan_name
        existing["price"] = price
    else:
        plans.append({"id": plan_id, "name": plan_name, "price": price})

    config["plans"] = plans
    save_config(config)
    await update.message.reply_text(f"✅ Plan #{plan_id} updated: *{plan_name}* at ₹{price}", parse_mode="Markdown")

async def bot_config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin Command: /botconfig"""
    config = load_config()
    current_admin = str(ADMIN_ID or config.get("admin_id", "0"))
    if str(update.effective_user.id) != current_admin and current_admin != "0":
        return
    merchant = config.get("merchant", {})
    msg = (
        f"⚙️ *CURRENT BOT CONFIGURATION*\n\n"
        f"🏦 *UPI ID:* `{config.get('upi_id')}`\n"
        f"👤 *Admin Telegram ID:* `{config.get('admin_id')}`\n"
        f"📢 *Channel ID:* `{config.get('channel_id')}`\n"
        f"🎓 *Course Link:* {config.get('course_link')}\n"
        f"💳 *Merchant Gateway:* {'Enabled ✅' if merchant.get('enabled') else 'Disabled ❌'}\n"
        f"🆔 *Paytm MID:* `{merchant.get('merchant_id', 'N/A')}`\n\n"
        f"📋 *Active Plans:*\n"
    )
    for p in config.get("plans", []):
        msg += f"• #{p['id']}: {p['name']} - ₹{p['price']}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def set_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin Command: /setadmin <admin_id>"""
    config = load_config()
    current_admin = str(ADMIN_ID or config.get("admin_id", "0"))
    if str(update.effective_user.id) != current_admin and current_admin != "0":
        return
    if not context.args:
        await update.message.reply_text("Usage: `/setadmin 123456789`", parse_mode="Markdown")
        return
    new_admin_id = context.args[0].strip()
    config["admin_id"] = new_admin_id
    save_config(config)
    await update.message.reply_text(f"✅ Admin Telegram ID updated to: `{new_admin_id}`", parse_mode="Markdown")

async def set_course_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin Command: /setcourse <link>"""
    config = load_config()
    current_admin = str(ADMIN_ID or config.get("admin_id", "0"))
    if str(update.effective_user.id) != current_admin and current_admin != "0":
        return
    if not context.args:
        await update.message.reply_text("Usage: `/setcourse https://t.me/+YourLink`", parse_mode="Markdown")
        return
    new_link = " ".join(context.args).strip()
    config["course_link"] = new_link
    save_config(config)
    await update.message.reply_text(f"✅ Course / VIP Link updated to:\n{new_link}", parse_mode="Markdown")

async def set_merchant_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin Command: /setmerchant <mid> <token> <upi>"""
    config = load_config()
    current_admin = str(ADMIN_ID or config.get("admin_id", "0"))
    if str(update.effective_user.id) != current_admin and current_admin != "0":
        return
    if len(context.args) < 3:
        await update.message.reply_text("Usage: `/setmerchant <MID> <TOKEN> <UPI_ID>`", parse_mode="Markdown")
        return
    mid = context.args[0].strip()
    token = context.args[1].strip()
    upi = context.args[2].strip()

    config["upi_id"] = upi
    config["merchant"] = {
        "merchant_id": mid,
        "merchant_token": token,
        "upi_id": upi,
        "enabled": True
    }
    save_config(config)
    await update.message.reply_text(f"✅ Paytm Merchant Auto-Approve Gateway configured:\n• MID: `{mid}`\n• UPI: `{upi}`\n• Status: Enabled", parse_mode="Markdown")

# --- FLASK WEB ADMIN PANEL SERVER ---

flask_app = Flask(__name__)
flask_app.secret_key = SECRET_KEY
flask_app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # Allow up to 200 MB uploads

@flask_app.errorhandler(413)
def request_entity_too_large(error):
    return redirect(url_for('dashboard', err="Video file is too large! Kripya 200MB se chhoti video upload karein."))

@flask_app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(UPLOADS_DIR, filename)

@flask_app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password_input = (request.form.get('password') or '').strip()
        config = load_config()
        expected_password = (os.getenv("ADMIN_PASSWORD") or config.get("admin_password", "admin123pass")).strip()
        if password_input == expected_password:
            session['admin_logged_in'] = True
            return redirect(url_for('dashboard'))
        return render_template('login.html', error=f"Invalid admin password!")
    return render_template('login.html')

@flask_app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('login'))

@flask_app.route('/')
def dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))

    config = load_config()
    payments = config.get("payments", {})

    # Calculate Analytics Metrics
    total_revenue = sum(p.get("price", 0) for p in payments.values() if p.get("status") == "APPROVED")
    pending_count = sum(1 for p in payments.values() if p.get("status") == "PENDING")
    approved_count = sum(1 for p in payments.values() if p.get("status") == "APPROVED")
    rejected_count = sum(1 for p in payments.values() if p.get("status") == "REJECTED")

    msg = request.args.get('msg')
    err = request.args.get('err')

    return render_template(
        'dashboard.html',
        config=config,
        payments=payments,
        total_revenue=total_revenue,
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count,
        msg=msg,
        err=err
    )

@flask_app.route('/approve_payment', methods=['POST'])
def web_approve_payment():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))

    payment_id = request.form.get('payment_id')

    # Execute async telegram approval from flask thread using bot_app
    if bot_app and loop:
        future = asyncio.run_coroutine_threadsafe(process_approval(payment_id, bot_app.bot), loop)
        try:
            success, message = future.result(timeout=10)
            if success:
                return redirect(url_for('dashboard', msg="Payment Approved & Invite Link sent to customer DM!"))
            else:
                return redirect(url_for('dashboard', err=message))
        except Exception as e:
            return redirect(url_for('dashboard', err=f"Error executing approval: {e}"))
    return redirect(url_for('dashboard', err="Telegram Bot engine is not active."))

@flask_app.route('/reject_payment', methods=['POST'])
def web_reject_payment():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))

    payment_id = request.form.get('payment_id')
    if bot_app and loop:
        future = asyncio.run_coroutine_threadsafe(process_rejection(payment_id, bot_app.bot), loop)
        try:
            success, message = future.result(timeout=10)
            if success:
                return redirect(url_for('dashboard', msg="Payment request rejected and user notified."))
            else:
                return redirect(url_for('dashboard', err=message))
        except Exception as e:
            return redirect(url_for('dashboard', err=f"Error executing rejection: {e}"))
    return redirect(url_for('dashboard', err="Telegram Bot engine is not active."))

@flask_app.route('/update_upi', methods=['POST'])
def web_update_upi():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))
    upi_id = request.form.get('upi_id')
    admin_name = request.form.get('admin_name')
    channel_id = request.form.get('channel_id')

    config = load_config()
    config['upi_id'] = upi_id
    config['admin_name'] = admin_name
    config['channel_id'] = channel_id
    save_config(config)
    return redirect(url_for('dashboard', msg="UPI & General Settings updated successfully!"))

@flask_app.route('/update_merchant', methods=['POST'])
def web_update_merchant():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))

    merchant_id = (request.form.get('merchant_id') or '').strip()
    merchant_token = (request.form.get('merchant_token') or '').strip()
    upi_id = (request.form.get('upi_id') or '').strip()
    enabled = request.form.get('enabled') == 'true'

    config = load_config()
    config['upi_id'] = upi_id
    config['merchant'] = {
        'merchant_id': merchant_id,
        'merchant_token': merchant_token,
        'upi_id': upi_id,
        'enabled': enabled
    }
    save_config(config)
    return redirect(url_for('dashboard', msg="Paytm Merchant Gateway Settings updated!"))

@flask_app.route('/update_course_link', methods=['POST'])
def web_update_course_link():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))

    channel_id = (request.form.get('channel_id') or '').strip()
    course_link = (request.form.get('course_link') or '').strip()

    config = load_config()
    config['channel_id'] = channel_id
    config['course_link'] = course_link
    save_config(config)
    return redirect(url_for('dashboard', msg="Channel ID & Course Link updated successfully!"))

@flask_app.route('/update_admin_id', methods=['POST'])
def web_update_admin_id():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))

    admin_id_input = (request.form.get('admin_id') or '').strip()
    admin_password = (request.form.get('admin_password') or '').strip()

    config = load_config()
    if admin_id_input:
        config['admin_id'] = admin_id_input
    if admin_password:
        config['admin_password'] = admin_password
    save_config(config)
    return redirect(url_for('dashboard', msg="Admin Telegram ID & Web Password updated successfully!"))

@flask_app.route('/update_message', methods=['POST'])
def web_update_message():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))
    welcome_message = request.form.get('welcome_message')

    config = load_config()
    config['welcome_message'] = welcome_message
    save_config(config)
    return redirect(url_for('dashboard', msg="Welcome Message updated!"))

@flask_app.route('/save_plan', methods=['POST'])
def web_save_plan():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))

    plan_id = request.form.get('id')
    name = request.form.get('name')
    price = int(request.form.get('price', 0))

    config = load_config()
    plans = config.get("plans", [])

    existing = next((p for p in plans if str(p["id"]) == str(plan_id)), None)
    if existing:
        existing["name"] = name
        existing["price"] = price
    else:
        plans.append({"id": plan_id, "name": name, "price": price})

    config["plans"] = plans
    save_config(config)
    return redirect(url_for('dashboard', msg=f"Plan #{plan_id} saved successfully!"))

@flask_app.route('/delete_plan', methods=['POST'])
def web_delete_plan():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))

    plan_id = request.form.get('plan_id')
    config = load_config()
    config["plans"] = [p for p in config.get("plans", []) if str(p["id"]) != str(plan_id)]
    save_config(config)
    return redirect(url_for('dashboard', msg="Plan deleted!"))

@flask_app.route('/save_demo_video', methods=['POST'])
def web_save_demo_video():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))

    title = (request.form.get('video_title') or '').strip()
    video_url = (request.form.get('video_url') or '').strip()
    file = request.files.get('video_file')

    # Option 1: Direct Video File Upload
    if file and file.filename != '':
        try:
            DEMO_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            clean_fname = f"demo_{int(time.time())}_{Path(file.filename).name.replace(' ', '_')}"
            save_path = DEMO_UPLOADS_DIR / clean_fname
            file.save(str(save_path))

            if not title:
                title = f"🎬 Demo Video: {file.filename}"

            rel_path = f"uploads/demo_videos/{clean_fname}"
            video_entry = {
                "id": f"vid_{int(time.time())}",
                "title": title,
                "filename": file.filename,
                "file_path": rel_path,
                "file_id": None
            }

            config = load_config()
            demo_videos = config.get("demo_videos", [])
            demo_videos.append(video_entry)
            config["demo_videos"] = demo_videos
            save_config(config)

            return redirect(url_for('dashboard', msg="Demo Video File uploaded successfully!"))
        except Exception as e:
            print(f"[ERROR] Failed uploading video file: {e}")
            return redirect(url_for('dashboard', err=f"Video upload error: {e}"))

    # Option 2: Video URL Link
    elif video_url:
        if not title:
            title = "🎬 Demo Video Link"
        config = load_config()
        demo_videos = config.get("demo_videos", [])
        entry = f"{title}\n{video_url}"
        demo_videos.append(entry)
        config["demo_videos"] = demo_videos
        save_config(config)
        return redirect(url_for('dashboard', msg="Demo Video Link added successfully!"))

    return redirect(url_for('dashboard', err="Kripya ek Video File select karein ya Video Link enter karein."))

@flask_app.route('/delete_demo_video', methods=['POST'])
def web_delete_demo_video():
    if not session.get('admin_logged_in'):
        return redirect(url_for('login'))

    try:
        index = int(request.form.get('video_index', -1))
        config = load_config()
        demo_videos = config.get("demo_videos", [])
        if 0 <= index < len(demo_videos):
            removed = demo_videos.pop(index)
            # Remove local file if exists
            if isinstance(removed, dict) and removed.get("file_path"):
                local_file = BASE_DIR / removed["file_path"]
                if local_file.exists():
                    try:
                        local_file.unlink()
                    except Exception as fe:
                        print(f"[WARNING] Could not delete local video file: {fe}")
            config["demo_videos"] = demo_videos
            save_config(config)
            return redirect(url_for('dashboard', msg="Demo video file deleted!"))
    except Exception as e:
        print(f"[ERROR] Deleting demo video failed: {e}")

    return redirect(url_for('dashboard', err="Could not delete demo video."))

def run_flask_server():
    print(f"🌐 [WEB DASHBOARD] Starting Admin Web Panel on http://0.0.0.0:{PORT}")
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

# --- MAIN APPLICATION ENTRY POINT ---

async def main():
    global bot_app, loop
    loop = asyncio.get_running_loop()

    if not BOT_TOKEN:
        print("\n❌ [ERROR] BOT_TOKEN environment variable is missing!")
        print("Kripya `.env` file me apna Telegram Bot Token set karein.")
        sys.exit(1)

    print("🤖 [BOT ENGINE] Initializing python-telegram-bot...")
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Conversation Handler for payment verification
    payment_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(payment_done_clicked, pattern=r"^paid_")],
        states={
            WAITING_UTR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_utr)],
            WAITING_SCREENSHOT: [MessageHandler(filters.PHOTO, receive_screenshot)]
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)]
    )

    # Register Bot Handlers
    bot_app.add_handler(CommandHandler("start", start_handler))
    bot_app.add_handler(CallbackQueryHandler(plan_selected_callback, pattern=r"^select_plan_"))
    bot_app.add_handler(CallbackQueryHandler(back_to_plans_callback, pattern=r"^back_to_plans$"))
    bot_app.add_handler(payment_conv_handler)
    bot_app.add_handler(CallbackQueryHandler(admin_decision_callback, pattern=r"^tg_(approve|reject)_"))

    # Admin Bot Commands
    bot_app.add_handler(CommandHandler("setupi", set_upi_cmd))
    bot_app.add_handler(CommandHandler("setmessage", set_message_cmd))
    bot_app.add_handler(CommandHandler("setplan", set_plan_cmd))
    bot_app.add_handler(CommandHandler("botconfig", bot_config_cmd))
    bot_app.add_handler(CommandHandler("setadmin", set_admin_cmd))
    bot_app.add_handler(CommandHandler("setcourse", set_course_cmd))
    bot_app.add_handler(CommandHandler("setmerchant", set_merchant_cmd))

    # Start Flask Web Dashboard in a daemon thread
    flask_thread = threading.Thread(target=run_flask_server, daemon=True)
    flask_thread.start()

    print("🚀 [READY] Telegram Bot & Web Admin Panel are running concurrently!")
    print(f"👉 Web Panel URL: http://localhost:{PORT}")
    
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    # Keep running loop active
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        await bot_app.updater.stop()
        await bot_app.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n👋 Bot shut down cleanly.")
