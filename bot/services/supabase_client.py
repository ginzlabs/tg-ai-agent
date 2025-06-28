import os
from supabase import AsyncClient, acreate_client
from postgrest.exceptions import APIError
from dotenv import load_dotenv
from utils.logger import logger
from utils.error_handler import DatabaseError
import ast
load_dotenv()  # Ensure environment variables are loaded

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

class SupabaseClient:
    def __init__(self, sb_client: AsyncClient):
        self.sb_client: AsyncClient = sb_client

    async def create_user(self, user_data: dict):
        """Insert a new record in the 'chats' table."""
        try:
            logger.info(f"Creating user: {user_data.get('user_name')}")
            response = await self.sb_client.table("chats").insert(user_data).execute()
            logger.info(f"User created successfully: {user_data.get('user_name')}")
            return response
        except Exception as e:
            logger.error(f"Error creating user: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to create user: {str(e)}", {"user_data": user_data})

    async def update_user(self, user_id: int, update_data: dict):
        """Update a user record in the 'chats' table."""
        try:
            logger.info(f"Updating user with ID: {user_id}")
            response = await self.sb_client.table("chats").update(update_data).eq("id", user_id).execute()
            logger.info(f"User updated successfully: {user_id}")
            return response
        except Exception as e:
            logger.error(f"Error updating user: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to update user: {str(e)}", {"user_id": user_id, "update_data": update_data})

    async def get_user(self, chat_id: int = None, user_name: str = None):
        """Retrieve a user by chat_id or user_name."""
        try:
            identifier = chat_id if chat_id is not None else user_name
            logger.info(f"Getting user with identifier: {identifier}")
            
            # Start a SELECT query
            query = self.sb_client.table("chats").select("*")
            if chat_id is not None:
                query = query.eq("chat_id", chat_id)
            elif user_name is not None:
                query = query.eq("user_name", user_name)
            else:
                raise ValueError("Either chat_id or user_name must be provided")
                
            response = await query.execute()
            
            if response.data:
                logger.info(f"User found with identifier: {identifier}")
            else:
                logger.info(f"No user found with identifier: {identifier}")
                
            return response.data if response.data else None
        except Exception as e:
            logger.error(f"Error getting user: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to get user: {str(e)}", {"chat_id": chat_id, "user_name": user_name})

    async def delete_user(self, chat_id: int = None, user_name: str = None):
        """Delete a user record and all related data using the delete_user RPC function."""
        try:
            identifier = chat_id if chat_id is not None else user_name
            logger.info(f"Deleting user with identifier: {identifier}")
            
            if not chat_id and not user_name:
                raise ValueError("Either chat_id or user_name must be provided")
            
            # Call the delete_user RPC function
            params = {}
            if chat_id is not None:
                params["p_chat_id"] = chat_id
            if user_name is not None:
                params["p_user_name"] = user_name
                
            response = await self.sb_client.rpc("delete_user", params).execute()
            print(response)
            
            # Check if operation was successful
            if response.data and isinstance(response.data, list) and len(response.data) > 0:
                result = response.data[0].get('result', {})
                success = result.get('success', False)
                message = result.get('message', '')
                
                if success:
                    logger.info(f"User deleted successfully: {identifier}")
                else:
                    logger.warning(f"Failed to delete user: {message}")
                    
            logger.info(f"RPC delete_user completed for: {identifier}")
            return response
        except Exception as e:
            logger.error(f"Error deleting user: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to delete user: {str(e)}", {"chat_id": chat_id, "user_name": user_name})

    async def create_thread(self, thread_data: dict):
        """Create a new thread record in the 'threads' table."""
        try:
            logger.info(f"Creating thread for user: {thread_data.get('chat_id')}")
            response = await self.sb_client.table("threads").insert(thread_data).execute()
            logger.info(f"Thread created successfully for user: {thread_data.get('chat_id')}")
            return response
        except Exception as e:
            logger.error(f"Error creating thread: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to create thread: {str(e)}", {"thread_data": thread_data})

    async def update_stt_record(self, record_id: str, update_data: dict):
        """Update an STT record in the 'stt_files' table."""
        try:
            logger.info(f"Updating STT record with ID: {record_id}")
            response = await self.sb_client.table("stt_files").update(update_data).eq("id", record_id).execute()
            logger.info(f"STT record updated successfully: {record_id}")
            return response
        except Exception as e:
            logger.error(f"Error updating STT record: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to update STT record: {str(e)}", {"record_id": record_id, "update_data": update_data})

    async def call_rpc(self, rpc_name: str, params: dict):
        """Call a Supabase RPC function."""
        try:
            logger.info(f"Calling RPC: {rpc_name}")
            response = await self.sb_client.rpc(rpc_name, params).execute()
            logger.info(f"RPC call successful: {rpc_name}")
            return response
        except APIError as e:
            # Check if this is a rate limiting response from our custom RPC
            error_content = {}
            
            # Try to extract the error data
            if hasattr(e, 'args') and e.args:
                if isinstance(e.args[0], dict):
                    error_content = e.args[0]
                elif isinstance(e.args[0], str):
                    try:
                        error_content = ast.literal_eval(e.args[0])
                    except (ValueError, SyntaxError):
                        error_content = {"message": e.args[0]}
            
            # If it contains 'allowed' field and it's False, it's our rate limit response
            if isinstance(error_content, dict) and 'allowed' in error_content and error_content.get('allowed') is False:
                logger.info(f"RPC {rpc_name} returned rate limit response: {error_content.get('message', 'Rate limited')}")
                return error_content
                
            # Otherwise, it's a real error
            logger.error(f"Error calling RPC {rpc_name}: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to call RPC {rpc_name}: {str(e)}", {"params": params})
        except Exception as e:
            logger.error(f"Error calling RPC {rpc_name}: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to call RPC {rpc_name}: {str(e)}", {"params": params})
        
    async def get_chat_ids(self, limit: int = 10):
        """
        Get a list of chat IDs ordered by creation date.
        
        Args:
            limit: Maximum number of chat IDs to return
            
        Returns:
            List of chat IDs ordered by created_at
        """
        try:
            logger.info(f"Getting {limit} chat IDs ordered by created_at")

            # Query the chats table for IDs
            response = await self.sb_client.table("chats").select("chat_id, created_at").order("created_at", desc=True).limit(limit).execute()
           

            if response.data:
                # Extract just the chat_id values
                chat_ids = [record.get('chat_id') for record in response.data]
                logger.info(f"Retrieved {len(chat_ids)} chat IDs")
                return chat_ids
            else:
                logger.info("No chat IDs found")
                return []
                
        except Exception as e:
            logger.error(f"Error getting chat IDs: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to get chat IDs: {str(e)}", {"limit": limit})

    async def clear_dialog(self, chat_id: int, thread_id: int):
        """
        Clear the dialog history for a specific thread.
        
        Args:
            chat_id: The chat ID of the user
            thread_id: The thread ID to clear
            
        Returns:
            The RPC response
        """
        try:
            logger.info(f"Clearing dialog for chat_id {chat_id}, thread_id {thread_id}")
            response = await self.sb_client.rpc("clear_user_dialog", {
                "p_chat_id": chat_id,
                "p_thread_id": thread_id
            }).execute()
            logger.info(f"Dialog cleared successfully for chat_id {chat_id}")
            return response
        except Exception as e:
            logger.error(f"Error clearing dialog: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to clear dialog: {str(e)}", {"chat_id": chat_id, "thread_id": thread_id})

    async def clear_memory(self, chat_id: int, thread_id: int):
        """
        Clear the memory/context for a specific thread.
        
        Args:
            chat_id: The chat ID of the user
            thread_id: The thread ID to clear memory for
            
        Returns:
            The RPC response
        """
        try:
            logger.info(f"Clearing memory for chat_id {chat_id}, thread_id {thread_id}")
            response = await self.sb_client.rpc("clear_user_memory", {
                "p_chat_id": chat_id,
                "p_thread_id": thread_id
            }).execute()
            logger.info(f"Memory cleared successfully for chat_id {chat_id}")
            return response
        except Exception as e:
            logger.error(f"Error clearing memory: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to clear memory: {str(e)}", {"chat_id": chat_id, "thread_id": thread_id})

    async def check_limits(self, chat_id: int):
        """
        Check the usage limits for a specific user.
        
        Args:
            chat_id: The chat ID of the user
            
        Returns:
            The RPC response with user limits information:
            - daily_usage: Current daily message count
            - monthly_usage: Current monthly message count
            - daily_limit: Maximum daily messages allowed
            - monthly_limit: Maximum monthly messages allowed
            - pause_seconds: Cooldown time between messages (not exposed to users)
            - error: Error message if user not found
        """
        try:
            logger.info(f"Checking limits for chat_id {chat_id}")
            response = await self.sb_client.rpc("get_user_limits", {
                "p_chat_id": chat_id
            }).execute()
            logger.info(f"Limits checked successfully for chat_id {chat_id}")
            return response
        except Exception as e:
            logger.error(f"Error checking limits: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to check limits: {str(e)}", {"chat_id": chat_id})

    async def get_server_settings(self):
        """
        Retrieve server settings including allowed_llms from server_settings table.
        
        Returns:
            Dictionary containing server settings with allowed_llms array
        """
        try:
            logger.info("Retrieving server settings")
            # Call the get_allowed_llms RPC function
            response = await self.sb_client.rpc("get_allowed_llms", {}).execute()
            
            if response.data and len(response.data) > 0:
                # The function returns a result JSON object
                settings = response.data[0].get('result', {})
                logger.info("Server settings retrieved successfully")
                return settings
            else:
                logger.warning("No server settings found in database")
                return {"allowed_llms": []}  # Default empty array if no settings
        except Exception as e:
            logger.error(f"Error retrieving server settings: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to retrieve server settings: {str(e)}", {})
            
    async def get_user_model(self, user_id: int):
        """
        Get the current model for a specific user.
        
        Args:
            user_id: The chat ID of the user
            
        Returns:
            Dictionary containing the model name for the user
        """
        try:
            logger.info(f"Getting model for user {user_id}")
            response = await self.sb_client.rpc("get_allowed_llms", {
                "p_chat_id": user_id
            }).execute()
            logger.info(f"Model retrieved successfully for user {user_id}")
            return response
        except Exception as e:
            logger.error(f"Error getting user model: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to get user model: {str(e)}", {"user_id": user_id})

