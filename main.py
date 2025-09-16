#!/usr/bin/env python3
"""
Professional Telegram Bot for Anime Caption Formatting
Enhanced with prefix management, dump channel functionality, and improved reliability
Compatible with Python 3.13 and latest telegram library versions
"""

import re
import logging
import json
import os
import asyncio
from pathlib import Path
from telegram import Update, BotCommand
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from telegram.error import TelegramError

# =============================================================================
# CONFIGURATION SECTION
# =============================================================================

fixed_anime_name = ""  # Global variable to store fixed anime name (empty = auto-detect)
BOT_TOKEN = "8480202493:AAH7BGoSrOS4xu5TYxbamcJXAcqhE4GSU5k"  # Replace with your actual bot token
dump_channel_id = ""  # Dump channel ID (will be configurable via commands)

# Configuration file to persist settings - Fixed path handling
def get_config_file_path():
    """Get the appropriate config file path based on environment"""
    # Try different possible paths
    possible_paths = [
        "/app/data/bot_config.json",
        "./data/bot_config.json", 
        "./bot_config.json",
        "bot_config.json"
    ]
    
    # First, try to use existing file
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    # If no existing file, try to create in writable directory
    for path in possible_paths:
        try:
            # Create directory if it doesn't exist
            directory = os.path.dirname(path)
            if directory:
                Path(directory).mkdir(parents=True, exist_ok=True)
            
            # Test write permissions
            test_path = path + ".test"
            with open(test_path, 'w') as f:
                f.write("test")
            os.remove(test_path)
            return path
        except (OSError, IOError, PermissionError):
            continue
    
    # Fallback to current directory
    return "bot_config.json"

CONFIG_FILE = get_config_file_path()

# =============================================================================
# LOGGING SETUP
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
# CONFIGURATION MANAGEMENT WITH IMPROVED ERROR HANDLING
# =============================================================================

