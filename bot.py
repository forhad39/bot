import sqlite3
import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters
)
from telegram.error import TelegramError

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# ADMIN CONFIG
# ==========================================
ADMIN_ID = 6678848886  # শুধু এই ID বট কন্ট্রোল করতে পারবে

def is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update):
            await update.message.reply_text(
                "❌  *A C C E S S   D E N I E D*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n🚫  Unauthorized!",
                parse_mode="Markdown"
            )
            return
        return await func(update, context)
    return wrapper

# ==========================================
# DATABASE SETUP
# ==========================================
def init_db():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS channels
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  chat_id TEXT UNIQUE,
                  title TEXT,
                  added_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS groups
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  chat_id TEXT UNIQUE,
                  title TEXT,
                  added_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS source_channels
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  chat_id TEXT UNIQUE,
                  title TEXT,
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

# --- Channels ---
def add_channel_db(chat_id, title=""):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO channels (chat_id, title, added_at) VALUES (?, ?, ?)",
                  (str(chat_id), title, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remove_channel_db(chat_id):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute("DELETE FROM channels WHERE chat_id=?", (str(chat_id),))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_channels():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute("SELECT chat_id, title FROM channels")
    result = c.fetchall()
    conn.close()
    return result

# --- Groups ---
def add_group_db(chat_id, title=""):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO groups (chat_id, title, added_at) VALUES (?, ?, ?)",
                  (str(chat_id), title, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remove_group_db(chat_id):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute("DELETE FROM groups WHERE chat_id=?", (str(chat_id),))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_groups():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute("SELECT chat_id, title FROM groups")
    result = c.fetchall()
    conn.close()
    return result

# --- Sources ---
def add_source_db(chat_id, title=""):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO source_channels (chat_id, title, added_at) VALUES (?, ?, ?)",
                  (str(chat_id), title, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_sources():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute("SELECT chat_id, title FROM source_channels")
    result = c.fetchall()
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
# BROADCAST HELPER
# ==========================================
async def broadcast(bot, targets, text=None, media_file_id=None, media_type=None):
    results = {"success": 0, "fail": 0}
    for chat_id in targets:
        try:
            if media_file_id and media_type == "photo":
                await bot.send_photo(chat_id=chat_id, photo=media_file_id, caption=text)
            elif media_file_id and media_type == "video":
                await bot.send_video(chat_id=chat_id, video=media_file_id, caption=text)
            elif media_file_id and media_type == "document":
                await bot.send_document(chat_id=chat_id, document=media_file_id, caption=text)
            elif media_file_id and media_type == "audio":
                await bot.send_audio(chat_id=chat_id, audio=media_file_id, caption=text)
            elif media_file_id and media_type == "animation":
                await bot.send_animation(chat_id=chat_id, animation=media_file_id, caption=text)
            elif text:
                await bot.send_message(chat_id=chat_id, text=text)
            results["success"] += 1
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Failed {chat_id}: {e}")
            results["fail"] += 1
    return results

# ==========================================
# KEYBOARDS
# ==========================================
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("📺  C H A N N E L S", callback_data="menu_channels")],
        [InlineKeyboardButton("👥  G R O U P S", callback_data="menu_groups")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("📡  S O U R C E   C H A N N E L S", callback_data="menu_sources")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("📤  B R O A D C A S T", callback_data="menu_post")],
        [InlineKeyboardButton("⏰  S C H E D U L E   P O S T", callback_data="menu_schedule")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("🛡️  A D M I N   P O W E R S", callback_data="menu_admin")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("📖  H E L P", callback_data="menu_help")],
    ])

