# api/endpoints.py
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse, Response
from typing import Dict, Any, Optional, List
from schemas import TranscriptionRequest, STTRequest, TaskResponse, MarketReportRequest
from services.task_manager import (
    add_task, get_task_status, get_queue_status,
    TaskStatus, TaskType
)
from services.report_generator import generate_market_report
from services.transcription import transcribe_audio as transcribe_audio_service
from services.speech_to_text import process_speech_to_text, get_transcript_result
from utils.limiter import limiter, get_rate_limit
from utils.logger import logger
from utils.security import verify_api_key
from config import API_PREFIX
from datetime import datetime, UTC
from services.supabase_client import get_supabase_client
import os
from config import STT_SUMMARY_TEXTS
import aiohttp

# Get environment variables
TAGENT_LOCAL_URL = os.getenv("TAGENT_LOCAL_URL")
OUR_SECRET_TOKEN = os.getenv("OUR_SECRET_TOKEN")

# Main router with API prefix
router = APIRouter(prefix=API_PREFIX)

# Webhook router without prefix for external accessibility
webhook_router = APIRouter()


@router.post("/transcribe", response_model=TaskResponse, dependencies=[Depends(verify_api_key)])
@limiter.limit(get_rate_limit("transcribe"))
async def transcribe_audio(request: Request, transcription_request: TranscriptionRequest, background_tasks: BackgroundTasks):
    """
    Start an audio transcription task.
    This is a long-running task that will be processed in the background.
    Requires API key authentication.
    
    The task will be queued if the concurrency limit (2 concurrent transcriptions) is reached.
    Takes approximately 30 seconds to complete.
    
    Example calls:
        Windows CMD:
        curl -X POST "http://localhost:8001/api/v1/transcribe" -H "X-API-Key: your_api_key" -H "Content-Type: application/json" -d "{\"audio_url\": \"https://example.com/short.mp3\", \"language\": \"en\"}"
        
        Linux/Mac:
        curl -X POST "http://localhost:8001/api/v1/transcribe" -H "X-API-Key: your_api_key" -H "Content-Type: application/json" -d '{"audio_url": "https://example.com/short.mp3", "language": "en"}'
    """
    logger.info(f"Received transcription request for audio: {transcription_request.audio_url}")
    
    async def transcribe():
        return await transcribe_audio_service(
            audio_url=transcription_request.audio_url,
            language=transcription_request.language
        )
    
    task_id = await add_task(transcribe, TaskType.TRANSCRIPTION, transcription_request.task_id)
    status, result = await get_task_status(task_id)
    return result


@router.get("/task/{task_id}", response_model=TaskResponse, dependencies=[Depends(verify_api_key)])
async def get_task(task_id: str):
    """
    Get the status and result of a task.
    Requires API key authentication.
    
    Example call:
    curl -X GET "http://localhost:8001/api/v1/task/your-task-id-here" -H "X-API-Key: your_api_key"
    """
    status, result = await get_task_status(task_id)
    if status == TaskStatus.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return result

@router.get("/chat-ids", dependencies=[Depends(verify_api_key)])
async def get_chat_ids(limit: int = 10, supabase=Depends(get_supabase_client)):
    """
    Get a list of chat IDs ordered by creation date.
    Requires API key authentication.
    
    Parameters:
        - limit: Maximum number of chat IDs to return (default: 10)
    
    Returns:
        - List of chat IDs ordered by created_at (newest first)
    
    Example call:
    curl -X GET "http://localhost:8001/api/v1/chat-ids?limit=20" -H "X-API-Key: your_api_key"
    """
    logger.info(f"Retrieving {limit} chat IDs ordered by creation date")
    
    try:
        chat_ids = await supabase.get_chat_ids(limit)
        
        return {
            "total": len(chat_ids),
            "chat_ids": chat_ids
        }
    except Exception as e:
        logger.error(f"Error retrieving chat IDs: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve chat IDs: {str(e)}"
        )

@router.get("/queue-status", dependencies=[Depends(verify_api_key)])
async def queue_status(task_type: Optional[str] = None):
    """
    Get the current status of task queues.
    Requires API key authentication.
    
    Args:
        task_type: Optional task type to check specific queue (transcription, report, or default)
    
    Returns:
        Queue status information including running tasks, queued tasks, and concurrency limits
    """
    try:
        if task_type:
            task_enum = TaskType[task_type.upper()]
            return await get_queue_status(task_enum)
        return await get_queue_status()
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task type. Must be one of: {', '.join(t.value for t in TaskType)}"
        )

