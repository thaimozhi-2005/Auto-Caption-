#!/usr/bin/env python3
"""
Professional Telegram Bot for Anime Caption Formatting
Deployment-ready version with:
- Prefix management
- Dump channel functionality
- Config persistence
- Render/Heroku/Webhook support
"""

import re
import logging
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from telegram import Update, BotCommand
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from telegram.error import TelegramError

# =============================================================================
# CONFIGURATION
# =============================================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable must be set")

CONFIG_FILE = "bot_config.json"

fixed_anime_name = ""  
dump_channel_id = ""  
message_count = 0
prefixes = ["/leech -n", "/leech1 -n", "/leech2 -n", "/leechx -n", "/leech4 -n", "/leech3 -n", "/leech5 -n"]

QUALITY_ORDER = ["480P", "720P", "1080P"]

# =============================================================================
# LOGGING
# =============================================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, LOG_LEVEL, logging.INFO)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=log_level,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIG MANAGEMENT
# =============================================================================
def save_config():
    config = {
        "fixed_anime_name": fixed_anime_name,
        "prefixes": prefixes,
        "dump_channel_id": dump_channel_id,
        "message_count": message_count
    }
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save config: {e}")

def load_config():
    global fixed_anime_name, prefixes, dump_channel_id, message_count
    if not os.path.exists(CONFIG_FILE):
        save_config()
        return
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        fixed_anime_name = config.get("fixed_anime_name", "")
        prefixes[:] = config.get("prefixes", prefixes)
        dump_channel_id = config.get("dump_channel_id", "")
        message_count = config.get("message_count", 0)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        save_config()

# =============================================================================
# ANIME PARSER
# =============================================================================
class AnimeParser:
    def extract_episode_info(self, text):
        season, episode, anime_name = "01", "01", ""
        clean_text = text.strip()
        m = re.search(r'S(\d+)\s*EP?(\d+)', clean_text, re.IGNORECASE)
        if m:
            season, episode = m.groups()
            anime_name = re.split(r'S\d+', clean_text, 1)[0].strip()
            return season.zfill(2), episode.zfill(2), anime_name
        return season, episode, clean_text

    def extract_quality(self, text):
        m = re.search(r'(\d{3,4})[pP]', text)
        if m:
            return f"{m.group(1)}P"
        return "720P"

    def extract_language(self, text):
        langs = {"tamil": "Tam", "english": "Eng", "multi": "Multi", "dual": "Dual"}
        for k, v in langs.items():
            if k in text.lower():
                return v
        return ""

    def clean_anime_name(self, name):
        return re.sub(r'\s+', ' ', re.sub(r'[\[\](){}]', '', name)).strip()

