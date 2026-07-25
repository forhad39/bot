import sqlite3
import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# 1. DATABASE SETUP
# ==========================================
def init_db():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()

    # Target channels table
    c.execute('''CREATE TABLE IF NOT EXISTS channels
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  added_at TEXT)''')

    # Source channels table (to monitor & auto-forward)
    c.execute('''CREATE TABLE IF NOT EXISTS source_channels
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  added_at TEXT)''')

    # Scheduled posts table
    c.execute('''CREATE TABLE IF NOT EXISTS scheduled_posts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  message TEXT,
                  media_file_id TEXT,
                  media_type TEXT,
                  schedule_time TEXT,
                  sent INTEGER DEFAULT 0)''')

    conn.commit()
    conn.close()

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
    channels = [row[0] for row in c.fetchall()]
    conn.close()
    return channels

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
    sources = [row[0] for row in c.fetchall()]
    conn.close()
    return sources

def add_scheduled_post(message, media_file_id, media_type, schedule_time):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute(
        "INSERT INTO scheduled_posts (message, media_file_id, media_type, schedule_time) VALUES (?, ?, ?, ?)",
        (message, media_file_id, media_type, schedule_time)
    )
    conn.commit()
    conn.close()

def get_pending_scheduled():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    c.execute(
        "SELECT id, message, media_file_id, media_type FROM scheduled_posts WHERE schedule_time <= ? AND sent = 0",
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
async def broadcast(bot, channels, text=None, media_file_id=None, media_type=None):
    results = {"success": 0, "fail": 0}
    for channel in channels:
        try:
            if media_file_id and media_type == "photo":
                await bot.send_photo(chat_id=channel, photo=media_file_id, caption=text)
            elif media_file_id and media_type == "video":
                await bot.send_video(chat_id=channel, video=media_file_id, caption=text)
            elif media_file_id and media_type == "document":
                await bot.send_document(chat_id=channel, document=media_file_id, caption=text)
            elif media_file_id and media_type == "audio":
                await bot.send_audio(chat_id=channel, audio=media_file_id, caption=text)
            elif media_file_id and media_type == "animation":
                await bot.send_animation(chat_id=channel, animation=media_file_id, caption=text)
            elif text:
                await bot.send_message(chat_id=channel, text=text)
            results["success"] += 1
            await asyncio.sleep(0.3)  # Avoid flood limits
        except Exception as e:
            logger.error(f"Failed to send to {channel}: {e}")
            results["fail"] += 1
    return results

# ==========================================
# 3. AUTO-FORWARD FROM SOURCE CHANNEL
# ==========================================
async def auto_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-forward any message from source channels to all target channels."""
    if not update.channel_post:
        return

    chat_username = f"@{update.channel_post.chat.username}" if update.channel_post.chat.username else None
    sources = get_sources()

    if chat_username not in sources:
        return

    channels = get_channels()
    if not channels:
        return

    msg = update.channel_post
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

    results = await broadcast(context.bot, channels, text, media_file_id, media_type)
    logger.info(f"Auto-forward from {chat_username}: ✅{results['success']} ❌{results['fail']}")

# ==========================================
# 4. SCHEDULED POST CHECKER
# ==========================================
async def check_scheduled(context: ContextTypes.DEFAULT_TYPE):
    posts = get_pending_scheduled()
    if not posts:
        return

    channels = get_channels()
    for post in posts:
        post_id, message, media_file_id, media_type = post
        await broadcast(context.bot, channels, message, media_file_id, media_type)
        mark_scheduled_sent(post_id)
        logger.info(f"Scheduled post {post_id} sent to {len(channels)} channels.")

# ==========================================
# 5. BOT COMMAND HANDLERS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📋 Channel List", callback_data="list"),
         InlineKeyboardButton("📡 Source List", callback_data="sources")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 *Telegram Broadcast Bot*\n\n"
        "✅ Auto-forward from source channel\n"
        "✅ Text, Photo, Video, File, Audio support\n"
        "✅ Schedule posts\n"
        "✅ Add/Remove target channels\n\n"
        "Use /help to see all commands.",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Command List:*\n\n"
        "*Target Channels:*\n"
        "/addchannel @username — Add target channel\n"
        "/removechannel @username — Remove channel\n"
        "/listchannels — Show all target channels\n\n"
        "*Source Channels (Auto-forward):*\n"
        "/addsource @username — Add source channel\n"
        "/listsources — Show source channels\n\n"
        "*Broadcasting:*\n"
        "/post Your message — Send text to all\n"
        "Reply to a media + /post — Send media to all\n\n"
        "*Scheduling:*\n"
        "/schedule YYYY-MM-DD HH:MM Your message\n"
        "Example: /schedule 2025-08-01 09:00 Good morning!"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addchannel @channelname")
        return
    channel = context.args[0]
    if not channel.startswith("@"):
        channel = "@" + channel
    if add_channel_db(channel):
        await update.message.reply_text(f"✅ *{channel}* added as target channel.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ *{channel}* already exists.", parse_mode="Markdown")

async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /removechannel @channelname")
        return
    channel = context.args[0]
    if not channel.startswith("@"):
        channel = "@" + channel
    if remove_channel_db(channel):
        await update.message.reply_text(f"🗑️ *{channel}* removed.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ *{channel}* not found.", parse_mode="Markdown")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channels = get_channels()
    if channels:
        text = "📋 *Target Channels:*\n" + "\n".join(f"• {c}" for c in channels)
    else:
        text = "No target channels added yet.\nUse /addchannel @name"
    await update.message.reply_text(text, parse_mode="Markdown")

async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addsource @channelname")
        return
    channel = context.args[0]
    if not channel.startswith("@"):
        channel = "@" + channel
    if add_source_db(channel):
        await update.message.reply_text(
            f"📡 *{channel}* added as source channel.\n"
            f"All new posts will be auto-forwarded to target channels.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"⚠️ *{channel}* already a source.", parse_mode="Markdown")

async def list_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sources = get_sources()
    if sources:
        text = "📡 *Source Channels (Auto-forward):*\n" + "\n".join(f"• {s}" for s in sources)
    else:
        text = "No source channels added yet.\nUse /addsource @name"
    await update.message.reply_text(text, parse_mode="Markdown")

async def post_to_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channels = get_channels()
    if not channels:
        await update.message.reply_text("No channels! Add with /addchannel @name")
        return

    text = " ".join(context.args) if context.args else ""
    media_file_id = None
    media_type = None

    # If replying to a media message
    reply = update.message.reply_to_message
    if reply:
        if reply.photo:
            media_file_id = reply.photo[-1].file_id
            media_type = "photo"
        elif reply.video:
            media_file_id = reply.video.file_id
            media_type = "video"
        elif reply.document:
            media_file_id = reply.document.file_id
            media_type = "document"
        elif reply.audio:
            media_file_id = reply.audio.file_id
            media_type = "audio"
        elif reply.animation:
            media_file_id = reply.animation.file_id
            media_type = "animation"
        if not text and reply.caption:
            text = reply.caption

    if not text and not media_file_id:
        await update.message.reply_text("Please provide a message or reply to a media.\nExample: /post Hello World")
        return

    await update.message.reply_text(f"📤 Broadcasting to {len(channels)} channels...")
    results = await broadcast(context.bot, channels, text, media_file_id, media_type)
    await update.message.reply_text(
        f"✅ Sent: {results['success']}\n❌ Failed: {results['fail']}"
    )

async def schedule_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /schedule 2025-08-01 09:00 Your message"""
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /schedule YYYY-MM-DD HH:MM Your message\n"
            "Example: /schedule 2025-08-01 09:00 Good morning!"
        )
        return

    date_str = context.args[0]
    time_str = context.args[1]
    message = " ".join(context.args[2:])
    schedule_time = f"{date_str} {time_str}"

    try:
        datetime.strptime(schedule_time, "%Y-%m-%d %H:%M")
    except ValueError:
        await update.message.reply_text("❌ Invalid format. Use: YYYY-MM-DD HH:MM")
        return

    add_scheduled_post(message, None, None, schedule_time)
    await update.message.reply_text(
        f"⏰ *Scheduled!*\n📅 Time: `{schedule_time}`\n💬 Message: {message}",
        parse_mode="Markdown"
    )