@router.post("/stt", dependencies=[Depends(verify_api_key)])
@limiter.limit(get_rate_limit("stt"))
async def speech_to_text(request: Request, stt_request: STTRequest, supabase=Depends(get_supabase_client)):
    """
    Process speech-to-text for the given audio input and store results in database.
    This endpoint processes the request using AssemblyAI webhooks for faster responses.
    Requires API key authentication.
    
    Parameters:
        - audio_url / audio_input: URL or path to the audio file (both parameter names are accepted)
        - chat_id: The ID of the chat this audio is associated with
        - db_thread_id: The ID of the thread this audio is associated with
        - message_id: The ID of the message this audio is associated with
        - speaker_labels: Whether to enable speaker diarization (default: False)
        - model: Speech model to use (options: "nano" for faster processing, "best" for more accuracy, default: "nano")
        - language_detection: Whether to enable automatic language detection (default: True)
        - language_code: Optional language code to use (e.g., "en_us", "fr", "es")
    
    Returns:
        - Initial response containing transcript_id and record_id
        - Results will be delivered via webhook when processing is complete
        - When complete, results will include:
          - processed_at: Timestamp when processing completed
          - processing_time: Time in seconds from request to completion
    
    Example calls:
        Windows CMD:
        curl -X POST "http://localhost:8001/api/v1/stt" -H "X-API-Key: your_api_key" -H "Content-Type: application/json" -d "{\"audio_url\": \"https://example.com/audio.mp3\", \"chat_id\": 123456, \"message_id\": 789, \"speaker_labels\": true, \"model\": \"best\"}"
        
        Linux/Mac:
        curl -X POST "http://localhost:8001/api/v1/stt" -H "X-API-Key: your_api_key" -H "Content-Type: application/json" -d '{"audio_url": "https://example.com/audio.mp3", "chat_id": 123456, "message_id": 789, "speaker_labels": true, "model": "best"}'
        
        With audio_input parameter:
        curl -X POST "http://localhost:8001/api/v1/stt" -H "X-API-Key: your_api_key" -H "Content-Type: application/json" -d '{"audio_input": "https://example.com/audio.mp3", "chat_id": 123456, "message_id": 789, "speaker_labels": true, "model": "best"}'
    """
    logger.info(f"Received direct STT request for audio: {stt_request.audio_url} "
                f"(chat_id={stt_request.chat_id}, db_thread_id={stt_request.db_thread_id}, message_id={stt_request.message_id}, "
                f"speaker_labels={stt_request.speaker_labels}, model={stt_request.model}, "
                f"language_detection={stt_request.language_detection}, "
                f"language_code={stt_request.language_code or 'auto'})")
    
    # Get Supabase client
    # supabase = get_supabase_client() # Remove this line
    
    # Create initial record in the database
    stt_config = {
        "speaker_labels": stt_request.speaker_labels,
        "model": stt_request.model,
        "language_detection": stt_request.language_detection,
        "language_code": stt_request.language_code
    }
    
    stt_data = {
        "chat_id": stt_request.chat_id,
        "db_thread_id": stt_request.db_thread_id,
        "message_id": stt_request.message_id,
        "temp_msg_id": stt_request.temp_msg_id,
        "audio_url": stt_request.audio_url,
        "status": "processing",
        "stt_config": stt_config
    }
    
    try:
        # Create the initial record
        stt_record = await supabase.create_stt_record(stt_data)
        record_id = stt_record.data[0]['id'] if stt_record.data else None
        
        # Process speech-to-text with webhook
        result = await process_speech_to_text(
            stt_request.audio_url,
            speaker_labels=stt_request.speaker_labels, 
            model=stt_request.model,
            language_detection=stt_request.language_detection,
            language_code=stt_request.language_code,
            t_id=record_id,
            chat_id=stt_request.chat_id,
            db_thread_id=stt_request.db_thread_id,
            message_id=stt_request.message_id,
            temp_msg_id=stt_request.temp_msg_id
        )
        
        # Update record with transcript_id
        if record_id and 'transcript_id' in result:
            await supabase.update_stt_transcript_id(record_id, result['transcript_id'])
        
        return {
            "status": "processing",
            "message": "Transcription started. Results will be delivered via webhook.",
            "record_id": record_id,
            "transcript_id": result.get('transcript_id'),
            "request_received_at": datetime.now(UTC).isoformat()
        }
    except Exception as e:
        logger.error(f"STT processing failed: {str(e)}", exc_info=True)
        
        # Update the record with error status
        if record_id:
            error_data = {
                "status": "error",
                "error": str(e)
            }
            await supabase.update_stt_record(record_id, error_data)
        
        raise HTTPException(
            status_code=500,
            detail=f"Speech-to-text processing failed: {str(e)}"
        )

