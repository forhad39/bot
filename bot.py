import sqlite3
import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters, ConversationHandler
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
WAITING_CHANNEL = 1
WAITING_GROUP = 2
WAITING_POST_TARGET = 3

# ==========================================
# 1. DATABASE SETUP
# ==========================================
def init_db():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS channels
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  type TEXT DEFAULT 'channel',
                  added_at TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS groups
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  added_at TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS source_channels
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  added_at TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS scheduled_posts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  message TEXT,
                  media_file_id TEXT,
                  media_type TEXT,
                  schedule_time TEXT,
                  target TEXT DEFAULT 'all',
                  sent INTEGER DEFAULT 0)''')

    conn.commit()
    conn.close()

# --- Channel DB ---
def add_channel_db(username):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO channels (username, added_at) VALUES (?, ?)",
                  (username, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remove_channel_db(username):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute("DELETE FROM channels WHERE username=?", (username,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_channels():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute("SELECT username FROM channels")
    result = [row[0] for row in c.fetchall()]
    conn.close()
    return result

# --- Group DB ---
def add_group_db(username):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO groups (username, added_at) VALUES (?, ?)",
                  (username, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remove_group_db(username):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute("DELETE FROM groups WHERE username=?", (username,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_groups():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute("SELECT username FROM groups")
    result = [row[0] for row in c.fetchall()]
    conn.close()
    return result

# --- Source DB ---
def add_source_db(username):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO source_channels (username, added_at) VALUES (?, ?)",
                  (username, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_sources():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute("SELECT username FROM source_channels")
    result = [row[0] for row in c.fetchall()]
    conn.close()
    return result

# --- Scheduled ---
def add_scheduled_post(message, media_file_id, media_type, schedule_time, target='all'):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute(
        "INSERT INTO scheduled_posts (message, media_file_id, media_type, schedule_time, target) VALUES (?, ?, ?, ?, ?)",
        (message, media_file_id, media_type, schedule_time, target)
    )
    conn.commit()
    conn.close()

def get_pending_scheduled():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    c.execute(
        "SELECT id, message, media_file_id, media_type, target FROM scheduled_posts WHERE schedule_time <= ? AND sent=0",
        (now,)
    )
    posts = c.fetchall()
    conn.close()
    return posts

def mark_scheduled_sent(post_id):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute("UPDATE scheduled_posts SET sent=1 WHERE id=?", (post_id,))
    conn.commit()
    conn.close()

# ==========================================
# 2. BROADCAST HELPER
# ==========================================
async def broadcast(bot, targets, text=None, media_file_id=None, media_type=None):
    results = {"success": 0, "fail": 0}
    for target in targets:
        try:
            if media_file_id and media_type == "photo":
                await bot.send_photo(chat_id=target, photo=media_file_id, caption=text)
            elif media_file_id and media_type == "video":
                await bot.send_video(chat_id=target, video=media_file_id, caption=text)
            elif media_file_id and media_type == "document":
                await bot.send_document(chat_id=target, document=media_file_id, caption=text)
            elif media_file_id and media_type == "audio":
                await bot.send_audio(chat_id=target, audio=media_file_id, caption=text)
            elif media_file_id and media_type == "animation":
                await bot.send_animation(chat_id=target, animation=media_file_id, caption=text)
            elif text:
                await bot.send_message(chat_id=target, text=text)
            results["success"] += 1
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Failed to send to {target}: {e}")
            results["fail"] += 1
    return results

# ==========================================
# 3. MAIN MENU
# ==========================================
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📺 চ্যানেল ম্যানেজ", callback_data="menu_channels"),
         InlineKeyboardButton("👥 গ্রুপ ম্যানেজ", callback_data="menu_groups")],
        [InlineKeyboardButton("📡 সোর্স চ্যানেল", callback_data="menu_sources"),
         InlineKeyboardButton("📤 পোস্ট করুন", callback_data="menu_post")],
        [InlineKeyboardButton("⏰ শিডিউল পোস্ট", callback_data="menu_schedule"),
         InlineKeyboardButton("ℹ️ হেল্প", callback_data="menu_help")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Broadcast Bot*\n\nনিচের মেনু থেকে যা করতে চান বেছে নিন:",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )

# ==========================================
# 4. CHANNEL MANAGEMENT MENU
# ==========================================
def channel_manage_keyboard():
    channels = get_channels()
    keyboard = []
    for ch in channels:
        keyboard.append([
            InlineKeyboardButton(f"📺 {ch}", callback_data=f"ch_info_{ch}"),
            InlineKeyboardButton("🗑️ Delete", callback_data=f"ch_del_{ch}")
        ])
    keyboard.append([InlineKeyboardButton("➕ নতুন চ্যানেল যোগ করুন", callback_data="ch_add")])
    keyboard.append([InlineKeyboardButton("🔙 মেনুতে ফিরুন", callback_data="back_main")])
    return InlineKeyboardMarkup(keyboard)

def group_manage_keyboard():
    groups = get_groups()
    keyboard = []
    for g in groups:
        keyboard.append([
            InlineKeyboardButton(f"👥 {g}", callback_data=f"gr_info_{g}"),
            InlineKeyboardButton("🗑️ Delete", callback_data=f"gr_del_{g}")
        ])
    keyboard.append([InlineKeyboardButton("➕ নতুন গ্রুপ যোগ করুন", callback_data="gr_add")])
    keyboard.append([InlineKeyboardButton("🔙 মেনুতে ফিরুন", callback_data="back_main")])
    return InlineKeyboardMarkup(keyboard)

def post_target_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📺 শুধু চ্যানেলে", callback_data="post_channels"),
         InlineKeyboardButton("👥 শুধু গ্রুপে", callback_data="post_groups")],
        [InlineKeyboardButton("🌐 সব জায়গায় (চ্যানেল+গ্রুপ)", callback_data="post_all")],
        [InlineKeyboardButton("🔙 মেনুতে ফিরুন", callback_data="back_main")]
    ])

# ==========================================
# 5. CALLBACK HANDLER (Main Router)
# ==========================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # --- Main Menu ---
    if data == "back_main":
        await query.edit_message_text(
            "🤖 *Broadcast Bot*\n\nনিচের মেনু থেকে যা করতে চান বেছে নিন:",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )

    # --- Channel Menu ---
    elif data == "menu_channels":
        channels = get_channels()
        count = len(channels)
        await query.edit_message_text(
            f"📺 *চ্যানেল ম্যানেজমেন্ট*\nমোট চ্যানেল: {count}টি\n\nচ্যানেল বেছে নিন বা নতুন যোগ করুন:",
            parse_mode="Markdown",
            reply_markup=channel_manage_keyboard()
        )

    elif data == "ch_add":
        context.user_data['action'] = 'add_channel'
        await query.edit_message_text(
            "📺 নতুন চ্যানেলের username লিখুন:\nউদাহরণ: @mychannel\n\nবাতিল করতে /cancel লিখুন",
        )

    elif data.startswith("ch_del_"):
        ch = data[7:]
        remove_channel_db(ch)
        channels = get_channels()
        await query.edit_message_text(
            f"🗑️ *{ch}* মুছে ফেলা হয়েছে!\nবাকি চ্যানেল: {len(channels)}টি",
            parse_mode="Markdown",
            reply_markup=channel_manage_keyboard()
        )

    # --- Group Menu ---
    elif data == "menu_groups":
        groups = get_groups()
        count = len(groups)
        await query.edit_message_text(
            f"👥 *গ্রুপ ম্যানেজমেন্ট*\nমোট গ্রুপ: {count}টি\n\nগ্রুপ বেছে নিন বা নতুন যোগ করুন:",
            parse_mode="Markdown",
            reply_markup=group_manage_keyboard()
        )

    elif data == "gr_add":
        context.user_data['action'] = 'add_group'
        await query.edit_message_text(
            "👥 নতুন গ্রুপের username লিখুন:\nউদাহরণ: @mygroup\n\nবাতিল করতে /cancel লিখুন",
        )

    elif data.startswith("gr_del_"):
        gr = data[7:]
        remove_group_db(gr)
        groups = get_groups()
        await query.edit_message_text(
            f"🗑️ *{gr}* মুছে ফেলা হয়েছে!\nবাকি গ্রুপ: {len(groups)}টি",
            parse_mode="Markdown",
            reply_markup=group_manage_keyboard()
        )

    # --- Source Menu ---
    elif data == "menu_sources":
        sources = get_sources()
        text = "📡 *সোর্স চ্যানেল (অটো-ফরওয়ার্ড)*\n\n"
        if sources:
            text += "\n".join(f"• {s}" for s in sources)
        else:
            text += "কোনো সোর্স নেই।"
        text += "\n\nনতুন যোগ করতে: /addsource @channelname"
        await query.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরুন", callback_data="back_main")]]))

    # --- Post Menu ---
    elif data == "menu_post":
        await query.edit_message_text(
            "📤 *কোথায় পোস্ট করবেন?*",
            parse_mode="Markdown",
            reply_markup=post_target_keyboard()
        )

    elif data in ("post_channels", "post_groups", "post_all"):
        context.user_data['post_target'] = data
        label = {"post_channels": "চ্যানেলে", "post_groups": "গ্রুপে", "post_all": "সব জায়গায়"}[data]
        context.user_data['action'] = 'post_message'
        await query.edit_message_text(
            f"✍️ *{label}* পোস্ট করতে মেসেজ লিখুন:\n(টেক্সট, ছবি, ভিডিও, ফাইল — সব পাঠাতে পারবেন)\n\nবাতিল করতে /cancel",
            parse_mode="Markdown"
        )

    # --- Schedule Menu ---
    elif data == "menu_schedule":
        await query.edit_message_text(
            "⏰ *শিডিউল পোস্ট*\n\nকমান্ড:\n`/schedule YYYY-MM-DD HH:MM আপনার মেসেজ`\n\nউদাহরণ:\n`/schedule 2025-08-01 09:00 সুপ্রভাত!`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরুন", callback_data="back_main")]]))

    # --- Help ---
    elif data == "menu_help":
        text = (
            "📖 *সব কমান্ড:*\n\n"
            "*/start* — মেনু দেখুন\n"
            "*/addsource @name* — সোর্স চ্যানেল যোগ\n"
            "*/addchannel @name* — টার্গেট চ্যানেল যোগ\n"
            "*/addgroup @name* — গ্রুপ যোগ\n"
            "*/post message* — সব চ্যানেল+গ্রুপে পোস্ট\n"
            "*/postc message* — শুধু চ্যানেলে পোস্ট\n"
            "*/postg message* — শুধু গ্রুপে পোস্ট\n"
            "*/schedule DATE TIME msg* — শিডিউল পোস্ট\n"
        )
        await query.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরুন", callback_data="back_main")]]))

# ==========================================
# 6. MESSAGE HANDLER (for add channel/group/post via button flow)
# ==========================================
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get('action')

    if action == 'add_channel':
        username = update.message.text.strip()
        if not username.startswith("@"):
            username = "@" + username
        if add_channel_db(username):
            await update.message.reply_text(
                f"✅ *{username}* চ্যানেল যোগ হয়েছে!",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                f"⚠️ *{username}* আগে থেকেই আছে।",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        context.user_data['action'] = None

    elif action == 'add_group':
        username = update.message.text.strip()
        if not username.startswith("@"):
            username = "@" + username
        if add_group_db(username):
            await update.message.reply_text(
                f"✅ *{username}* গ্রুপ যোগ হয়েছে!",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                f"⚠️ *{username}* আগে থেকেই আছে।",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        context.user_data['action'] = None

    elif action == 'post_message':
        post_target = context.user_data.get('post_target', 'post_all')
        msg = update.message
        text = msg.text or msg.caption or ""
        media_file_id = None
        media_type = None

        if msg.photo:
            media_file_id = msg.photo[-1].file_id
            media_type = "photo"
        elif msg.video:
            media_file_id = msg.video.file_id
            media_type = "video"
        elif msg.document:
            media_file_id = msg.document.file_id
            media_type = "document"
        elif msg.audio:
            media_file_id = msg.audio.file_id
            media_type = "audio"
        elif msg.animation:
            media_file_id = msg.animation.file_id
            media_type = "animation"

        targets = []
        if post_target in ("post_channels", "post_all"):
            targets += get_channels()
        if post_target in ("post_groups", "post_all"):
            targets += get_groups()

        if not targets:
            await update.message.reply_text("❌ কোনো টার্গেট নেই! আগে চ্যানেল/গ্রুপ যোগ করুন।",
                reply_markup=main_menu_keyboard())
            context.user_data['action'] = None
            return

        status = await update.message.reply_text(f"📤 {len(targets)}টি জায়গায় পাঠানো হচ্ছে...")
        results = await broadcast(update.get_bot(), targets, text, media_file_id, media_type)
        await status.edit_text(
            f"✅ সফল: {results['success']}\n❌ ব্যর্থ: {results['fail']}",
            reply_markup=main_menu_keyboard()
        )
        context.user_data['action'] = None

# ==========================================
# 7. COMMAND-BASED POST (Quick commands)
# ==========================================
async def post_all_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send to all channels + groups"""
    await _send_message(update, context, get_channels() + get_groups())

async def post_channels_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send to channels only"""
    await _send_message(update, context, get_channels())

async def post_groups_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send to groups only"""
    await _send_message(update, context, get_groups())

async def _send_message(update, context, targets):
    if not targets:
        await update.message.reply_text("❌ কোনো টার্গেট নেই!")
        return

    text = " ".join(context.args) if context.args else ""
    media_file_id, media_type = None, None

    reply = update.message.reply_to_message
    if reply:
        if reply.photo:
            media_file_id, media_type = reply.photo[-1].file_id, "photo"
        elif reply.video:
            media_file_id, media_type = reply.video.file_id, "video"
        elif reply.document:
            media_file_id, media_type = reply.document.file_id, "document"
        elif reply.audio:
            media_file_id, media_type = reply.audio.file_id, "audio"
        elif reply.animation:
            media_file_id, media_type = reply.animation.file_id, "animation"
        if not text and reply.caption:
            text = reply.caption

    if not text and not media_file_id:
        await update.message.reply_text("মেসেজ লিখুন বা মিডিয়া reply করুন।")
        return

    await update.message.reply_text(f"📤 {len(targets)}টি জায়গায় পাঠানো হচ্ছে...")
    results = await broadcast(context.bot, targets, text, media_file_id, media_type)
    await update.message.reply_text(f"✅ সফল: {results['success']}\n❌ ব্যর্থ: {results['fail']}")

# ==========================================
# 8. ADD COMMANDS
# ==========================================
async def add_channel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addchannel @name")
        return
    ch = context.args[0] if context.args[0].startswith("@") else "@" + context.args[0]
    if add_channel_db(ch):
        await update.message.reply_text(f"✅ *{ch}* চ্যানেল যোগ হয়েছে!", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ আগে থেকেই আছে।")

async def add_group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addgroup @name")
        return
    gr = context.args[0] if context.args[0].startswith("@") else "@" + context.args[0]
    if add_group_db(gr):
        await update.message.reply_text(f"✅ *{gr}* গ্রুপ যোগ হয়েছে!", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ আগে থেকেই আছে।")

async def add_source_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addsource @name")
        return
    ch = context.args[0] if context.args[0].startswith("@") else "@" + context.args[0]
    if add_source_db(ch):
        await update.message.reply_text(f"✅ *{ch}* সোর্স চ্যানেল যোগ হয়েছে!\nসব নতুন পোস্ট অটো ফরওয়ার্ড হবে।", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ আগে থেকেই আছে।")

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['action'] = None
    await update.message.reply_text("❌ বাতিল করা হয়েছে।", reply_markup=main_menu_keyboard())

# ==========================================
# 9. AUTO-FORWARD
# ==========================================
async def auto_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.channel_post:
        return
    chat_username = f"@{update.channel_post.chat.username}" if update.channel_post.chat.username else None
    if chat_username not in get_sources():
        return

    targets = get_channels() + get_groups()
    if not targets:
        return

    msg = update.channel_post
    text = msg.text or msg.caption or ""
    media_file_id, media_type = None, None

    if msg.photo:
        media_file_id, media_type = msg.photo[-1].file_id, "photo"
    elif msg.video:
        media_file_id, media_type = msg.video.file_id, "video"
    elif msg.document:
        media_file_id, media_type = msg.document.file_id, "document"
    elif msg.audio:
        media_file_id, media_type = msg.audio.file_id, "audio"
    elif msg.animation:
        media_file_id, media_type = msg.animation.file_id, "animation"

    results = await broadcast(context.bot, targets, text, media_file_id, media_type)
    logger.info(f"Auto-forward from {chat_username}: ✅{results['success']} ❌{results['fail']}")

# ==========================================
# 10. SCHEDULE
# ==========================================
async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /schedule YYYY-MM-DD HH:MM মেসেজ\nউদাহরণ: /schedule 2025-08-01 09:00 সুপ্রভাত!"
        )
        return
    date_str, time_str = context.args[0], context.args[1]
    message = " ".join(context.args[2:])
    schedule_time = f"{date_str} {time_str}"
    try:
        datetime.strptime(schedule_time, "%Y-%m-%d %H:%M")
    except ValueError:
        await update.message.reply_text("❌ ভুল ফরম্যাট। YYYY-MM-DD HH:MM ব্যবহার করুন।")
        return
    add_scheduled_post(message, None, None, schedule_time)
    await update.message.reply_text(
        f"⏰ *শিডিউল হয়েছে!*\n📅 সময়: `{schedule_time}`\n💬 মেসেজ: {message}",
        parse_mode="Markdown"
    )

async def check_scheduled(context: ContextTypes.DEFAULT_TYPE):
    posts = get_pending_scheduled()
    for post in posts:
        post_id, message, media_file_id, media_type, target = post
        targets = []
        if target in ("channels", "all"):
            targets += get_channels()
        if target in ("groups", "all"):
            targets += get_groups()
        if not targets:
            targets = get_channels() + get_groups()
        await broadcast(context.bot, targets, message, media_file_id, media_type)
        mark_scheduled_sent(post_id)
        logger.info(f"Scheduled post {post_id} sent.")

# ==========================================
# 11. MAIN
# ==========================================
if __name__ == '__main__':
    init_db()

    # ✅ এখানে আপনার BotFather টোকেন বসান
    BOT_TOKEN = "8956561820:AAEBsYWuucvkhiUkq9SkWyg72ud17T53ATQ"

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel_cmd))
    application.add_handler(CommandHandler("addchannel", add_channel_cmd))
    application.add_handler(CommandHandler("addgroup", add_group_cmd))
    application.add_handler(CommandHandler("addsource", add_source_cmd))
    application.add_handler(CommandHandler("post", post_all_cmd))
    application.add_handler(CommandHandler("postc", post_channels_cmd))
    application.add_handler(CommandHandler("postg", post_groups_cmd))
    application.add_handler(CommandHandler("schedule", schedule_cmd))

    # Button handler
    application.add_handler(CallbackQueryHandler(button_handler))

    # Text/Media input handler (for button-flow add channel/group/post)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND | filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.ANIMATION,
        handle_text_input
    ))

    # Auto-forward from source channel
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL, auto_forward))

    # Scheduled checker
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(check_scheduled, interval=60, first=10)
    else:
        logger.warning("JobQueue not available. Install: pip install 'python-telegram-bot[job-queue]'")

    print("🤖 Bot চালু হয়েছে!")
    print("✅ বাটন মেনু | ✅ চ্যানেল+গ্রুপ | ✅ অটো-ফরওয়ার্ড | ✅ শিডিউল")
    application.run_polling()
