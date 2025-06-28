# api/endpoints.py
from fastapi import APIRouter, Depends, Request, HTTPException
from schemas import UserCreate, SendMessage
from utils.security import verify_secret_token, verify_tgagent_secret
from services import telegram_service, user_service, task_manager
from services.supabase_client import get_supabase_client  # dependency getter
from utils.limiter import dynamic_rate_limit
from utils.logger import logger
from utils.error_handler import handle_exception, DatabaseError, ValidationError

import config
import re
router = APIRouter()

# Check if the message is essentially empty considering markdown, html tags and whitespace
def is_essentially_empty(text: str) -> bool:
    if not text:
        return True
    # Remove markdown formatting
    text = re.sub(r'[*_`~]', '', text)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove whitespace
    text = text.strip()
    return not bool(text)


@router.post("/send_message_to_user", dependencies=[Depends(verify_secret_token)])
@dynamic_rate_limit("send_message_to_user", "10/minute")
async def send_message_to_user(
    data: SendMessage, request: Request,
    supabase=Depends(get_supabase_client)
):
    """
    Endpoint to send a message to a Telegram user.
    Can also send files by providing a file_url and file_type.
    
    Examples (Windows curl):
        1. Sending a simple text message:
           ```
           curl -X POST "http://localhost:8000/send_message_to_user" -H "X-Secret-Token: TGAGENT_SECRET_TOKEN" -H "Content-Type: application/json" -d "{\"chat_id\":1084810791, \"message\":\"Hello from the API!\"}"
           ```
        
        2. Sending a message with a document file attachment:
           ```
           curl -X POST "http://localhost:8000/send_message_to_user" -H "X-Secret-Token: TGAGENT_SECRET_TOKEN" -H "Content-Type: application/json" -d "{\"chat_id\":1084810791, \"message\":\"Please see the attached document\", \"file_url\":\"http://127.0.0.1:54321/storage/v1/object/public/stt_files/1084810791/stt_22032025_211451.docx\", \"file_type\":\"document\", \"file_name\":\"report.docx\"}"
           ```
    """
    try:
        logger.info(f"Sending message to user {data.chat_id}")

        # Validate required fields
        if not data.chat_id:
            raise ValidationError("chat_id is required")
        if not data.message:
            raise ValidationError("message is required")

        # If message is empty, use "No text" as default
        if is_essentially_empty(data.message):
            data.message = config.EMPTY_MESSAGE_DEFAULT
        
        # Log the full data for debugging
        logger.debug(f"Processing message data: {data}")
        
        # Check if a file is being sent
        if data.file_url and data.file_type:
            logger.info(f"Sending file of type {data.file_type} to user {data.chat_id}")
            # Use the caption if provided, otherwise use the message
            caption = data.caption if data.caption else data.message
            result = await telegram_service.send_file_by_type(
                data.chat_id, 
                data.file_url, 
                data.file_type, 
                caption, 
                data.file_name,
                data.message_id if data.message_id else None
            )
            logger.info(f"{data.file_type.capitalize()} sent to user {data.chat_id}")
        
        else:
            # Send a regular text message
            # If we have message_id, send a reply to the message
            if data.message_id:
                result = await telegram_service.send_reply(data.chat_id, data.message, data.message_id, parse_mode="Markdown")
            else:
                result = await telegram_service.send_message(data.chat_id, data.message, parse_mode="Markdown")
            logger.info(f"Message sent to user {data.chat_id}")

        # Delete the temporary message if it exists
        if hasattr(data, 'temp_msg_id') and data.temp_msg_id:
            try:
                await telegram_service.delete_message(data.chat_id, data.temp_msg_id)
                logger.info(f"Temporary message {data.temp_msg_id} deleted")
            except Exception as e:
                logger.error(f"Failed to delete temporary message: {str(e)}")
                # Continue execution even if temp message deletion fails

        # In case of STT record, set delivered_to_user to True
        # Set delivered_to_user to True
        if hasattr(data, 'metadata') and data.metadata and 'stt_record_id' in data.metadata:
            logger.info(f"Setting delivered_to_user to True for STT record {data.metadata.get('stt_record_id')}")
            try:
                await supabase.update_stt_record(data.metadata.get("stt_record_id"), {"delivered_to_user": True})
            except Exception as e:
                logger.error(f"Failed to update STT record: {str(e)}")
        # else:
        #     logger.info("No STT record ID found in metadata")

        return {"success": True, "result": "Message sent"}
    except Exception as e:
        error_response = handle_exception(e, f"Error sending message to user {data.chat_id}")
        return {"success": False, "error": error_response["error"]}

