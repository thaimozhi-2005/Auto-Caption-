#!/usr/bin/env python3
"""
Professional Telegram Bot for Anime Caption Formatting
Enhanced with prefix management, dump channel functionality, and improved reliability
"""

import re
import logging
import json
import os
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
        
        try:
            # Clean text first
            clean_text = text.strip() if text else ""
            
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
        
        except Exception as e:
            logger.warning(f"Error parsing episode info: {e}")
        
        return season, episode, clean_text  # Fallback
    
    def _parse_structured_format(self, text):
        """Parse structured format with emojis"""
        season = "01"
        episode = "01"
        anime_name = ""
        
        try:
            # Extract anime name and season
            title_match = re.search(r'📺\s*([^\[]+)\s*\[S(\d+)\]', text, re.IGNORECASE)
            if title_match:
                anime_name = title_match.group(1).strip()
                season = title_match.group(2).zfill(2)
            
            # Extract episode
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
                    if quality_number.isdigit() and int(quality_number) in [144, 240, 360, 480, 720, 1080, 1440, 2160]:
                        # Always return with 'P' suffix
                        return f"{quality_number}P"
        
        except Exception as e:
            logger.warning(f"Error extracting quality: {e}")
        
        # Default quality with 'P' suffix
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
        
        except Exception as e:
            logger.warning(f"Error extracting language: {e}")
        
        return ""  # No language detected
    
    def clean_anime_name(self, name):
        """Clean and standardize anime name"""
        if not name:
            return ""
        
        try:
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
        
        except Exception as e:
            logger.warning(f"Error cleaning anime name: {e}")
            return name  # Return original name if cleaning fails
        
        return name

def parse_caption(caption: str) -> str:
    """
    Enhanced caption parser with support for multiple formats and professional quality handling
    """
    global message_count, fixed_anime_name
    
    try:
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
    
    except Exception as e:
        logger.error(f"Error parsing caption: {e}")
        return f"/leech -n [S01-E01] Unknown Anime [720P] [Single].mkv"  # Fallback format

# =============================================================================
# DUMP CHANNEL FUNCTIONALITY WITH IMPROVED ERROR HANDLING
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
            
            error_str = str(e).lower()
            if "chat not found" in error_str:
                return False, "Dump channel not found"
            elif "not enough rights" in error_str or "forbidden" in error_str:
                return False, "Bot lacks permissions in dump channel"
            elif "network" in error_str or "timeout" in error_str:
                if retry_count < max_retries:
                    continue  # Retry network errors
                else:
                    return False, f"Network error after {max_retries} attempts"
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
# BOT COMMAND HANDLERS WITH IMPROVED ERROR HANDLING
# =============================================================================

async def setup_commands(application):
    """Set up bot commands menu for better UX"""
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
    """Handle /start command and set up commands menu"""
    try:
        # Set up commands menu when bot starts (if not already set)
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
            "**📝 New Commands:**\n"
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

