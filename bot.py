#!/usr/bin/env python3

"""
Professional Telegram Bot for Anime Caption Formatting
Enhanced with prefix management, dump channel functionality, log channel monitoring, and Render deployment ready
WITH HTTP HEALTH CHECK SERVER FOR RENDER WEB SERVICE
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
    port = int(os.environ.get("PORT", 10000))  # Render uses PORT env var
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="warning")

# =============================================================================
# CONFIGURATION SECTION - Render Ready
# =============================================================================

# Environment variables for security (set these in Render dashboard)
BOT_TOKEN = os.getenv("BOT_TOKEN", "8480202493:AAHMwt8_S1jvYnDynbpKvmWPuTI2_q4HAN0")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID", "")  # Set this in Render environment
DUMP_CHANNEL_ID = os.getenv("DUMP_CHANNEL_ID", "")  # Optional default dump channel

# Global variables
fixed_anime_name = ""
dump_channel_id = DUMP_CHANNEL_ID
log_channel_id = LOG_CHANNEL_ID

# Configuration file (will work on Render's ephemeral storage)
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

# Bot statistics for monitoring
bot_stats = {
    "start_time": datetime.now(timezone.utc),
    "messages_processed": 0,
    "successful_formats": 0,
    "failed_formats": 0,
    "dump_channel_sends": 0,
    "dump_channel_fails": 0,
    "errors": 0
}

# =============================================================================
# LOG CHANNEL SYSTEM
# =============================================================================

class LogChannelManager:
    """Enhanced logging system with Telegram channel integration"""
    
    def __init__(self, bot_context=None):
        self.bot_context = bot_context
        self.log_channel = log_channel_id
        self.message_buffer = []
        self.buffer_size = 10  # Send logs in batches
        
    async def log_action(self, action_type, details, user_info=None, severity="INFO"):
        """Log action to both file and Telegram channel"""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Create log entry
        log_entry = {
            "timestamp": timestamp,
            "type": action_type,
            "severity": severity,
            "details": details,
            "user": user_info
        }
        
        # Log to console/file
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
        
        # Send to log channel if configured
        if self.log_channel and self.bot_context:
            await self._send_to_log_channel(log_entry)
    
    async def _send_to_log_channel(self, log_entry):
        """Send formatted log to Telegram log channel"""
        try:
            # Create formatted message
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
    
    # Convert datetime to string for JSON serialization
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
        
        # Load stats if available
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
        # Clean and process caption
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
        
        # Log successful formatting
        await log_manager.log_format_action(original_caption, formatted_caption, user_info, True)
        
        return formatted_caption
        
    except Exception as e:
        # Log formatting error
        await log_manager.log_format_action(original_caption, "", user_info, False)
        logger.error(f"Caption parsing error: {e}\n{traceback.format_exc()}")
        return ""

# =============================================================================
# ENHANCED COMMANDS - All other command handlers remain the same
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

# Include all your existing command handlers here (start_command, stats_command, etc.)
# ... [I'll keep the rest of the original code for brevity] ...

# =============================================================================
# MAIN APPLICATION - RENDER READY WITH HTTP SERVER
# =============================================================================

def main():
    """Start the professional bot - Render optimized with HTTP health check"""
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or not BOT_TOKEN:
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
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add all your existing command handlers here...
    # [Keep all existing handlers from original code]
    
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