@router.get("/stt/{transcript_id}", dependencies=[Depends(verify_api_key)])
async def get_stt_result(transcript_id: str, supabase=Depends(get_supabase_client)):
    """
    Get the result of a speech-to-text job by transcript ID.
    This can be used to check the status of a pending transcription or retrieve 
    the results of a completed one.
    
    Parameters:
        - transcript_id: The AssemblyAI transcript ID
        
    Example call:
    curl -X GET "http://localhost:8001/api/v1/stt/5552493-16d8-42d8-8feb-c2a16b56f6e8" -H "X-API-Key: your_api_key"
    """
    logger.info(f"Checking status of transcript: {transcript_id}")
    
    try:
        # Get the record from our database first
        # supabase = get_supabase_client() # Remove this line
        record = await supabase.get_stt_record_by_transcript_id(transcript_id)
        
        if record and record.get('status') == 'completed' and record.get('transcript'):
            # If we already have the completed result, return it
            logger.info(f"Found completed transcript in database: {transcript_id}")
            response_data = {
                "status": "completed",
                "text": record.get('transcript'),
                "model_used": record.get('model_used'),
                "detected_language": record.get('detected_language'),
                "processed_at": record.get('processed_at'),
                "processing_time": record.get('processing_time'),
                "from_cache": True
            }
            
            # Include DOCX flag if storage path is available
            if record.get('transcript_docx_path'):
                response_data["has_docx"] = True
                
            return response_data
            
        # Get the latest from AssemblyAI directly
        stt_config = record.get('stt_config', {}) if record else {}
        result = await get_transcript_result(
            transcript_id,
            speaker_labels=stt_config.get('speaker_labels', False),
            language_detection=stt_config.get('language_detection', True),
            model=stt_config.get('model')
        )
        
        # If completed and we have a record ID, update our database
        if result.get('status') == 'completed' and record and record.get('id'):
            processed_at = datetime.now(UTC).isoformat()
            update_data = {
                "status": "completed",
                "transcript": result.get("text", ""),
                "model_used": result.get("model_used"),
                "detected_language": result.get("detected_language"),
                "processed_at": processed_at
            }
            response = await supabase.update_stt_record(record.get('id'), update_data)
            
            # Add processing time to result if available
            if response and response.data and len(response.data) > 0 and 'processing_time' in response.data[0]:
                result['processing_time'] = response.data[0]['processing_time']
                result['processed_at'] = processed_at
        
        return result
    except Exception as e:
        logger.error(f"Failed to get STT result: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get speech-to-text result: {str(e)}"
        )
 
