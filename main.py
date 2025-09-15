#!/usr/bin/env python3
"""
Professional Telegram Bot for Anime Caption Formatting
Merged, deployment-ready full script for Render/Heroku/Railway.

Features:
- Robust caption parsing (multiple patterns + emoji structured)
- Quality normalization (ends with 'P') and QUALITY_ORDER
- Prefix rotation (every 3 processed messages) - consistent
- Full command set: /start, /name, /format, /status, /quality, /help,
  /addprefix, /prefixlist, /delprefix, /dumpchannel, /dumpstatus
- Persistent configuration in bot_config.json (async-safe)
- Dump channel sending with retry logic and status checks
- Health check server for deployment (port from PORT env)
- Webhook (if WEBHOOK_URL set) or Polling fallback
- Logging configurable via LOG_LEVEL env var
"""
from __future__ import annotations

import os
import re
import json
import logging
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from typing import Tuple, Optional, Dict, Any

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError

# -----------------------------------------------------------------------------
# Configuration (environment)
# -----------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable must be set")

CONFIG_FILE = os.getenv("CONFIG_FILE", "bot_config.json")
LOG_FILE = os.getenv("LOG_FILE", "bot.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
ENABLE_HEALTH_CHECK = os.getenv("ENABLE_HEALTH_CHECK", "true").lower() == "true"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # optional
PORT = int(os.getenv("PORT", 8080))

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
log_level = getattr(logging, LOG_LEVEL, logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, mode="a"),
    ],
)
logger = logging.getLogger("anime-leech-bot")

# -----------------------------------------------------------------------------
# Global (in-memory) state
# -----------------------------------------------------------------------------
# Default prefixes (can be modified by commands)
_prefixes_default = [
    "/leech -n",
    "/leech1 -n",
    "/leech2 -n",
    "/leechx -n",
    "/leech4 -n",
    "/leech3 -n",
    "/leech5 -n",
]

QUALITY_ORDER = ["480P", "720P", "1080P"]

# These will be populated from config file on load
fixed_anime_name: str = ""
prefixes: list[str] = _prefixes_default.copy()
dump_channel_id: str = ""
message_count: int = 0

# Async lock for config read/write and for message_count updates
_config_lock = asyncio.Lock()

