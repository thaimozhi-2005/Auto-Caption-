#!/usr/bin/env python3
"""
Professional Telegram Bot for Anime Caption Formatting
Enhanced with prefix management, dump channel functionality, log channel monitoring, and Render deployment ready
WITH HTTP HEALTH CHECK SERVER FOR RENDER WEB SERVICE
FIXED FOR RENDER DEPLOYMENT
"""
import re
import logging
import json
import os
import asyncio
from datetime import datetime, timezone
from telegram import Update, BotCommand
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from telegram.error import TelegramError
import traceback
from threading import Thread
import uvicorn
from fastapi import FastAPI

# =============================================================================
# RENDER WEB SERVICE COMPATIBILITY - HTTP SERVER
# =============================================================================
# Initialize bot_stats BEFORE it's used in FastAPI endpoints
bot_stats = {
    "start_time": datetime.now(timezone.utc),
    "messages_processed": 0,
    "successful_formats": 0,
    "failed_formats": 0,
    "dump_channel_sends": 0,
    "dump_channel_fails": 0,
    "errors": 0
}

# Create FastAPI app for health checks
fastapi_app = FastAPI(title="Telegram Bot Health Check")

@fastapi_app.get("/")
@fastapi_app.get("/health")
async def health_check():
    """Health check endpoint for Render"""
    return {
        "status": "healthy",
        "bot": "Professional Anime Caption Formatter",
        "uptime": str(datetime.now(timezone.utc) - bot_stats.get("start_time", datetime.now(timezone.utc))),
        "messages_processed": bot_stats.get("messages_processed", 0)
    }

@fastapi_app.get("/stats")
async def api_stats():
    """API endpoint for bot statistics"""
    uptime = datetime.now(timezone.utc) - bot_stats.get("start_time", datetime.now(timezone.utc))
    return {
        "uptime_seconds": uptime.total_seconds(),
        "messages_processed": bot_stats.get("messages_processed", 0),
        "successful_formats": bot_stats.get("successful_formats", 0),
        "failed_formats": bot_stats.get("failed_formats", 0),
        "dump_channel_sends": bot_stats.get("dump_channel_sends", 0),
        "errors": bot_stats.get("errors", 0)
    }

def start_health_server():
    """Start HTTP server for Render health checks"""
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="warning")

# =============================================================================
# CONFIGURATION SECTION - Render Ready
# =============================================================================
# Environment variables for security (set these in Render dashboard)
BOT_TOKEN = os.getenv("BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID", "")
DUMP_CHANNEL_ID = os.getenv("DUMP_CHANNEL_ID", "")

# Validate required environment variables
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required!")

# Global variables
fixed_anime_name = ""
dump_channel_id = DUMP_CHANNEL_ID
log_channel_id = LOG_CHANNEL_ID
CONFIG_FILE = "bot_config.json"

# =============================================================================
# LOGGING SETUP WITH ENHANCED FORMATTING
# =============================================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =============================================================================
# GLOBAL VARIABLES FOR PREFIX ROTATION AND SETTINGS
# =============================================================================
message_count = 0
prefixes = ["/leech -n", "/leech1 -n", "/leech2 -n", "/leechx -n", "/leech4 -n", "/leech3 -n", "/leech5 -n"]