@webhook_router.post("/webhooks/assemblyai")
async def assemblyai_webhook(request: Request, supabase=Depends(get_supabase_client)):
    """
    Webhook endpoint for AssemblyAI to send transcription results.
    This endpoint should not be called directly.
    """
    logger.info(f"Received webhook request at /webhooks/assemblyai - Headers: {dict(request.headers)}")
    logger.info(f"Query params: {dict(request.query_params)}")
    try:
        # Verify webhook secret
        webhook_secret = os.getenv("OUR_SECRET_TOKEN")
        if webhook_secret:
            auth_header = request.headers.get("X-Webhook-Secret")
            if not auth_header or auth_header != webhook_secret:
                logger.warning("Invalid webhook secret")
                return JSONResponse(
                    status_code=401,
                    content={"error": "Unauthorized: Invalid webhook secret"}
                )
            
        logger.info(f"Received and verified webhook from AssemblyAI")
        
        # Get parameters from query parameters
        t_id = request.query_params.get("t_id")
        chat_id = request.query_params.get("chat_id")
        db_thread_id = request.query_params.get("db_thread_id")
        message_id = request.query_params.get("message_id")
        temp_msg_id = request.query_params.get("temp_msg_id")

        if not t_id:
            logger.warning("No t_id provided in webhook call")
            return JSONResponse(
                status_code=400,
                content={"error": "Bad request: Missing t_id parameter"}
            )
            
        if not chat_id:
            logger.warning("No chat_id provided in webhook call")
            return JSONResponse(
                status_code=400,
                content={"error": "Bad request: Missing chat_id parameter"}
            )
            
        if not db_thread_id:
            logger.warning("No db_thread_id provided in webhook call")
            return JSONResponse(
                status_code=400,
                content={"error": "Bad request: Missing db_thread_id parameter"}
            )
        # Try to convert chat_id to integer
        try:
            chat_id = int(chat_id)
        except (ValueError, TypeError):
            logger.warning(f"Invalid chat_id format: {chat_id}")
            return JSONResponse(
                status_code=400,
                content={"error": "Bad request: Invalid chat_id format"}
            )
        
        # Get Supabase client
        # supabase = get_supabase_client() # Remove this line

        # Check if result was already delivered to user
        delivered = await supabase.check_stt_record_delivery(t_id)
        if delivered:
            logger.warning(f"Result for transcript {t_id} was already delivered to user, skipping webhook processing")
            return {"success": True, "message": "Result already delivered to user"}
        
        # Parse the payload
        payload = await request.json()
        transcript_id = payload.get("transcript_id")
        status = payload.get("status")
        
        if not transcript_id or not status:
            logger.warning("Missing transcript_id or status in webhook payload")
            return JSONResponse(
                status_code=400,
                content={"error": "Bad request: Missing required fields"}
            )
                
        if status == "completed":
            # Get the complete transcript result from AssemblyAI
            result = await get_transcript_result(transcript_id)
            
            # Get the current time for processed_at
            processed_at = datetime.now(UTC).isoformat()
            
            # Get the transcript text
            transcript_text = result.get("text", "")
            
            # Update the record in our database
            update_data = {
                "status": "completed",
                "transcript": transcript_text,
                "model_used": result.get("model_used"),
                "detected_language": result.get("detected_language"),
                "processed_at": processed_at
            }
            
            # DOCX file storage path
            docx_path = None
            
            # Handle the DOCX if it was generated
            if "transcription_docx" in result:
                # Ensure we're passing bytes data
                docx_data = result["transcription_docx"]
                if hasattr(docx_data, 'getvalue'):
                    # Already a BytesIO object, pass it as is
                    update_data["transcription_docx"] = docx_data
                    logger.info(f"Including BytesIO DOCX data for storage with transcript {transcript_id}")
                elif isinstance(docx_data, bytes):
                    # Already bytes, pass it as is
                    update_data["transcription_docx"] = docx_data
                    logger.info(f"Including bytes DOCX data for storage with transcript {transcript_id}")
                else:
                    # Skip invalid data
                    logger.warning(f"DOCX data has unexpected type {type(docx_data)}, skipping storage")

            # Update the record in our database
            response = await supabase.update_stt_record(t_id, update_data)
            
            # Get the docx_path from the updated record
            if response and response.data and len(response.data) > 0:
                record = response.data[0]
                docx_path = record.get('transcript_docx_path')
                
                # Log processing time if available
                if 'processing_time' in record:
                    logger.info(f"Transcription completed in {record['processing_time']} seconds for record {t_id}")
                else:
                    logger.info(f"Updated STT record {t_id} with completed transcript {transcript_id}")
            else:
                logger.info(f"Updated STT record {t_id} with completed transcript {transcript_id}")
            
            # Prepare message for user
            # Truncate transcript text if it's more than max_chars_in_message characters
            # If summary is available, use it instead of the transcript text
            summary = result.get("summary")
            text = summary or transcript_text
            truncated = text if len(text) <= 1000 else text[:1000] + "..."
            # Substitue html tags with telegram markdown    
            user_message = f"**{STT_SUMMARY_TEXTS['summary']['title']}**\n_{truncated}_" if summary else f"_{truncated}_"
            
            # Send message to user
            if not TAGENT_LOCAL_URL or not OUR_SECRET_TOKEN:
                logger.error("TAGENT_LOCAL_URL or OUR_SECRET_TOKEN not set in environment")
                return
            
            # Prepare headers
            headers = {
                "X-Secret-Token": OUR_SECRET_TOKEN,
                "Content-Type": "application/json"
            }
            
            # Prepare the message payload
            payload = {
                "chat_id": chat_id,
                "db_thread_id": db_thread_id,
                "message_id": message_id,
                "temp_msg_id": temp_msg_id,
                "message": user_message,
                "metadata": {
                    "stt_record_id": t_id,
                    "stt_transcript_id": transcript_id
                }
            }
            
            # If we have a DOCX file, include it in the message
            if docx_path:
                # Generate the full URL for the DOCX file
                file_name = f"stt_{datetime.now().strftime('%d%m%Y_%H%M%S')}.docx"
                file_url = f"{os.getenv('SUPABASE_URL', '')}/storage/v1/object/public/{docx_path}"
                
                # Update payload with file information
                payload.update({
                    "file_url": file_url,
                    "file_type": "document",
                    "file_name": file_name
                })

            # Log the payload
            logger.info(f"Sending message to user with payload: {payload}")
            
            message_sent = False
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(TAGENT_LOCAL_URL + "/send_message_to_user", headers=headers, json=payload) as response:
                        if response.status == 200:
                            logger.info(f"Successfully sent transcript to user in chat {chat_id}")
                            message_sent = True
                        else:
                            response_text = await response.text()
                            logger.error(f"Failed to send transcript to user: HTTP {response.status} - {response_text}")
            except Exception as e:
                logger.error(f"Error sending transcript message: {str(e)}", exc_info=True)
            
            # Process the transcribed message with the agent after sending it to the user
            if message_sent:
                try:
                    # Prepare the payload for processing
                    process_payload = {
                        "chat_id": chat_id,
                        "db_thread_id": db_thread_id,
                        "text": transcript_text,
                        "message_id": None,  # No message_id as this is agent-initiated
                    }
                    
                    logger.info(f"Sending transcribed text to agent for processing: {process_payload}")
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.post(TAGENT_LOCAL_URL + "/process_message", headers=headers, json=process_payload) as response:
                            if response.status == 200:
                                logger.info(f"Successfully sent transcript to agent for processing in chat {chat_id}")
                            else:
                                response_text = await response.text()
                                logger.error(f"Failed to send transcript to agent for processing: HTTP {response.status} - {response_text}")
                except Exception as e:
                    logger.error(f"Error sending transcript to agent for processing: {str(e)}", exc_info=True)
                
        elif status == "error":
            # Get the current time for processed_at
            processed_at = datetime.now(UTC).isoformat()
            
            # Update the record with error status
            update_data = {
                "status": "error",
                "error": "Transcription failed at AssemblyAI",
                "processed_at": processed_at
            }
            response = await supabase.update_stt_record(t_id, update_data)
            
            # Log processing time if available
            if response and response.data and len(response.data) > 0:
                record = response.data[0]
                if 'processing_time' in record:
                    logger.info(f"Transcription failed after {record['processing_time']} seconds for record {t_id}")
                else:
                    logger.error(f"Transcription {transcript_id} failed at AssemblyAI")
            else:
                logger.error(f"Transcription {transcript_id} failed at AssemblyAI")
            
            if not TAGENT_LOCAL_URL or not OUR_SECRET_TOKEN:
                logger.error("TAGENT_LOCAL_URL or OUR_SECRET_TOKEN not set in environment")
            else:
                
                headers = {
                    "X-Secret-Token": OUR_SECRET_TOKEN,
                    "Content-Type": "application/json"
                }
                
                # Prepare the error message
                payload = {
                    "chat_id": chat_id,
                    "message": "Sorry, there was an error processing your audio transcription."
                }
                
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(TAGENT_LOCAL_URL + "/send_message_to_user", headers=headers, json=payload) as response:
                            if response.status == 200:
                                logger.info(f"Successfully sent error message to user in chat {chat_id}")
                            else:
                                response_text = await response.text()
                                logger.error(f"Failed to send error message to user: HTTP {response.status} - {response_text}")
                except Exception as e:
                    logger.error(f"Error sending error message: {str(e)}", exc_info=True)
        
        return {"success": True, "processed_at": datetime.now(UTC).isoformat()}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": f"Internal server error: {str(e)}"}
        )
    