# -----------------------------------------------------------------------------
# Config persistence helpers (async-safe)
# -----------------------------------------------------------------------------
async def save_config_async() -> None:
    """Save current config to CONFIG_FILE (async-safe)."""
    async with _config_lock:
        cfg = {
            "fixed_anime_name": fixed_anime_name,
            "prefixes": prefixes,
            "dump_channel_id": dump_channel_id,
            "message_count": message_count,
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            logger.debug("Config saved to %s", CONFIG_FILE)
        except Exception as e:
            logger.exception("Failed to save config: %s", e)


def save_config_sync() -> None:
    """Synchronous wrapper for initial calls (not used in handlers)."""
    # This intentionally blocks; used only during startup/shutdown.
    cfg = {
        "fixed_anime_name": fixed_anime_name,
        "prefixes": prefixes,
        "dump_channel_id": dump_channel_id,
        "message_count": message_count,
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        logger.debug("Config saved (sync) to %s", CONFIG_FILE)
    except Exception as e:
        logger.exception("Failed to save config (sync): %s", e)


async def load_config_async() -> None:
    """Load config from CONFIG_FILE (async-safe)."""
    global fixed_anime_name, prefixes, dump_channel_id, message_count
    async with _config_lock:
        if not os.path.exists(CONFIG_FILE):
            save_config_sync()
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            fixed_anime_name = cfg.get("fixed_anime_name", "")
            prefixes[:] = cfg.get("prefixes", prefixes)
            dump_channel_id = cfg.get("dump_channel_id", "")
            message_count = int(cfg.get("message_count", 0))
            logger.info("Config loaded: prefixes=%d dump=%s messages=%d", len(prefixes), "set" if dump_channel_id else "unset", message_count)
        except Exception as e:
            logger.exception("Failed to load config: %s", e)
            save_config_sync()


# -----------------------------------------------------------------------------
# Anime parsing utilities
# -----------------------------------------------------------------------------
class AnimeParser:
    """Comprehensive parser supporting many caption formats."""

    def __init__(self) -> None:
        self.patterns = {
            # Standard bracket formats
            "bracket_se": r"\[S(\d+)\s*E(\d+)\]",  # [S01 E12]
            "bracket_sep": r"\[S(\d+)\s*EP(\d+)\]",  # [S01 EP12]
            # Channel prefix formats
            "channel_se": r"@\w+\s*-\s*(.+?)\s+S(\d+)\s*EP(\d+)",  # @channel - Name S01 EP01
            "channel_bracket": r"@\w+\s*-\s*\[S(\d+)\s*EP(\d+)\]\s*(.+?)(?:\s*\[|$)",  # @channel - [S01 EP12] Name
            # Structured format with emojis (common)
            "structured_emoji": r"📺\s*([^\[]]+)\s*\[S(\d+)\]",  # 📺 NAME [S01]
            # Simple formats
            "simple_se": r"S(\d+)\s*E(\d+)",  # S01 E12
            "simple_ep": r"S(\d+)\s*EP(\d+)",  # S01 EP01
        }

    def extract_episode_info(self, text: str) -> Tuple[str, str, str]:
        """Return (season, episode, anime_name)."""
        season, episode, anime_name = "01", "01", ""

        clean_text = (text or "").strip()
        if not clean_text:
            return season, episode, anime_name

        # structured emoji format with special "Eᴘɪꜱᴏᴅᴇ" tokens (some uploads use stylized text)
        if "📺" in clean_text and "Eᴘɪꜱᴏᴅᴇ" in clean_text:
            s, e, name = self._parse_structured_format(clean_text)
            return s, e, name

        # Channel prefix patterns
        for key in ("channel_se", "channel_bracket"):
            pattern = self.patterns.get(key)
            if not pattern:
                continue
            m = re.search(pattern, clean_text, re.IGNORECASE)
            if m:
                if key == "channel_se":
                    name, s, e = m.groups()
                else:
                    s, e, name = m.groups()
                return s.zfill(2), e.zfill(2), name.strip()

        # bracket formats
        for key in ("bracket_se", "bracket_sep"):
            pattern = self.patterns.get(key)
            m = re.search(pattern, clean_text, re.IGNORECASE)
            if m:
                s, e = m.groups()
                # anime name is text before bracket
                anime_name = re.split(r"\[S\d+", clean_text, flags=re.IGNORECASE)[0].strip()
                return s.zfill(2), e.zfill(2), anime_name

        # simple formats
        for key in ("simple_se", "simple_ep"):
            pattern = self.patterns.get(key)
            m = re.search(pattern, clean_text, re.IGNORECASE)
            if m:
                s, e = m.groups()
                anime_name = re.split(r"S\d+", clean_text, flags=re.IGNORECASE)[0].strip()
                return s.zfill(2), e.zfill(2), anime_name

        # fallback: try to find naked "EP\d+" / "Episode \d+" patterns
        m = re.search(r"(?:EP|EPI|Episode)\s*[:\-]?\s*(\d+)", clean_text, re.IGNORECASE)
        if m:
            e = m.group(1)
            # season guess: look for S\d+
            ms = re.search(r"S(\d+)", clean_text, re.IGNORECASE)
            if ms:
                season = ms.group(1)
            return season.zfill(2), e.zfill(2), clean_text

        return season, episode, clean_text

    def _parse_structured_format(self, text: str) -> Tuple[str, str, str]:
        season, episode, anime_name = "01", "01", ""
        title_match = re.search(r"📺\s*([^\[]]+)\s*\[S(\d+)\]", text, re.IGNORECASE)
        if title_match:
            anime_name = title_match.group(1).strip()
            season = title_match.group(2).zfill(2)
        episode_match = re.search(r"Eᴘɪꜱᴏᴅᴇ\s*[:\-]?\s*(\d+)", text, re.IGNORECASE)
        if episode_match:
            episode = episode_match.group(1).zfill(2)
        return season, episode, anime_name

    def extract_quality(self, text: str) -> str:
        # patterns looking for quality numbers with optional 'p' or inside brackets
        quality_patterns = [
            r"(\d+)[pP]\b",  # 1080p or 720P
            r"\[(\d+)[pP]?\]",  # [1080] or [720p]
            r"Q(?:ᴜᴀʟɪᴛʏ|uality)\s*[:\-]?\s*(\d+)[pP]?",  # Quality: 1080
            r"\b(\d+)\s*[pP]\b",  # '1080 P'
        ]
        for pat in quality_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                qnum = m.group(1)
                try:
                    qint = int(qnum)
                except ValueError:
                    continue
                # Validate common qualities; accept 144,240,360,480,720,1080,1440,2160
                if qint in (144, 240, 360, 480, 720, 1080, 1440, 2160):
                    return f"{qint}P"
        return "720P"  # default

    def extract_language(self, text: str) -> str:
        # mapping common language indicators to short tags
        mapping = {
            "தமிழ்": "Tam",
            "tamil": "Tam",
            "tam": "Tam",
            "english": "Eng",
            "eng": "Eng",
            "multi audio": "Multi",
            "multi": "Multi",
            "dual audio": "Dual",
            "dual": "Dual",
        }
        lower = (text or "").lower()
        for k, v in mapping.items():
            if k in lower:
                return v
        # check for uppercase Tamil script etc
        return ""

    def clean_anime_name(self, name: str) -> str:
        name = (name or "").strip()
        if not name:
            return ""
        # remove channel prefixes like @Channel - 
        name = re.sub(r"^@\w+\s*-\s*", "", name, flags=re.IGNORECASE)
        # remove bracketed content and parentheses
        name = re.sub(r"\[.*?\]|\(.*?\)|\{.*?\}", "", name)
        # replace common words
        replacements = {
            "Tamil": "Tam",
            "English": "Eng",
            "Dubbed": "Dub",
            "Subbed": "Sub",
        }
        for old, new in replacements.items():
            name = re.sub(rf"\b{old}\b", new, name, flags=re.IGNORECASE)
        # remove unwanted punctuation (keep - and &)
        name = re.sub(r'[!@#$%^&*(),.?":{}|<>]', "", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name


parser = AnimeParser()

# -----------------------------------------------------------------------------
# Caption formatting and prefix rotation
# -----------------------------------------------------------------------------
async def get_next_prefix_and_increment() -> str:
    """
    Returns the prefix based on message_count and increments message_count safely.
    Rotation logic: prefixes rotate every 3 messages. Uses async lock to avoid races.
    """
    global message_count
    async with _config_lock:
        message_count += 1
        # ensure there is at least one prefix
        if not prefixes:
            prefixes.append("/leech -n")
        prefix_index = ((message_count - 1) // 3) % len(prefixes)
        current = prefixes[prefix_index]
    # persist message_count occasionally (not every message to reduce IO)
    if message_count % 10 == 0:
        # schedule save without awaiting to speed reply
        asyncio.create_task(save_config_async())
    return current


def determine_extension_from_caption(text: str) -> str:
    t = (text or "").lower()
    if ".mp4" in t:
        return ".mp4"
    if ".avi" in t:
        return ".avi"
    if ".mkv" in t:
        return ".mkv"
    if ".mov" in t:
        return ".mov"
    if ".webm" in t:
        return ".webm"
    return ".mkv"  # default


async def format_caption(caption: str) -> str:
    """Main formatting entry — returns final formatted caption string."""
    season, episode, extracted_name = parser.extract_episode_info(caption)
    quality = parser.extract_quality(caption)
    language = parser.extract_language(caption)
    # Use fixed name if set
    name = fixed_anime_name or parser.clean_anime_name(extracted_name) or "Unknown Anime"
    # append language short tag if detected and not already part of name
    if language and language not in name:
        name = f"{name} {language}".strip()
    season_episode = f"[S{season}-E{episode}]"
    extension = determine_extension_from_caption(caption)
    prefix = await get_next_prefix_and_increment()
    # Build final string (quality always ends with 'P')
    final = f"{prefix} {season_episode} {name} [{quality}] [Single]{extension}"
    return final

# -----------------------------------------------------------------------------
# Dump channel functionality
# -----------------------------------------------------------------------------
async def send_to_dump_channel(context: ContextTypes.DEFAULT_TYPE, message_obj, formatted_caption: str) -> Tuple[bool, str]:
    """Send formatted caption to dump channel with retry logic. Returns (success, message)."""
    global dump_channel_id
    if not dump_channel_id:
        return False, "Dump channel not configured"

    max_retries = 3
    delay = 2  # seconds between retries
    for attempt in range(1, max_retries + 1):
        try:
            timestamp = getattr(message_obj, "date", datetime.utcnow())
            await context.bot.send_message(
                chat_id=dump_channel_id,
                text=f"📤 **Auto-formatted Caption**\n\n`{formatted_caption}`\n\n⏰ Processed at: {timestamp}",
                parse_mode="Markdown",
            )
            logger.info("Sent formatted caption to dump channel %s", dump_channel_id)
            return True, "Sent"
        except TelegramError as te:
            text = str(te).lower()
            logger.warning("Attempt %d: failed sending to dump channel: %s", attempt, te)
            if "chat not found" in text:
                return False, "Channel not found"
            if "not enough rights" in text or "forbidden" in text:
                return False, "Bot lacks permissions in dump channel"
        except Exception as e:
            logger.exception("Attempt %d: unexpected error sending to dump: %s", attempt, e)
        if attempt < max_retries:
            await asyncio.sleep(delay)
            delay *= 2
    return False, f"Failed after {max_retries} attempts"


async def check_dump_channel_status(context: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, Any]:
    """Check accessibility and bot permissions for the dump channel."""
    global dump_channel_id
    if not dump_channel_id:
        return False, "No dump channel configured"
    try:
        chat = await context.bot.get_chat(dump_channel_id)
        member = await context.bot.get_chat_member(dump_channel_id, context.bot.id)
        can_send = getattr(member, "can_post_messages", True)
        status = {
            "exists": True,
            "title": getattr(chat, "title", "Unknown"),
            "type": getattr(chat, "type", "unknown"),
            "can_send": bool(can_send),
            "bot_status": getattr(member, "status", "unknown"),
        }
        return True, status
    except TelegramError as te:
        text = str(te).lower()
        logger.warning("Dump status check error: %s", te)
        if "chat not found" in text:
            return False, "Channel not found"
        if "not enough rights" in text or "forbidden" in text:
            return False, "Bot lacks permissions"
        return False, str(te)
    except Exception as e:
        logger.exception("Unexpected dump status check error: %s", e)
        return False, str(e)

# -----------------------------------------------------------------------------
# Command Handlers
# -----------------------------------------------------------------------------
async def setup_commands(application: Application) -> None:
    """Register bot command menu that clients display."""
    commands = [
        BotCommand("start", "🚀 Start the bot"),
        BotCommand("name", "📝 Set/View anime name"),
        BotCommand("format", "🔧 Test caption formatting"),
        BotCommand("status", "📊 Bot status"),
        BotCommand("quality", "🎥 Show quality order"),
        BotCommand("help", "❓ Help & examples"),
        BotCommand("addprefix", "➕ Add new prefix"),
        BotCommand("prefixlist", "📋 List prefixes"),
        BotCommand("delprefix", "➖ Delete prefix"),
        BotCommand("dumpchannel", "📤 Set/Show dump channel"),
        BotCommand("dumpstatus", "📡 Check dump channel"),
    ]
    try:
        await application.bot.set_my_commands(commands)
    except Exception as e:
        logger.warning("Could not set commands: %s", e)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await setup_commands(context.application)
    text = (
        "🎬 **Professional Anime Caption Formatter**\n\n"
        "Send media (video/document/photo) with captions and I will format them.\n\n"
        "Use `/format TEXT` to test formatting.\n"
        "Use `/name YOUR NAME` to set a fixed anime name or `/name reset` to enable auto-detect.\n"
        "Use `/dumpchannel <chat_id>` to set dump channel for formatted captures.\n"
        "Type `/help` for more commands."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def name_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set or show fixed anime name. Use '/name reset' to clear."""
    global fixed_anime_name
    args = context.args or []
    if not args:
        current = fixed_anime_name or "Auto-detect mode"
        await update.message.reply_text(f"📝 **Current anime name:** {current}", parse_mode="Markdown")
        return
    argtext = " ".join(args).strip()
    if argtext.lower() == "reset":
        fixed_anime_name = ""
        await save_config_async()
        await update.message.reply_text("✅ Fixed anime name reset. Now using auto-detection.")
        return
    fixed_anime_name = argtext
    await save_config_async()
    await update.message.reply_text(f"✅ Fixed anime name set: `{fixed_anime_name}`", parse_mode="Markdown")


async def format_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Test format on provided text: /format some caption text"""
    if not context.args:
        await update.message.reply_text("Usage: `/format YOUR CAPTION TEXT`", parse_mode="Markdown")
        return
    text = " ".join(context.args)
    try:
        formatted = await format_caption(text)
        await update.message.reply_text(f"🔧 **Format Test Result**\n\n`{formatted}`", parse_mode="Markdown")
    except Exception as e:
        logger.exception("format_command error: %s", e)
        await update.message.reply_text("❌ Error formatting caption.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bot status and current settings."""
    async with _config_lock:
        cur_prefix_index = ((message_count) // 3) % (len(prefixes) or 1)
        current_prefix = prefixes[cur_prefix_index] if prefixes else "/leech -n"
        next_rotation_in = 3 - (message_count % 3) if (message_count % 3) != 0 else 3
        txt = (
            "📊 **Bot Status**\n\n"
            f"**Fixed anime name:** {fixed_anime_name or 'Auto-detect'}\n"
            f"**Prefixes count:** {len(prefixes)}\n"
            f"**Current prefix:** `{current_prefix}`\n"
            f"**Messages processed:** {message_count}\n"
            f"**Next prefix rotation in:** {next_rotation_in} messages\n"
            f"**Dump channel:** {dump_channel_id or 'Not set'}\n"
            f"**Quality order:** {' → '.join(QUALITY_ORDER)}"
        )
    await update.message.reply_text(txt, parse_mode="Markdown")


async def quality_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"🎥 **Quality Order:**\n{' → '.join(QUALITY_ORDER)}", parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "❓ **Help — Supported Input Examples**\n\n"
        "1. `[S01 E12] Anime Name [1080p] Tamil.mkv`\n"
        "2. `[S01 EP12] Anime Name [720p]`\n"
        "3. `@Channel - Anime Name S01 EP01 [480P]`\n"
        "4. `📺 Anime Name [S01] Episode : 15 Quality : 480p Audio : Tamil`\n\n"
        "Commands: /start /name /format /status /quality /help /addprefix /prefixlist /delprefix /dumpchannel /dumpstatus"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# Prefix management
async def addprefix_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global prefixes
    p = " ".join(context.args).strip()
    if not p:
        await update.message.reply_text("Usage: `/addprefix YOUR_PREFIX`", parse_mode="Markdown")
        return
    async with _config_lock:
        if p in prefixes:
            await update.message.reply_text("⚠️ Prefix already exists.", parse_mode="Markdown")
            return
        prefixes.append(p)
    await save_config_async()
    await update.message.reply_text(f"✅ Prefix added: `{p}`", parse_mode="Markdown")


async def prefixlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not prefixes:
        await update.message.reply_text("No prefixes configured.")
        return
    txt = "\n".join(f"{i+1}. `{p}`" for i, p in enumerate(prefixes))
    await update.message.reply_text(f"📋 **Current prefixes:**\n{txt}", parse_mode="Markdown")


async def delprefix_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global prefixes
    if not context.args:
        await update.message.reply_text("Usage: `/delprefix INDEX` (use /prefixlist to see indices)", parse_mode="Markdown")
        return
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await update.message.reply_text("Index must be a number.", parse_mode="Markdown")
        return
    async with _config_lock:
        if 0 <= idx < len(prefixes):
            removed = prefixes.pop(idx)
            await save_config_async()
            await update.message.reply_text(f"🗑 Removed prefix: `{removed}`", parse_mode="Markdown")
            return
    await update.message.reply_text("❌ Invalid index.", parse_mode="Markdown")


# Dump channel commands
async def dumpchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set or show dump channel. pass 'reset' to clear."""
    global dump_channel_id
    if not context.args:
        await update.message.reply_text(f"📤 Dump channel: {dump_channel_id or 'Not set'}", parse_mode="Markdown")
        return
    arg = context.args[0].strip()
    if arg.lower() == "reset":
        dump_channel_id = ""
        await save_config_async()
        await update.message.reply_text("✅ Dump channel reset.", parse_mode="Markdown")
        return
    dump_channel_id = arg
    await save_config_async()
    await update.message.reply_text(f"✅ Dump channel set to: `{dump_channel_id}`\nUse /dumpstatus to check access.", parse_mode="Markdown")


async def dumpstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok, status = await check_dump_channel_status(context)
    if ok:
        # status is dict
        st = status
        txt = (
            f"✅ Dump channel accessible\n"
            f"Title: {st.get('title')}\n"
            f"Type: {st.get('type')}\n"
            f"Can bot post: {st.get('can_send')}\n"
            f"Bot status: {st.get('bot_status')}"
        )
        await update.message.reply_text(txt)
    else:
        await update.message.reply_text(f"❌ Dump channel status: {status}")


# -----------------------------------------------------------------------------
# Media handlers
# -----------------------------------------------------------------------------
async def handle_media_with_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle media (video/document/photo) with captions."""
    msg = update.message
    if not msg:
        return
    caption = msg.caption or ""
    if not caption.strip():
        return

    logger.info("Received caption: %s", (caption[:200] + "...") if len(caption) > 200 else caption)
    try:
        formatted = await format_caption(caption)
    except Exception as e:
        logger.exception("Error formatting caption: %s", e)
        await msg.reply_text("❌ Error while formatting caption.")
        return

    # reply with formatted caption
    try:
        await msg.reply_text(f"`{formatted}`", parse_mode="Markdown", reply_to_message_id=msg.message_id)
    except Exception as e:
        logger.warning("Failed to reply with formatted caption: %s", e)

    # send to dump if configured
    if dump_channel_id:
        ok, info = await send_to_dump_channel(context, msg, formatted)
        if not ok:
            logger.warning("Dump failed: %s", info)

    # persist config occasionally (already scheduled inside get_next_prefix)
    if message_count % 10 == 0:
        await save_config_async()


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Allow testing by plain text messages (non-command)."""
    text = update.message and update.message.text or ""
    if not text or text.startswith("/"):
        return
    try:
        formatted = await format_caption(text)
        await update.message.reply_text(f"🔧 **Text Format Test**\n\n`{formatted}`", parse_mode="Markdown")
    except Exception as e:
        logger.exception("handle_text_message error: %s", e)
        await update.message.reply_text("❌ Error formatting text.")


# -----------------------------------------------------------------------------
# Health check server (simple)
# -----------------------------------------------------------------------------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:
        # suppress default std logging noise
        return


def start_health_server_bg() -> None:
    if not ENABLE_HEALTH_CHECK:
        logger.info("Health check disabled by environment.")
        return

    def _serve():
        server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
        logger.info("Health server listening on port %d", PORT)
        try:
            server.serve_forever()
        except Exception as e:
            logger.exception("Health server stopped: %s", e)

    t = threading.Thread(target=_serve, daemon=True)
    t.start()


# -----------------------------------------------------------------------------
# Main application setup & run
# -----------------------------------------------------------------------------
async def on_startup(application: Application) -> None:
    await load_config_async()
    await setup_commands(application)
    logger.info("Bot startup complete.")


def main() -> None:
    # Build application
    app = Application.builder().token(BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("name", name_command))
    app.add_handler(CommandHandler("format", format_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("quality", quality_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("addprefix", addprefix_command))
    app.add_handler(CommandHandler("prefixlist", prefixlist_command))
    app.add_handler(CommandHandler("delprefix", delprefix_command))
    app.add_handler(CommandHandler("dumpchannel", dumpchannel_command))
    app.add_handler(CommandHandler("dumpstatus", dumpstatus_command))

    # Media handlers
    # Accept any media/document/photo/video with caption
    app.add_handler(MessageHandler(filters.ALL & filters.CAPTION, handle_media_with_caption))
    # Text handler for testing (non-command texts)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # startup helper
    app.post_init = on_startup  # run after app initialized

    # health server background
    start_health_server_bg()

    # Run webhook if provided, else polling
    if WEBHOOK_URL:
        logger.info("Starting webhook mode with URL: %s", WEBHOOK_URL)
        # url_path should be unique - use BOT_TOKEN for simplicity
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            url_path=BOT_TOKEN,
        )
    else:
        logger.info("Starting polling mode (drop pending updates).")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.exception("Fatal error in main: %s", exc)
        # sync save to persist last state if possible
        try:
            save_config_sync()
        except Exception:
            pass
        raise
        print("Error at my code")