# =============================================================================
# LOG CHANNEL SYSTEM
# =============================================================================
class LogChannelManager:
    """Enhanced logging system with Telegram channel integration"""
    def __init__(self, bot_context=None):
        self.bot_context = bot_context
        self.log_channel = log_channel_id
        self.message_buffer = []
        self.buffer_size = 10

    async def log_action(self, action_type, details, user_info=None, severity="INFO"):
        """Log action to both file and Telegram channel"""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        log_entry = {
            "timestamp": timestamp,
            "type": action_type,
            "severity": severity,
            "details": details,
            "user": user_info
        }
        log_msg = f"[{severity}] {action_type}: {details}"
        if user_info:
            log_msg += f" | User: {user_info}"

        if severity == "ERROR":
            logger.error(log_msg)
            bot_stats["errors"] += 1
        elif severity == "WARNING":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        if self.log_channel and self.bot_context:
            try:
                await self._send_to_log_channel(log_entry)
            except Exception as e:
                logger.error(f"Failed to send log to channel: {e}")

    async def _send_to_log_channel(self, log_entry):
        """Send formatted log to Telegram log channel"""
        try:
            severity_emoji = {
                "INFO": "ℹ️",
                "WARNING": "⚠️",
                "ERROR": "❌",
                "SUCCESS": "✅"
            }.get(log_entry["severity"], "📝")
            
            message = (
                f"{severity_emoji} **{log_entry['type']}**\n"
                f"🕒 {log_entry['timestamp']}\n"
                f"📄 {log_entry['details']}\n"
            )
            if log_entry.get("user"):
                message += f"👤 User: {log_entry['user']}\n"
            message += f"🔢 Stats: {bot_stats['messages_processed']} processed, {bot_stats['errors']} errors"
            
            await self.bot_context.bot.send_message(
                chat_id=self.log_channel,
                text=message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to send to log channel: {e}")

    async def log_bot_start(self):
        """Log bot startup"""
        await self.log_action(
            "BOT_STARTUP",
            f"Professional Anime Bot started successfully. Prefix count: {len(prefixes)}, Dump channel: {'✅' if dump_channel_id else '❌'}",
            severity="SUCCESS"
        )

    async def log_user_command(self, command, user_info, success=True):
        """Log user command execution"""
        severity = "SUCCESS" if success else "WARNING"
        await self.log_action(
            "COMMAND_EXECUTED",
            f"Command /{command} executed",
            user_info,
            severity
        )

    async def log_format_action(self, original, formatted, user_info, success=True):
        """Log caption formatting action"""
        if success:
            bot_stats["successful_formats"] += 1
            await self.log_action(
                "CAPTION_FORMATTED",
                f"Caption successfully formatted. Length: {len(original)} → {len(formatted)}",
                user_info,
                "SUCCESS"
            )
        else:
            bot_stats["failed_formats"] += 1
            await self.log_action(
                "FORMAT_FAILED",
                f"Failed to format caption: {original[:100]}...",
                user_info,
                "WARNING"
            )

    async def log_dump_channel_action(self, success, error_msg=None, user_info=None):
        """Log dump channel operations"""
        if success:
            bot_stats["dump_channel_sends"] += 1
            await self.log_action(
                "DUMP_CHANNEL_SUCCESS",
                "Caption sent to dump channel successfully",
                user_info,
                "SUCCESS"
            )
        else:
            bot_stats["dump_channel_fails"] += 1
            await self.log_action(
                "DUMP_CHANNEL_FAILED",
                f"Dump channel send failed: {error_msg}",
                user_info,
                "ERROR"
            )

    async def send_stats_report(self):
        """Send periodic stats report"""
        uptime = datetime.now(timezone.utc) - bot_stats["start_time"]
        stats_msg = (
            f"📊 **Bot Statistics Report**\n\n"
            f"⏰ **Uptime:** {uptime.days}d {uptime.seconds//3600}h {(uptime.seconds//60)%60}m\n"
            f"📈 **Messages Processed:** {bot_stats['messages_processed']}\n"
            f"✅ **Successful Formats:** {bot_stats['successful_formats']}\n"
            f"❌ **Failed Formats:** {bot_stats['failed_formats']}\n"
            f"📤 **Dump Channel Sends:** {bot_stats['dump_channel_sends']}\n"
            f"🔴 **Dump Channel Fails:** {bot_stats['dump_channel_fails']}\n"
            f"⚠️ **Total Errors:** {bot_stats['errors']}\n\n"
            f"🎯 **Success Rate:** {(bot_stats['successful_formats']/(bot_stats['successful_formats']+bot_stats['failed_formats'])*100) if (bot_stats['successful_formats']+bot_stats['failed_formats']) > 0 else 0:.1f}%\n"
            f"📱 **Current Config:** {len(prefixes)} prefixes, Dump: {'✅' if dump_channel_id else '❌'}"
        )
        if self.log_channel and self.bot_context:
            try:
                await self.bot_context.bot.send_message(
                    chat_id=self.log_channel,
                    text=stats_msg,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to send stats report: {e}")

# Initialize log manager
log_manager = LogChannelManager()

# =============================================================================
# CONFIGURATION MANAGEMENT - Enhanced for Render
# =============================================================================
def save_config():
    """Save bot configuration to file (works on Render ephemeral storage)"""
    config = {
        "fixed_anime_name": fixed_anime_name,
        "prefixes": prefixes,
        "dump_channel_id": dump_channel_id,
        "message_count": message_count,
        "log_channel_id": log_channel_id,
        "stats": bot_stats.copy()
    }
    if "start_time" in config["stats"]:
        config["stats"]["start_time"] = config["stats"]["start_time"].isoformat()
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info("Configuration saved successfully")
    except Exception as e:
        logger.error(f"Failed to save config: {e}")

def load_config():
    """Load bot configuration from file"""
    global fixed_anime_name, prefixes, dump_channel_id, message_count, log_channel_id
    if not os.path.exists(CONFIG_FILE):
        save_config()
        return
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        fixed_anime_name = config.get("fixed_anime_name", "")
        prefixes = config.get("prefixes", ["/leech -n", "/leech1 -n", "/leech2 -n", "/leechx -n", "/leech4 -n", "/leech3 -n", "/leech5 -n"])
        dump_channel_id = config.get("dump_channel_id", DUMP_CHANNEL_ID)
        log_channel_id = config.get("log_channel_id", LOG_CHANNEL_ID)
        message_count = config.get("message_count", 0)
        if "stats" in config:
            saved_stats = config["stats"]
            if "start_time" in saved_stats and isinstance(saved_stats["start_time"], str):
                try:
                    bot_stats.update(saved_stats)
                    bot_stats["start_time"] = datetime.fromisoformat(saved_stats["start_time"])
                except:
                    bot_stats["start_time"] = datetime.now(timezone.utc)
        logger.info("Configuration loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        save_config()

# =============================================================================
# QUALITY ORDERING CONFIGURATION (Same as original)
# =============================================================================
QUALITY_ORDER = ["480P", "720P", "1080P"]

class AnimeParser:
    """Enhanced anime caption parser with multiple format support and professional quality handling"""
    def __init__(self):
        self.patterns = {
            'bracket_se': r'\[S(\d+)\s*E(\d+)\]',
            'bracket_sep': r'\[S(\d+)\s*EP(\d+)\]',
            'channel_se': r'@\w+\s*-\s*(.+?)\s+S(\d+)\s*EP(\d+)',
            'channel_bracket': r'@\w+\s*-\s*\[S(\d+)\s*EP(\d+)\]\s*(.+?)(?:\s*\[|$)',
            'structured_emoji': r'📺\s*([^\[]+)\s*\[S(\d+)\]',
            'simple_se': r'S(\d+)\s*E(\d+)',
            'simple_ep': r'S(\d+)\s*EP(\d+)',
        }

    def extract_episode_info(self, text):
        """Extract season, episode, and anime name from various formats"""
        season = "01"
        episode = "01"
        anime_name = ""
        clean_text = text.strip()
        if "📺" in clean_text and "Eᴘɪꜱᴏᴅᴇ" in clean_text:
            return self._parse_structured_format(clean_text)
        for pattern_name in ['channel_se', 'channel_bracket']:
            pattern = self.patterns[pattern_name]
            match = re.search(pattern, clean_text, re.IGNORECASE)
            if match:
                if pattern_name == 'channel_se':
                    anime_name, season, episode = match.groups()
                else:
                    season, episode, anime_name = match.groups()
                return season.zfill(2), episode.zfill(2), anime_name.strip()
        for pattern_name in ['bracket_se', 'bracket_sep']:
            pattern = self.patterns[pattern_name]
            match = re.search(pattern, clean_text, re.IGNORECASE)
            if match:
                season, episode = match.groups()
                anime_name = re.split(r'\[S\d+', clean_text, flags=re.IGNORECASE)[0].strip()
                return season.zfill(2), episode.zfill(2), anime_name
        for pattern_name in ['simple_se', 'simple_ep']:
            pattern = self.patterns[pattern_name]
            match = re.search(pattern, clean_text, re.IGNORECASE)
            if match:
                season, episode = match.groups()
                anime_name = re.split(r'S\d+', clean_text, flags=re.IGNORECASE)[0].strip()
                return season.zfill(2), episode.zfill(2), anime_name
        return season, episode, clean_text

    def _parse_structured_format(self, text):
        """Parse structured format with emojis"""
        season = "01"
        episode = "01"
        anime_name = ""
        title_match = re.search(r'📺\s*([^\[]+)\s*\[S(\d+)\]', text, re.IGNORECASE)
        if title_match:
            anime_name = title_match.group(1).strip()
            season = title_match.group(2).zfill(2)
        episode_match = re.search(r'Eᴘɪꜱᴏᴅᴇ\s*:\s*(\d+)', text, re.IGNORECASE)
        if episode_match:
            episode = episode_match.group(1).zfill(2)
        return season, episode, anime_name

    def extract_quality(self, text):
        """Extract video quality from text and ensure it ends with 'P'"""
        quality_patterns = [
            r'(\d+)[pP]',
            r'\[(\d+)[pP]?\]',
            r'Qᴜᴀʟɪᴛʏ\s*:\s*(\d+)[pP]?',
            r'QUALITY\s*:\s*(\d+)[pP]?',
            r'(\d+)\s*[pP]',
        ]
        for pattern in quality_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                quality_number = match.group(1)
                if int(quality_number) in [144, 240, 360, 480, 720, 1080, 1440, 2160]:
                    return f"{quality_number}P"
        return "720P"

    def extract_language(self, text):
        """Extract language/audio information"""
        language_mappings = {
            'தமிழ்': 'Tam',
            'tamil': 'Tam',
            'tam': 'Tam',
            'english': 'Eng',
            'eng': 'Eng',
            'multi audio': 'Multi',
            'multi': 'Multi',
            'dual audio': 'Dual',
            'dual': 'Dual',
        }
        audio_match = re.search(r'(?:Aᴜᴅɪᴏ|Audio)\s*:\s*([^,\n\]]+)', text, re.IGNORECASE)
        if audio_match:
            audio_text = audio_match.group(1).strip().lower()
            for key, value in language_mappings.items():
                if key in audio_text:
                    return value
        text_lower = text.lower()
        for key, value in language_mappings.items():
            if key in text_lower:
                return value
        return ""

    def clean_anime_name(self, name):
        """Clean and standardize anime name"""
        if not name:
            return ""
        name = re.sub(r'^@\w+\s*-\s*', '', name, flags=re.IGNORECASE)
        unwanted_patterns = [
            r'\[.*?\]',
            r'\(.*?\)',
            r'^\s*-\s*',
            r'\s*-\s*$',
        ]
        for pattern in unwanted_patterns:
            name = re.sub(pattern, '', name, flags=re.IGNORECASE)
        replacements = {
            'Tamil': 'Tam',
            'English': 'Eng',
            'Dubbed': 'Dub',
            'Subbed': 'Sub',
        }
        for old, new in replacements.items():
            name = re.sub(rf'\b{old}\b', new, name, flags=re.IGNORECASE)
        name = re.sub(r'[!@#$%^&*(),.?":{}|<>]', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        return name

async def parse_caption(caption: str, user_info=None) -> str:
    """Enhanced caption parser with logging"""
    global message_count, fixed_anime_name
    message_count += 1
    bot_stats["messages_processed"] += 1
    if not caption:
        return ""
    parser = AnimeParser()
    original_caption = caption.strip()
    try:
        clean_caption = original_caption
        if " - " in clean_caption and clean_caption.startswith("@"):
            parts = clean_caption.split(" - ", 1)
            if len(parts) > 1:
                clean_caption = parts[1]
        season, episode, extracted_name = parser.extract_episode_info(original_caption)
        quality = parser.extract_quality(original_caption)
        language = parser.extract_language(original_caption)
        if fixed_anime_name:
            anime_name = fixed_anime_name
        else:
            anime_name = parser.clean_anime_name(extracted_name) or "Unknown Anime"
        if language and language not in anime_name:
            anime_name = f"{anime_name} {language}".strip()
        season_episode = f"[S{season}-E{episode}]"
        extension = ".mkv"
        if ".mp4" in original_caption.lower():
            extension = ".mp4"
        elif ".avi" in original_caption.lower():
            extension = ".avi"
        if prefixes:
            prefix_index = (message_count - 1) // 3 % len(prefixes)
            current_prefix = prefixes[prefix_index]
        else:
            current_prefix = "/leech -n"
        formatted_caption = f"{current_prefix} {season_episode} {anime_name} [{quality}] [Single]{extension}"
        await log_manager.log_format_action(original_caption, formatted_caption, user_info, True)
        return formatted_caption
    except Exception as e:
        await log_manager.log_format_action(original_caption, "", user_info, False)
        logger.error(f"Caption parsing error: {e}\n{traceback.format_exc()}")
        return ""

# =============================================================================
# ENHANCED DUMP CHANNEL FUNCTIONALITY WITH LOGGING
# =============================================================================
async def send_to_dump_channel(context: ContextTypes.DEFAULT_TYPE, message, formatted_caption, user_info=None):
    """Send formatted caption to dump channel with enhanced logging"""
    global dump_channel_id
    if not dump_channel_id:
        return False, "Dump channel not configured"
    max_retries = 3
    retry_count = 0
    while retry_count < max_retries:
        try:
            await context.bot.send_message(
                chat_id=dump_channel_id,
                text=f"📤 **Auto-formatted Caption**\n\n`{formatted_caption}`\n\n⏰ Processed at: {message.date}\n👤 User: {user_info or 'Unknown'}",
                parse_mode='Markdown'
            )
            logger.info(f"Successfully sent to dump channel: {dump_channel_id}")
            await log_manager.log_dump_channel_action(True, None, user_info)
            return True, "Success"
        except TelegramError as e:
            retry_count += 1
            logger.warning(f"Failed to send to dump channel (attempt {retry_count}): {e}")
            if "chat not found" in str(e).lower():
                await log_manager.log_dump_channel_action(False, "Channel not found", user_info)
                return False, "Dump channel not found"
            elif "not enough rights" in str(e).lower():
                await log_manager.log_dump_channel_action(False, "Insufficient permissions", user_info)
                return False, "Bot lacks permissions in dump channel"
            elif retry_count >= max_retries:
                await log_manager.log_dump_channel_action(False, f"Max retries exceeded: {e}", user_info)
                return False, f"Failed after {max_retries} attempts: {e}"
        except Exception as e:
            logger.error(f"Unexpected error sending to dump channel: {e}")
            await log_manager.log_dump_channel_action(False, f"Unexpected error: {e}", user_info)
            return False, f"Unexpected error: {e}"
    return False, "Max retries exceeded"

# =============================================================================
# ENHANCED BOT COMMAND HANDLERS WITH LOGGING
# =============================================================================
async def setup_commands(application):
    """Set up bot commands menu with new log channel commands"""
    commands = [
        BotCommand("start", "🚀 Start the bot and see instructions"),
        BotCommand("name", "📝 Set/view anime name (fixed or auto-detect)"),
        BotCommand("format", "🔧 Test caption formatting on any text"),
        BotCommand("status", "📊 Show bot status and current settings"),
        BotCommand("stats", "📈 Detailed statistics and performance metrics"),
        BotCommand("help", "❓ Show detailed help and examples"),
        BotCommand("quality", "🎥 Show supported quality formats"),
        BotCommand("addprefix", "➕ Add new prefix to rotation"),
        BotCommand("prefixlist", "📋 Show all current prefixes"),
        BotCommand("delprefix", "➖ Delete prefix from rotation"),
        BotCommand("dumpchannel", "📤 Set/check dump channel"),
        BotCommand("dumpstatus", "📡 Check dump channel status"),
        BotCommand("logchannel", "📋 Set/check log channel for monitoring"),
        BotCommand("logs", "📊 Send stats report to log channel"),
    ]
    await application.bot.set_my_commands(commands)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced start command with log channel info"""
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    try:
        await setup_commands(context.application)
    except Exception as e:
        logger.warning(f"Command menu setup: {e}")
    welcome_message = (
        "🎬 **Professional Anime Caption Formatter** 🎬\n\n"
        "Enhanced with prefix management, dump channel, and log channel monitoring!\n\n"
        "**✨ Key Features:**\n"
        "• Professional quality formatting (480P, 720P, 1080P)\n"
        "• Dynamic prefix management\n"
        "• Dump channel integration\n"
        "• Log channel monitoring for all actions\n"
        "• Multiple input format support\n"
        "• Language detection (Tamil, English, Multi)\n"
        "• Detailed statistics and performance metrics\n\n"
        "**🎯 Quality Order:** 480P → 720P → 1080P\n\n"
        "**📝 Enhanced Commands:**\n"
        "• `/logchannel ID` - Set log monitoring channel\n"
        "• `/stats` - Detailed performance statistics\n"
        "• `/logs` - Send stats report to log channel\n"
        "• `/addprefix PREFIX` - Add new prefix\n"
        "• `/dumpchannel ID` - Set dump channel\n\n"
        "**🔥 Render Ready:** Optimized for cloud deployment\n\n"
        "**🚀 Usage:** Send videos/documents with captions!"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')
    await log_manager.log_user_command("start", user_info)

async def name_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /name command for setting fixed anime name"""
    global fixed_anime_name
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    
    if not context.args:
        current_name = fixed_anime_name or "Auto-detect (from captions)"
        await update.message.reply_text(
            f"📝 **Anime Name Setting**\n\n"
            f"**Current:** {current_name}\n\n"
            f"**Usage:**\n"
            f"• `/name Your Anime Name` - Set fixed name\n"
            f"• `/name reset` - Enable auto-detection\n\n"
            f"**Examples:**\n"
            f"• `/name Naruto Shippuden`\n"
            f"• `/name One Piece Tam`\n"
            f"• `/name reset`",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_user_command("name", user_info)
        return
    
    name_input = ' '.join(context.args).strip()
    
    if name_input.lower() == "reset":
        fixed_anime_name = ""
        save_config()
        await update.message.reply_text(
            "✅ **Auto-detection enabled!**\n\n"
            "Anime names will now be extracted from captions automatically.",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_action("NAME_RESET", "Auto-detection enabled", user_info, "SUCCESS")
    else:
        fixed_anime_name = name_input
        save_config()
        await update.message.reply_text(
            f"✅ **Fixed anime name set!**\n\n"
            f"**Name:** {fixed_anime_name}\n\n"
            f"All captions will now use this name instead of auto-detection.",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_action("NAME_SET", f"Fixed name set to: {fixed_anime_name}", user_info, "SUCCESS")
    
    await log_manager.log_user_command("name", user_info)

async def format_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /format command for testing caption formatting"""
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    
    if not context.args:
        await update.message.reply_text(
            "🔧 **Test Caption Formatting**\n\n"
            "**Usage:** `/format YOUR_CAPTION_TEXT`\n\n"
            "**Example:**\n"
            "`/format @channel - Naruto S01 EP05 [720p] Tamil`\n\n"
            "**Supported formats:**\n"
            "• `@channel - Anime Name S01 EP05`\n"
            "• `[S01E05] Anime Name [720p]`\n"
            "• `📺 Anime Name [S01] Episode: 5`\n"
            "• And many more!",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_user_command("format", user_info, False)
        return
    
    test_caption = ' '.join(context.args)
    formatted = await parse_caption(test_caption, user_info)
    
    if formatted:
        await update.message.reply_text(
            f"🔧 **Format Test Result**\n\n"
            f"**Original:**\n`{test_caption}`\n\n"
            f"**Formatted:**\n`{formatted}`\n\n"
            f"✅ Successfully parsed and formatted!",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
    else:
        await update.message.reply_text(
            f"❌ **Format Test Failed**\n\n"
            f"**Input:**\n`{test_caption}`\n\n"
            f"Could not parse this format. Try a different caption structure or check `/help` for supported formats.",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
    
    await log_manager.log_user_command("format", user_info)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command - current bot status"""
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    
    uptime = datetime.now(timezone.utc) - bot_stats["start_time"]
    
    status_message = (
        f"📊 **Bot Status**\n\n"
        f"🟢 **Status:** Online & Active\n"
        f"⏰ **Uptime:** {uptime.days}d {uptime.seconds//3600}h {(uptime.seconds//60)%60}m\n\n"
        f"**Current Configuration:**\n"
        f"• **Anime Name:** {fixed_anime_name or 'Auto-detect'}\n"
        f"• **Active Prefixes:** {len(prefixes)}\n"
        f"• **Dump Channel:** {'✅ Active' if dump_channel_id else '❌ Not set'}\n"
        f"• **Log Channel:** {'✅ Active' if log_channel_id else '❌ Not set'}\n\n"
        f"**Quick Stats:**\n"
        f"• Messages processed: {bot_stats['messages_processed']}\n"
        f"• Success rate: {(bot_stats['successful_formats']/(bot_stats['successful_formats']+bot_stats['failed_formats'])*100) if (bot_stats['successful_formats']+bot_stats['failed_formats']) > 0 else 0:.1f}%\n\n"
        f"Use `/stats` for detailed metrics"
    )
    
    await update.message.reply_text(
        status_message,
        parse_mode='Markdown',
        reply_to_message_id=update.message.message_id
    )
    await log_manager.log_user_command("status", user_info)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command - detailed help"""
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    
    help_message = (
        "❓ **Professional Anime Bot Help**\n\n"
        "**🎬 Main Function:**\nSend videos/documents with captions to get professionally formatted captions!\n\n"
        "**📝 Supported Input Formats:**\n"
        "• `@channel - Anime Name S01 EP05 [720p]`\n"
        "• `[S01E05] Anime Name [1080p] Tamil`\n"
        "• `📺 Anime Name [S01] Episode: 5 Quality: 720p`\n"
        "• `Anime Name S1 E5 Multi Audio`\n\n"
        "**🔧 Commands:**\n"
        "• `/name ANIME` - Set fixed anime name\n"
        "• `/format TEXT` - Test formatting\n"
        "• `/addprefix PREFIX` - Add new prefix\n"
        "• `/prefixlist` - View all prefixes\n"
        "• `/delprefix NUM` - Delete prefix by number\n"
        "• `/dumpchannel ID` - Set dump channel\n"
        "• `/logchannel ID` - Set log channel\n"
        "• `/stats` - Detailed statistics\n"
        "• `/status` - Current bot status\n\n"
        "**🎥 Quality Detection:**\n480P, 720P, 1080P (auto-detected)\n\n"
        "**🌍 Language Support:**\nTamil, English, Multi, Dual (auto-detected)\n\n"
        "**💡 Tips:**\n"
        "• Set fixed name with `/name` for consistency\n"
        "• Use dump channel to collect all formatted captions\n"
        "• Log channel tracks all bot activity"
    )
    
    await update.message.reply_text(
        help_message,
        parse_mode='Markdown',
        reply_to_message_id=update.message.message_id
    )
    await log_manager.log_user_command("help", user_info)

async def quality_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /quality command - show quality info"""
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    
    quality_message = (
        "🎥 **Video Quality Support**\n\n"
        "**🎯 Priority Order:**\n"
        "1. **480P** - Standard Definition\n"
        "2. **720P** - High Definition (Default)\n"
        "3. **1080P** - Full HD\n\n"
        "**📱 Detection Patterns:**\n"
        "• `[720p]`, `720P`, `720`\n"
        "• `Quality: 1080p`\n"
        "• `Qᴜᴀʟɪᴛʏ: 480P`\n\n"
        "**⚡ Auto-Detection:**\n"
        "The bot automatically detects quality from captions and formats accordingly. If no quality is found, defaults to **720P**.\n\n"
        "**✅ Supported Qualities:**\n"
        "144P, 240P, 360P, 480P, 720P, 1080P, 1440P, 2160P"
    )
    
    await update.message.reply_text(
        quality_message,
        parse_mode='Markdown',
        reply_to_message_id=update.message.message_id
    )
    await log_manager.log_user_command("quality", user_info)

async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send stats report to log channel"""
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    if not log_channel_id:
        await update.message.reply_text(
            "❌ **Log channel not configured!**\n\n"
            "Use `/logchannel CHANNEL_ID` to set up log monitoring first.",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        return
    await log_manager.send_stats_report()
    await update.message.reply_text(
        "✅ **Stats report sent to log channel!**\n\n"
        "Check your log channel for detailed performance metrics.",
        parse_mode='Markdown',
        reply_to_message_id=update.message.message_id
    )
    await log_manager.log_user_command("logs", user_info)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command - detailed statistics"""
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    uptime = datetime.now(timezone.utc) - bot_stats["start_time"]
    success_rate = (bot_stats['successful_formats']/(bot_stats['successful_formats']+bot_stats['failed_formats'])*100) if (bot_stats['successful_formats']+bot_stats['failed_formats']) > 0 else 0
    stats_message = (
        f"📊 **Detailed Bot Statistics**\n\n"
        f"⏰ **Uptime:** {uptime.days}d {uptime.seconds//3600}h {(uptime.seconds//60)%60}m\n"
        f"🚀 **Started:** {bot_stats['start_time'].strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"📈 **Processing Stats:**\n"
        f"• Messages processed: **{bot_stats['messages_processed']}**\n"
        f"• Successful formats: **{bot_stats['successful_formats']}**\n"
        f"• Failed formats: **{bot_stats['failed_formats']}**\n"
        f"• Success rate: **{success_rate:.1f}%**\n\n"
        f"📤 **Dump Channel Stats:**\n"
        f"• Successful sends: **{bot_stats['dump_channel_sends']}**\n"
        f"• Failed sends: **{bot_stats['dump_channel_fails']}**\n\n"
        f"⚙️ **Current Config:**\n"
        f"• Anime name: **{fixed_anime_name or 'Auto-detect'}**\n"
        f"• Prefixes: **{len(prefixes)}** total\n"
        f"• Dump channel: **{'✅ Active' if dump_channel_id else '❌ Not set'}**\n"
        f"• Log channel: **{'✅ Active' if log_channel_id else '❌ Not set'}**\n\n"
        f"🔥 **Total Errors:** {bot_stats['errors']}"
    )
    await update.message.reply_text(
        stats_message,
        parse_mode='Markdown',
        reply_to_message_id=update.message.message_id
    )
    await log_manager.log_user_command("stats", user_info)

async def logchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /logchannel command"""
    global log_channel_id
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    if not context.args:
        current_channel = log_channel_id or "Not configured"
        await update.message.reply_text(
            f"📋 **Log Channel Settings**\n\n"
            f"**Current channel:** `{current_channel}`\n\n"
            f"**Usage:**\n"
            f"• `/logchannel CHANNEL_ID` - Set log channel\n"
            f"• `/logchannel reset` - Remove log channel\n\n"
            f"**Examples:**\n"
            f"• `/logchannel -1001234567890`\n"
            f"• `/logchannel @logchannelname`\n"
            f"• `/logchannel reset`",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_user_command("logchannel", user_info)
        return
    channel_input = ' '.join(context.args).strip()
    if channel_input.lower() == "reset":
        log_channel_id = ""
        log_manager.log_channel = ""
        save_config()
        await update.message.reply_text(
            "✅ **Log channel reset!**\n\n"
            "Log channel monitoring disabled.\n"
            "Use `/logchannel ID` to set a new channel.",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_user_command("logchannel_reset", user_info)
        return
    if channel_input.startswith('-') or channel_input.startswith('@'):
        log_channel_id = channel_input
        log_manager.log_channel = channel_input
        log_manager.bot_context = context
        save_config()
        await update.message.reply_text(
            f"✅ **Log channel set successfully!**\n\n"
            f"**Channel ID:** `{log_channel_id}`\n"
            f"**Status:** Monitoring active\n\n"
            f"All bot actions will now be logged to this channel.",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_action(
            "LOG_CHANNEL_CONFIGURED",
            f"Log channel set to {log_channel_id} by user",
            user_info,
            "SUCCESS"
        )
        await log_manager.log_user_command("logchannel_set", user_info)
    else:
        await update.message.reply_text(
            f"❌ **Invalid channel format!**\n\n"
            f"**Valid formats:**\n"
            f"• `-1001234567890` (Channel ID)\n"
            f"• `@channelname` (Username)\n\n"
            f"**Your input:** `{channel_input}`",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )

async def addprefix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addprefix command with logging"""
    global prefixes
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    if not context.args:
        await update.message.reply_text(
            "➕ **Add New Prefix**\n\n"
            "**Usage:** `/addprefix YOUR_PREFIX`\n\n"
            "**Examples:**\n"
            "• `/addprefix /mirror -n`\n"
            "• `/addprefix /clone -n`\n"
            "• `/addprefix /leech6 -n`\n\n"
            f"**Current prefixes:** {len(prefixes)}",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_user_command("addprefix", user_info, False)
        return
    new_prefix = ' '.join(context.args).strip()
    if new_prefix in prefixes:
        await update.message.reply_text(
            f"⚠️ **Prefix already exists!**\n\n"
            f"**Prefix:** `{new_prefix}`\n"
            f"**Position:** {prefixes.index(new_prefix) + 1}",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_user_command("addprefix", user_info, False)
        return
    prefixes.append(new_prefix)
    save_config()
    await update.message.reply_text(
        f"✅ **Prefix added successfully!**\n\n"
        f"**New prefix:** `{new_prefix}`\n"
        f"**Total prefixes:** {len(prefixes)}\n"
        f"**Position:** {len(prefixes)}",
        parse_mode='Markdown',
        reply_to_message_id=update.message.message_id
    )
    await log_manager.log_action("PREFIX_ADDED", f"New prefix added: {new_prefix}", user_info, "SUCCESS")
    await log_manager.log_user_command("addprefix", user_info)

async def prefixlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /prefixlist command with logging"""
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    if not prefixes:
        await update.message.reply_text(
            "❌ **No prefixes configured!**\n\n"
            "Use `/addprefix PREFIX` to add your first prefix.",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_user_command("prefixlist", user_info)
        return
    prefix_list = "\n".join([f"{i+1}. `{prefix}`" for i, prefix in enumerate(prefixes)])
    await update.message.reply_text(
        f"📋 **Current Prefix List**\n\n"
        f"{prefix_list}\n\n"
        f"**Total:** {len(prefixes)} prefixes\n"
        f"**Rotation:** Every 3 messages\n\n"
        f"**Commands:**\n"
        f"• `/addprefix PREFIX` - Add new\n"
        f"• `/delprefix INDEX` - Delete by number",
        parse_mode='Markdown',
        reply_to_message_id=update.message.message_id
    )
    await log_manager.log_user_command("prefixlist", user_info)

async def delprefix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /delprefix command with logging"""
    global prefixes
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    if not context.args:
        if not prefixes:
            await update.message.reply_text(
                "❌ **No prefixes to delete!**\n\n"
                "Use `/addprefix PREFIX` to add prefixes first.",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
            await log_manager.log_user_command("delprefix", user_info, False)
            return
        prefix_list = "\n".join([f"{i+1}. `{prefix}`" for i, prefix in enumerate(prefixes)])
        await update.message.reply_text(
            f"➖ **Delete Prefix**\n\n"
            f"**Usage:** `/delprefix INDEX_NUMBER`\n\n"
            f"**Current prefixes:**\n{prefix_list}\n\n"
            f"**Example:** `/delprefix 3` (deletes 3rd prefix)",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_user_command("delprefix", user_info, False)
        return
    try:
        index = int(context.args[0]) - 1
        if index < 0 or index >= len(prefixes):
            await update.message.reply_text(
                f"❌ **Invalid index!**\n\n"
                f"**Valid range:** 1 to {len(prefixes)}\n"
                f"**You entered:** {index + 1}",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
            await log_manager.log_user_command("delprefix", user_info, False)
            return
        deleted_prefix = prefixes.pop(index)
        save_config()
        await update.message.reply_text(
            f"✅ **Prefix deleted successfully!**\n\n"
            f"**Deleted:** `{deleted_prefix}`\n"
            f"**Remaining:** {len(prefixes)} prefixes",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_action("PREFIX_DELETED", f"Prefix deleted: {deleted_prefix}", user_info, "SUCCESS")
        await log_manager.log_user_command("delprefix", user_info)
    except ValueError:
        await update.message.reply_text(
            f"❌ **Invalid number!**\n\n"
            f"Please enter a valid number.\n"
            f"**Example:** `/delprefix 2`",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_user_command("delprefix", user_info, False)

async def dumpchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /dumpchannel command with logging"""
    global dump_channel_id
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    if not context.args:
        current_channel = dump_channel_id or "Not configured"
        await update.message.reply_text(
            f"📤 **Dump Channel Settings**\n\n"
            f"**Current channel:** `{current_channel}`\n\n"
            f"**Usage:**\n"
            f"• `/dumpchannel CHANNEL_ID` - Set dump channel\n"
            f"• `/dumpchannel reset` - Remove dump channel\n\n"
            f"**Examples:**\n"
            f"• `/dumpchannel -1001234567890`\n"
            f"• `/dumpchannel @channelname`\n"
            f"• `/dumpchannel reset`",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_user_command("dumpchannel", user_info)
        return
    channel_input = ' '.join(context.args).strip()
    if channel_input.lower() == "reset":
        dump_channel_id = ""
        save_config()
        await update.message.reply_text(
            "✅ **Dump channel reset!**\n\n"
            "Dump channel functionality disabled.\n"
            "Use `/dumpchannel ID` to set a new channel.",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_action("DUMP_CHANNEL_RESET", "Dump channel disabled", user_info, "SUCCESS")
        await log_manager.log_user_command("dumpchannel", user_info)
        return
    if channel_input.startswith('-') or channel_input.startswith('@'):
        dump_channel_id = channel_input
        save_config()
        await update.message.reply_text(
            f"✅ **Dump channel set successfully!**\n\n"
            f"**Channel ID:** `{dump_channel_id}`\n"
            f"**Status:** Active\n\n"
            f"All formatted captions will be sent to this channel.",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_action("DUMP_CHANNEL_SET", f"Dump channel set to {dump_channel_id}", user_info, "SUCCESS")
        await log_manager.log_user_command("dumpchannel", user_info)
    else:
        await update.message.reply_text(
            f"❌ **Invalid channel format!**\n\n"
            f"**Valid formats:**\n"
            f"• `-1001234567890` (Channel ID)\n"
            f"• `@channelname` (Username)\n\n"
            f"**Your input:** `{channel_input}`",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        await log_manager.log_user_command("dumpchannel", user_info, False)

async def dumpstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /dumpstatus command"""
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    
    if not dump_channel_id:
        await update.message.reply_text(
            "📡 **Dump Channel Status**\n\n"
            "❌ **Not configured**\n\n"
            "Use `/dumpchannel CHANNEL_ID` to set up dump channel functionality.",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
    else:
        # Test connection to dump channel
        try:
            test_msg = await context.bot.send_message(
                chat_id=dump_channel_id,
                text="🔄 **Connection Test**\n\nDump channel is working properly!",
                parse_mode='Markdown'
            )
            await update.message.reply_text(
                f"📡 **Dump Channel Status**\n\n"
                f"✅ **Active & Connected**\n"
                f"**Channel:** `{dump_channel_id}`\n"
                f"**Successful sends:** {bot_stats['dump_channel_sends']}\n"
                f"**Failed sends:** {bot_stats['dump_channel_fails']}\n\n"
                f"Test message sent successfully!",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
        except Exception as e:
            await update.message.reply_text(
                f"📡 **Dump Channel Status**\n\n"
                f"❌ **Connection Failed**\n"
                f"**Channel:** `{dump_channel_id}`\n"
                f"**Error:** {str(e)}\n\n"
                f"Please check channel ID and bot permissions.",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
    
    await log_manager.log_user_command("dumpstatus", user_info)

# Enhanced message handlers with logging
async def handle_media_with_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle video/document/file messages with captions - Enhanced with logging"""
    message = update.message
    original_caption = message.caption
    user_info = f"{update.effective_user.first_name} (@{update.effective_user.username})" if update.effective_user.username else update.effective_user.first_name
    if not original_caption:
        return
    logger.info(f"Received caption from {user_info}: {original_caption}")
    formatted_caption = await parse_caption(original_caption, user_info)
    if formatted_caption and formatted_caption != original_caption:
        logger.info(f"Formatted caption: {formatted_caption}")
        dump_success = False
        dump_message = ""
        if dump_channel_id:
            dump_success, dump_message = await send_to_dump_channel(context, message, formatted_caption, user_info)
        response_text = f"\n`{formatted_caption}`\n"
        if dump_channel_id:
            if dump_success:
                response_text += "📤 **Sent to dump channel:** ✅\n"
            else:
                response_text += f"📤 **Dump channel failed:** {dump_message}\n"
        response_text += f"📊 **Processed:** {bot_stats['messages_processed']} total\n"
        response_text += "📋 Use `/stats` for detailed metrics"
        await message.reply_text(
            response_text,
            parse_mode='Markdown',
            reply_to_message_id=message.message_id
        )
        save_config()
    else:
        await message.reply_text(
            "❌ **Parsing Failed**\n\n"
            "Could not parse the caption format.\n"
            "Try `/format YOUR_TEXT` to test or `/help` for supported formats.",
            parse_mode='Markdown',
            reply_to_message_id=message.message_id
        )

# Initialize log manager properly and set up periodic stats
async def init_log_manager(context):
    """Initialize log manager with context"""
    log_manager.bot_context = context
    await log_manager.log_bot_start()

async def periodic_stats_task(context):
    """Send periodic stats to log channel every 6 hours"""
    while True:
        try:
            await asyncio.sleep(21600)  # 6 hours
            if log_channel_id:
                await log_manager.send_stats_report()
        except Exception as e:
            logger.error(f"Periodic stats error: {e}")

# =============================================================================
# ERROR HANDLING
# =============================================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors during polling"""
    logger.error(f"Error occurred: {context.error}")
    bot_stats["errors"] += 1
    
    if hasattr(context, 'error') and context.error:
        await log_manager.log_action(
            "BOT_ERROR",
            f"Unexpected error: {str(context.error)}",
            severity="ERROR"
        )

# =============================================================================
# MAIN APPLICATION - RENDER READY WITH HTTP SERVER
# =============================================================================
def main():
    """Start the professional bot - Render optimized with HTTP health check"""
    if not BOT_TOKEN:
        print("❌ Error: Please set your BOT_TOKEN environment variable!")
        print("Set BOT_TOKEN in Render dashboard environment variables")
        return

    print("🚀 Starting Enhanced Professional Anime Caption Formatter Bot...")
    print("🌐 Render Deployment: HTTP server + Telegram bot")
    print("📋 Features: Log channel monitoring, Stats tracking, Dump channel")

    # Start HTTP server in background thread for Render
    print(f"🌐 Starting HTTP health server on port {os.environ.get('PORT', 10000)}...")
    health_thread = Thread(target=start_health_server, daemon=True)
    health_thread.start()

    # Load configuration
    load_config()
    print(f"⚙️ Config loaded: {len(prefixes)} prefixes")
    print(f"📤 Dump channel: {'✅ Set' if dump_channel_id else '❌ Not set'}")
    print(f"📋 Log channel: {'✅ Set' if log_channel_id else '❌ Not set'}")

    # Create application  application.add_handler(CommandHandler("
    application = Application.builder().token(BOT_TOKEN).build()

    # Add error handler
    application.add_error_handler(error_handler)

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("name", name_command))
    application.add_handler(CommandHandler("format", format_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("quality", quality_command))
    application.add_handler(CommandHandler("addprefix", addprefix_command))
    application.add_handler(CommandHandler("prefixlist", prefixlist_command))
    application.add_handler(CommandHandler("delprefix", delprefix_command))
    application.add_handler(CommandHandler("dumpchannel", dumpchannel_command))
    application.add_handler(CommandHandler("dumpstatus", dumpstatus_command))
    application.add_handler(CommandHandler("logchannel", logchannel_command))
    application.add_handler(CommandHandler("logs", logs_command))

    # Add media handlers
    application.add_handler(MessageHandler(
        filters.Document.ALL & filters.CAPTION,
        handle_media_with_caption
    ))
    application.add_handler(MessageHandler(
        filters.VIDEO & filters.CAPTION,
        handle_media_with_caption
    ))
    application.add_handler(MessageHandler(
        filters.PHOTO & filters.CAPTION,
        handle_media_with_caption
    ))

    # Initialize log manager after application is created
    async def post_init(application):
        await init_log_manager(application)
        # Start periodic stats task
        asyncio.create_task(periodic_stats_task(application))

    application.post_init = post_init

    print("✅ Enhanced Professional bot is running on Render!")
    print("🌐 HTTP health check server: Active")
    print("📊 Log channel monitoring: Active")
    print("🔥 All actions will be tracked and logged")
    print("📱 Command Menu: Available via Telegram")

    # Run the bot
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
        save_config()
    except Exception as e:
        logger.error(f"Bot error: {e}")
        save_config()

if __name__ == '__main__':
    main()
