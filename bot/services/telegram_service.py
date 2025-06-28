# services/telegram_service.py
# This module uses python-telegram-bot to send, delete messages, and handle files.

import os
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import InvalidToken, TelegramError
import aiohttp
import aiofiles
from utils.logger import logger
from utils.error_handler import TelegramAPIError
import re

from dotenv import load_dotenv
load_dotenv()

# Initialize the Bot using the token from environment variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN or BOT_TOKEN.strip() == "":
    logger.error("TELEGRAM_BOT_TOKEN is not set or empty")
    raise InvalidToken("TELEGRAM_BOT_TOKEN is not set or empty. Please check your .env file.")

bot = Bot(BOT_TOKEN)


def construct_file_url(file_id: str, file_type: str = None, mime_type: str = None) -> str:
    """
    Constructs a direct file URL using the bot token.
    Note: This is a simplified approach. For production use,
    get_file_url with bot.get_file() is recommended for accurate file paths.
    
    Args:
        file_id (str): The file_id to construct URL for
        file_type (str): Type of file (photo, voice, document, video)
        mime_type (str): MIME type of the file, used to determine extension
        
    Returns:
        str: The constructed direct URL for the file
    """
    # Use file type to determine the path component and extension
    path_component = ""
    extension = ""
    
    if file_type == "photo":
        path_component = "photos/file_"
        extension = "jpg"
    elif file_type == "voice":
        path_component = "voice/file_"
        extension = "oga"
    elif file_type == "video":
        path_component = "videos/file_"
        extension = "mp4"
    elif file_type == "audio":
        path_component = "audio/file_"
        # Determine audio extension from mime_type
        if mime_type:
            if "mpeg" in mime_type or "mp3" in mime_type:
                extension = "mp3"
            elif "wav" in mime_type:
                extension = "wav"
            elif "ogg" in mime_type:
                extension = "ogg"
            elif "m4a" in mime_type or "aac" in mime_type:
                extension = "m4a"
            elif "flac" in mime_type:
                extension = "flac"
            else:
                extension = "mp3"  # Default to mp3 if unknown
        else:
            extension = "mp3"  # Default to mp3 if no mime_type
    elif file_type == "document":
        path_component = "documents/file_"
        # Try to determine extension from mime_type
        if mime_type:
            if "pdf" in mime_type:
                extension = "pdf"
            elif "word" in mime_type:
                extension = "docx"
            elif "excel" in mime_type or "spreadsheet" in mime_type:
                extension = "xlsx"
            elif "zip" in mime_type or "compressed" in mime_type:
                extension = "zip"
            else:
                extension = "dat"
        else:
            extension = "dat"
    
    # Extract a simpler ID from the file_id (this is a simplification)
    # In practice, we'd need to use the actual file path from bot.get_file()
    simple_id = str(hash(file_id))[-1]
    
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path_component}{simple_id}.{extension}"


async def extract_message_info(message: dict) -> dict:
    """
    Extract message information from a Telegram message using Telegram's native field names.
    Supports document, video, voice, and photo message types.

    Args:
        message (dict): The raw Telegram message dictionary.

    Returns:
        dict: A dictionary containing file info with Telegram field names and additional metadata.
              Returns empty dict if no supported file type is found.
    """
    try:

        msg_info = {
            'message_id': message.get('message_id'),
            'text': message.get('text', ''),
            'date': message.get('date'),
            'chat_id': message.get('chat', {}).get('id'),
            'username': message.get('from', {}).get('username'),
            'file_id': None,
            'file_name': None,
            'mime_type': None,
            'file_size': None,
            'file_url': None,
            'caption': message.get('caption', ''),
            'file_type': None,
            'reply_to_message': None
        }

        # Process reply_to_message if it exists
        if message.get('reply_to_message'):
            msg_info['reply_to_message'] = await extract_message_info(message.get('reply_to_message'))

        logger.debug(f"Extracted base message info: message_id={msg_info['message_id']}, chat_id={msg_info['chat_id']}")

        # Define a mapping of file types to their corresponding fields in the message
        file_types = {
            'document': message.get('document'),
            'audio': message.get('audio'),
            'video': message.get('video'),
            'voice': message.get('voice'),
            'photo': message.get('photo', [])[-1] if message.get('photo') else None
        }
        
        # Find the first file type in the message
        file_type, file_data = next(((k, v) for k, v in file_types.items() if v), (None, None))
        
        if file_data:
            # Common file attributes across all types
            msg_info['file_id'] = file_data.get('file_id')
            msg_info['file_size'] = file_data.get('file_size')
            msg_info['file_type'] = file_type
            msg_info['mime_type'] = file_data.get('mime_type')
            msg_info['file_url'] = await get_file_url(msg_info['file_id'])

        # Return a dictionary with only the non-None values
        return {k: v for k, v in msg_info.items() if v is not None}
    except Exception as e:
        logger.error(f"Error extracting message info: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to extract message info: {str(e)}", {"message_id": message.get("message_id")})