@router.get("/health")
async def health_check():
    """
    Health check endpoint to verify the service is running.
    This endpoint does not require authentication.

    Example call:
    curl -X GET "http://localhost:8001/api/v1/health"
    """
    return {"status": "healthy"}

@router.get("/stt-records", dependencies=[Depends(verify_api_key)])
async def get_stt_records(
    chat_id: Optional[int] = None,
    message_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 100,
    supabase=Depends(get_supabase_client)
):
    """
    Retrieve STT records from the database with optional filtering.
    Requires API key authentication.
    
    Parameters:
        - chat_id: Optional chat ID to filter records by
        - message_id: Optional message ID to filter records by
        - status: Optional status to filter records by (requested, processing, completed, error)
        - limit: Maximum number of records to return (default: 100)
    
    Returns:
        - List of STT records with fields including:
          - id, chat_id, message_id, audio_url, transcript, status
          - created_at: When the record was created
          - processed_at: When processing completed (for completed/error status)
          - processing_time: Time in seconds from request to completion
    
    Example call:
    curl -X GET "http://localhost:8001/api/v1/stt-records?chat_id=123456&status=completed" -H "X-API-Key: your_api_key"
    """
    logger.info(f"Retrieving STT records with filters: chat_id={chat_id}, message_id={message_id}, status={status}, limit={limit}")
    
    try:
        records = await supabase.get_stt_records(chat_id, message_id, status, limit)
        
        return {
            "total": len(records),
            "records": records
        }
    except Exception as e:
        logger.error(f"Error retrieving STT records: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve STT records: {str(e)}"
        )