def parse_caption(caption: str) -> str:
    global message_count, fixed_anime_name
    message_count += 1
    parser = AnimeParser()
    season, episode, extracted_name = parser.extract_episode_info(caption)
    quality = parser.extract_quality(caption)
    language = parser.extract_language(caption)
    anime_name = fixed_anime_name or parser.clean_anime_name(extracted_name) or "Unknown Anime"
    if language and language not in anime_name:
        anime_name += f" {language}"
    season_episode = f"[S{season}-E{episode}]"
    ext = ".mkv"
    if ".mp4" in caption.lower(): ext = ".mp4"
    elif ".avi" in caption.lower(): ext = ".avi"
    prefix = prefixes[(message_count - 1) // 3 % len(prefixes)]
    return f"{prefix} {season_episode} {anime_name} [{quality}] [Single]{ext}"

# =============================================================================
# DUMP CHANNEL
# =============================================================================
async def send_to_dump_channel(context, message, formatted_caption):
    if not dump_channel_id:
        return False, "Dump not set"
    try:
        await context.bot.send_message(
            chat_id=dump_channel_id,
            text=f"📤 **Auto Caption**\n\n`{formatted_caption}`",
            parse_mode='Markdown'
        )
        return True, "Success"
    except Exception as e:
        return False, str(e)

async def check_dump_channel_status(context):
    if not dump_channel_id:
        return False, "No dump channel"
    try:
        chat = await context.bot.get_chat(dump_channel_id)
        return True, f"✅ Dump channel: {chat.title}"
    except Exception as e:
        return False, str(e)

# =============================================================================
# COMMANDS
# =============================================================================
async def setup_commands(application):
    cmds = [
        BotCommand("start", "Start bot"),
        BotCommand("name", "Set/View anime name"),
        BotCommand("format", "Test formatting"),
        BotCommand("status", "Bot status"),
        BotCommand("help", "Help"),
        BotCommand("quality", "Quality info"),
        BotCommand("addprefix", "Add prefix"),
        BotCommand("prefixlist", "List prefixes"),
        BotCommand("delprefix", "Delete prefix"),
        BotCommand("dumpchannel", "Set dump channel"),
        BotCommand("dumpstatus", "Check dump channel"),
    ]
    await application.bot.set_my_commands(cmds)

async def start_command(update, context):
    await setup_commands(context.application)
    await update.message.reply_text("🎬 Bot ready! Send media with captions.")

async def name_command(update, context):
    global fixed_anime_name
    if context.args:
        fixed_anime_name = " ".join(context.args)
        save_config()
        await update.message.reply_text(f"✅ Fixed anime name set: {fixed_anime_name}")
    else:
        await update.message.reply_text(f"📺 Current name: {fixed_anime_name or 'Auto-detect'}")

async def format_command(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /format CAPTION")
        return
    text = " ".join(context.args)
    fc = parse_caption(text)
    await update.message.reply_text(f"`{fc}`", parse_mode='Markdown')

async def status_command(update, context):
    await update.message.reply_text(
        f"📊 Status:\nPrefixes: {len(prefixes)}\nDump: {dump_channel_id or '❌'}\nFixed name: {fixed_anime_name or 'Auto'}"
    )

async def quality_command(update, context):
    await update.message.reply_text("🎥 Qualities: " + " → ".join(QUALITY_ORDER))

async def addprefix_command(update, context):
    global prefixes
    if not context.args:
        await update.message.reply_text("Usage: /addprefix PREFIX")
        return
    p = " ".join(context.args)
    if p not in prefixes:
        prefixes.append(p)
        save_config()
        await update.message.reply_text(f"✅ Added: {p}")
    else:
        await update.message.reply_text("⚠️ Prefix exists")

async def prefixlist_command(update, context):
    txt = "\n".join(f"{i+1}. {p}" for i, p in enumerate(prefixes))
    await update.message.reply_text(f"📋 Prefixes:\n{txt}")

async def delprefix_command(update, context):
    global prefixes
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /delprefix INDEX")
        return
    idx = int(context.args[0]) - 1
    if 0 <= idx < len(prefixes):
        removed = prefixes.pop(idx)
        save_config()
        await update.message.reply_text(f"🗑 Removed: {removed}")
    else:
        await update.message.reply_text("❌ Invalid index")

async def dumpchannel_command(update, context):
    global dump_channel_id
    if not context.args:
        await update.message.reply_text(f"Dump: {dump_channel_id or 'Not set'}")
        return
    dump_channel_id = context.args[0]
    save_config()
    await update.message.reply_text(f"✅ Dump set: {dump_channel_id}")

async def dumpstatus_command(update, context):
    ok, msg = await check_dump_channel_status(context)
    await update.message.reply_text(msg)

async def help_command(update, context):
    await update.message.reply_text("📖 Commands:\n/start\n/name\n/format\n/status\n/quality\n/addprefix\n/prefixlist\n/delprefix\n/dumpchannel\n/dumpstatus")

# =============================================================================
# MEDIA HANDLER
# =============================================================================
async def handle_media_with_caption(update, context):
    cap = update.message.caption
    if not cap: return
    fc = parse_caption(cap)
    await update.message.reply_text(f"`{fc}`", parse_mode='Markdown')
    if dump_channel_id:
        await send_to_dump_channel(context, update.message, fc)
    save_config()

# =============================================================================
# HEALTH CHECK
# =============================================================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *a): pass

def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

# =============================================================================
# MAIN
# =============================================================================
def main():
    load_config()
    run_health_server()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("name", name_command))
    app.add_handler(CommandHandler("format", format_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("quality", quality_command))
    app.add_handler(CommandHandler("addprefix", addprefix_command))
    app.add_handler(CommandHandler("prefixlist", prefixlist_command))
    app.add_handler(CommandHandler("delprefix", delprefix_command))
    app.add_handler(CommandHandler("dumpchannel", dumpchannel_command))
    app.add_handler(CommandHandler("dumpstatus", dumpstatus_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.ALL & filters.CAPTION, handle_media_with_caption))
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        app.run_webhook(listen="0.0.0.0", port=int(os.getenv("PORT", 8080)), url_path=BOT_TOKEN, webhook_url=webhook_url)
    else:
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