async def get_file_url(file_id: str) -> str:
    """
    Given a file_id, retrieves the downloadable URL from Telegram.
    
    Args:
        file_id (str): The file_id to get a URL for
        
    Returns:
        str: The direct download URL for the file
    """
    try:
        logger.info(f"Getting file URL for file_id: {file_id}")
        file = await bot.get_file(file_id)
        file_url = file.file_path
        logger.debug(f"File URL retrieved successfully: {file_url}")
        return file_url
    except TelegramError as e:
        logger.error(f"Telegram error getting file URL: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to get file URL: {str(e)}", {"file_id": file_id})
    except Exception as e:
        logger.error(f"Error getting file URL: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to get file URL: {str(e)}", {"file_id": file_id})


async def download_file_to_disk(file_id: str, download_path: str) -> str:
    """
    Downloads a file from Telegram to the specified path.
    
    Args:
        file_id (str): The file_id to download
        download_path (str): The directory path to save the file to
        
    Returns:
        str: The full path to the downloaded file
    """
    try:
        logger.info(f"Downloading file to disk: {file_id}")
        file_url = await get_file_url(file_id)
        
        if not os.path.exists(download_path):
            os.makedirs(download_path, exist_ok=True)
            logger.debug(f"Created directory: {download_path}")
        
        file_name = file_url.split('/')[-1]
        file_path = os.path.join(download_path, file_name)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as response:
                if response.status == 200:
                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(await response.read())
                    logger.info(f"File downloaded successfully to: {file_path}")
                    return file_path
                else:
                    error_msg = f"Failed to download file: HTTP {response.status}"
                    logger.error(error_msg)
                    raise TelegramAPIError(error_msg, {"file_id": file_id, "status": response.status})
    except TelegramAPIError:
        # Re-raise the TelegramAPIError without wrapping it
        raise
    except Exception as e:
        logger.error(f"Error downloading file to disk: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to download file: {str(e)}", 
                             {"file_id": file_id, "download_path": download_path})


async def download_file_to_memory(file_id: str) -> bytes:
    """
    Downloads a file from Telegram and returns it as bytes.
    
    Args:
        file_id (str): The file_id to download
        
    Returns:
        bytes: The file content as bytes
    """
    try:
        logger.info(f"Downloading file to memory: {file_id}")
        file_url = await get_file_url(file_id)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as response:
                if response.status == 200:
                    content = await response.read()
                    logger.info(f"File downloaded successfully to memory ({len(content)} bytes)")
                    return content
                else:
                    error_msg = f"Failed to download file to memory: HTTP {response.status}"
                    logger.error(error_msg)
                    raise TelegramAPIError(error_msg, {"file_id": file_id, "status": response.status})
    except TelegramAPIError:
        # Re-raise the TelegramAPIError without wrapping it
        raise
    except Exception as e:
        logger.error(f"Error downloading file to memory: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to download file to memory: {str(e)}", {"file_id": file_id})

def escape_markdown_v2(text):
    escape_chars = r'_*\[\]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

async def send_message(chat_id: int, text: str, parse_mode: str = None):
    """
    Send a message to a Telegram user using python-telegram-bot.
    
    Args:
        chat_id (int): The chat ID to send the message to
        text (str): The text content of the message
        parse_mode (str, optional): Parse mode for text formatting (HTML, Markdown, etc.)
    """
    try:
        logger.info(f"Sending message to chat_id: {chat_id}")
        
        # Limit the text to 4096 characters
        text = text[:4096]

        # If text is empty, send a message to the user that response was empty
        if not text:
            text = "..."

        message = await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
        logger.info(f"Message sent successfully. Message ID: {message.message_id}")
        return message
    # If the message is not sent, try again with escaped characters and markdown v2
    except TelegramError as e:
        logger.error(f"Telegram error sending message {text} to {chat_id} with parse_mode {parse_mode}: {str(e)}. Will try again with escaped characters and markdown v2", exc_info=True)
        escaped_text = escape_markdown_v2(text)
        try:
            message = await bot.send_message(chat_id=chat_id, text=escaped_text, parse_mode="MarkdownV2")
            logger.info(f"Message sent successfully. Message ID: {message.message_id}")
            return message
        # If the message is still not sent, try with parse_mode set to None
        except TelegramError as e:
            logger.error(f"Telegram error sending message {escaped_text} to {chat_id} with parse_mode MarkdownV2: {str(e)}. Will try again without parse_mode", exc_info=True)
            try:
                message = await bot.send_message(chat_id=chat_id, text=text, parse_mode=None)
                logger.info(f"Message sent successfully. Message ID: {message.message_id}")
                return message
            except TelegramError as e:
                logger.error(f"Telegram error sending message {text} to {chat_id} without parse_mode: {str(e)}", exc_info=True)
                raise TelegramAPIError(f"Failed to send message: {str(e)}", {"chat_id": chat_id, "text": text})
    except Exception as e:
        logger.error(f"Error sending message to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send message: {str(e)}", {"chat_id": chat_id})