async def addprefix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addprefix command"""
    global prefixes
    
    try:
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
    
    except Exception as e:
        logger.error(f"Error in addprefix command: {e}")
        await update.message.reply_text(
            "❌ Error processing command. Please try again.",
            reply_to_message_id=update.message.message_id
        )

async def prefixlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /prefixlist command"""
    try:
        if not prefixes:
            await update.message.reply_text(
                "❌ **No prefixes configured!**\n\n"
                "Use `/addprefix PREFIX` to add your first prefix.",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
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
    
    except Exception as e:
        logger.error(f"Error in prefixlist command: {e}")
        await update.message.reply_text(
            f"Current prefixes: {len(prefixes)} configured",
            reply_to_message_id=update.message.message_id
        )

async def delprefix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /delprefix command"""
    global prefixes
    
    try:
        if not context.args:
            if not prefixes:
                await update.message.reply_text(
                    "❌ **No prefixes to delete!**\n\n"
                    "Use `/addprefix PREFIX` to add prefixes first.",
                    parse_mode='Markdown',
                    reply_to_message_id=update.message.message_id
                )
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
            return
        
        try:
            index = int(context.args[0]) - 1  # Convert to 0-based index
            
            if index < 0 or index >= len(prefixes):
                await update.message.reply_text(
                    f"❌ **Invalid index!**\n\n"
                    f"**Valid range:** 1 to {len(prefixes)}\n"
                    f"**You entered:** {index + 1}",
                    parse_mode='Markdown',
                    reply_to_message_id=update.message.message_id
                )
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
            
        except ValueError:
            await update.message.reply_text(
                f"❌ **Invalid number!**\n\n"
                f"Please enter a valid number.\n"
                f"**Example:** `/delprefix 2`",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
    
    except Exception as e:
        logger.error(f"Error in delprefix command: {e}")
        await update.message.reply_text(
            "❌ Error processing command. Please try again.",
            reply_to_message_id=update.message.message_id
        )

async def dumpchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /dumpchannel command"""
    global dump_channel_id
    
    try:
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
            return
        
        # Validate channel ID format
        if channel_input.startswith('-') or channel_input.startswith('@'):
            dump_channel_id = channel_input
            save_config()
            
            # Test the channel
            success, status = await check_dump_channel_status(context)
            
            if success:
                await update.message.reply_text(
                    f"✅ **Dump channel set successfully!**\n\n"
                    f"**Channel ID:** `{dump_channel_id}`\n"
                    f"**Title:** {status.get('title', 'Unknown')}\n"
                    f"**Type:** {status.get('type', 'Unknown')}\n"
                    f"**Bot Status:** {status.get('bot_status', 'Unknown')}\n"
                    f"**Can Send:** {'Yes' if status.get('can_send', False) else 'Limited'}",
                    parse_mode='Markdown',
                    reply_to_message_id=update.message.message_id
                )
            else:
                await update.message.reply_text(
                    f"⚠️ **Dump channel set but not accessible!**\n\n"
                    f"**Channel ID:** `{dump_channel_id}`\n"
                    f"**Issue:** {status}\n\n"
                    f"**Please ensure:**\n"
                    f"• Bot is added to the channel\n"
                    f"• Bot has send message permissions\n"
                    f"• Channel ID is correct",
                    parse_mode='Markdown',
                    reply_to_message_id=update.message.message_id
                )
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
    
    except Exception as e:
        logger.error(f"Error in dumpchannel command: {e}")
        await update.message.reply_text(
            "❌ Error processing command. Please try again.",
            reply_to_message_id=update.message.message_id
        )

async def dumpstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /dumpstatus command"""
    global dump_channel_id
    
    try:
        if not dump_channel_id:
            await update.message.reply_text(
                "📡 **Dump Channel Status**\n\n"
                "❌ **Not configured**\n\n"
                "Use `/dumpchannel CHANNEL_ID` to set up dump channel.",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
            return
        
        success, status = await check_dump_channel_status(context)
        
        if success:
            await update.message.reply_text(
                f"📡 **Dump Channel Status**\n\n"
                f"✅ **Channel is accessible**\n\n"
                f"**ID:** `{dump_channel_id}`\n"
                f"**Title:** {status.get('title', 'Unknown')}\n"
                f"**Type:** {status.get('type', 'Unknown')}\n"
                f"**Bot Status:** {status.get('bot_status', 'Unknown')}\n"
                f"**Can Send Messages:** {'Yes' if status.get('can_send', False) else 'Limited'}\n\n"
                f"**Status:** Ready to receive formatted captions!",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
        else:
            await update.message.reply_text(
                f"📡 **Dump Channel Status**\n\n"
                f"❌ **Channel not accessible**\n\n"
                f"**ID:** `{dump_channel_id}`\n"
                f"**Issue:** {status}\n\n"
                f"**Troubleshooting:**\n"
                f"• Check if bot is added to channel\n"
                f"• Verify bot has proper permissions\n"
                f"• Confirm channel ID is correct\n"
                f"• Use `/dumpchannel reset` to clear",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
    
    except Exception as e:
        logger.error(f"Error in dumpstatus command: {e}")
        await update.message.reply_text(
            "❌ Error checking dump channel status.",
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
                "Now using auto-detection mode. The bot will extract anime names from captions.",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
        else:
            fixed_anime_name = new_name
            save_config()
            await update.message.reply_text(
                f"✅ **Fixed anime name set!**\n\n"
                f"**Name:** {fixed_anime_name}\n\n"
                "All episodes will now use this name until reset with `/name reset`",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
    
    except Exception as e:
        logger.error(f"Error in name command: {e}")
        await update.message.reply_text(
            "❌ Error processing command. Please try again.",
            reply_to_message_id=update.message.message_id
        )

async def format_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /format command for testing"""
    try:
        if not context.args:
            await update.message.reply_text(
                "🔧 **Format Tester**\n\n"
                "**Usage:** `/format YOUR TEXT HERE`\n\n"
                "**Examples:**\n"
                "• `/format [S01 E05] Naruto [1080p] Tamil.mkv`\n"
                "• `/format @Channel - Anime S01 EP12 [720] Tamil.mp4`\n"
                "• `/format 📺 One Piece [S01] Episode : 15 Quality : 480p`",
                parse_mode='Markdown',
                reply_to_message_id=update.message.message_id
            )
            return
        
        test_text = ' '.join(context.args)
        formatted = parse_caption(test_text)
        
        await update.message.reply_text(
            f"🔧 **Format Test Result**\n\n"
            f"**Original:**\n`{test_text}`\n\n"
            f"**Formatted:**\n`{formatted}`\n\n"
            f"**Quality Format:** Professional (always ends with 'P')",
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
    
    except Exception as e:
        logger.error(f"Error in format command: {e}")
        await update.message.reply_text(
            "❌ Error processing format test.",
            reply_to_message_id=update.message.message_id
        )

async def quality_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /quality command"""
    try:
        quality_info = (
            "🎥 **Professional Quality Formatting**\n\n"
            "**Supported Quality Order:**\n"
            "1️⃣ **480P** - Standard Definition\n"
            "2️⃣ **720P** - HD Ready\n"
            "3️⃣ **1080P** - Full HD\n\n"
            "**✨ Key Features:**\n"
            "• All qualities formatted with 'P' suffix\n"
            "• Automatic quality detection from various formats\n"
            "• Professional consistency across all files\n"
            "• Default: 720P (if not detected)\n\n"
            "**Input Examples:**\n"
            "• `1080p`, `1080P`, `[1080]` → **1080P**\n"
            "• `720p`, `720P`, `[720]` → **720P**\n"
            "• `480p`, `480P`, `[480]` → **480P**\n"
            "• `Quality: 1080` → **1080P**"
        )
        await update.message.reply_text(
            quality_info,
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
    
    except Exception as e:
        logger.error(f"Error in quality command: {e}")
        await update.message.reply_text(
            "Quality formats: 480P, 720P, 1080P",
            reply_to_message_id=update.message.message_id
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    try:
        help_message = (
            "❓ **Professional Bot Help**\n\n"
            "**🎯 Supported Input Formats:**\n"
            "1. `[S01 E12] Anime Name [1080p] Tamil.mkv`\n"
            "2. `[S01 EP12] Anime Name [1080p] Tamil.mkv`\n"
            "3. `@Channel - Anime Name S01 EP01 [480P] Tamil.mkv`\n"
            "4. `@Channel - [S01 EP12] Anime Name [1080p] Tamil.mkv`\n"
            "5. `📺 Anime Name [S01] Episode : 15 Quality : 720p Audio : Tamil`\n\n"
            "**🔄 Output Format:**\n"
            "`/leech -n [S01-E12] Anime Name [1080P] [Single].mkv`\n\n"
            "**📋 Basic Commands:**\n"
            "• `/start` - Welcome message\n"
            "• `/name ANIME` - Set fixed anime name\n"
            "• `/format TEXT` - Test formatting\n"
            "• `/quality` - Quality info\n"
            "• `/status` - Current settings\n\n"
            "**🔧 Prefix Management:**\n"
            "• `/addprefix PREFIX` - Add new prefix\n"
            "• `/prefixlist` - Show all prefixes\n"
            "• `/delprefix INDEX` - Delete prefix\n\n"
            "**📤 Dump Channel:**\n"
            "• `/dumpchannel ID` - Set dump channel\n"
            "• `/dumpstatus` - Check channel status\n\n"
            "**🚀 Pro Tips:**\n"
            "• Prefixes rotate every 3 messages\n"
            "• All formatted captions sent to dump channel\n"
            "• Supports Tamil, English, Multi audio detection"
        )
        await update.message.reply_text(
            help_message,
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
    
    except Exception as e:
        logger.error(f"Error in help command: {e}")
        await update.message.reply_text(
            "Professional Anime Caption Formatter Bot\n"
            "Send videos/documents with captions to format them.",
            reply_to_message_id=update.message.message_id
        )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    global fixed_anime_name, message_count, dump_channel_id
    
    try:
        current_name = fixed_anime_name or "Auto-detect mode"
        current_prefix = prefixes[(message_count // 3) % len(prefixes)] if prefixes else "No prefixes"
        dump_status = "✅ Configured" if dump_channel_id else "❌ Not set"
        
        status_message = (
            f"📊 **Professional Bot Status**\n\n"
            f"**🎬 Anime Name:** {current_name}\n"
            f"**📈 Messages Processed:** {message_count}\n"
            f"**🔄 Current Prefix:** `{current_prefix}`\n"
            f"**⚙️ Total Prefixes:** {len(prefixes)}\n"
            f"**📤 Dump Channel:** {dump_status}\n"
            f"**🎥 Quality Order:** 480P → 720P → 1080P\n\n"
            f"**✅ Features Active:**\n"
            f"• Professional Quality Format: ✅\n"
            f"• Multi-Format Support: ✅ (6+ patterns)\n"
            f"• Auto-Quality Detection: ✅\n"
            f"• Language Detection: ✅\n"
            f"• Prefix Rotation: ✅\n"
            f"• Dump Channel Integration: {dump_status}\n"
            f"• Configuration Persistence: ✅\n\n"
            f"**🔧 Next Actions:**\n"
            f"• Prefix rotation in: {3 - (message_count % 3)} messages\n"
            f"• Use `/prefixlist` to manage prefixes\n"
            f"• Use `/dumpstatus` to check dump channel"
        )
        
        await update.message.reply_text(
            status_message,
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
    
    except Exception as e:
        logger.error(f"Error in status command: {e}")
        await update.message.reply_text(
            f"Bot Status: {message_count} messages processed, {len(prefixes)} prefixes configured",
            reply_to_message_id=update.message.message_id
        )

# =============================================================================
# BOT MESSAGE HANDLERS WITH IMPROVED ERROR HANDLING
# =============================================================================

async def handle_media_with_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle video/document/file messages with captions"""
    try:
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
    
    except Exception as e:
        logger.error(f"Error handling media with caption: {e}")
        try:
            await update.message.reply_text(
                "❌ Error processing your request. Please try again.",
                reply_to_message_id=update.message.message_id
            )
        except:
            logger.error("Failed to send error message")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages for testing caption formatting"""
    try:
        text = update.message.text
        
        # Skip if it's a command (handled by command handlers)
        if text.startswith('/'):
            return
        
        # Format any text message as a test
        formatted = parse_caption(text)
        
        # Send to dump channel for testing if configured
        dump_success = False
        dump_message = ""
        
        if dump_channel_id:
            dump_success, dump_message = await send_to_dump_channel(context, update.message, formatted)
        
        response_text = f"🔧 **Text Format Test**\n\n"
        response_text += f"**Original:**\n`{text}`\n\n"
        response_text += f"**Professional Format:**\n`{formatted}`\n\n"
        
        if dump_channel_id:
            if dump_success:
                response_text += "📤 **Test sent to dump channel:** ✅\n\n"
            else:
                response_text += f"📤 **Dump channel test failed:** {dump_message}\n\n"
        
        response_text += "💡 **Tip:** Use `/name ANIME_NAME` to set fixed anime name"
        
        await update.message.reply_text(
            response_text,
            parse_mode='Markdown',
            reply_to_message_id=update.message.message_id
        )
        
        # Save config after processing
        save_config()
    
    except Exception as e:
        logger.error(f"Error handling text message: {e}")
        try:
            await update.message.reply_text(
                "❌ Error processing your message.",
                reply_to_message_id=update.message.message_id
            )
        except:
            logger.error("Failed to send error message for text handling")

# =============================================================================
# MAIN APPLICATION WITH IMPROVED ERROR HANDLING
# =============================================================================

def main():
    """Start the professional bot with improved error handling"""
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Error: Please set your BOT_TOKEN in the configuration section!")
        print("Get your bot token from @BotFather on Telegram")
        return
    
    print("🚀 Starting Enhanced Professional Anime Caption Formatter Bot...")
    print("📋 Features: Dynamic prefix management, Dump channel, Quality standardization")
    print(f"💾 Config file path: {CONFIG_FILE}")
    
    # Load saved configuration
    config_loaded = load_config()
    if config_loaded:
        print(f"⚙️ Loaded config: {len(prefixes)} prefixes, dump channel: {'✅' if dump_channel_id else '❌'}")
    else:
        print("⚠️ Using default configuration")
    
    # Create the Application
    try:
        application = Application.builder().token(BOT_TOKEN).build()
    except Exception as e:
        print(f"❌ Failed to create application: {e}")
        return
    
    try:
        # Add command handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("name", name_command))
        application.add_handler(CommandHandler("format", format_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("quality", quality_command))
        application.add_handler(CommandHandler("addprefix", addprefix_command))
        application.add_handler(CommandHandler("prefixlist", prefixlist_command))
        application.add_handler(CommandHandler("delprefix", delprefix_command))
        application.add_handler(CommandHandler("dumpchannel", dumpchannel_command))
        application.add_handler(CommandHandler("dumpstatus", dumpstatus_command))
        
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
        
        # Handle text messages (for testing and forwarded messages)
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text_message
        ))
        
        print("✅ Enhanced Professional bot handlers configured!")
        print("🎥 Quality Format: All qualities end with 'P' (480P, 720P, 1080P)")
        print("📱 Command Menu: Type '/' to see available commands")
        print("🔄 Prefix Management: addprefix, prefixlist, delprefix")
        print("📤 Dump Channel: dumpchannel, dumpstatus")
        print("💾 Configuration: Auto-saved with error handling")
        print("\nPress Ctrl+C to stop.")
        
        # Run the bot until the user presses Ctrl-C
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except KeyboardInterrupt:
        print("\n🛑 Enhanced Professional bot stopped by user")
        save_config()  # Save config on exit
    except Exception as e:
        logger.error(f"Bot error: {e}")
        print(f"❌ Bot encountered an error: {e}")
        save_config()  # Save config on error

if __name__ == '__main__':
    main()
