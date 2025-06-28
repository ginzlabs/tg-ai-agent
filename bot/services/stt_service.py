# services/stt_service.py
# This module handles speech-to-text processing using a backend API service

import os
import aiohttp
from utils.logger import logger
from utils.error_handler import APIError
from dotenv import load_dotenv

load_dotenv()
 
# Get API credentials from environment variables
BACKEND01_LOCAL_URL = os.getenv("BACKEND01_LOCAL_URL")
OUR_SECRET_TOKEN = os.getenv("OUR_SECRET_TOKEN")

if not BACKEND01_LOCAL_URL or not OUR_SECRET_TOKEN:
    logger.error("BACKEND01_LOCAL_URL or OUR_SECRET_TOKEN is not set")

async def submit_audio_for_transcription(file_url: str, chat_id: int, db_thread_id: str, message_id: int, temp_msg_id: int):
    """
    Submit an audio file for asynchronous transcription.
    
    Args:
        file_url (str): URL of the audio file to transcribe
        chat_id (int): Telegram chat ID for the request
        message_id (int): Telegram message ID for the request
        
    Returns:
        dict: Response from the STT API service
    """
    try:
        logger.info(f"Submitting audio file for transcription: chat_id={chat_id}, message_id={message_id}")
        
        payload = {
            "audio_input": file_url,
            "chat_id": chat_id,
            "db_thread_id": db_thread_id,
            "message_id": message_id,
            "temp_msg_id": temp_msg_id,
            "speaker_labels": True,
            "model": "nano"  # Default model
        }
        
        headers = {
            "X-API-Key": OUR_SECRET_TOKEN,
            "Content-Type": "application/json"
        }

        logger.info(f"Submitting audio for transcription with payload: {payload}")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                BACKEND01_LOCAL_URL + "/api/v1/stt", 
                json=payload, 
                headers=headers
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Audio transcription request submitted successfully for message {message_id}")
                    return result
                else:
                    error_text = await response.text()
                    error_msg = f"Failed to submit audio for transcription: HTTP {response.status} - {error_text}"
                    logger.error(error_msg)
                    raise APIError(error_msg, {
                        "status": response.status,
                        "chat_id": chat_id,
                        "message_id": message_id
                    })
                    
    except aiohttp.ClientError as e:
        logger.error(f"Network error submitting audio for transcription: {str(e)}", exc_info=True)
        raise APIError(f"Connection error when submitting audio: {str(e)}", {
            "chat_id": chat_id,
            "message_id": message_id
        })
    except Exception as e:
        logger.error(f"Error submitting audio for transcription: {str(e)}", exc_info=True)
        raise APIError(f"Failed to submit audio for transcription: {str(e)}", {
            "chat_id": chat_id,
            "message_id": message_id
        }) 