@router.post("/create_user", dependencies=[Depends(verify_secret_token)])
@dynamic_rate_limit("create_user", "5/minute")
async def create_user_endpoint(
    user: UserCreate, request: Request,
    supabase=Depends(get_supabase_client)
):
    """
    Create a user in the database if one does not already exist.
    """
    try:
        logger.info(f"Creating user: {user.user_name}")
        result = await user_service.create_user(user, supabase)
        logger.info(f"User created: {user.user_name}")
        return {"success": True, "result": "User created", "data": result}
    except Exception as e:
        error_response = handle_exception(e, f"Error creating user: {user.user_name}")
        return {"success": False, "error": error_response["error"]}

@router.delete("/delete_user", dependencies=[Depends(verify_secret_token)])
@dynamic_rate_limit("delete_user", "5/minute")
async def delete_user_endpoint(
    chat_id: int = None, user_name: str = None, request: Request = None,
    supabase=Depends(get_supabase_client)
):
    """
    Delete a user from the database by chat_id or user_name.
    """
    try:
        identifier = chat_id if chat_id else user_name
        logger.info(f"Deleting user with identifier: {identifier}")
        
        if not chat_id and not user_name:
            raise ValidationError("Either chat_id or user_name must be provided")
            
        result = await user_service.delete_user(chat_id=chat_id, user_name=user_name, supabase=supabase)
        logger.info(f"User deleted with identifier: {identifier}")
        return {"success": True, "result": "User deleted", "data": result}
    except Exception as e:
        error_response = handle_exception(e, f"Error deleting user with identifier: {chat_id or user_name}")
        return {"success": False, "error": error_response["error"]}

@router.post("/process_message", dependencies=[Depends(verify_secret_token)])
@dynamic_rate_limit("process_message", "5/minute")
async def process_message_endpoint(
    msg_info: dict, request: Request,
    supabase=Depends(get_supabase_client)
):
    """
    Process a message:
    The task is queued per user.
    """
    try:
        logger.info(f"Processing message for user: {msg_info.get('chat_id') or msg_info.get('user_name')}")
        result = await user_service.process_user_message(msg_info, supabase, request)
        logger.info(f"Message processed for user: {msg_info.get('chat_id') or msg_info.get('user_name')}")
        return {"success": True, "result": "Message processing requested successfully."}
    except Exception as e:
        error_response = handle_exception(e, f"Error requesting message processing for user: {msg_info.get('chat_id') or msg_info.get('user_name')}")
        return {"success": False, "error": error_response["error"]}

@router.get("/check_user", dependencies=[Depends(verify_secret_token)])
@dynamic_rate_limit("check_user", "10/minute")
async def check_user_endpoint(
    chat_id: int = None, user_name: str = None, request: Request = None,
    supabase=Depends(get_supabase_client)
):
    """
    Returns user data from the chats table by chat_id or user_name.
    """
    try:
        identifier = chat_id if chat_id else user_name
        logger.info(f"Retrieving user data for identifier: {identifier}")
        
        if not chat_id and not user_name:
            raise ValidationError("Either chat_id or user_name must be provided")
            
        if chat_id:
            result = await supabase.table("chats").select("*").eq("chat_id", chat_id).execute()
        else:
            result = await supabase.table("chats").select("*").eq("user_name", user_name).execute()
            
        if not result.data or len(result.data) == 0:
            raise DatabaseError(f"User with identifier {identifier} not found")
            
        logger.info(f"User data retrieved for identifier: {identifier}")
        return {"success": True, "result": "User data retrieved", "data": result.data[0]}
    except Exception as e:
        error_response = handle_exception(e, f"Error retrieving user data for identifier: {chat_id or user_name}")
        return {"success": False, "error": error_response["error"]}