# Inline button handler
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "list":
        channels = get_channels()
        text = "📋 *Target Channels:*\n" + ("\n".join(f"• {c}" for c in channels) if channels else "None added yet.")
    elif query.data == "sources":
        sources = get_sources()
        text = "📡 *Source Channels:*\n" + ("\n".join(f"• {s}" for s in sources) if sources else "None added yet.")
    elif query.data == "help":
        text = (
            "📖 *Commands:*\n"
            "/addchannel @name — Add target\n"
            "/removechannel @name — Remove target\n"
            "/addsource @name — Add source (auto-forward)\n"
            "/post message — Broadcast now\n"
            "/schedule DATE TIME message — Schedule post"
        )
    else:
        text = "Unknown action."

    await query.edit_message_text(text, parse_mode="Markdown")

# ==========================================
# 6. MAIN EXECUTION
# ==========================================
if __name__ == '__main__':
    init_db()

    # ✅ Replace with your actual Bot Token from BotFather
    BOT_TOKEN = "8956561820:AAEBsYWuucvkhiUkq9SkWyg72ud17T53ATQ"

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("addchannel", add_channel))
    application.add_handler(CommandHandler("removechannel", remove_channel))
    application.add_handler(CommandHandler("listchannels", list_channels))
    application.add_handler(CommandHandler("addsource", add_source))
    application.add_handler(CommandHandler("listsources", list_sources))
    application.add_handler(CommandHandler("post", post_to_all))
    application.add_handler(CommandHandler("schedule", schedule_post))

    # Auto-forward: listens to channel posts
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL, auto_forward))

    # Inline button handler
    application.add_handler(CallbackQueryHandler(button_handler))

    # Scheduled post checker — runs every 60 seconds
    job_queue = application.job_queue
    job_queue.run_repeating(check_scheduled, interval=60, first=10)

    print("🤖 Bot is running with full features...")
    print("✅ Auto-forward | ✅ Media support | ✅ Scheduler | ✅ Add/Remove channels")
    application.run_polling()