@router.get("/stt/{transcript_id}/docx", dependencies=[Depends(verify_api_key)])
async def get_stt_docx(transcript_id: str, supabase=Depends(get_supabase_client)):
    """
    Get the DOCX document for a transcript if available.
    
    Parameters:
        - transcript_id: The AssemblyAI transcript ID
        
    Returns:
        - Binary DOCX document as a downloadable file
        
    Example call:
    curl -X GET "http://localhost:8001/api/v1/stt/5552493-16d8-42d8-8feb-c2a16b56f6e8/docx" -H "X-API-Key: your_api_key" --output transcript.docx
    """
    logger.info(f"Getting DOCX for transcript: {transcript_id}")
    
    try:
        # Get the record from our database
        record = await supabase.get_stt_record_by_transcript_id(transcript_id)
        
        if not record:
            raise HTTPException(
                status_code=404,
                detail="Transcript not found"
            )
        
        # Check for storage path
        docx_path = record.get('transcript_docx_path')
        
        if not docx_path:
            raise HTTPException(
                status_code=404,
                detail="DOCX file not found for this transcript"
            )
        
        # Get the DOCX file from storage
        try:
            docx_data = await supabase.get_docx_from_storage(docx_path)
            
            # Return the file
            return Response(
                content=docx_data,
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={
                    "Content-Disposition": f"attachment; filename=stt_{transcript_id[:8]}.docx"
                }
            )
        except Exception as e:
            logger.error(f"Failed to retrieve DOCX from storage: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to retrieve DOCX file from storage: {str(e)}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get DOCX: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get DOCX: {str(e)}"
        )