# Main Telegram Webhook for receiving messages
@router.post("/webhook")
async def telegram_webhook(
    update: dict,
    request: Request,
    x_telegram_bot_api_secret_token: str = Depends(verify_tgagent_secret),
    supabase = Depends(get_supabase_client)
): 
    try:
        # Check if this is a callback query (button click)
        callback_query = update.get('callback_query')
        if callback_query:
            await handle_callback_query(callback_query, supabase)
            return {"success": True, "result": "Callback query processed"}

        # Handle regular messages
        message = update.get("message")
        if not message:
            logger.info("Webhook received with no message content")
            return {"success": True, "result": "No message content"}
    
        # Check if user exists and apply rate limits
        try:
            # This will now return the rate limit data properly without raising exceptions
            rpc_result = await supabase.call_rpc(
                "user_auth_checks", 
                {"p_chat_id": message.get("chat", {}).get("id"), "p_user_name": message.get("chat", {}).get("username")}
            )

            logger.info(f"RPC result: {rpc_result}")

            # Convert to dict if it's a response object
            if hasattr(rpc_result, "data"):
                rpc_result = rpc_result.data

            if not rpc_result:
                return
                
            # If user is not active, ignore the message
            if rpc_result.get("user_active") is False:
                # Check if "role" and "message" are in rpc_result
                if rpc_result.get("role") and rpc_result.get("message"):
                    # Send the message to the user
                    await telegram_service.send_message(message.get("chat", {}).get("id"), rpc_result.get("message"), parse_mode="MarkdownV2")    
                return

            logger.info(f"Received message in webhook: {message.get('message_id')}")
            
            # Get the message info that we need to process
            msg_info = await telegram_service.extract_message_info(message)

            # Lets add db_thread_id to the message info 
            if rpc_result and rpc_result.get("db_thread_id"):
                msg_info['db_thread_id'] = rpc_result.get("db_thread_id")
            else:
                # Raise an error
                raise ValidationError("No db_thread_id found in rpc_result")
            
            # Lets add user role to the message info ("role": rpc_result.get("role"))
            if rpc_result and rpc_result.get("role"):
                msg_info['role'] = rpc_result.get("role")
            else:
                # Raise an error
                raise ValidationError("No role found in rpc_result")
            
            # Lets add llm_choice to the message info
            if rpc_result and rpc_result.get("llm_choice"):
                msg_info['llm_choice'] = rpc_result.get("llm_choice")
            else:
                # Raise an error
                raise ValidationError("No llm_choice found in rpc_result")

            # Get the file URL if it exists
            if 'file_id' in msg_info and msg_info['file_id']:
                msg_info['file_url'] = await telegram_service.get_file_url(msg_info['file_id'])

            logger.debug(f"Message info extracted: {msg_info}")
            
            # If rate limit is applied, send the rate limit message
            if rpc_result and rpc_result.get("allowed") is False:
                message_to_send = rpc_result.get("message")
                if message_to_send:
                    logger.info(f"Sending rate limit message to user: {msg_info['chat_id']}")
                    await telegram_service.send_reply(msg_info["chat_id"], message_to_send, msg_info["message_id"], parse_mode=None)
                    return {"success": True, "result": "Rate limit message sent"}
                else:
                    logger.info(f"Rate limited user with no message: {msg_info['chat_id']}")
                    return {"success": True, "result": "Rate limited"}
            
            # Check for special commands
            command_handled, command_result = await telegram_service.handle_special_commands(msg_info, supabase)
            if command_handled:
                return command_result
                
            # If a file is attached, store its metadata
            if "file_id" in msg_info:
                logger.info(f"Processing file from user: {msg_info['chat_id']}")
                try:
                    await user_service.store_file_metadata(msg_info, supabase)
                except Exception as e:
                    logger.error(f"Error storing file metadata: {str(e)}", exc_info=True)
                    # Continue processing even if file storage fails
            
            # Process all messages through the agent
            logger.info(f"Processing message for user: {msg_info['chat_id']}")
            await user_service.process_user_message(msg_info, supabase, request)
            return {"success": True, "result": "Message processed"}
            
        except Exception as e:
            logger.error(f"Error checking user rate limits: {str(e)}", exc_info=True)
            return
            # Continue processing even if rate limit check fails
    
    except Exception as e:
        error_response = handle_exception(e, "Error in telegram_webhook")
        # Don't return the full error details to the webhook caller for security reasons
        return {"success": False, "result": "An error occurred while processing the update."}

