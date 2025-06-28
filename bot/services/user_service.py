import uuid
import asyncio
from datetime import datetime, UTC
from schemas import UserCreate
from services.supabase_client import SupabaseClient
from services import telegram_service, task_manager, stt_service
from utils.logger import logger
from utils.error_handler import DatabaseError, TelegramAPIError, ValidationError
from agent.graph import builder
from langchain_core.messages import RemoveMessage
import config
import os
import time
from fastapi import Request
from dotenv import load_dotenv
import re
from langgraph.types import Command


# Load .env from the root directory
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

async def create_user(user: UserCreate, sb_client: SupabaseClient):
    """
    Create a user record in the 'chats' table if one does not already exist.
    Also creates an initial thread record using the new user's id.
    """
    try:
        # Deal with the user_name if its provided as https://t.me/i68930266
        if user.user_name.startswith("https://t.me/"):
            user.user_name = user.user_name.split("/")[-1]

        # Sanitize the user_name by only allowing alphanumeric characters and underscores
        user.user_name = re.sub(r'[^a-zA-Z0-9_]', '', user.user_name)

        logger.info(f"Checking if user already exists: {user.user_name}")
        existing = await sb_client.get_user(chat_id=user.chat_id, user_name=user.user_name)
        if existing:
            logger.info(f"User already exists: {user.user_name}")
            return existing

        logger.info(f"Creating new user: {user.user_name}")
        user_data = {
            "chat_id": user.chat_id,
            "user_name": user.user_name,
            "role": user.role,
            "status": "created",  # initially created
            "tier": user.tier,
            "expire_at": user.expire_at,
            "created_at": datetime.now(UTC).isoformat(),
            "messages_count": 0,
            "active": False,
        }
        response = await sb_client.create_user(user_data)
        if response.data:
            # Extract the newly inserted user record (assuming it's returned in response.data[0])
            new_user = response.data[0]
            logger.info(f"User created successfully: {user.user_name}, ID: {new_user['id']}")
            
            # Create an initial thread record using the user's primary key.
            thread_data = {
                "user_id": new_user["id"],
                "created_at": datetime.now(UTC).isoformat(),
            }
            await sb_client.create_thread(thread_data)
            logger.info(f"Initial thread created for user: {user.user_name}")
        else:
            logger.warning(f"User creation response contained no data")
        
        return response.data
    except Exception as e:
        logger.error(f"Error creating user {user.user_name}: {str(e)}", exc_info=True)
        raise DatabaseError(f"Failed to create user: {str(e)}", 
                          {"user_name": user.user_name, "chat_id": user.chat_id})

async def delete_user(chat_id: int = None, user_name: str = None, sb_client: SupabaseClient = None):
    """
    Delete a user record by chat_id or user_name.
    """
    try:
        if not chat_id and not user_name:
            logger.error("No identifier provided for user deletion")
            raise ValidationError("Either chat_id or user_name must be provided")
            
        identifier = chat_id if chat_id is not None else user_name
        logger.info(f"Deleting user with identifier: {identifier}")
        
        result = await sb_client.delete_user(chat_id=chat_id, user_name=user_name)
        
        if not result.data:
            logger.warning(f"No user found to delete with identifier: {identifier}")
        else:
            logger.info(f"User deleted successfully: {identifier}")
            
        return result
    except ValidationError:
        # Re-raise validation errors without wrapping
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {str(e)}", exc_info=True)
        raise DatabaseError(f"Failed to delete user: {str(e)}", 
                          {"chat_id": chat_id, "user_name": user_name})

async def store_file_metadata(msg_info: dict, sb_client: SupabaseClient):
    """
    Store metadata for a received file in the 'file_messages' table.
    """
    try:
        if not msg_info.get('file_id'):
            logger.warning("No file_id found in message info")
            return
            
        logger.info(f"Storing file metadata for chat_id: {msg_info['chat_id']}")
        
        # # First, get the user's ID by their chat_id
        # user = await sb_client.get_user(chat_id=msg_info['chat_id'])
        # if not user:
        #     logger.warning(f"User not found for chat_id: {msg_info['chat_id']}")
        #     return
             
        # Enrich the message info with the file URL
        # await telegram_service.enrich_message_with_file_url(msg_info)
        
        result = await sb_client.sb_client.table("file_messages").insert(msg_info).execute()
        logger.info(f"File metadata stored successfully for chat_id: {msg_info['chat_id']}")
        return result.data
    except Exception as e:
        logger.error(f"Error storing file metadata: {str(e)}", exc_info=True)
        raise DatabaseError(f"Failed to store file metadata: {str(e)}", {"msg_info": msg_info})

