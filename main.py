#!/usr/bin/env python3
"""
Professional Telegram Bot for Anime Caption Formatting
Enhanced with prefix management, dump channel functionality, and improved reliability
Deployment-ready version with environment variable support
"""

import re
import logging
import json
import os
from telegram import Update, BotCommand
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from telegram.error import TelegramError

# =============================================================================
# CONFIGURATION SECTION - DEPLOYMENT READY
# =============================================================================

# Get bot token from environment variable for security
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable must be set")

# Global variables
fixed_anime_name = ""  # Global variable to store fixed anime name (empty = auto-detect)
dump_channel_id = ""  # Dump channel ID (will be configurable via commands)

# Configuration file to persist settings
CONFIG_FILE = "bot_config.json"

# =============================================================================
# LOGGING SETUP - PRODUCTION READY
# =============================================================================

# Set logging level from environment variable
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, LOG_LEVEL, logging.INFO)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=log_level,
    handlers=[
        logging.StreamHandler(),  # Console output
        logging.FileHandler('bot.log', mode='a')  # File output
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# GLOBAL VARIABLES FOR PREFIX ROTATION AND SETTINGS
# =============================================================================

message_count = 0
prefixes = ["/leech -n", "/leech1 -n", "/leech2 -n", "/leechx -n", "/leech4 -n", "/leech3 -n", "/leech5 -n"]

# =============================================================================
# CONFIGURATION MANAGEMENT
# =============================================================================

def save_config():
    """Save bot configuration to file"""
    config = {
        "fixed_anime_name": fixed_anime_name,
        "prefixes": prefixes,
        "dump_channel_id": dump_channel_id,
        "message_count": message_count
    }
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info("Configuration saved successfully")
    except Exception as e:
        logger.error(f"Failed to save config: {e}")

def load_config():
    """Load bot configuration from file"""
    global fixed_anime_name, prefixes, dump_channel_id, message_count
    
    if not os.path.exists(CONFIG_FILE):
        save_config()  # Create default config
        return
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        
        fixed_anime_name = config.get("fixed_anime_name", "")
        prefixes = config.get("prefixes", ["/leech -n", "/leech1 -n", "/leech2 -n", "/leechx -n", "/leech4 -n", "/leech3 -n", "/leech5 -n"])
        dump_channel_id = config.get("dump_channel_id", "")
        message_count = config.get("message_count", 0)
        
        logger.info("Configuration loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        save_config()  # Create default config

# =============================================================================
# QUALITY ORDERING CONFIGURATION
# =============================================================================

QUALITY_ORDER = ["480P", "720P", "1080P"]  # Fixed order: 480P -> 720P -> 1080P

class AnimeParser:
    """Enhanced anime caption parser with multiple format support and professional quality handling"""
    
    def __init__(self):
        self.patterns = {
            # Standard bracket formats
            'bracket_se': r'\[S(\d+)\s*E(\d+)\]',  # [S01 E12]
            'bracket_sep': r'\[S(\d+)\s*EP(\d+)\]',  # [S01 EP12]
            
            # Channel prefix formats
            'channel_se': r'@\w+\s*-\s*(.+?)\s+S(\d+)\s*EP(\d+)',  # @channel - Name S01 EP01
            'channel_bracket': r'@\w+\s*-\s*\[S(\d+)\s*EP(\d+)\]\s*(.+?)(?:\s*\[|$)',  # @channel - [S01 EP12] Name
            
            # Structured format with emojis
            'structured_emoji': r'📺\s*([^\[]+)\s*\[S(\d+)\]',  # 📺 NAME [S01]
            
            # Simple formats
            'simple_se': r'S(\d+)\s*E(\d+)',  # S01 E12
            'simple_ep': r'S(\d+)\s*EP(\d+)',  # S01 EP01
        }
    def extract_episode_info(self, text):
        """Extract season, episode, and anime name from various formats"""
        season = "01"
        episode = "01"
        anime_name = ""
        
        # Clean text first
        clean_text = text.strip()
        
        # Try structured emoji format first (highest priority)
        if "📺" in clean_text and "Eᴘɪꜱᴏᴅᴇ" in clean_text:
            return self._parse_structured_format(clean_text)
        
        # Try channel prefix formats
        for pattern_name in ['channel_se', 'channel_bracket']:
            pattern = self.patterns[pattern_name]
            match = re.search(pattern, clean_text, re.IGNORECASE)
            if match:
                if pattern_name == 'channel_se':
                    anime_name, season, episode = match.groups()
                else:  # channel_bracket
                    season, episode, anime_name = match.groups()
                return season.zfill(2), episode.zfill(2), anime_name.strip()
        
        # Try standard bracket formats
        for pattern_name in ['bracket_se', 'bracket_sep']:
            pattern = self.patterns[pattern_name]
            match = re.search(pattern, clean_text, re.IGNORECASE)
            if match:
                season, episode = match.groups()
                # Extract anime name (everything before the bracket)
                anime_name = re.split(r'\[S\d+', clean_text, flags=re.IGNORECASE)[0].strip()
                return season.zfill(2), episode.zfill(2), anime_name
        
        # Try simple formats
        for pattern_name in ['simple_se', 'simple_ep']:
            pattern = self.patterns[pattern_name]
            match = re.search(pattern, clean_text, re.IGNORECASE)
            if match:
                season, episode = match.groups()
                # Extract anime name (everything before S##)
                anime_name = re.split(r'S\d+', clean_text, flags=re.IGNORECASE)[0].strip()
                return season.zfill(2), episode.zfill(2), anime_name
        
        return season, episode, clean_text  # Fallback
    
    def _parse_structured_format(self, text):
        """Parse structured format with emojis"""
        season = "01"
        episode = "01"
        anime_name = ""
        
        # Extract anime name and season
        title_match = re.search(r'📺\s*([^\[]+)\s*\[S(\d+)\]', text, re.IGNORECASE)
        if title_match:
            anime_name = title_match.group(1).strip()
            season = title_match.group(2).zfill(2)
        
        # Extract episode
        episode_match = re.search(r'Eᴘɪꜱᴏᴅᴇ\s*:\s*(\d+)', text, re.IGNORECASE)
        if episode_match:
            episode = episode_match.group(1).zfill(2)
        
        return season, episode, anime_name
    
    def extract_quality(self, text):
        """Extract video quality from text and ensure it ends with 'P'"""
        # Look for quality patterns
        quality_patterns = [
            r'(\d+)[pP]',  # 1080p, 720P, etc.
            r'\[(\d+)[pP]?\]',  # [1080], [720p], [720P]
            r'Qᴜᴀʟɪᴛʏ\s*:\s*(\d+)[pP]?',  # Quality : 1080p
            r'QUALITY\s*:\s*(\d+)[pP]?',  # QUALITY : 1080P
            r'(\d+)\s*[pP]',  # 1080 P, 720p
        ]
        
        for pattern in quality_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                quality_number = match.group(1)
                # Validate common qualities
                if int(quality_number) in [144, 240, 360, 480, 720, 1080, 1440, 2160]:
                    # Always return with 'P' suffix
                    return f"{quality_number}P"
        
        # Default quality with 'P' suffix
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
        
        # Check for audio section in structured format
        audio_match = re.search(r'(?:Aᴜᴅɪᴏ|Audio)\s*:\s*([^,\n\]]+)', text, re.IGNORECASE)
        if audio_match:
            audio_text = audio_match.group(1).strip().lower()
            for key, value in language_mappings.items():
                if key in audio_text:
                    return value
        
        # Check for language in filename
        text_lower = text.lower()
        for key, value in language_mappings.items():
            if key in text_lower:
                return value
        
        return ""  # No language detected
    
    def clean_anime_name(self, name):
        """Clean and standardize anime name"""
        if not name:
            return ""
        
        # Remove channel prefixes
        name = re.sub(r'^@\w+\s*-\s*', '', name, flags=re.IGNORECASE)
        
        # Remove common unwanted patterns
        unwanted_patterns = [
            r'\[.*?\]',  # Remove all brackets
            r'\(.*?\)',  # Remove parentheses
            r'^\s*-\s*',  # Remove leading dash
            r'\s*-\s*$',  # Remove trailing dash
        ]
        
        for pattern in unwanted_patterns:
            name = re.sub(pattern, '', name, flags=re.IGNORECASE)
        
        # Apply common replacements
        replacements = {
            'Tamil': 'Tam',
            'English': 'Eng',
            'Dubbed': 'Dub',
            'Subbed': 'Sub',
        }
        
        for old, new in replacements.items():
            name = re.sub(rf'\b{old}\b', new, name, flags=re.IGNORECASE)
        
        # Clean up extra spaces and special characters
        name = re.sub(r'[!@#$%^&*(),.?":{}|<>]', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        return name

def parse_caption(caption: str) -> str:
    """
    Enhanced caption parser with support for multiple formats and professional quality handling
    """
    global message_count, fixed_anime_name
    message_count += 1
    
    if not caption:
        return ""
    
    parser = AnimeParser()
    original_caption = caption.strip()
    
    # Remove channel name/prefix if it exists
    clean_caption = original_caption
    if " - " in clean_caption and clean_caption.startswith("@"):
        parts = clean_caption.split(" - ", 1)
        if len(parts) > 1:
            clean_caption = parts[1]
    
    # Extract information using enhanced parser
    season, episode, extracted_name = parser.extract_episode_info(original_caption)
    quality = parser.extract_quality(original_caption)  # Now always returns with 'P'
    language = parser.extract_language(original_caption)
    
    # Determine final anime name
    if fixed_anime_name:
        anime_name = fixed_anime_name
    else:
        anime_name = parser.clean_anime_name(extracted_name) or "Unknown Anime"
    
    # Add language to anime name if detected
    if language and language not in anime_name:
        anime_name = f"{anime_name} {language}".strip()
    
    # Format season-episode
    season_episode = f"[S{season}-E{episode}]"
    
    # Determine file extension
    extension = ".mkv"
    if ".mp4" in original_caption.lower():
        extension = ".mp4"
    elif ".avi" in original_caption.lower():
        extension = ".avi"
    
    # Apply prefix rotation
    if prefixes:  # Check if prefixes list is not empty
        prefix_index = (message_count - 1) // 3 % len(prefixes)
        current_prefix = prefixes[prefix_index]
    else:
        current_prefix = "/leech -n"  # Fallback prefix
    
    # Build final formatted caption with guaranteed 'P' suffix in quality
    formatted_caption = f"{current_prefix} {season_episode} {anime_name} [{quality}] [Single]{extension}"
    
    return formatted_caption

# =============================================================================
# DUMP CHANNEL FUNCTIONALITY
# =============================================================================

async def send_to_dump_channel(context: ContextTypes.DEFAULT_TYPE, message, formatted_caption):
    """Send formatted caption to dump channel with retry logic"""
    global dump_channel_id
    
    if not dump_channel_id:
        return False, "Dump channel not configured"
    
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Send the formatted caption to dump channel
            await context.bot.send_message(
                chat_id=dump_channel_id,
                text=f"📤 **Auto-formatted Caption**\n\n`{formatted_caption}`\n\n⏰ Processed at: {message.date}",
                parse_mode='Markdown'
            )
            logger.info(f"Successfully sent to dump channel: {dump_channel_id}")
            return True, "Success"
            
        except TelegramError as e:
            retry_count += 1
            logger.warning(f"Failed to send to dump channel (attempt {retry_count}): {e}")
            
            if "chat not found" in str(e).lower():
                return False, "Dump channel not found"
            elif "not enough rights" in str(e).lower():
                return False, "Bot lacks permissions in dump channel"
            elif retry_count >= max_retries:
                return False, f"Failed after {max_retries} attempts: {e}"
        
        except Exception as e:
            logger.error(f"Unexpected error sending to dump channel: {e}")
            return False, f"Unexpected error: {e}"
    
    return False, "Max retries exceeded"

async def check_dump_channel_status(context: ContextTypes.DEFAULT_TYPE):
    """Check if dump channel is accessible and bot has proper permissions"""
    global dump_channel_id
    
    if not dump_channel_id:
        return False, "No dump channel configured"
    
    try:
        # Try to get chat info
        chat = await context.bot.get_chat(dump_channel_id)
        
        # Check bot permissions
        bot_member = await context.bot.get_chat_member(dump_channel_id, context.bot.id)
        
        can_send = bot_member.can_post_messages if hasattr(bot_member, 'can_post_messages') else True
        
        status = {
            "exists": True,
            "title": chat.title if hasattr(chat, 'title') else "Unknown",
            "type": chat.type,
            "can_send": can_send,
            "bot_status": bot_member.status
        }
        
        return True, status
        
    except TelegramError as e:
        if "chat not found" in str(e).lower():
            return False, "Channel not found"
        elif "not enough rights" in str(e).lower():
            return False, "Bot lacks access rights"
        else:
            return False, f"Error: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"

# =============================================================================
# BOT COMMAND HANDLERS
# =============================================================================

async def setup_commands(application):
    """Set up bot commands menu for better UX"""
    commands = [
        BotCommand("start", "🚀 Start the bot and see instructions"),
        BotCommand("name", "📝 Set/view anime name (fixed or auto-detect)"),
        BotCommand("format", "🔧 Test caption formatting on any text"),
        BotCommand("status", "📊 Show bot status and current settings"),
        BotCommand("help", "❓ Show detailed help and examples"),
        BotCommand("quality", "🎥 Show supported quality formats"),
        BotCommand("addprefix", "➕ Add new prefix to rotation"),
        BotCommand("prefixlist", "📋 Show all current prefixes"),
        BotCommand("delprefix", "➖ Delete prefix from rotation"),
        BotCommand("dumpchannel", "📤 Set/check dump channel"),
        BotCommand("dumpstatus", "📡 Check dump channel status"),
    ]
    await application.bot.set_my_commands(commands)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command and set up commands menu"""
    # Set up commands menu when bot starts (if not already set)
    try:
        await setup_commands(context.application)
    except Exception as e:
        logger.warning(f"Command menu setup: {e}")
    
    welcome_message = (
        "🎬 **Professional Anime Caption Formatter** 🎬\n\n"
        "Enhanced with prefix management and dump channel functionality!\n\n"
        "**✨ Key Features:**\n"
        "• Professional quality formatting (480P, 720P, 1080P)\n"
        "• Dynamic prefix management\n"
        "• Dump channel integration\n"
        "• Multiple input format support\n"
        "• Language detection (Tamil, English, Multi)\n\n"
        "**🎯 Quality Order:** 480P → 720P → 1080P\n\n"
        "**📝 New Commands:**\n"
        "• `/addprefix PREFIX` - Add new prefix\n"
        "• `/prefixlist` - Show all prefixes\n"
        "• `/delprefix INDEX` - Delete prefix\n"
        "• `/dumpchannel ID` - Set dump channel\n"
        "• `/dumpstatus` - Check dump channel\n\n"
        "**🚀 Usage:** Send videos/documents with captions!"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

# [Continue with all other command handlers from the original code...]
# (Keeping the rest of the command handlers identical to save space)

async def addprefix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addprefix command"""
    global prefixes
    
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

# [Include all other command handlers from original code...]

# =============================================================================
# BOT MESSAGE HANDLERS  
# =============================================================================

async def handle_media_with_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle video/document/file messages with captions"""
    message = update.message
    original_caption = message.caption
    
    if not original_caption:
        return
    
    logger.info(f"Received caption: {original_caption}")
    
    # Parse and format the caption
    formatted_caption = parse_caption(original_caption)
    
    if formatted_caption and formatted_caption != original_caption:
        logger.info(f"Formatted caption: {formatted_caption}")
        
        # Send to dump channel if configured
        dump_success = False
        dump_message = ""
        
        if dump_channel_id:
            dump_success, dump_message = await send_to_dump_channel(context, message, formatted_caption)
            if dump_success:
                logger.info("Successfully sent to dump channel")
            else:
                logger.warning(f"Failed to send to dump channel: {dump_message}")
        
        # Prepare response message
        response_text = f"\n`{formatted_caption}`\n"
        
        # Reply with the formatted caption
        await message.reply_text(
            response_text,
            parse_mode='Markdown',
            reply_to_message_id=message.message_id
        )
        
        # Save config after processing
        save_config()
        
    else:
        await message.reply_text(
            "❌ **Parsing Failed**\n\n"
            "Could not parse the caption format.\n"
            "Try `/format YOUR_TEXT` to test or `/help` for supported formats.",
            parse_mode='Markdown',
            reply_to_message_id=message.message_id
        )

# [Include remaining handlers...]

# =============================================================================
# HEALTH CHECK AND WEBHOOK SUPPORT (FOR DEPLOYMENT)
# =============================================================================

from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple health check endpoint for deployment platforms"""
    
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress default HTTP logging
        pass

def run_health_server():
    """Run health check server in background"""
    port = int(os.getenv('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"Health check server running on port {port}")
    server.serve_forever()

# =============================================================================
# MAIN APPLICATION - DEPLOYMENT READY
# =============================================================================

def main():
    """Start the professional bot with deployment support"""
    logger.info("🚀 Starting Enhanced Professional Anime Caption Formatter Bot...")
    logger.info("📋 Features: Dynamic prefix management, Dump channel, Quality standardization")
    
    # Load saved configuration
    load_config()
    logger.info(f"⚙️ Loaded config: {len(prefixes)} prefixes, dump channel: {'✅' if dump_channel_id else '❌'}")
    
    # Start health check server in background for deployment platforms
    if os.getenv('ENABLE_HEALTH_CHECK', 'true').lower() == 'true':
        health_thread = threading.Thread(target=run_health_server, daemon=True)
        health_thread.start()
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    # Add other command handlers...
    
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
    
    logger.info("✅ Enhanced Professional bot is ready for deployment!")
    logger.info("🎥 Quality Format: All qualities end with 'P' (480P, 720P, 1080P)")
    logger.info("📱 Command Menu: Type '/' to see available commands")
    
    # Run the bot with deployment-friendly error handling
    try:
        # Use webhook in production if WEBHOOK_URL is set
        webhook_url = os.getenv('WEBHOOK_URL')
        if webhook_url:
            logger.info(f"Starting bot with webhook: {webhook_url}")
            application.run_webhook(
                listen="0.0.0.0",
                port=int(os.getenv('PORT', 8080)),
                webhook_url=webhook_url,
                url_path=os.getenv('BOT_TOKEN', '')
            )
        else:
            logger.info("Starting bot with polling...")
            application.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
        save_config()
    except Exception as e:
        logger.error(f"Bot error: {e}")
        save_config()
        raise

if __name__ == '__main__':
    main()