async def handle_callback_query(callback_query: dict, supabase):
    """
    Handle callback query from inline buttons.
    
    Args:
        callback_query (dict): The callback query data
        supabase: Supabase client instance
    """
    try:
        query_id = callback_query.get('id')
        chat_id = callback_query.get('message', {}).get('chat', {}).get('id')
        message_id = callback_query.get('message', {}).get('message_id')
        data = callback_query.get('data', '')
        
        logger.info(f"Received callback query: {data} from chat_id: {chat_id}")
        
        # Always answer the callback query to stop the loading indicator
        await telegram_service.bot.answer_callback_query(query_id)
        
        # Handle cancel task request
        if data.startswith('cancel_task'):
            # Cancel the task
            user_id = str(chat_id)
            cancelled = await task_manager.cancel_user_task(user_id)
            
            if cancelled:
                logger.info(f"Task cancelled for user {user_id}")
                
                # Get message IDs for cancel message and task message
                cancel_message_ids = task_manager.get_cancel_message(user_id)
                if cancel_message_ids:
                    cancel_message_id, task_message_id = cancel_message_ids
                    
                    # Update the cancel message to indicate task was cancelled
                    await telegram_service.edit_message_text(
                        chat_id, 
                        cancel_message_id, 
                        config.TASK_CANCELLED_BY_USER_MESSAGE
                    )
                    
                    # Update the task request message to indicate it was cancelled
                    await telegram_service.send_reply(
                        chat_id,
                        config.REJECTED_REQUEST_MESSAGE,
                        task_message_id,
                        parse_mode=None
                    )
            else:
                logger.warning(f"No active task found to cancel for user {user_id}")
                
                # Update the message to remove the button
                await telegram_service.edit_message_text(
                    chat_id, 
                    message_id,
                    config.REJECTED_REQUEST_MESSAGE,
                )
        
        # Handle model change request
        elif data.startswith('change_model:'):
            # Extract the model name from the callback data
            model_name = data.split(':', 1)[1] if ':' in data else None
            
            if model_name == 'cancel':
                # User cancelled the model selection - delete the message
                logger.info(f"Model selection cancelled by user {chat_id}")
                try:
                    await telegram_service.delete_message(chat_id, message_id)
                    logger.info(f"Deleted model selection message for user {chat_id}")
                except Exception as e:
                    logger.error(f"Failed to delete message: {str(e)}")
                    # Fallback to editing the message if deletion fails
                    await telegram_service.edit_message_text(
                        chat_id,
                        message_id,
                        "❌ Model selection cancelled."
                    )
            else:
                # Set the user's model preference using the RPC function
                result = await supabase.sb_client.rpc(
                    "set_user_llm", 
                    {
                        "p_chat_id": chat_id,
                        "p_llm_choice": model_name
                    }
                ).execute()
                
                logger.info(f"Result: {result}")
                
                # Process the RPC response - corrected structure based on logs
                response_data = result.data[0] if result and result.data else {}
                result_obj = response_data.get('result', {})
                success = result_obj.get('success', False)
                message = result_obj.get('message', '')
                
                if success:
                    # Model changed successfully
                    await telegram_service.edit_message_text(
                        chat_id,
                        message_id,
                        f"✅ *Model changed successfully\\!*\n\nYou are now using the `{model_name}` model\\.",
                        parse_mode="MarkdownV2"
                    )
                    logger.info(f"User {chat_id} changed model to {model_name}")
                else:
                    # Failed to change model
                    allowed_llms = result_obj.get('allowed_llms', [])
                    allowed_list = ', '.join([f'`{llm}`' for llm in allowed_llms]) if allowed_llms else "None available"
                    
                    error_message = f"❌ *Could not change model*\n\nError: {message}\n\nAllowed models: {allowed_list}"
                    await telegram_service.edit_message_text(
                        chat_id,
                        message_id,
                        error_message,
                        parse_mode="MarkdownV2"
                    )
                    logger.warning(f"Failed to change model for user {chat_id} to {model_name}: {message}")

     
    except Exception as e:
        logger.error(f"Error handling callback query: {str(e)}", exc_info=True)
        # Try to answer the callback query to stop the loading indicator
        try:
            if query_id and not await telegram_service.bot.answer_callback_query(query_id):
                await telegram_service.bot.answer_callback_query(query_id)
        except Exception:
            pass

@router.get("/chat-ids", dependencies=[Depends(verify_secret_token)])
async def get_chat_ids(limit: int = 10, supabase = Depends(get_supabase_client)):
    """
    Get a list of chat IDs ordered by creation date.
    Requires API key authentication.
    
    Parameters:
        - limit: Maximum number of chat IDs to return (default: 10)
    
    Returns:
        - List of chat IDs ordered by created_at (newest first)
    
    Example call:
    curl -X GET "http://localhost:8001/api/v1/chat-ids?limit=20" -H "X-Secret-Token: TGAGENT_SECRET_TOKEN"
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