import os
from supabase import AsyncClient, acreate_client
from postgrest.exceptions import APIError
from dotenv import load_dotenv
from utils.logger import logger
from utils.error_handler import DatabaseError
import ast
from datetime import datetime
import os
from typing import Dict, Any

load_dotenv()  # Ensure environment variables are loaded

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

class SupabaseClient:
    def __init__(self, sb_client: AsyncClient):
        self.sb_client: AsyncClient = sb_client
        self.storage_bucket = "stt_files"
        self.reports_bucket = "reports"  # Updated bucket name

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
        """Delete a user record from the 'chats' table."""
        try:
            identifier = chat_id if chat_id is not None else user_name
            logger.info(f"Deleting user with identifier: {identifier}")
            
            if not chat_id and not user_name:
                raise ValueError("Either chat_id or user_name must be provided")
            
            # Start a DELETE query
            query = self.sb_client.table("chats").delete()
            if chat_id is not None:
                query = query.eq("chat_id", chat_id)
            elif user_name is not None:
                query = query.eq("user_name", user_name)
                
            response = await query.execute()
            logger.info(f"User deleted successfully: {identifier}")
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

    async def create_stt_record(self, stt_data: dict):
        """Create a new record in the 'stt_files' table."""
        try:
            logger.info(f"Creating STT record for chat: {stt_data.get('chat_id')} message: {stt_data.get('message_id')}")
            response = await self.sb_client.table("stt_files").insert(stt_data).execute()
            logger.info(f"STT record created successfully with ID: {response.data[0]['id'] if response.data else 'unknown'}")
            return response
        except Exception as e:
            logger.error(f"Error creating STT record: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to create STT record: {str(e)}", {"stt_data": stt_data})

    async def upload_docx_to_storage(self, chat_id: int, transcript_id: str, docx_data: bytes) -> str:
        """
        Upload a DOCX file to Supabase storage.
        
        Args:
            chat_id: The chat ID for folder organization
            transcript_id: The transcript ID for file naming
            docx_data: Binary DOCX data
            
        Returns:
            str: The file path in storage
        """
        try:
            now = datetime.now()
            date_str = now.strftime("%d%m%Y_%H%M%S")
            filename = f"stt_{date_str}.docx"
            
            # Create folder path for this chat_id
            folder_path = f"{chat_id}"
            file_path = f"{folder_path}/{filename}"
            
            logger.info(f"Uploading DOCX file to storage: {file_path}")
            
            # Ensure we have bytes (convert from BytesIO if needed)
            if hasattr(docx_data, 'getvalue'):  # Handle BytesIO objects
                file_size = len(docx_data.getvalue())
                docx_data = docx_data.getvalue()  # Get the actual bytes from BytesIO
            else:
                file_size = len(docx_data)
            
            # Upload directly using bytes data
            response = await self.sb_client.storage.from_(self.storage_bucket).upload(
                file_path,
                docx_data,
                file_options={"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
            )
            
            # Get the full path
            storage_path = f"{self.storage_bucket}/{file_path}"
            logger.info(f"Successfully uploaded DOCX file to storage: {storage_path} (size: {file_size} bytes)")
            
            return storage_path
                
        except Exception as e:
            logger.error(f"Error uploading DOCX file to storage: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to upload DOCX file: {str(e)}", 
                               {"chat_id": chat_id, "transcript_id": transcript_id})

    async def get_docx_from_storage(self, file_path: str) -> bytes:
        """
        Get a DOCX file from Supabase storage.
        
        Args:
            file_path: The file path in storage (with or without bucket name)
            
        Returns:
            bytes: The binary DOCX data
        """
        try:
            # Extract the path without bucket name if it's included
            if file_path.startswith(f"{self.storage_bucket}/"):
                path_parts = file_path.split('/', 1)
                if len(path_parts) > 1:
                    path_without_bucket = path_parts[1]
                else:
                    path_without_bucket = ""
            else:
                path_without_bucket = file_path
                
            logger.info(f"Getting DOCX file from storage: {path_without_bucket}")
            
            response = await self.sb_client.storage.from_(self.storage_bucket).download(path_without_bucket)
            
            logger.info(f"Successfully retrieved DOCX file from storage: {file_path} (size: {len(response)} bytes)")
            return response
        except Exception as e:
            logger.error(f"Error getting DOCX file from storage: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to get DOCX file: {str(e)}", {"file_path": file_path})

    async def update_stt_record(self, record_id: str, update_data: dict):
        """Update a record in the 'stt_files' table."""
        try:
            logger.info(f"Updating STT record with ID: {record_id}")
            
            # If status is changing to 'completed' or 'error', add processed_at timestamp
            if 'status' in update_data and (update_data['status'] == 'completed' or update_data['status'] == 'error'):
                if 'processed_at' not in update_data:
                    update_data['processed_at'] = 'now()'  # Use Supabase/PostgreSQL function to set current timestamp
            
            # If transcription_docx is in update_data, upload it to storage and save the path
            if 'transcription_docx' in update_data:
                # Get the chat_id for this record to organize storage
                record_response = await self.sb_client.table("stt_files").select("chat_id,transcript_id").eq("id", record_id).execute()
                if record_response.data and len(record_response.data) > 0:
                    chat_id = record_response.data[0].get('chat_id')
                    transcript_id = record_response.data[0].get('transcript_id')
                    
                    if chat_id and transcript_id:
                        docx_data = update_data['transcription_docx']
                        
                        # Check if it's bytes or BytesIO
                        is_valid_data = isinstance(docx_data, bytes) or hasattr(docx_data, 'getvalue')
                        
                        if is_valid_data:
                            try:
                                # Upload to storage and get path
                                storage_path = await self.upload_docx_to_storage(chat_id, transcript_id, docx_data)
                                # Replace binary data with storage path
                                update_data.pop('transcription_docx', None)
                                update_data['transcript_docx_path'] = storage_path
                                logger.info(f"Saved DOCX file path in database: {storage_path}")
                            except Exception as e:
                                logger.error(f"Failed to upload DOCX to storage: {str(e)}", exc_info=True)
                                # Remove the docx data to avoid DB serialization errors
                                update_data.pop('transcription_docx', None)
                        else:
                            # If not valid data, remove it from update
                            logger.warning(f"Invalid transcription_docx data type: {type(docx_data)}")
                            update_data.pop('transcription_docx', None)
                
            response = await self.sb_client.table("stt_files").update(update_data).eq("id", record_id).execute()
            logger.info(f"STT record updated successfully: {record_id}")
            return response
        except Exception as e:
            logger.error(f"Error updating STT record: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to update STT record: {str(e)}", {"record_id": record_id, "update_data_keys": list(update_data.keys())})

    async def update_stt_transcript_id(self, record_id: str, transcript_id: str):
        """Update the transcript_id field in an stt_files record."""
        try:
            logger.info(f"Updating transcript_id for STT record {record_id} to {transcript_id}")
            update_data = {"transcript_id": transcript_id}
            response = await self.sb_client.table("stt_files").update(update_data).eq("id", record_id).execute()
            logger.info(f"Transcript ID updated successfully for record: {record_id}")
            return response
        except Exception as e:
            logger.error(f"Error updating transcript_id: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to update transcript_id: {str(e)}", {"record_id": record_id, "transcript_id": transcript_id})

    async def get_stt_record_by_transcript_id(self, transcript_id: str):
        """Retrieve an STT record using its AssemblyAI transcript ID."""
        try:
            logger.info(f"Getting STT record with transcript_id: {transcript_id}")
            
            response = await self.sb_client.table("stt_files").select("*").eq("transcript_id", transcript_id).execute()
            
            if response.data and len(response.data) > 0:
                logger.info(f"Found STT record for transcript_id {transcript_id}")
                
                record = response.data[0]
                
                # Check for storage path
                if 'transcript_docx_path' in record and record['transcript_docx_path']:
                    logger.info(f"DOCX file path found for transcript_id {transcript_id}: {record['transcript_docx_path']}")
                
                return record
            
            logger.info(f"No STT record found for transcript_id {transcript_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting STT record by transcript_id: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to get STT record by transcript_id: {str(e)}", {"transcript_id": transcript_id})

    async def get_stt_records(self, chat_id: int = None, message_id: int = None, status: str = None, limit: int = 100):
        """Retrieve STT records with optional filtering."""
        try:
            logger.info(f"Getting STT records (chat_id: {chat_id}, message_id: {message_id}, status: {status})")
            
            # Start a SELECT query
            query = self.sb_client.table("stt_files").select("*")
            
            # Apply filters if provided
            if chat_id is not None:
                query = query.eq("chat_id", chat_id)
            if message_id is not None:
                query = query.eq("message_id", message_id)
            if status is not None:
                query = query.eq("status", status)
                
            # Order by created_at in descending order and limit results
            query = query.order("created_at", desc=True).limit(limit)
            
            response = await query.execute()
            
            logger.info(f"Retrieved {len(response.data)} STT records")
            return response.data
        except Exception as e:
            logger.error(f"Error getting STT records: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to get STT records: {str(e)}")

    async def check_stt_record_delivery(self, record_id: str) -> bool:
        """
        Check if an STT record was already delivered to the user.
        
        Args:
            record_id: The ID of the STT record
            
        Returns:
            bool: True if the record was delivered, False otherwise
        """
        try:
            logger.info(f"Checking delivery status for STT record: {record_id}")
            
            response = await self.sb_client.table("stt_files").select("delivered_to_user").eq("id", record_id).execute()
            
            if response.data and len(response.data) > 0:
                delivered = response.data[0].get('delivered_to_user', False)
                logger.info(f"Delivery status for record {record_id}: {delivered}")
                return delivered
            
            logger.info(f"No STT record found with ID: {record_id}")
            return False
        except Exception as e:
            logger.error(f"Error checking STT record delivery status: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to check STT record delivery status: {str(e)}", {"record_id": record_id})

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

    async def upload_pdf_to_storage(self, chat_id: str, report_type: str, pdf_data: bytes) -> str:
        """
        Upload a PDF file to Supabase storage in the reports bucket.
        
        Args:
            chat_id: The chat ID for folder organization
            report_type: The type of report for file naming
            pdf_data: Binary PDF data
            
        Returns:
            str: The file path in storage
        """
        try:
            now = datetime.now()
            date_str = now.strftime("%d%m%Y_%H%M%S")
            filename = f"{report_type}_{date_str}.pdf"
            
            # Create folder path for this chat_id
            folder_path = f"{chat_id}"
            file_path = f"{folder_path}/{filename}"
            
            logger.info(f"Uploading PDF file to reports storage: {file_path}")
            
            # Ensure we have bytes (convert from BytesIO if needed)
            if hasattr(pdf_data, 'getvalue'):  # Handle BytesIO objects
                file_size = len(pdf_data.getvalue())
                pdf_data = pdf_data.getvalue()  # Get the actual bytes from BytesIO
            else:
                file_size = len(pdf_data)
            
            # Upload directly using bytes data
            response = await self.sb_client.storage.from_(self.reports_bucket).upload(
                file_path,
                pdf_data,
                file_options={"content-type": "application/pdf"}
            )
            
            # Get the full path
            storage_path = f"{self.reports_bucket}/{file_path}"
            logger.info(f"Successfully uploaded PDF file to storage: {storage_path} (size: {file_size} bytes)")
            
            return storage_path
                
        except Exception as e:
            logger.error(f"Error uploading PDF file to storage: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to upload PDF file: {str(e)}", 
                               {"chat_id": chat_id, "report_type": report_type})


    async def get_market_report_config(self) -> Dict[str, Any]:
        """
        Get market report configuration.
            
        Returns:
            Dict containing the market report configuration
        """
        logger.info("Getting market report configuration")
        
        try: 
            # Query the tools table for the report configuration
            response = await self.sb_client.table("tools").select("tool_config").eq("tool_name", "generate_market_report").execute()
            
            if response.data and len(response.data) > 0:
                config = response.data[0].get('tool_config')
                if config:
                    logger.info("Found market report configuration in tools table")
                    return config
                else:
                    logger.warning("No tool configuration found for market report")
            else:
                logger.warning("No market report tool found in tools table")
            
            raise ValueError("No market report configuration found in tools table")
            
        except Exception as e:
            logger.error(f"Error getting market report configuration: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to get market report configuration: {str(e)}")

    async def get_chat_ids(self, limit: int = 10):
        """
        Get a list of chat IDs ordered by creation date.
        
        Args:
            limit: Maximum number of chat IDs to return
            
        Returns:
            List of chat IDs ordered by created_at
        """
        try:
            logger.info(f"As a check, getting max {limit} chat IDs ordered by created_at")

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