def save_config():
    """Save bot configuration to file with error handling"""
    config = {
        "fixed_anime_name": fixed_anime_name,
        "prefixes": prefixes,
        "dump_channel_id": dump_channel_id,
        "message_count": message_count
    }
    
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            # Ensure directory exists
            directory = os.path.dirname(CONFIG_FILE)
            if directory:
                Path(directory).mkdir(parents=True, exist_ok=True)
            
            # Write config with atomic operation
            temp_file = CONFIG_FILE + ".tmp"
            with open(temp_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            # Atomic move
            if os.path.exists(CONFIG_FILE):
                os.replace(temp_file, CONFIG_FILE)
            else:
                os.rename(temp_file, CONFIG_FILE)
            
            logger.info(f"Configuration saved successfully to {CONFIG_FILE}")
            return True
            
        except (OSError, IOError, PermissionError) as e:
            logger.warning(f"Failed to save config (attempt {attempt + 1}): {e}")
            if attempt == max_attempts - 1:
                logger.error(f"Failed to save config after {max_attempts} attempts: {e}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error saving config: {e}")
            return False
    
    return False

def load_config():
    """Load bot configuration from file with error handling"""
    global fixed_anime_name, prefixes, dump_channel_id, message_count
    
    try:
        if not os.path.exists(CONFIG_FILE):
            logger.info(f"Config file {CONFIG_FILE} doesn't exist, creating default config")
            save_config()  # Create default config
            return True
        
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        
        # Load with defaults for missing keys
        fixed_anime_name = config.get("fixed_anime_name", "")
        prefixes = config.get("prefixes", ["/leech -n", "/leech1 -n", "/leech2 -n", "/leechx -n", "/leech4 -n", "/leech3 -n", "/leech5 -n"])
        dump_channel_id = config.get("dump_channel_id", "")
        message_count = config.get("message_count", 0)
        
        # Validate loaded data
        if not isinstance(prefixes, list) or not prefixes:
            prefixes = ["/leech -n", "/leech1 -n", "/leech2 -n", "/leechx -n", "/leech4 -n", "/leech3 -n", "/leech5 -n"]
        
        if not isinstance(message_count, int) or message_count < 0:
            message_count = 0
        
        logger.info(f"Configuration loaded successfully from {CONFIG_FILE}")
        return True
        
    except (OSError, IOError) as e:
        logger.error(f"Failed to load config file: {e}")
        logger.info("Using default configuration")
        return False
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config file: {e}")
        logger.info("Creating new config file with defaults")
        save_config()
        return False
    except Exception as e:
        logger.error(f"Unexpected error loading config: {e}")
        logger.info("Using default configuration")
        return False

# =============================================================================
# QUALITY ORDERING CONFIGURATION
# =============================================================================

QUALITY_ORDER = ["480P", "720P", "1080P"]

class AnimeParser:
    """Enhanced anime caption parser with multiple format support and professional quality handling"""
    
    def __init__(self):
        self.patterns = {
            # Standard bracket formats
            'bracket_se': r'\[S(\d+)\s*E(\d+)\]',
            'bracket_sep': r'\[S(\d+)\s*EP(\d+)\]',
            
            # Channel prefix formats
            'channel_se': r'@\w+\s*-\s*(.+?)\s+S(\d+)\s*EP(\d+)',
            'channel_bracket': r'@\w+\s*-\s*\[S(\d+)\s*EP(\d+)\]\s*(.+?)(?:\s*\[|$)',
            
            # Structured format with emojis
            'structured_emoji': r'📺\s*([^\[]+)\s*\[S(\d+)\]',
            
            # Simple formats
            'simple_se': r'S(\d+)\s*E(\d+)',
            'simple_ep': r'S(\d+)\s*EP(\d+)',
        }
    
    def extract_episode_info(self, text):
        """Extract season, episode, and anime name from various formats"""
        season = "01"
        episode = "01"
        anime_name = ""
        
        try:
            clean_text = text.strip() if text else ""
            
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
        
        except Exception as e:
            logger.warning(f"Error parsing episode info: {e}")
        
        return season, episode, clean_text
    
    def _parse_structured_format(self, text):
        """Parse structured format with emojis"""
        season = "01"
        episode = "01"
        anime_name = ""
        
        try:
            title_match = re.search(r'📺\s*([^\[]+)\s*\[S(\d+)\]', text, re.IGNORECASE)
            if title_match:
                anime_name = title_match.group(1).strip()
                season = title_match.group(2).zfill(2)
            
            episode_match = re.search(r'Eᴘɪꜱᴏᴅᴇ\s*:\s*(\d+)', text, re.IGNORECASE)
            if episode_match:
                episode = episode_match.group(1).zfill(2)
        
        except Exception as e:
            logger.warning(f"Error parsing structured format: {e}")
        
        return season, episode, anime_name
    
    def extract_quality(self, text):
        """Extract video quality from text and ensure it ends with 'P'"""
        if not text:
            return "720P"
        
        try:
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
                    if quality_number.isdigit() and int(quality_number) in [144, 240, 360, 480, 720, 1080, 1440, 2160]:
                        return f"{quality_number}P"
        
        except Exception as e:
            logger.warning(f"Error extracting quality: {e}")
        
        return "720P"
    
    def extract_language(self, text):
        """Extract language/audio information"""
        if not text:
            return ""
        
        try:
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
        
        except Exception as e:
            logger.warning(f"Error extracting language: {e}")
        
        return ""
    
    def clean_anime_name(self, name):
        """Clean and standardize anime name"""
        if not name:
            return ""
        
        try:
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
        
        except Exception as e:
            logger.warning(f"Error cleaning anime name: {e}")
            return name
        
        return name

def parse_caption(caption: str) -> str:
    """Enhanced caption parser with support for multiple formats"""
    global message_count, fixed_anime_name
    
    try:
        message_count += 1
        
        if not caption:
            return ""
        
        parser = AnimeParser()
        original_caption = caption.strip()
        
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
        
        return formatted_caption
    
    except Exception as e:
        logger.error(f"Error parsing caption: {e}")
        return f"/leech -n [S01-E01] Unknown Anime [720P] [Single].mkv"

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
            
            error_str = str(e).lower()
            if "chat not found" in error_str:
                return False, "Dump channel not found"
            elif "not enough rights" in error_str or "forbidden" in error_str:
                return False, "Bot lacks permissions in dump channel"
            elif "network" in error_str or "timeout" in error_str:
                if retry_count < max_retries:
                    continue
                else:
                    return False, f"Network error after {max_retries} attempts"
            elif retry_count >= max_retries:
                return False, f"Failed after {max_retries} attempts: {e}"
        
        except Exception as e:
            logger.error(f"Unexpected error sending to dump channel: {e}")
            return False, f"Unexpected error: {e}"
    
    return False, "Max retries exceeded"

async def check_dump_channel_status(context: ContextTypes.DEFAULT_TYPE):
    """Check if dump channel is accessible"""
    global dump_channel_id
    
    if not dump_channel_id:
        return False, "No dump channel configured"
    
    try:
        chat = await context.bot.get_chat(dump_channel_id)
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
        error_str = str(e).lower()
        if "chat not found" in error_str:
            return False, "Channel not found"
        elif "not enough rights" in error_str or "forbidden" in error_str:
            return False, "Bot lacks access rights"
        else:
            return False, f"Error: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"

# =============================================================================
# COMMAND HANDLERS
# =============================================================================

async def setup_commands(application):
    """Set up bot commands menu"""
    try:
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
        logger.info("Bot commands menu set up successfully")
    except Exception as e:
        logger.warning(f"Failed to set up command menu: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    try:
        await setup_commands(context.application)
        
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
            "**📝 Commands:**\n"
            "• `/addprefix PREFIX` - Add new prefix\n"
            "• `/prefixlist` - Show all prefixes\n"
            "• `/delprefix INDEX` - Delete prefix\n"
            "• `/dumpchannel ID` - Set dump channel\n"
            "• `/dumpstatus` - Check dump channel\n\n"
            "**🚀 Usage:** Send videos/documents with captions!"
        )
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
    
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await update.message.reply_text(
            "🚀 Professional Anime Caption Formatter Bot is running!\n"
            "Send videos/documents with captions to format them.",
            reply_to_message_id=update.message.message_id
        )

async def name_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /name command"""
    global fixed_anime_name
    
    try:
        if not context.args:
            current_name = fixed_anime_name or "Auto-detect mode"
            await update.message.reply_text(
                f"📝 **Current anime name:** {current_name}\n\n"
                "**Usage:**\n"
                "• `/name YOUR ANIME NAME` - Set fixed name\n"
                "• `/name reset` - Enable auto-detection\n\n"
                "**Examples:**\n"
                "• `/name Naruto Shippuden Tam`\n"
                "• `/name One Piece Eng`\n"
                "• `/name reset`",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
            return
        
        new_name = ' '.join(context.args).strip()
        
        if new_name.lower() == "reset":
            fixed_anime_name = ""
            save_config()
            await update.message.reply_text(
                "✅ **Fixed anime name reset!**\n\n"
                "Now using auto-detection mode.",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
        else:
            fixed_anime_name = new_name
            save_config()
            await update.message.reply_text(
                f"✅ **Fixed anime name set!**\n\n"
                f"**Name:** {fixed_anime_name}\n\n"
                "All episodes will use this name until reset.",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
    
    except Exception as e:
        logger.error(f"Error in name command: {e}")
        await update.message.reply_text(
            "❌ Error processing command. Please try again.",
            reply_to_message_id=update.message.message_id
        )

async def addprefix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addprefix command"""
    global prefixes
    
    try:
        if not context.args:
            await update.message.reply_text(
                "➕ **Add New Prefix**\n\n"
                "**Usage:** `/addprefix YOUR_PREFIX`\n\n"
                f"**Current prefixes:** {len(prefixes)}",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
            return
        
        new_prefix = ' '.join(context.args).strip()
        
        if new_prefix in prefixes:
            await update.message.reply_text(
                f"⚠️ **Prefix already exists!**\n\n"
                f"**Prefix:** `{new_prefix}`",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
            return
        
        prefixes.append(new_prefix)
        save_config()
        
        await update.message.reply_text(
            f"✅ **Prefix added successfully!**\n\n"
            f"**New prefix:** `{new_prefix}`\n"
            f"**Total prefixes:** {len(prefixes)}",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
    
    except Exception as e:
        logger.error(f"Error in addprefix command: {e}")
        await update.message.reply_text(
            "❌ Error processing command.",
            reply_to_message_id=update.message.message_id
        )

async def handle_media_with_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle media messages with captions"""
    try:
        message = update.message
        original_caption = message.caption
        
        if not original_caption:
            return
        
        logger.info(f"Processing caption: {original_caption}")
        
        formatted_caption = parse_caption(original_caption)
        
        if formatted_caption and formatted_caption != original_caption:
            # Send to dump channel if configured
            if dump_channel_id:
                dump_success, dump_message = await send_to_dump_channel(context, message, formatted_caption)
                if dump_success:
                    logger.info("Successfully sent to dump channel")
                else:
                    logger.warning(f"Failed to send to dump channel: {dump_message}")
            
            await message.reply_text(
                f"\n`{formatted_caption}`\n",
                parse_mode='Markdown',
                reply_to_message_id=message.message_id
            )
            
            save_config()
        else:
            await message.reply_text(
                "❌ **Parsing Failed**\n\n"
                "Could not parse the caption format.\n"
                "Try `/format YOUR_TEXT` to test formats.",
                parse_mode='Markdown',
                reply_to_message_id=message.message_id
            )
    
    except Exception as e:
        logger.error(f"Error handling media: {e}")
        try:
            await update.message.reply_text(
                "❌ Error processing your request.",
                reply_to_message_id=update.message.message_id
            )
        except:
            pass

# =============================================================================
# APPLICATION SETUP WITH COMPATIBILITY FIX
# =============================================================================

async def create_application():
    """Create and configure the Application with compatibility handling"""
    try:
        # Create application using the builder pattern with explicit configuration
        # This approach is more compatible with different Python versions
        builder = Application.builder()
        builder = builder.token(BOT_TOKEN)
        
        # Build the application
        application = builder.build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("name", name_command))
        application.add_handler(CommandHandler("addprefix", addprefix_command))
        
        # Add media handlers with better filtering
        application.add_handler(MessageHandler(
            filters.Document.ALL & filters.CAPTION,
            handle_media_with_caption
        ))
        application.add_handler(MessageHandler(
            filters.VIDEO & filters.CAPTION,
            handle_media_with_caption
        ))
        
        logger.info("Application created and configured successfully")
        return application
        
    except Exception as e:
        logger.error(f"Failed to create application: {e}")
        raise

def main():
    """Main function with improved compatibility"""
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Error: Please set your BOT_TOKEN!")
        return
    
    print("🚀 Starting Professional Anime Caption Formatter Bot...")
    print(f"💾 Config file path: {CONFIG_FILE}")
    
    # Load configuration
    config_loaded = load_config()
    if config_loaded:
        print(f"⚙️ Config loaded: {len(prefixes)} prefixes")
    else:
        print("⚠️ Using default configuration")
    
    try:
        # Create and run the application
        application = asyncio.run(create_application())
        
        print("✅ Bot configured successfully!")
        print("🎥 Quality Format: 480P, 720P, 1080P")
        print("Press Ctrl+C to stop.")
        
        # Run the bot
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
        save_config()
    except Exception as e:
        logger.error(f"Critical bot error: {e}")
        print(f"❌ Bot error: {e}")
        save_config()

if __name__ == '__main__':
    main()
