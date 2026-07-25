import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ==========================================
# 1. DATABASE SETUP (Auto-creates SQLite file)
# ==========================================
def init_db():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS channels
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE)''')
    conn.commit()
    conn.close()

def add_channel_db(username):
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO channels (username) VALUES (?)", (username,))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    finally:
        conn.close()
    return success

def get_channels():
    conn = sqlite3.connect('channels.db')
    c = conn.cursor()
    c.execute("SELECT username FROM channels")
    channels = [row[0] for row in c.fetchall()]
    conn.close()
    return channels

# ==========================================
# 2. BOT COMMAND HANDLERS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hello! Welcome to the Telegram Broadcast Bot.\n\n"
        "1. To add a channel:\n"
        "/addchannel @your_channel_username\n\n"
        "2. To broadcast a message to all channels:\n"
        "/post Your message text here"
    )

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        channel = context.args[0]
        if add_channel_db(channel):
            await update.message.reply_text(f'✅ {channel} successfully added to database.')
        else:
            await update.message.reply_text(f'⚠️ {channel} is already in the database.')
    else:
        await update.message.reply_text('Please provide a channel username.\nExample: /addchannel @mychannel')

async def post_to_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot
    channels = get_channels()
    message = " ".join(context.args)

    if not message:
        await update.message.reply_text('Please write a message to post.\nExample: /post Hello World')
        return

    if not channels:
        await update.message.reply_text('No channels found! Add a channel first using /addchannel.')
        return

    for channel in channels:
        try:
            await bot.send_message(chat_id=channel, text=message)
            await update.message.reply_text(f'✅ Post sent to {channel}')
        except Exception as e:
            await update.message.reply_text(f'❌ Failed to send post to {channel}: {e}')

# ==========================================
# 3. MAIN EXECUTION
# ==========================================
if __name__ == '__main__':
    # Initialize Database
    init_db()
    
    # Replace "8956561820:AAEBsYWuucvkhiUkq9SkWyg72ud17T53ATQ" with your actual Bot Token from BotFather
    BOT_TOKEN = "8956561820:AAEBsYWuucvkhiUkq9SkWyg72ud17T53ATQ"
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addchannel", add_channel))
    application.add_handler(CommandHandler("post", post_to_all))

    print("Bot is running successfully...")
    application.run_polling()