async def process_user_message(msg_info: dict, sb_client: SupabaseClient, request: Request = None):
    """
    Process a user message:
    - If it's an audio/voice file, process it with STT
    - If it's a text message, process it with the memory agent
    """
    try:
        chat_id = msg_info.get("chat_id") 
        original_message_id = msg_info.get("message_id")
        user_id = str(chat_id)
        file_type = msg_info.get("file_type")
        file_url = msg_info.get("file_url")
        text = msg_info.get("text", "")
        db_thread_id = msg_info.get("db_thread_id")
        role = msg_info.get("role")
        llm_choice = msg_info.get("llm_choice")
        logger.info(f"Processing message {original_message_id} for chat_id: {chat_id}, db_thread_id: {db_thread_id}, role: {role}")
        
        # Check if this is an audio or voice message that needs transcription
        if file_type in ["voice", "audio"] and file_url:
            # Define task for speech-to-text processing
            # Send a processing message
            temp_msg_text = config.STT_PROCESSING_MESSAGE
            temp_msg = await telegram_service.send_message(
                chat_id,
                temp_msg_text,
                parse_mode="Markdown"
            )

            async def stt_task():
                try:
                    # Submit the audio file for transcription
                    await stt_service.submit_audio_for_transcription(
                        file_url, 
                        chat_id,
                        db_thread_id,
                        original_message_id,
                        temp_msg.message_id
                    )
                    
                    # If there's a cancel message for this task, update it
                    cancel_message_ids = task_manager.get_cancel_message(user_id)
                    if cancel_message_ids:
                        cancel_message_id, task_message_id = cancel_message_ids
                        # Update the message to remove the button and show completed
                        await telegram_service.edit_message_text(
                            chat_id, 
                            cancel_message_id,
                            config.REJECTED_REQUEST_MESSAGE
                        )
                except asyncio.CancelledError:
                    logger.warning(f"STT task for chat_id {chat_id} was cancelled by user")
                    raise
                except Exception as e:
                    logger.error(f"Error in STT task for chat_id {chat_id}: {str(e)}", exc_info=True)
                    # Notify the user of the error
                    await telegram_service.send_message(
                        chat_id,
                        config.STT_FAILED_MESSAGE,
                        parse_mode="Markdown"
                    )
                    
            # Queue the STT task
            result = await task_manager.queue_task(user_id, stt_task, original_message_id)
            
            # Handle case where a task is already running in single task mode
            if not config.ENABLE_TASK_QUEUING and result == -1:
                logger.info(f"Task already running for user {user_id}, sending cancel option")
                
                # Create button for cancellation
                cancel_button = [[("Cancel previous task", f"cancel_task_{user_id}")]]
                
                # Send message with cancel button
                cancel_msg = await telegram_service.send_reply_with_inline_keyboard(
                    chat_id,
                    config.TASK_ALREADY_RUNNING_MESSAGE,
                    original_message_id,
                    cancel_button
                )
                
                # Store the cancel message ID for later reference
                task_manager.set_cancel_message(user_id, cancel_msg.message_id, original_message_id)
                
                return {"status": "task_already_running", "cancel_message_id": cancel_msg.message_id}
            
            logger.info(f"STT task queued for chat_id: {chat_id}")
            return {"status": "processing_stt"}
        
        # Process text message with memory agent
        else:
            # Process text message with memory agent
            logger.info(f"Processing text message with memory agent for chat_id: {chat_id}")
            
            # Send a temporary processing message
            temp_msg = await telegram_service.send_message(
                chat_id, 
                config.PROCESSING_MESSAGE,
                parse_mode="Markdown"
            )
            
            async def agent_task():
                try:

                    # Prepare agent config
                    agent_config = {
                        "configurable": {
                            "user_id": user_id,
                            "thread_id": db_thread_id,
                            "role": role,
                            "model": llm_choice,
                            "use_openrouter": os.getenv("USE_OPENROUTER"),
                            "openrouter_api_key": os.getenv("OPENROUTER_API_KEY"),
                            "openai_api_key": os.getenv("OPENAI_API_KEY"),
                        }
                    }
                    
                    # Check if we have a request with access to the app state checkpointer and memory store
                    if request and hasattr(request.app.state, "checkpointer") and hasattr(request.app.state, "mem_store"):
                        logger.info(f"Using PostgreSQL checkpointer and memory store for chat_id: {chat_id}")
                        # Use the PostgreSQL checkpointer
                        checkpointer = request.app.state.checkpointer
                        mem_store = request.app.state.mem_store
                    else:
                        # Log and raise an error
                        logger.error(f"No request context provided for chat_id: {chat_id}")
                        # Raise DB error
                        raise DatabaseError(f"No request context provided for chat_id: {chat_id}")

                    # Time the agent graph compilation
                    start_time = time.perf_counter()

                    # Compile the agent graph with the PostgreSQL checkpointer
                    agent_graph = builder.compile(store=mem_store, checkpointer=checkpointer)
                        
                    # End timer here and show result to 3 decimal places in seconds
                    end_time = time.perf_counter()
                    logger.info(f"Time taken to compile agent graph: {end_time - start_time:.3f} seconds")

                    # Get the agent's state
                    agent_state = await agent_graph.aget_state(agent_config)
                    logger.info(f"Pending tasks: {agent_state.tasks}")

                    # Check if there are any pending tasks such as interrupts
                    if agent_state.tasks:
                        # Resume the conversation with the user's answer
                        result = await agent_graph.ainvoke(
                            Command(resume={"user_answered": text}),
                             agent_config
                        )
                    else:
                        # Process the message normally
                        result = await agent_graph.ainvoke(
                            {"messages": [("user", text)]},
                            agent_config
                        )

                    # In case of interrupt, we need to resume the conversation
                    # If response is empty, it's likely that the conversation was interrupted
                    response = result['messages'][-1].content

                    if not response:
                        # Get current graph state to get interrupt information
                        agent_state = await agent_graph.aget_state(agent_config)
                        # # # Log the state values
                        # logger.info(f"State values: {current_agent_state.values}")
                        # # # Log the pending tasks
                        logger.info(f"Pending tasks: {agent_state.tasks}")

                        # Try and get action message from the agent task
                        response = agent_state.tasks[0].interrupts[0].value.get("action")
                        if not response: response = "I'm sorry, there was an error processing your message. Please try again."

                    # Delete the temporary message
                    await telegram_service.delete_message(chat_id, temp_msg.message_id)
                    
                    # Send the agent's response
                    # Log the response
                    # logger.info(f"Agent response: {response}")

                    await telegram_service.send_message(
                        chat_id,
                        response.replace("**", "*"),
                        parse_mode="Markdown"
                    )
                    
                    # If there's a cancel message for this task, update it
                    cancel_message_ids = task_manager.get_cancel_message(user_id)
                    if cancel_message_ids:
                        cancel_message_id, task_message_id = cancel_message_ids
                        # Update the message to remove the button and show completed
                        await telegram_service.edit_message_text(
                            chat_id, 
                            cancel_message_id,
                            config.REJECTED_REQUEST_MESSAGE
                        )
                        
                except asyncio.CancelledError:
                    logger.warning(f"Agent task for chat_id {chat_id} was cancelled by user")
                    raise
                except Exception as e:
                    logger.error(f"Error in agent task for chat_id {chat_id}: {str(e)}", exc_info=True)

                    # Try to delete the temporary message
                    try:
                        await telegram_service.delete_message(chat_id, temp_msg.message_id)
                    except Exception:
                        pass
                    # Send error message
                    await telegram_service.send_message(
                        chat_id,
                        "❌ Error processing your message. Please try again later.",
                        parse_mode=None
                    )

                    # TODO: could store the error in the database, check if error is persistent and if so, do some acttion (clear checkpointer, etc.)
                    
                    # Try to remove the last message from the agent's state
                    agent_messages = agent_state.values["messages"]
                    if agent_messages:
                        # remmove last message since it was probably the one that caused the error (e.g. tool call did not have corresponding ai message )
                        message_to_remove_id = agent_messages[-1].id
                        await agent_graph.aupdate_state(agent_config, {"messages": RemoveMessage(id=message_to_remove_id)})
                 
                        
                        

            
            # Queue the agent task
            result = await task_manager.queue_task(user_id, agent_task, original_message_id)
            
            # Handle case where a task is already running in single task mode
            if not config.ENABLE_TASK_QUEUING and result == -1:
                logger.info(f"Task already running for user {user_id}, sending cancel option")
                
                # Create button for cancellation
                cancel_button = [[("Cancel previous task", f"cancel_task_{user_id}")]]
                
                # Send message with cancel button
                cancel_msg = await telegram_service.send_reply_with_inline_keyboard(
                    chat_id,
                    config.TASK_ALREADY_RUNNING_MESSAGE,
                    original_message_id,
                    cancel_button
                )
                
                # Store the cancel message ID for later reference
                task_manager.set_cancel_message(user_id, cancel_msg.message_id, original_message_id)
                
                return {"status": "task_already_running", "cancel_message_id": cancel_msg.message_id}
            
            logger.info(f"Agent task queued for chat_id: {chat_id}")
            return {"status": "processing"}
            
    except Exception as e:
        logger.error(f"Error processing user message: {str(e)}", exc_info=True)
        raise TelegramAPIError(f"Failed to process user message: {str(e)}", {"msg_info": msg_info})