@router.post("/generate-market-report", response_model=TaskResponse, dependencies=[Depends(verify_api_key)])
@limiter.limit(get_rate_limit("generate_report"))
async def generate_market_report_endpoint(request: Request, market_request: MarketReportRequest):
    """
    Generate a market report and send it to the user.
    Requires API key authentication.
    
    Parameters:
        - chat_id: The chat ID to send the report to
        - message_id: Optional message ID to update
        - temp_msg_id: Optional temporary message ID for status updates
    
    Returns:
        - TaskResponse containing the task ID and initial status
        - The actual report will be generated in the background and sent to the user via Telegram
    
    Example call:
    curl -X POST "http://localhost:8001/api/v1/generate-market-report" -H "X-API-Key: tg_api_key" -H "Content-Type: application/json" -d "{\"chat_id\": \"1111111\"}"
    """
    logger.info(f"Received market report generation request for chat_id: {market_request.chat_id}")
    
    async def generate_report_task():
        try:
            # Generate the report
            result = await generate_market_report(
                chat_id=market_request.chat_id,
                message_id=market_request.message_id,
                temp_msg_id=market_request.temp_msg_id
            )
            
            # Send the report to the user
            try:
                if not TAGENT_LOCAL_URL or not OUR_SECRET_TOKEN:
                    raise ValueError("Missing required environment variables for sending report")
                    
                headers = {
                    "X-Secret-Token": OUR_SECRET_TOKEN,
                    "Content-Type": "application/json"
                }
                
                # Prepare the message payload
                message_payload = {
                    "chat_id": int(market_request.chat_id),
                    "message": result.get("message", "Market report generated"),
                    "file_url": result.get("file_url"),
                    "file_name": result.get("file_name"),
                    "file_type": result.get("file_type", "document")
                }
                
                # Add optional fields if they exist
                if market_request.message_id:
                    message_payload["message_id"] = market_request.message_id
                if market_request.temp_msg_id:
                    message_payload["temp_msg_id"] = market_request.temp_msg_id
                    
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{TAGENT_LOCAL_URL}/send_message_to_user",
                        headers=headers,
                        json=message_payload
                    ) as response:
                        if response.status != 200:
                            raise HTTPException(
                                status_code=500,
                                detail=f"Failed to send report to user: HTTP {response.status}"
                            )
            except Exception as e:
                logger.error(f"Error sending market report message: {str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Error sending report to user: {str(e)}"
                )
                
            # Return success response
            return {
                "status": "completed",
                "message": "Market report generated and sent to user",
                "file_url": result.get("file_url"),
                "generated_at": result.get("generated_at")
            }
            
        except ValueError as e:
            logger.error(f"Market report generation failed with validation error: {str(e)}")
            # Send error message to user
            try:
                if not TAGENT_LOCAL_URL or not OUR_SECRET_TOKEN:
                    raise ValueError("Missing required environment variables for sending error message")
                    
                headers = {
                    "X-Secret-Token": OUR_SECRET_TOKEN,
                    "Content-Type": "application/json"
                }
                error_payload = {
                    "chat_id": int(market_request.chat_id),
                    "message": f"❌ Error generating market report: {str(e)}"
                }
                if market_request.message_id:
                    error_payload["message_id"] = market_request.message_id
                if market_request.temp_msg_id:
                    error_payload["temp_msg_id"] = market_request.temp_msg_id
                    
                async with aiohttp.ClientSession() as session:
                    await session.post(TAGENT_LOCAL_URL + "/send_message_to_user", headers=headers, json=error_payload)
            except Exception as send_error:
                logger.error(f"Failed to send error message to user: {str(send_error)}")
                
            raise HTTPException(
                status_code=400,
                detail=str(e)
            )
        except Exception as e:
            logger.error(f"Market report generation failed: {str(e)}", exc_info=True)
            # Send error message to user
            try:
                if not TAGENT_LOCAL_URL or not OUR_SECRET_TOKEN:
                    raise ValueError("Missing required environment variables for sending error message")
                    
                headers = {
                    "X-Secret-Token": OUR_SECRET_TOKEN,
                    "Content-Type": "application/json"
                }
                error_payload = {
                    "chat_id": int(market_request.chat_id),
                    "message": "❌ Error generating market report. Please try again later."
                }
                if market_request.message_id:
                    error_payload["message_id"] = market_request.message_id
                if market_request.temp_msg_id:
                    error_payload["temp_msg_id"] = market_request.temp_msg_id
                    
                async with aiohttp.ClientSession() as session:
                    await session.post(TAGENT_LOCAL_URL + "/send_message_to_user", headers=headers, json=error_payload)
            except Exception as send_error:
                logger.error(f"Failed to send error message to user: {str(send_error)}")
                
            raise HTTPException(
                status_code=500,
                detail="Internal server error while generating market report"
            )
    
    # Add the task to the task manager and return immediately
    task_id = await add_task(generate_report_task, TaskType.REPORT)
    status, result = await get_task_status(task_id)
    return result