def channel_manage_keyboard():
    channels = get_channels()
    keyboard = [[InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")]]
    if channels:
        for chat_id, title in channels:
            label = title if title else chat_id
            keyboard.append([
                InlineKeyboardButton(f"📺  {label}", callback_data="noop"),
                InlineKeyboardButton("🗑  REMOVE", callback_data=f"ch_del_{chat_id}")
            ])
    else:
        keyboard.append([InlineKeyboardButton("❌  No channels added yet", callback_data="noop")])
    keyboard.append([InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")])
    keyboard.append([InlineKeyboardButton("➕  A D D   C H A N N E L", callback_data="ch_add")])
    keyboard.append([InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")])
    keyboard.append([InlineKeyboardButton("🔙  B A C K", callback_data="back_main")])
    return InlineKeyboardMarkup(keyboard)

def group_manage_keyboard():
    groups = get_groups()
    keyboard = [[InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")]]
    if groups:
        for chat_id, title in groups:
            label = title if title else chat_id
            keyboard.append([
                InlineKeyboardButton(f"👥  {label}", callback_data="noop"),
                InlineKeyboardButton("🗑  REMOVE", callback_data=f"gr_del_{chat_id}")
            ])
    else:
        keyboard.append([InlineKeyboardButton("❌  No groups added yet", callback_data="noop")])
    keyboard.append([InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")])
    keyboard.append([InlineKeyboardButton("➕  A D D   G R O U P", callback_data="gr_add")])
    keyboard.append([InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")])
    keyboard.append([InlineKeyboardButton("🔙  B A C K", callback_data="back_main")])
    return InlineKeyboardMarkup(keyboard)

def post_target_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("📺  CHANNELS ONLY", callback_data="post_channels")],
        [InlineKeyboardButton("👥  GROUPS ONLY", callback_data="post_groups")],
        [InlineKeyboardButton("🌐  ALL (CHANNELS + GROUPS)", callback_data="post_all")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("🔙  B A C K", callback_data="back_main")],
    ])

def admin_power_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("🔇  M U T E   U S E R", callback_data="admin_mute"),
         InlineKeyboardButton("🔊  U N M U T E", callback_data="admin_unmute")],
        [InlineKeyboardButton("🚫  B A N   U S E R", callback_data="admin_ban"),
         InlineKeyboardButton("✅  U N B A N", callback_data="admin_unban")],
        [InlineKeyboardButton("👢  K I C K   U S E R", callback_data="admin_kick")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("📌  P I N   M S G", callback_data="admin_pin"),
         InlineKeyboardButton("🗑  D E L   M S G", callback_data="admin_delete")],
        [InlineKeyboardButton("━━━━━━━━━━━━━━━━━━━━", callback_data="noop")],
        [InlineKeyboardButton("🔙  B A C K", callback_data="back_main")],
    ])

def back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙  B A C K   T O   M E N U", callback_data="back_main")]
    ])

# ==========================================
# START
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌  *ACCESS DENIED*\n\n🚫  Unauthorized!", parse_mode="Markdown")
        return
    channels = len(get_channels())
    groups = len(get_groups())
    sources = len(get_sources())
    text = (
        "🤖  *B R O A D C A S T   B O T*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📺  *Channels :*  `{channels}`\n"
        f"👥  *Groups :*  `{groups}`\n"
        f"📡  *Sources :*  `{sources}`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇  *Select an option below*"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

# ==========================================
# GET ID COMMAND — যেকোনো গ্রুপে কাজ করে
# ==========================================
async def getid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    text = (
        "🆔  *C H A T   I N F O*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💬  *Chat Title :*  `{chat.title or 'N/A'}`\n"
        f"🔢  *Chat ID :*  `{chat.id}`\n"
        f"📋  *Chat Type :*  `{chat.type}`\n\n"
        f"👤  *Your ID :*  `{user.id}`\n"
        f"👤  *Your Name :*  `{user.full_name}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ==========================================
# CALLBACK HANDLER
# ==========================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Access Denied!", show_alert=True)
        return

    data = query.data

    if data == "noop":
        return

    elif data == "back_main":
        channels = len(get_channels())
        groups = len(get_groups())
        sources = len(get_sources())
        text = (
            "🤖  *B R O A D C A S T   B O T*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📺  *Channels :*  `{channels}`\n"
            f"👥  *Groups :*  `{groups}`\n"
            f"📡  *Sources :*  `{sources}`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "👇  *Select an option below*"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

    elif data == "menu_channels":
        channels = get_channels()
        text = (
            "📺  *C H A N N E L   M A N A G E R*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔢  *Total Channels :*  `{len(channels)}`\n\n"
            "💡  Channel ID পেতে ওই channel-এ `/getid` পাঠাও\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=channel_manage_keyboard())

    elif data == "ch_add":
        context.user_data['action'] = 'add_channel'
        await query.edit_message_text(
            "📺  *A D D   C H A N N E L*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Channel এর Chat ID টাইপ করো :\n\n"
            "📌  Example :  `-1001234567890`\n\n"
            "💡  ID পেতে channel-এ `/getid` দাও\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "❌  /cancel",
            parse_mode="Markdown"
        )

    elif data.startswith("ch_del_"):
        chat_id = data[7:]
        remove_channel_db(chat_id)
        channels = get_channels()
        await query.edit_message_text(
            f"🗑  *Removed :*  `{chat_id}`\n🔢  *Remaining :*  `{len(channels)}`",
            parse_mode="Markdown", reply_markup=channel_manage_keyboard()
        )

    elif data == "menu_groups":
        groups = get_groups()
        text = (
            "👥  *G R O U P   M A N A G E R*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔢  *Total Groups :*  `{len(groups)}`\n\n"
            "💡  Group ID পেতে ওই group-এ `/getid` পাঠাও\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=group_manage_keyboard())

    elif data == "gr_add":
        context.user_data['action'] = 'add_group'
        await query.edit_message_text(
            "👥  *A D D   G R O U P*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Group এর Chat ID টাইপ করো :\n\n"
            "📌  Example :  `-1001234567890`\n\n"
            "💡  Private group-এও কাজ করে!\n"
            "ID পেতে group-এ `/getid` দাও\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "❌  /cancel",
            parse_mode="Markdown"
        )

    elif data.startswith("gr_del_"):
        chat_id = data[7:]
        remove_group_db(chat_id)
        groups = get_groups()
        await query.edit_message_text(
            f"🗑  *Removed :*  `{chat_id}`\n🔢  *Remaining :*  `{len(groups)}`",
            parse_mode="Markdown", reply_markup=group_manage_keyboard()
        )

    elif data == "menu_sources":
        sources = get_sources()
        text = "📡  *S O U R C E   C H A N N E L S*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        if sources:
            for chat_id, title in sources:
                label = title if title else chat_id
                text += f"  ✅  `{label}` (`{chat_id}`)\n"
        else:
            text += "  ❌  No source channels added yet.\n"
        text += (
            "\n━━━━━━━━━━━━━━━━━━━━━━━\n"
            "➕  To add :  `/addsource CHAT_ID`\n"
            "🗑  To remove :  `/removesource CHAT_ID`"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_keyboard())

    elif data == "menu_post":
        await query.edit_message_text(
            "📤  *B R O A D C A S T*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n📌  কোথায় পাঠাবে?",
            parse_mode="Markdown", reply_markup=post_target_keyboard()
        )

    elif data in ("post_channels", "post_groups", "post_all"):
        context.user_data['post_target'] = data
        context.user_data['action'] = 'post_message'
        label_map = {
            "post_channels": "📺  Channels Only",
            "post_groups": "👥  Groups Only",
            "post_all": "🌐  All"
        }
        await query.edit_message_text(
            f"📤  *Target :*  {label_map[data]}\n\n✏️  Message টাইপ করো বা media পাঠাও\n\n❌  /cancel",
            parse_mode="Markdown"
        )

    elif data == "menu_schedule":
        await query.edit_message_text(
            "⏰  *S C H E D U L E   P O S T*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Format :\n`/schedule YYYY-MM-DD HH:MM message`\n\n"
            "Example :\n`/schedule 2025-08-01 09:00 Good morning!`",
            parse_mode="Markdown", reply_markup=back_keyboard()
        )

    elif data == "menu_admin":
        await query.edit_message_text(
            "🛡️  *A D M I N   P O W E R S*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔇  Mute — কথা বলা বন্ধ\n"
            "🔊  Unmute — কথা বলার অনুমতি ফিরে\n"
            "🚫  Ban — গ্রুপ থেকে বের করে block\n"
            "✅  Unban — Ban তুলে নেওয়া\n"
            "👢  Kick — শুধু বের করে দেওয়া\n"
            "📌  Pin — message পিন করা\n"
            "🗑  Delete — message ডিলিট করা\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️  বটকে group-এ *Admin* করতে হবে!",
            parse_mode="Markdown", reply_markup=admin_power_keyboard()
        )

    elif data in ("admin_mute", "admin_unmute", "admin_ban", "admin_unban",
                  "admin_kick", "admin_pin", "admin_delete"):
        action_map = {
            "admin_mute": ("🔇  M U T E", "admin_mute"),
            "admin_unmute": ("🔊  U N M U T E", "admin_unmute"),
            "admin_ban": ("🚫  B A N", "admin_ban"),
            "admin_unban": ("✅  U N B A N", "admin_unban"),
            "admin_kick": ("👢  K I C K", "admin_kick"),
            "admin_pin": ("📌  P I N   M S G", "admin_pin"),
            "admin_delete": ("🗑  D E L E T E   M S G", "admin_delete"),
        }
        label, act = action_map[data]
        context.user_data['action'] = act
        await query.edit_message_text(
            f"{label}\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Format টাইপ করো :\n`CHAT_ID USER_ID`\n\n"
            "📌  Example :\n`-1001234567890 987654321`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n❌  /cancel",
            parse_mode="Markdown"
        )

    elif data == "menu_help":
        await query.edit_message_text(
            "📖  *C O M M A N D   L I S T*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔹  `/start`  —  Main menu\n"
            "🔹  `/getid`  —  Chat ID দেখো\n\n"
            "📺  *Channel :*\n"
            "  `/addchannel CHAT_ID`\n"
            "  `/removechannel CHAT_ID`\n\n"
            "👥  *Group :*\n"
            "  `/addgroup CHAT_ID`\n"
            "  `/removegroup CHAT_ID`\n\n"
            "📡  *Source :*\n"
            "  `/addsource CHAT_ID`\n"
            "  `/removesource CHAT_ID`\n\n"
            "📤  *Broadcast :*\n"
            "  `/post msg`  —  All\n"
            "  `/postc msg`  —  Channels\n"
            "  `/postg msg`  —  Groups\n\n"
            "⏰  `/schedule DATE TIME msg`\n\n"
            "🛡️  *Admin Powers :*\n"
            "  `/mute CHAT_ID USER_ID`\n"
            "  `/unmute CHAT_ID USER_ID`\n"
            "  `/ban CHAT_ID USER_ID`\n"
            "  `/unban CHAT_ID USER_ID`\n"
            "  `/kick CHAT_ID USER_ID`\n"
            "  `/pin CHAT_ID MSG_ID`\n"
            "  `/delmsg CHAT_ID MSG_ID`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown", reply_markup=back_keyboard()
        )

# ==========================================
# TEXT INPUT HANDLER
# ==========================================
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    action = context.user_data.get('action')

    if action == 'add_channel':
        raw = update.message.text.strip()
        try:
            chat_info = await context.bot.get_chat(raw)
            title = chat_info.title or raw
            chat_id = str(chat_info.id)
            if add_channel_db(chat_id, title):
                text = (
                    "✅  *C H A N N E L   A D D E D*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📺  *Title :*  `{title}`\n"
                    f"🔢  *ID :*  `{chat_id}`\n"
                    f"📊  *Total :*  `{len(get_channels())}`\n\n━━━━━━━━━━━━━━━━━━━━━━━"
                )
            else:
                text = f"⚠️  `{chat_id}` already exists."
        except Exception as e:
            text = f"❌  *Error :*  `{e}`\n\nChat ID সঠিকভাবে দাও।"
        context.user_data['action'] = None
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

    elif action == 'add_group':
        raw = update.message.text.strip()
        try:
            chat_info = await context.bot.get_chat(raw)
            title = chat_info.title or raw
            chat_id = str(chat_info.id)
            if add_group_db(chat_id, title):
                text = (
                    "✅  *G R O U P   A D D E D*\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"👥  *Title :*  `{title}`\n"
                    f"🔢  *ID :*  `{chat_id}`\n"
                    f"📊  *Total :*  `{len(get_groups())}`\n\n━━━━━━━━━━━━━━━━━━━━━━━"
                )
            else:
                text = f"⚠️  `{chat_id}` already exists."
        except Exception as e:
            text = f"❌  *Error :*  `{e}`\n\nChat ID সঠিকভাবে দাও।"
        context.user_data['action'] = None
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())

    elif action == 'post_message':
        post_target = context.user_data.get('post_target', 'post_all')
        msg = update.message
        text = msg.text or msg.caption or ""
        media_file_id, media_type = None, None
        if msg.photo: media_file_id, media_type = msg.photo[-1].file_id, "photo"
        elif msg.video: media_file_id, media_type = msg.video.file_id, "video"
        elif msg.document: media_file_id, media_type = msg.document.file_id, "document"
        elif msg.audio: media_file_id, media_type = msg.audio.file_id, "audio"
        elif msg.animation: media_file_id, media_type = msg.animation.file_id, "animation"

        targets = []
        if post_target in ("post_channels", "post_all"): targets += [r[0] for r in get_channels()]
        if post_target in ("post_groups", "post_all"): targets += [r[0] for r in get_groups()]

        if not targets:
            await update.message.reply_text("❌  No targets! Add channels/groups first.", reply_markup=main_menu_keyboard())
            context.user_data['action'] = None
            return

        st = await update.message.reply_text(
            f"📤  *SENDING...*\n🎯  Targets: `{len(targets)}`", parse_mode="Markdown"
        )
        results = await broadcast(context.bot, targets, text, media_file_id, media_type)
        await st.edit_text(
            f"📤  *DONE*\n✅  Success: `{results['success']}`\n❌  Failed: `{results['fail']}`",
            parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )
        context.user_data['action'] = None

    elif action in ('admin_mute', 'admin_unmute', 'admin_ban', 'admin_unban',
                    'admin_kick', 'admin_pin', 'admin_delete'):
        parts = update.message.text.strip().split()
        if len(parts) < 2:
            await update.message.reply_text("❌  Format: `CHAT_ID USER_ID`", parse_mode="Markdown")
            return
        chat_id, target_id = parts[0], parts[1]
        context.user_data['action'] = None
        try:
            if action == 'admin_mute':
                await context.bot.restrict_chat_member(
                    chat_id=chat_id, user_id=int(target_id),
                    permissions=ChatPermissions(
                        can_send_messages=False, can_send_media_messages=False,
                        can_send_polls=False, can_send_other_messages=False
                    )
                )
                resp = f"🔇  *MUTED*\n\n👤  `{target_id}` in `{chat_id}`"
            elif action == 'admin_unmute':
                await context.bot.restrict_chat_member(
                    chat_id=chat_id, user_id=int(target_id),
                    permissions=ChatPermissions(
                        can_send_messages=True, can_send_media_messages=True,
                        can_send_polls=True, can_send_other_messages=True,
                        can_add_web_page_previews=True
                    )
                )
                resp = f"🔊  *UNMUTED*\n\n👤  `{target_id}` in `{chat_id}`"
            elif action == 'admin_ban':
                await context.bot.ban_chat_member(chat_id=chat_id, user_id=int(target_id))
                resp = f"🚫  *BANNED*\n\n👤  `{target_id}` from `{chat_id}`"
            elif action == 'admin_unban':
                await context.bot.unban_chat_member(chat_id=chat_id, user_id=int(target_id))
                resp = f"✅  *UNBANNED*\n\n👤  `{target_id}` in `{chat_id}`"
            elif action == 'admin_kick':
                await context.bot.ban_chat_member(chat_id=chat_id, user_id=int(target_id))
                await context.bot.unban_chat_member(chat_id=chat_id, user_id=int(target_id))
                resp = f"👢  *KICKED*\n\n👤  `{target_id}` from `{chat_id}`"
            elif action == 'admin_pin':
                await context.bot.pin_chat_message(chat_id=chat_id, message_id=int(target_id))
                resp = f"📌  *PINNED*\n\nMsg `{target_id}` in `{chat_id}`"
            elif action == 'admin_delete':
                await context.bot.delete_message(chat_id=chat_id, message_id=int(target_id))
                resp = f"🗑  *DELETED*\n\nMsg `{target_id}` from `{chat_id}`"

            await update.message.reply_text(
                f"━━━━━━━━━━━━━━━━━━━━━━━\n{resp}\n━━━━━━━━━━━━━━━━━━━━━━━",
                parse_mode="Markdown", reply_markup=admin_power_keyboard()
            )
        except TelegramError as e:
            await update.message.reply_text(
                f"❌  *ERROR :*  `{e}`\n\n⚠️  বটকে ওই group-এ Admin করা আছে?",
                parse_mode="Markdown", reply_markup=admin_power_keyboard()
            )

# ==========================================
# COMMAND HANDLERS
# ==========================================
@admin_only
async def add_channel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addchannel CHAT_ID")
        return
    try:
        chat_info = await context.bot.get_chat(context.args[0])
        title = chat_info.title or context.args[0]
        chat_id = str(chat_info.id)
        if add_channel_db(chat_id, title):
            await update.message.reply_text(f"✅  Added: `{title}` (`{chat_id}`)", parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️  Already exists.")
    except Exception as e:
        await update.message.reply_text(f"❌  `{e}`", parse_mode="Markdown")

@admin_only
async def remove_channel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /removechannel CHAT_ID")
        return
    if remove_channel_db(context.args[0]):
        await update.message.reply_text(f"🗑  Removed: `{context.args[0]}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌  Not found.")

@admin_only
async def add_group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addgroup CHAT_ID")
        return
    try:
        chat_info = await context.bot.get_chat(context.args[0])
        title = chat_info.title or context.args[0]
        chat_id = str(chat_info.id)
        if add_group_db(chat_id, title):
            await update.message.reply_text(f"✅  Added: `{title}` (`{chat_id}`)", parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️  Already exists.")
    except Exception as e:
        await update.message.reply_text(f"❌  `{e}`", parse_mode="Markdown")

@admin_only
async def remove_group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /removegroup CHAT_ID")
        return
    if remove_group_db(context.args[0]):
        await update.message.reply_text(f"🗑  Removed: `{context.args[0]}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌  Not found.")

@admin_only
async def add_source_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addsource CHAT_ID")
        return
    try:
        chat_info = await context.bot.get_chat(context.args[0])
        title = chat_info.title or context.args[0]
        chat_id = str(chat_info.id)
        if add_source_db(chat_id, title):
            await update.message.reply_text(f"✅  Source Added: `{title}` (`{chat_id}`)", parse_mode="Markdown")
        else:
            await update.message.reply_text("⚠️  Already exists.")
    except Exception as e:
        await update.message.reply_text(f"❌  `{e}`", parse_mode="Markdown")

@admin_only
async def remove_source_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /removesource CHAT_ID")
        return
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute("DELETE FROM source_channels WHERE chat_id=?", (context.args[0],))
    affected = c.rowcount
    conn.commit()
    conn.close()
    if affected:
        await update.message.reply_text(f"🗑  Source Removed: `{context.args[0]}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌  Not found.")

@admin_only
async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['action'] = None
    await update.message.reply_text(
        "❌  *CANCELLED*\n━━━━━━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )

@admin_only
async def post_all_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_message(update, context, [r[0] for r in get_channels()] + [r[0] for r in get_groups()])

@admin_only
async def post_channels_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_message(update, context, [r[0] for r in get_channels()])

@admin_only
async def post_groups_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_message(update, context, [r[0] for r in get_groups()])

async def _send_message(update, context, targets):
    if not targets:
        await update.message.reply_text("❌  No targets!")
        return
    text = " ".join(context.args) if context.args else ""
    media_file_id, media_type = None, None
    reply = update.message.reply_to_message
    if reply:
        if reply.photo: media_file_id, media_type = reply.photo[-1].file_id, "photo"
        elif reply.video: media_file_id, media_type = reply.video.file_id, "video"
        elif reply.document: media_file_id, media_type = reply.document.file_id, "document"
        elif reply.audio: media_file_id, media_type = reply.audio.file_id, "audio"
        elif reply.animation: media_file_id, media_type = reply.animation.file_id, "animation"
        if not text and reply.caption: text = reply.caption
    if not text and not media_file_id:
        await update.message.reply_text("Please provide message or reply to media.")
        return
    st = await update.message.reply_text(f"📤  Sending... Targets: `{len(targets)}`", parse_mode="Markdown")
    results = await broadcast(context.bot, targets, text, media_file_id, media_type)
    await st.edit_text(f"✅  Success: `{results['success']}`\n❌  Failed: `{results['fail']}`", parse_mode="Markdown")

# ==========================================
# ADMIN POWER COMMANDS (direct)
# ==========================================
async def _admin_action(update, context, action_name):
    if not is_admin(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text(f"Usage: /{action_name} CHAT_ID USER_OR_MSG_ID")
        return
    chat_id, target_id = context.args[0], context.args[1]
    try:
        if action_name == 'mute':
            await context.bot.restrict_chat_member(chat_id=chat_id, user_id=int(target_id),
                permissions=ChatPermissions(can_send_messages=False, can_send_media_messages=False,
                    can_send_polls=False, can_send_other_messages=False))
            msg = f"🔇  Muted `{target_id}`"
        elif action_name == 'unmute':
            await context.bot.restrict_chat_member(chat_id=chat_id, user_id=int(target_id),
                permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True,
                    can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True))
            msg = f"🔊  Unmuted `{target_id}`"
        elif action_name == 'ban':
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=int(target_id))
            msg = f"🚫  Banned `{target_id}`"
        elif action_name == 'unban':
            await context.bot.unban_chat_member(chat_id=chat_id, user_id=int(target_id))
            msg = f"✅  Unbanned `{target_id}`"
        elif action_name == 'kick':
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=int(target_id))
            await context.bot.unban_chat_member(chat_id=chat_id, user_id=int(target_id))
            msg = f"👢  Kicked `{target_id}`"
        elif action_name == 'pin':
            await context.bot.pin_chat_message(chat_id=chat_id, message_id=int(target_id))
            msg = f"📌  Pinned msg `{target_id}`"
        elif action_name == 'delmsg':
            await context.bot.delete_message(chat_id=chat_id, message_id=int(target_id))
            msg = f"🗑  Deleted msg `{target_id}`"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except TelegramError as e:
        await update.message.reply_text(f"❌  `{e}`\n⚠️  বটকে Admin করা আছে?", parse_mode="Markdown")

async def mute_cmd(u, c): await _admin_action(u, c, 'mute')
async def unmute_cmd(u, c): await _admin_action(u, c, 'unmute')
async def ban_cmd(u, c): await _admin_action(u, c, 'ban')
async def unban_cmd(u, c): await _admin_action(u, c, 'unban')
async def kick_cmd(u, c): await _admin_action(u, c, 'kick')
async def pin_cmd(u, c): await _admin_action(u, c, 'pin')
async def delmsg_cmd(u, c): await _admin_action(u, c, 'delmsg')

# ==========================================
# AUTO-FORWARD
# ==========================================
async def auto_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.channel_post:
        return
    chat_id = str(update.channel_post.chat.id)
    source_ids = [r[0] for r in get_sources()]
    if chat_id not in source_ids:
        return
    targets = [r[0] for r in get_channels()] + [r[0] for r in get_groups()]
    if not targets:
        return
    msg = update.channel_post
    text = msg.text or msg.caption or ""
    media_file_id, media_type = None, None
    if msg.photo: media_file_id, media_type = msg.photo[-1].file_id, "photo"
    elif msg.video: media_file_id, media_type = msg.video.file_id, "video"
    elif msg.document: media_file_id, media_type = msg.document.file_id, "document"
    elif msg.audio: media_file_id, media_type = msg.audio.file_id, "audio"
    elif msg.animation: media_file_id, media_type = msg.animation.file_id, "animation"
    results = await broadcast(context.bot, targets, text, media_file_id, media_type)
    logger.info(f"Auto-forward from {chat_id}: {results}")

# ==========================================
# SCHEDULE
# ==========================================
@admin_only
async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: `/schedule YYYY-MM-DD HH:MM message`", parse_mode="Markdown"
        )
        return
    schedule_time = f"{context.args[0]} {context.args[1]}"
    message = " ".join(context.args[2:])
    try:
        datetime.strptime(schedule_time, "%Y-%m-%d %H:%M")
    except ValueError:
        await update.message.reply_text("❌  Format: `YYYY-MM-DD HH:MM`", parse_mode="Markdown")
        return
    add_scheduled_post(message, None, None, schedule_time)
    await update.message.reply_text(f"⏰  *SCHEDULED!*\n📅  `{schedule_time}`\n💬  {message}", parse_mode="Markdown")

async def check_scheduled(context: ContextTypes.DEFAULT_TYPE):
    posts = get_pending_scheduled()
    for post in posts:
        post_id, message, media_file_id, media_type, target = post
        targets = []
        if target in ("channels", "all"): targets += [r[0] for r in get_channels()]
        if target in ("groups", "all"): targets += [r[0] for r in get_groups()]
        if not targets: targets = [r[0] for r in get_channels()] + [r[0] for r in get_groups()]
        await broadcast(context.bot, targets, message, media_file_id, media_type)
        mark_scheduled_sent(post_id)

# ==========================================
# MAIN
# ==========================================
if __name__ == '__main__':
    init_db()

    BOT_TOKEN = "8956561820:AAGdSxN1-rsvMn1acNtQkHGVMEusrMbcXUk"

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel_cmd))
    application.add_handler(CommandHandler("getid", getid_cmd))
    application.add_handler(CommandHandler("addchannel", add_channel_cmd))
    application.add_handler(CommandHandler("removechannel", remove_channel_cmd))
    application.add_handler(CommandHandler("addgroup", add_group_cmd))
    application.add_handler(CommandHandler("removegroup", remove_group_cmd))
    application.add_handler(CommandHandler("addsource", add_source_cmd))
    application.add_handler(CommandHandler("removesource", remove_source_cmd))
    application.add_handler(CommandHandler("post", post_all_cmd))
    application.add_handler(CommandHandler("postc", post_channels_cmd))
    application.add_handler(CommandHandler("postg", post_groups_cmd))
    application.add_handler(CommandHandler("schedule", schedule_cmd))
    application.add_handler(CommandHandler("mute", mute_cmd))
    application.add_handler(CommandHandler("unmute", unmute_cmd))
    application.add_handler(CommandHandler("ban", ban_cmd))
    application.add_handler(CommandHandler("unban", unban_cmd))
    application.add_handler(CommandHandler("kick", kick_cmd))
    application.add_handler(CommandHandler("pin", pin_cmd))
    application.add_handler(CommandHandler("delmsg", delmsg_cmd))

    application.add_handler(CallbackQueryHandler(button_handler))

    application.add_handler(MessageHandler(
        (filters.TEXT & ~filters.COMMAND) | filters.PHOTO | filters.VIDEO |
        filters.Document.ALL | filters.AUDIO | filters.ANIMATION,
        handle_text_input
    ))

    application.add_handler(MessageHandler(filters.ChatType.CHANNEL, auto_forward))

    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(check_scheduled, interval=60, first=10)
    else:
        logger.warning("JobQueue missing. Run: pip install 'python-telegram-bot[job-queue]'")

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  🤖  B R O A D C A S T   B O T")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  👑  Admin: {ADMIN_ID}")
    print("  ✅  Private Group Support (Chat ID)")
    print("  ✅  Admin Powers (mute/ban/kick)")
    print("  ✅  Auto-Forward | Scheduler")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    application.run_polling()
