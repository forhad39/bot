import os
import asyncio
import threading
from datetime import datetime
from typing import List, Optional

import aiosqlite
import uvicorn
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    ChatMemberHandler,
)

# -----------------------
# Configuration (Set directly)
# -----------------------
BOT_TOKEN = "8956561820:AAEBsYWuucvkhiUkq9SkWyg72ud17T53ATQ"
API_KEY = "supersecretapikey"
DB_PATH = "channels.db"

# -----------------------
# Database helpers (async)
# -----------------------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE,
                username TEXT,
                title TEXT,
                chat_type TEXT,
                is_premium INTEGER DEFAULT 0,
                added_at TEXT
            )
            """
        )
        await db.commit()

async def add_channel_db(chat_id: int, username: Optional[str], title: Optional[str], chat_type: Optional[str], is_premium: int = 0) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO channels (chat_id, username, title, chat_type, is_premium, added_at) VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, username, title, chat_type, int(is_premium), datetime.utcnow().isoformat()),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def remove_channel_db(chat_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM channels WHERE chat_id = ?", (chat_id,))
        await db.commit()
        return cur.rowcount > 0

async def get_channels_db() -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT chat_id, username, title, chat_type, is_premium, added_at FROM channels")
        rows = await cur.fetchall()
        return [
            {
                "chat_id": r[0],
                "username": r[1],
                "title": r[2],
                "chat_type": r[3],
                "is_premium": bool(r[4]),
                "added_at": r[5],
            }
            for r in rows
        ]

# -----------------------
# Telegram bot handlers
# -----------------------
application = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! Broadcast Bot ready.\n\n"
        "- Add me to a channel or group and make me an admin: I'll auto-register that chat.\n"
        "- Use /post <message> to send a message to all registered channels (or use the API).\n"
        "- Use the API (with API_KEY) to list/send/selective broadcast."
    )

async def post_to_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = " ".join(context.args)
    if not message:
        await update.message.reply_text("Please provide a message. Example: /post Hello everyone")
        return

    channels = await get_channels_db()
    if not channels:
        await update.message.reply_text("No registered channels. Add the bot to channels or use the API to add.")
        return

    sent = 0
    failed = 0
    for ch in channels:
        try:
            await context.bot.send_message(chat_id=ch["chat_id"], text=message)
            sent += 1
        except Exception as e:
            failed += 1
    await update.message.reply_text(f"Sent: {sent}, Failed: {failed}")

async def my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        new_status = update.my_chat_member.new_chat_member.status
        if new_status in ("member", "administrator"):
            username = getattr(chat, "username", None)
            title = getattr(chat, "title", None)
            chat_type = getattr(chat, "type", None)
            ok = await add_channel_db(chat.id, username, title, chat_type)
            try:
                if ok:
                    await context.bot.send_message(chat_id=chat.id, text="✅ This chat has been registered for broadcasts.")
            except Exception:
                pass
    except Exception:
        return

# -----------------------
# FastAPI (REST) part
# -----------------------
app = FastAPI(title="Broadcast Bot API")

def api_key_check(x_api_key: Optional[str] = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

class ChannelIn(BaseModel):
    chat_id: Optional[int] = None
    username: Optional[str] = None
    title: Optional[str] = None
    chat_type: Optional[str] = None
    is_premium: Optional[bool] = False

class SendRequest(BaseModel):
    message: str
    targets: Optional[List[int]] = None

@app.get("/api/channels", dependencies=[Depends(api_key_check)])
async def list_channels():
    return await get_channels_db()

@app.post("/api/channels", dependencies=[Depends(api_key_check)])
async def add_channel(item: ChannelIn):
    if not item.chat_id and not item.username:
        raise HTTPException(status_code=400, detail="Provide chat_id or username")
    chat_id = item.chat_id
    if chat_id is None:
        try:
            chat = await application.bot.get_chat(item.username)
            chat_id = chat.id
            item.title = item.title or getattr(chat, "title", None)
            item.chat_type = item.chat_type or getattr(chat, "type", None)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not resolve username to chat_id: {e}")

    ok = await add_channel_db(int(chat_id), item.username, item.title, item.chat_type, int(bool(item.is_premium)))
    return {"added": ok, "chat_id": chat_id}

@app.delete("/api/channels/{chat_id}", dependencies=[Depends(api_key_check)])
async def delete_channel(chat_id: int):
    ok = await remove_channel_db(chat_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"deleted": True, "chat_id": chat_id}

@app.post("/api/send", dependencies=[Depends(api_key_check)])
async def send_message(req: SendRequest):
    channels = await get_channels_db()
    if not channels:
        raise HTTPException(status_code=400, detail="No registered channels")

    if req.targets:
        targets_set = set(req.targets)
        targets = [c for c in channels if c["chat_id"] in targets_set]
    else:
        targets = channels

    if not targets:
        raise HTTPException(status_code=400, detail="No matching targets")

    results = []
    for c in targets:
        try:
            await application.bot.send_message(chat_id=c["chat_id"], text=req.message)
            results.append({"chat_id": c["chat_id"], "status": "ok"})
        except Exception as e:
            results.append({"chat_id": c["chat_id"], "status": "error", "error": str(e)})
    return {"results": results}

# -----------------------
# Utility: run FastAPI
# -----------------------
def start_api_in_thread(host="0.0.0.0", port=8000):
    def _run():
        uvicorn.run(app, host=host, port=port, log_level="info")
    t = threading.Thread(target=_run, daemon=True)
    t.start()

# -----------------------
# Main
# -----------------------
def main():
    global application
    
    # initialize DB
    asyncio.run(init_db())

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("post", post_to_all_command))
    application.add_handler(
        ChatMemberHandler(my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )

    # Start API server in background thread
    start_api_in_thread(host="0.0.0.0", port=8000)
    print("API server started at http://0.0.0.0:8000 (use X-API-KEY header)")

    # Run the bot
    print("Starting Telegram bot...")
    application.run_polling()

if __name__ == "__main__":
    main()