async def send_document(chat_id: int, document_url: str, caption: str = None, filename: str = None, reply_to_message_id: int = None):
    """
    Send a document to a Telegram user.
    
    Args:
        chat_id (int): The chat ID to send the document to
        document_url (str): URL of the document to be sent
        caption (str, optional): Caption for the document
        filename (str, optional): Custom filename for the document
        reply_to_message_id (int, optional): Message ID to reply to
        
    Returns:
        The sent message object
    """
    try:
        logger.info(f"Sending document to chat_id: {chat_id}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(document_url) as response:
                if response.status != 200:
                    error_msg = f"Failed to download document from URL: HTTP {response.status}"
                    logger.error(error_msg)
                    raise TelegramAPIError(error_msg, {"document_url": document_url})
                
                content = await response.read()

                message = await bot.send_document(
                    chat_id=chat_id,
                    document=content,
                    caption=caption,
                    filename=filename,
                    parse_mode="HTML",
                    reply_to_message_id=reply_to_message_id
                )
                
        logger.info(f"Document sent successfully. Message ID: {message.message_id}")
        return message
    except TelegramError as e:
        logger.error(f"Telegram error sending document to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send document: {str(e)}", {"chat_id": chat_id})
    except Exception as e:
        logger.error(f"Error sending document to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send document: {str(e)}", {"chat_id": chat_id})


async def send_photo(chat_id: int, photo_url: str, caption: str = None, reply_to_message_id: int = None):
    """
    Send a photo to a Telegram user.
    
    Args:
        chat_id (int): The chat ID to send the photo to
        photo_url (str): URL of the photo to be sent
        caption (str, optional): Caption for the photo
        reply_to_message_id (int, optional): Message ID to reply to
        
    Returns:
        The sent message object
    """
    try:
        logger.info(f"Sending photo to chat_id: {chat_id}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url) as response:
                if response.status != 200:
                    error_msg = f"Failed to download photo from URL: HTTP {response.status}"
                    logger.error(error_msg)
                    raise TelegramAPIError(error_msg, {"photo_url": photo_url})
                
                content = await response.read()
                
                message = await bot.send_photo(
                    chat_id=chat_id,
                    photo=content,
                    caption=caption,
                    reply_to_message_id=reply_to_message_id
                )
                
        logger.info(f"Photo sent successfully. Message ID: {message.message_id}")
        return message
    except TelegramError as e:
        logger.error(f"Telegram error sending photo to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send photo: {str(e)}", {"chat_id": chat_id})
    except Exception as e:
        logger.error(f"Error sending photo to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send photo: {str(e)}", {"chat_id": chat_id})


async def send_audio(chat_id: int, audio_url: str, caption: str = None, filename: str = None, reply_to_message_id: int = None):
    """
    Send an audio file to a Telegram user.
    
    Args:
        chat_id (int): The chat ID to send the audio to
        audio_url (str): URL of the audio to be sent
        caption (str, optional): Caption for the audio
        filename (str, optional): Custom filename for the audio
        reply_to_message_id (int, optional): Message ID to reply to
        
    Returns:
        The sent message object
    """
    try:
        logger.info(f"Sending audio to chat_id: {chat_id}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(audio_url) as response:
                if response.status != 200:
                    error_msg = f"Failed to download audio from URL: HTTP {response.status}"
                    logger.error(error_msg)
                    raise TelegramAPIError(error_msg, {"audio_url": audio_url})
                
                content = await response.read()
                
                message = await bot.send_audio(
                    chat_id=chat_id,
                    audio=content,
                    caption=caption,
                    filename=filename,
                    reply_to_message_id=reply_to_message_id
                )
                
        logger.info(f"Audio sent successfully. Message ID: {message.message_id}")
        return message
    except TelegramError as e:
        logger.error(f"Telegram error sending audio to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send audio: {str(e)}", {"chat_id": chat_id})
    except Exception as e:
        logger.error(f"Error sending audio to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send audio: {str(e)}", {"chat_id": chat_id})


async def send_video(chat_id: int, video_url: str, caption: str = None, filename: str = None, reply_to_message_id: int = None):
    """
    Send a video to a Telegram user.
    
    Args:
        chat_id (int): The chat ID to send the video to
        video_url (str): URL of the video to be sent
        caption (str, optional): Caption for the video
        filename (str, optional): Custom filename for the video
        reply_to_message_id (int, optional): Message ID to reply to
        
    Returns:
        The sent message object
    """
    try:
        logger.info(f"Sending video to chat_id: {chat_id}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(video_url) as response:
                if response.status != 200:
                    error_msg = f"Failed to download video from URL: HTTP {response.status}"
                    logger.error(error_msg)
                    raise TelegramAPIError(error_msg, {"video_url": video_url})
                
                content = await response.read()
                
                message = await bot.send_video(
                    chat_id=chat_id,
                    video=content,
                    caption=caption,
                    filename=filename,
                    reply_to_message_id=reply_to_message_id
                )
                
        logger.info(f"Video sent successfully. Message ID: {message.message_id}")
        return message
    except TelegramError as e:
        logger.error(f"Telegram error sending video to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send video: {str(e)}", {"chat_id": chat_id})
    except Exception as e:
        logger.error(f"Error sending video to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send video: {str(e)}", {"chat_id": chat_id})


async def send_voice(chat_id: int, voice_url: str, caption: str = None, filename: str = None, reply_to_message_id: int = None):
    """
    Send a voice message to a Telegram user.
    
    Args:
        chat_id (int): The chat ID to send the voice message to
        voice_url (str): URL of the voice message to be sent
        caption (str, optional): Caption for the voice message
        filename (str, optional): Custom filename for the voice message
        reply_to_message_id (int, optional): Message ID to reply to
        
    Returns:
        The sent message object
    """
    try:
        logger.info(f"Sending voice message to chat_id: {chat_id}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(voice_url) as response:
                if response.status != 200:
                    error_msg = f"Failed to download voice message from URL: HTTP {response.status}"
                    logger.error(error_msg)
                    raise TelegramAPIError(error_msg, {"voice_url": voice_url})
                
                content = await response.read()
                
                message = await bot.send_voice(
                    chat_id=chat_id,
                    voice=content,
                    caption=caption,
                    filename=filename,
                    reply_to_message_id=reply_to_message_id
                )
                
        logger.info(f"Voice message sent successfully. Message ID: {message.message_id}")
        return message
    except TelegramError as e:
        logger.error(f"Telegram error sending voice message to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send voice message: {str(e)}", {"chat_id": chat_id})
    except Exception as e:
        logger.error(f"Error sending voice message to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send voice message: {str(e)}", {"chat_id": chat_id})


async def send_file_by_type(chat_id: int, file_url: str, file_type: str, caption: str = None, file_name: str = None, reply_to_message_id: int = None):
    """
    Send a file to a Telegram user based on its type.
    
    Args:
        chat_id (int): The chat ID to send the file to
        file_url (str): URL of the file to be sent
        file_type (str): Type of the file ("document", "photo", "audio", "video", "voice")
        caption (str, optional): Caption for the file
        file_name (str, optional): Custom filename for the file
        reply_to_message_id (int, optional): Message ID to reply to
        
    Returns:
        The sent message object
    """
    
    if file_type == "document":
        return await send_document(chat_id, file_url, caption, file_name, reply_to_message_id)
    elif file_type == "photo":
        return await send_photo(chat_id, file_url, caption, reply_to_message_id)
    elif file_type == "audio":
        return await send_audio(chat_id, file_url, caption, file_name, reply_to_message_id)
    elif file_type == "video":
        return await send_video(chat_id, file_url, caption, file_name, reply_to_message_id)
    elif file_type == "voice":
        return await send_voice(chat_id, file_url, caption, file_name, reply_to_message_id)
    else:
        logger.error(f"Invalid file type: {file_type}")
        raise TelegramAPIError(f"Invalid file type: {file_type}", {"file_type": file_type})


async def send_reply(chat_id: int, text: str, reply_to_message_id: int, parse_mode: str = None):
    """
    Send a reply to a specific message in Telegram.
    
    Args:
        chat_id (int): The chat ID to send the reply to
        text (str): The text content of the reply message
        reply_to_message_id (int): The message ID to reply to
        parse_mode (str, optional): Parse mode for text formatting (HTML, Markdown, etc.)
        
    Returns:
        The sent message object
    """
    try:
        logger.info(f"Sending reply to message {reply_to_message_id} in chat {chat_id}")
                
        message = await bot.send_message(
            chat_id=chat_id, 
            text=text, 
            reply_to_message_id=reply_to_message_id,
            parse_mode=parse_mode
        )
        logger.info(f"Reply sent successfully. Reply message ID: {message.message_id}")
        return message
    except TelegramError as e:
        logger.error(f"Telegram error sending reply to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send reply: {str(e)}", 
                             {"chat_id": chat_id, "reply_to_message_id": reply_to_message_id})
    except Exception as e:
        logger.error(f"Error sending reply to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send reply: {str(e)}", 
                             {"chat_id": chat_id, "reply_to_message_id": reply_to_message_id})


async def delete_message(chat_id: int, message_id: int):
    """
    Delete a message from Telegram.
    """
    try:
        logger.info(f"Deleting message {message_id} from chat {chat_id}")
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Message {message_id} deleted successfully")
        return True
    except TelegramError as e:
        logger.error(f"Telegram error deleting message {message_id} from {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to delete message: {str(e)}", 
                             {"chat_id": chat_id, "message_id": message_id})
    except Exception as e:
        logger.error(f"Error deleting message {message_id} from {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to delete message: {str(e)}", 
                             {"chat_id": chat_id, "message_id": message_id})


async def enrich_message_with_file_url(msg_info: dict) -> dict:
    """
    Enriches a message info dictionary with a file URL if it contains a file_id.
    
    Args:
        msg_info (dict): Message info dictionary from extract_message_info
        
    Returns:
        dict: The same dictionary with file_url populated if applicable
    """
    if msg_info.get('file_id'):
        try:
            logger.info(f"Enriching message with file URL for file_id: {msg_info['file_id']}")
            msg_info['file_url'] = await get_file_url(msg_info['file_id'])
            logger.info(f"Message enriched with file URL")
        except Exception as e:
            logger.error(f"Error getting file URL: {str(e)}", exc_info=True)
            # Don't raise here - we want to continue even if getting the URL fails
    
    return msg_info


async def send_message_with_inline_keyboard(chat_id: int, text: str, buttons: list):
    """
    Send a message with inline keyboard buttons.
    
    Args:
        chat_id (int): The chat ID to send the message to
        text (str): The text content of the message
        buttons (list): List of button tuples (text, callback_data)
        
    Returns:
        The sent message object
    """
    try:
        logger.info(f"Sending message with inline keyboard to chat_id: {chat_id}")
        
        # Create keyboard markup
        keyboard = []
        for row in buttons:
            keyboard_row = []
            for button_text, callback_data in row:
                keyboard_row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
            keyboard.append(keyboard_row)
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = await bot.send_message(
            chat_id=chat_id, 
            text=text, 
            reply_markup=reply_markup
        )
        logger.info(f"Message with inline keyboard sent successfully. Message ID: {message.message_id}")
        return message
    except TelegramError as e:
        logger.error(f"Telegram error sending message with inline keyboard to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send message with inline keyboard: {str(e)}", {"chat_id": chat_id})
    except Exception as e:
        logger.error(f"Error sending message with inline keyboard to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send message with inline keyboard: {str(e)}", {"chat_id": chat_id})


async def send_reply_with_inline_keyboard(chat_id: int, text: str, reply_to_message_id: int, buttons: list, parse_mode: str = None):
    """
    Send a reply with inline keyboard buttons to a specific message.
    
    Args:
        chat_id (int): The chat ID to send the reply to
        text (str): The text content of the reply message
        reply_to_message_id (int): The message ID to reply to
        buttons (list): List of button tuples (text, callback_data)
        
    Returns:
        The sent message object
    """
    try:
        logger.info(f"Sending reply with inline keyboard to message {reply_to_message_id} in chat {chat_id}")
        
        # Create keyboard markup
        keyboard = []
        for row in buttons:
            keyboard_row = []
            for button_text, callback_data in row:
                keyboard_row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
            keyboard.append(keyboard_row)
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = await bot.send_message(
            chat_id=chat_id, 
            text=text, 
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        logger.info(f"Reply with inline keyboard sent successfully. Reply message ID: {message.message_id}")
        return message
    except TelegramError as e:
        logger.error(f"Telegram error sending reply with inline keyboard to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send reply with inline keyboard: {str(e)}", 
                             {"chat_id": chat_id, "reply_to_message_id": reply_to_message_id})
    except Exception as e:
        logger.error(f"Error sending reply with inline keyboard to {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to send reply with inline keyboard: {str(e)}", 
                             {"chat_id": chat_id, "reply_to_message_id": reply_to_message_id})


async def edit_message_text(chat_id: int, message_id: int, text: str, parse_mode: str = None, reply_markup=None):
    """
    Edit an existing message text.
    
    Args:
        chat_id (int): The chat ID where the message is
        message_id (int): The message ID to edit
        text (str): The new text content
        reply_markup: Optional inline keyboard markup
        
    Returns:
        The edited message object
    """
    try:
        logger.info(f"Editing message {message_id} in chat {chat_id}")
        message = await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
        logger.info(f"Message {message_id} edited successfully")
        return message
    except TelegramError as e:
        logger.error(f"Telegram error editing message {message_id} in chat {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to edit message: {str(e)}", 
                             {"chat_id": chat_id, "message_id": message_id})
    except Exception as e:
        logger.error(f"Error editing message {message_id} in chat {chat_id}: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to edit message: {str(e)}", 
                             {"chat_id": chat_id, "message_id": message_id})


async def handle_special_commands(msg_info: dict, supabase_client) -> tuple:
    """
    Handles special commands like /clear_dialog, /clear_memory, /check_limits, /change_model, and /list_abilities.
    
    Special commands:
    - /clear_dialog: Clears the message history from the conversation.
    - /clear_memory: Clears the context/memory but keeps the message history.
    - /check_limits: Shows the user's usage statistics, limits, and subscription tier.
    - /change_model: Shows available language models and allows the user to switch between them.
    - /list_abilities: Shows the user's tier and available tools based on their subscription.
    
    For /check_limits, the response includes:
    - Daily and monthly usage
    - Daily and monthly limits if they exist
    - Percentage of daily limit used and status indicator
    - Remaining messages for the day
    - Scheduled tasks usage and limits
    - Subscription tier information
    
    Args:
        msg_info (dict): The message information dictionary
        supabase_client: The Supabase client for database operations
        
    Returns:
        tuple: (was_command_handled, result_data)
              was_command_handled (bool): True if a special command was handled, False otherwise
              result_data (dict): Dictionary with result information or None if no command was handled
    """
    try:
        # Check if there's text in the message and if it's a special command
        if not msg_info.get('text'):
            return False, None
            
        text = msg_info['text'].strip()
        chat_id = msg_info['chat_id']
        message_id = msg_info['message_id']
        
        # Handle /clear_dialog command
        if text == '/clear_dialog':
            logger.info(f"Handling /clear_dialog command for user: {chat_id}")
            try:
                thread_id = msg_info.get('db_thread_id')
                if not thread_id:
                    raise ValueError("No thread_id found in message info")
                    
                response = await supabase_client.clear_dialog(chat_id, thread_id)
                await send_reply(
                    chat_id, 
                    "🗑️ *Dialog history has been cleared successfully\\!*\n\n_Your previous conversation messages have been removed\\._", 
                    message_id,
                    parse_mode="MarkdownV2"
                )
                return True, {"success": True, "result": "Dialog cleared"}
            except Exception as e:
                logger.error(f"Error clearing dialog: {str(e)}", exc_info=True)
                await send_reply(
                    chat_id, 
                    "❌ *Failed to clear dialog history\\.*\n_Please try again later\\._", 
                    message_id,
                    parse_mode="MarkdownV2"
                )
                return True, {"success": False, "result": "Failed to clear dialog"}
        
        # Handle /clear_memory command
        elif text == '/clear_memory':
            logger.info(f"Handling /clear_memory command for user: {chat_id}")
            try:
                thread_id = msg_info.get('db_thread_id')
                if not thread_id:
                    raise ValueError("No thread_id found in message info")
                    
                response = await supabase_client.clear_memory(chat_id, thread_id)
                await send_reply(
                    chat_id, 
                    "🧹 *Memory context has been cleared successfully\\!*\n\n_The bot has forgotten the context of your conversation but kept the message history\\._", 
                    message_id,
                    parse_mode="MarkdownV2"
                )
                return True, {"success": True, "result": "Memory cleared"}
            except Exception as e:
                logger.error(f"Error clearing memory: {str(e)}", exc_info=True)
                await send_reply(
                    chat_id, 
                    "❌ *Failed to clear memory context\\.*\n_Please try again later\\._", 
                    message_id,
                    parse_mode="MarkdownV2"
                )
                return True, {"success": False, "result": "Failed to clear memory"}
        
        # Handle /check_limits command
        elif text == '/check_limits':
            logger.info(f"Handling /check_limits command for user: {chat_id}")
            try:
                response = await supabase_client.check_limits(chat_id)
                
                # Format the limits information
                if hasattr(response, "data"):
                    limits_data = response.data
                else:
                    limits_data = response
                    
                if limits_data:
                    # Format the limits information into a user-friendly message with markdown
                    if "error" in limits_data:
                        error_text = limits_data['error'].replace('.', '\\.').replace('-', '\\-').replace('!', '\\!')
                        limits_message = f"❌ *Error: {error_text}*"
                    else:
                        # Include chat ID in the header
                        limits_message = f"📊 *Usage Statistics for User ID:* `{chat_id}`\n\n"
                        
                        # Show daily usage with limit
                        if "daily_usage" in limits_data:
                            daily_usage = limits_data['daily_usage']
                            daily_limit = limits_data.get('daily_limit', 0)
                            
                            # Format differently based on whether limit exists
                            if daily_limit > 0:
                                limits_message += f"• *Daily usage:* `{daily_usage}/{daily_limit}` messages\n"
                                
                                # Calculate daily percentage usage
                                daily_percent = min(100, round((daily_usage / daily_limit) * 100))
                                status_emoji = "🟢" if daily_percent < 80 else "🟠" if daily_percent < 95 else "🔴"
                                limits_message += f"{status_emoji} {daily_percent}% used\n"
                                
                                # Show remaining messages for today
                                remaining = max(0, daily_limit - daily_usage)
                                limits_message += f"`{remaining}` remaining\n\n"
                            else:
                                limits_message += f"• *Daily usage:* `{daily_usage}` messages\n\n"
                            
                        # Show monthly usage with limit
                        if "monthly_usage" in limits_data:
                            monthly_usage = limits_data['monthly_usage']
                            monthly_limit = limits_data.get('monthly_limit', 0)
                            
                            # Format differently based on whether limit exists
                            if monthly_limit > 0:
                                limits_message += f"• *Monthly usage:* `{monthly_usage}/{monthly_limit}` messages\n"
                                
                                # Calculate monthly percentage usage
                                monthly_percent = min(100, round((monthly_usage / monthly_limit) * 100))
                                status_emoji = "🟢" if monthly_percent < 80 else "🟠" if monthly_percent < 95 else "🔴"
                                limits_message += f"{status_emoji} {monthly_percent}% used\n"
                                
                                # Show remaining messages for the month
                                remaining_monthly = max(0, monthly_limit - monthly_usage)
                                limits_message += f"`{remaining_monthly}` remaining\n\n"
                            else:
                                limits_message += f"• *Monthly usage:* `{monthly_usage}` messages\n\n"
                        
                        # Show cron jobs usage with limit - New section
                        if "cron_usage" in limits_data and "crons_limit" in limits_data:
                            cron_usage = limits_data['cron_usage']
                            crons_limit = limits_data.get('crons_limit', 0)
                            
                            # Format differently based on whether limit exists
                            if crons_limit > 0:
                                limits_message += f"• *Scheduled tasks:* `{cron_usage}/{crons_limit}` tasks\n"
                                
                                # Calculate cron percentage usage
                                cron_percent = min(100, round((cron_usage / crons_limit) * 100))
                                status_emoji = "🟢" if cron_percent < 80 else "🟠" if cron_percent < 95 else "🔴"
                                limits_message += f"{status_emoji} {cron_percent}% used\n"
                                
                                # Show remaining cron slots
                                remaining_crons = max(0, crons_limit - cron_usage)
                                limits_message += f"`{remaining_crons}` available slots\n\n"
                            else:
                                limits_message += f"• *Scheduled tasks:* `{cron_usage}` tasks\n\n"
                        
                        limits_message += "_Usage counters are updated in real\\-time\\._"
                else:
                    limits_message = "❓ *Could not retrieve your usage information\\.*\n\n_Please try again later\\._"
                    
                await send_reply(
                    chat_id, 
                    limits_message, 
                    message_id,
                    parse_mode="MarkdownV2"
                )
                return True, {"success": True, "result": "Limits checked"}
            except Exception as e:
                logger.error(f"Error checking limits: {str(e)}", exc_info=True)
                await send_reply(
                    chat_id, 
                    "❌ *Failed to check usage limits\\.*\n\n_Please try again later\\._", 
                    message_id,
                    parse_mode="MarkdownV2"
                )
                return True, {"success": False, "result": "Failed to check limits"}
                
        # Handle /change_model command
        elif text == '/change_model':
            logger.info(f"Handling /change_model command for user: {chat_id}")
            try:
                # Fetch allowed models and current user model from server_settings table
                response = await supabase_client.sb_client.rpc("get_allowed_llms", {"p_chat_id": chat_id}).execute()
                
                if hasattr(response, "data"):
                    settings_data = response.data
                else:
                    settings_data = response
                    
                if not settings_data or len(settings_data) == 0 or 'result' not in settings_data[0]:
                    await send_reply(
                        chat_id,
                        "❌ *No available models found\\.*\n\n_Please try again later or contact the administrator\\._",
                        message_id,
                        parse_mode="MarkdownV2"
                    )
                    return True, {"success": False, "result": "No models found"}
                
                result_data = settings_data[0]['result']
                allowed_models = result_data.get('allowed_llms', [])
                current_model = result_data.get('llm_choice')
                
                if not allowed_models or len(allowed_models) == 0:
                    await send_reply(
                        chat_id,
                        "❌ *No available models configured\\.*\n\n_Please contact the administrator to set up models\\._",
                        message_id,
                        parse_mode="MarkdownV2"
                    )
                    return True, {"success": False, "result": "Empty models list"}
                
                # Create a keyboard with available models
                model_buttons = []
                
                # Format models as button rows (one model per row)
                for model in allowed_models:
                    # Add a checkmark to the current model
                    button_text = f"✓ {model}" if model == current_model else model
                    # The callback data includes the model name to identify which model was selected
                    model_buttons.append([(button_text, f"change_model:{model}")])
                
                # Add a button to cancel model selection
                model_buttons.append([("Cancel", "change_model:cancel")])
                
                await send_reply_with_inline_keyboard(
                    chat_id,
                    "🤖 *Choose a language model:*",
                    message_id,
                    model_buttons,
                    parse_mode="MarkdownV2"
                )
                return True, {"success": True, "result": "Models displayed"}
            except Exception as e:
                logger.error(f"Error displaying available models: {str(e)}", exc_info=True)
                await send_reply(
                    chat_id,
                    "❌ *Failed to retrieve available models\\.*\n\n_Please try again later\\._",
                    message_id,
                    parse_mode="MarkdownV2"
                )
                return True, {"success": False, "result": "Failed to display models", "error": str(e)}
                
        # Handle /list_abilities command
        elif text == '/list_abilities':
            logger.info(f"Handling /list_abilities command for user: {chat_id}")
            try:
                # Fetch user profile and tools using the provided RPC
                response = await supabase_client.sb_client.rpc("get_user_profile_and_tools", {"p_chat_id": chat_id}).execute()
                
                if hasattr(response, "data"):
                    profile_data = response.data
                else:
                    profile_data = response
                    
                if not profile_data or len(profile_data) == 0 or 'result' not in profile_data[0]:
                    await send_reply(
                        chat_id,
                        "❌ *Could not retrieve your profile information.*\n\n_Please try again later._",
                        message_id,
                        parse_mode="Markdown"
                    )
                    return True, {"success": False, "result": "No profile found"}
                
                result_data = profile_data[0]['result']
                
                # Check if the result was successful
                if not result_data.get('success', False):
                    error_message = result_data.get('message', 'Unknown error')
                    await send_reply(
                        chat_id,
                        f"❌ *Error: {error_message}*",
                        message_id,
                        parse_mode="Markdown"
                    )
                    return True, {"success": False, "result": "Error in profile data"}
                
                # Format the user profile and tools information
                tier = result_data.get('tier', 0)
                expire_at = result_data.get('expire_at')
                tools = result_data.get('tools', [])
                
                # Create a user-friendly message with markdown
                profile_message = f"🧰 *Your Abilities & Tools*\n\n"
                
                # Add tier information with corresponding emoji
                tier_emoji = "⭐" * tier if 1 <= tier <= 4 else "🔹"
                profile_message += f"*Subscription tier:* {tier_emoji} `Tier {tier}`\n\n"

                # Add expiration date if available
                if expire_at:
                    # Format the date as YYYY-MM-DD, no need to escape for Markdown
                    try:
                        from datetime import datetime
                        if isinstance(expire_at, str):
                            expire_date = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
                        else:
                            expire_date = expire_at
                        formatted_date = expire_date.strftime('%Y-%m-%d')
                        profile_message += f"*Expires on:* `{formatted_date}`\n\n"
                    except Exception as date_error:
                        logger.error(f"Error formatting expiration date: {str(date_error)}", exc_info=True)
                        # Use raw value if parsing fails
                        profile_message += f"*Expires on:* `{expire_at}`\n\n"
                
                # Add available tools list
                if tools and len(tools) > 0:
                    profile_message += f"*Available tools ({len(tools)}):*\n\n"
                    
                    for i, tool in enumerate(tools):
                        tool_title = tool.get('tool_title', 'Unknown tool')
                        tool_description = tool.get('tool_description', '')
                        
                        # Add a tool number and its title/description
                        profile_message += f"{i+1}. *{tool_title}*\n"
                        if tool_description:
                            profile_message += f"   _{tool_description}_\n\n"
                        else:
                            profile_message += "\n"
                else:
                    profile_message += "*No tools available at your tier.*\n\n"
                                
                await send_reply(
                    chat_id,
                    profile_message,
                    message_id,
                    parse_mode="Markdown"
                )
                return True, {"success": True, "result": "Profile displayed"}
            except Exception as e:
                logger.error(f"Error retrieving user profile and tools: {str(e)}", exc_info=True)
                await send_reply(
                    chat_id,
                    "❌ *Failed to retrieve your abilities and tools.*\n\n_Please try again later._",
                    message_id,
                    parse_mode="Markdown"
                )
                return True, {"success": False, "result": "Failed to display profile", "error": str(e)}
                
        # No special command found
        return False, None
            
    except Exception as e:
        logger.error(f"Error handling special commands: {str(e)}", exc_info=True)
        return False, {"error": str(e)}


# Example usage (for testing purposes, can be removed in production):
if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv

    load_dotenv()

    # Example document message
    sample_message = {
        'message_id': 186,
        'date': 1742232545,
        'chat': {'id': 1000001, 'type': 'private'},
        'from': {'id': 1000001, 'username': 'test1'},
        'document': {
            'file_name': 'test1.pdf',
            'mime_type': 'application/pdf',
            'file_id': 'BQACAgQAAxkBAAO6Z9hb4U7z9p00UW_YSSkl',
            'file_size': 12464556
        },
        'caption': 'Sample document'
    }

    async def test_functions():
        # Extract file info
        msg_info = extract_message_info(sample_message)
        print("Extracted message info:", msg_info)

        # Enrich with file URL
        enriched_msg = await enrich_message_with_file_url(msg_info)
        print(f"Enriched message info with URL: {enriched_msg.get('file_url')}")

        # Download to disk
        local_path = await download_file_to_disk(msg_info['file_id'], "downloads")
        print(f"Downloaded to disk: {local_path}")

        # Download to memory
        file_bytes = await download_file_to_memory(msg_info['file_id'])
        print(f"Downloaded to memory: {len(file_bytes)} bytes")

    asyncio.run(test_functions())