async def init_supabase_client() -> SupabaseClient:
    """Initialize a new Supabase client."""
    try:
        logger.info("Initializing Supabase client")
        if not SUPABASE_URL or not SUPABASE_KEY:
            logger.error("Supabase URL or key is missing in environment variables")
            raise ValueError("Supabase URL or key is missing in environment variables")
            
        sb_client = await acreate_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase client initialized successfully")
        return SupabaseClient(sb_client)
    except Exception as e:
        logger.error(f"Error initializing Supabase client: {str(e)}", exc_info=True)
        raise DatabaseError(f"Failed to initialize Supabase client: {str(e)}")

# In-memory global client to avoid repeated initializations.
_supabase_client = None

def get_supabase_client() -> SupabaseClient:
    """
    Return the global Supabase client. This is a FastAPI dependency.
    """
    if _supabase_client is None:
        logger.error("Supabase client not initialized. Call initialize_global_supabase_client() first.")
        raise DatabaseError("Supabase client not initialized")
    return _supabase_client

async def initialize_global_supabase_client() -> SupabaseClient:
    """
    Initialize the global Supabase client.
    This should be called once during application startup.
    """
    global _supabase_client
    try:
        _supabase_client = await init_supabase_client()
        return _supabase_client
    except Exception as e:
        logger.error(f"Failed to initialize global Supabase client: {str(e)}", exc_info=True)
        raise DatabaseError(f"Failed to initialize global Supabase client: {str(e)}")
