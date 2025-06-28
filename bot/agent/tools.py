"""Define the agent's tools."""

import uuid
from typing import Annotated, Optional, Any, cast
import aiohttp
import os

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from langgraph.store.base import BaseStore
from langgraph.prebuilt import InjectedStore
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command
from langgraph.prebuilt import InjectedState
from langchain_core.messages import ToolMessage

from agent.configuration import Configuration
from langchain_community.tools.tavily_search import TavilySearchResults
from utils.logger import logger
from services import user_service
from services.supabase_client import get_supabase_client
from schemas import UserCreate



async def check_tool_access(chat_id: int, tool_name: str) -> bool:
    """
    Helper function to check if a user has access to a specific tool.
    
    Args:
        chat_id: The user's chat ID
        tool_name: The name of the tool to check access for
        
    Returns:
        True if the user has access, False otherwise
    """
    logger.info(f"Checking access to {tool_name} for chat {chat_id}")
    
    # Get the Supabase client
    supabase = get_supabase_client()
    
    # Check if the user has access to this tool
    try:
        access_response = await supabase.call_rpc("check_tool_access", {
            "chat_id_input": int(chat_id),
            "tool_name_input": tool_name
        })
        
        has_access = access_response and access_response.data
        
        if not has_access:
            logger.warning(f"Access denied to {tool_name} for chat {chat_id}")
            
        return has_access
    except Exception as e:
        logger.error(f"Error checking access for {tool_name}: {str(e)}")
        # If there's an error checking access, default to NO access
        return False

async def upsert_memory(
    content: str,
    context: str,
    *,
    memory_id: Optional[uuid.UUID] = None,
    config: Annotated[RunnableConfig, InjectedToolArg],
    store: Annotated[BaseStore, InjectedStore],
) -> str:
    """Upsert a memory in the database.

    If a memory conflicts with an existing one, then just UPDATE the
    existing one by passing in memory_id - don't create two memories
    that are the same. If the user corrects a memory, UPDATE it.

    Args:
        content: The main content of the memory. For example:
            "User expressed interest in learning about French."
        context: Additional context for the memory. For example:
            "This was mentioned while discussing career options in Europe."
        memory_id: ONLY PROVIDE IF UPDATING AN EXISTING MEMORY.
        The memory to overwrite.
    """

    mem_id = memory_id or uuid.uuid4()
    user_id = Configuration.from_runnable_config(config).user_id

    logger.info(f"Upserting memory for user {user_id} with ID {mem_id}")

    await store.aput(
        ("memories", user_id),
        key=str(mem_id),
        value={"content": content, "context": context},
    )
    return f"Stored memory {mem_id}"
 
async def search_tavily(
    query: str, *, config: Annotated[RunnableConfig, InjectedToolArg]
) -> Optional[list[dict[str, Any]]]:
    """Search for general web results.

    This function performs a search using the Tavily search engine, which is designed
    to provide comprehensive, accurate, and trusted results. It's particularly useful
    for answering questions about current events.
    """

    logger.info(f"Searching for {query}")

    configuration = Configuration.from_runnable_config(config)
    wrapped = TavilySearchResults(max_results=configuration.max_search_results)
    result = await wrapped.ainvoke({"query": query})
    return cast(list[dict[str, Any]], result)

async def test_tool(
    message: str, 
    *,
    config: Annotated[RunnableConfig, InjectedToolArg],
    tools_call_approvals: Annotated[dict, InjectedState("tools_call_approvals")],
    tool_call_id: Annotated[str, InjectedToolCallId]
) -> str:
    """A simple test tool that logs the input message and returns a response.
    
    This tool is useful for testing the agent's ability to use tools and for
    debugging the agent's behavior.
    
    Args:
        message: The message to log and respond to.
    """

    # Check if the tool call was approved
    logger.info(f"Pending approvals: {tools_call_approvals}")
    if tools_call_approvals.get("test_tool", True):
        logger.info(f"Tool call {tool_call_id} for test_tool was approved")
    else:
        logger.info(f"Tool call {tool_call_id} for test_tool was rejected")
        return "Tool call rejected."

    user_id = Configuration.from_runnable_config(config).user_id
    
    logger.info(f"Test tool called by user {user_id} with message: {message} and tool call id: {tool_call_id}")
    logger.info(f"Processing test tool request: {message}")
    
    # Simulate some processing
    response = f"Test tool received: '{message}'"
    
    logger.info(f"Test tool response: {response}")

    return Command(
        update={
            # update the state to False after running the tools
            "tools_call_approvals": {"test_tool": False},
            # update the message history
            "messages": [
                ToolMessage(
                    f"Tool ran successfully {response}", tool_call_id=tool_call_id
                )
            ],
        }
    )


async def generate_market_report(
    *,
    config: Annotated[RunnableConfig, InjectedToolArg]
) -> str:
    """Generate a market report.
    
    This tool makes an API call to generate a market report.
    The report will contain the latest market bond yields.
    The report will be sent to the user who requested it automatically by our backend if response is successful.
    So reply with a very brief message like "Report generated successfully."
    """
    configuration = Configuration.from_runnable_config(config)
    chat_id = configuration.user_id
    
    # Check if user has access to this tool
    has_access = await check_tool_access(int(chat_id), "generate_market_report")
    if not has_access:
        return "You don't have access to the market report feature."
    
    logger.info(f"Generating market report for chat {chat_id}")
    
    base_url = os.getenv("BACKEND01_LOCAL_URL", "http://localhost:8001")
    url = f"{base_url}/api/v1/generate-market-report"
    headers = {
        "X-API-Key": os.getenv("OUR_SECRET_TOKEN"),
        "Content-Type": "application/json"
    }
    data = {"chat_id": chat_id}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    return "Report requested successfully. It will be sent to you shortly."
                else:
                    error_text = await response.text()
                    return f"Failed to generate market report. Status: {response.status}, Error: {error_text}"
    except Exception as e:
        logger.error(f"Error generating market report: {str(e)}")
        return f"Error generating market report: {str(e)}"

async def manage_users(
    action: str,
    user_identifier: str = "all",
    role: str = "user",
    tier: Optional[int] = None,
    suspended: Optional[bool] = None,
    service_maintenance: Optional[bool] = None,
    expire_at: Optional[str] = None,
    *,
    config: Annotated[RunnableConfig, InjectedToolArg]
) -> str:
    """Manage user accounts (admin only). Only run if user is ADMIN.
    
    This tool allows administrators to check, create, delete, or update users. 
    Before performing any action, it verifies the requesting user has admin privileges.
    
    Args:
        action: The action to perform - "check", "create", "delete", or "update"
        user_identifier: Either a username (string) or chat_id (numeric string).
                       Use "all" for updating all non-admin users at once.
        role: For "create" or "update" action - the role to assign (default: "user")
        tier: For "update" action - the subscription tier (integer)
        suspended: For "update" action - user suspended status (e.g., True or False)
        service_maintenance: For "update" action - user service_maintenance status (e.g., True or False)
        expire_at: ISO format date when user access expires (YYYY-MM-DDTHH:MM:SS+00:00)
    """
    configuration = Configuration.from_runnable_config(config)
    admin_chat_id = configuration.user_id
    
    logger.info(f"User management tool called by {admin_chat_id}, action: {action}, target: {user_identifier}")
    
    # Get the Supabase client
    supabase = get_supabase_client()
    
    # First verify the user has admin privileges
    try:
        # Check if current user is admin by directly fetching user data
        admin_data = await supabase.get_user(chat_id=int(admin_chat_id))
        if not admin_data or not admin_data[0].get("role") == "admin":
            return "Error: You don't have admin privileges to manage users."
        
        # Special case for update action with "all" user_identifier
        if action.lower() == "update" and user_identifier.lower() == "all":
            # Special handling for service_maintenance mode affecting all users
            if service_maintenance is not None:
                logger.info(f"Setting service_maintenance={service_maintenance} for all non-admin users")
                
                try:
                    # Use the RPC function to update all non-admin users
                    response = await supabase.call_rpc("set_service_maintenance", {
                        "p_enabled": service_maintenance
                    })
                    
                    # Process the RPC response according to the function's return structure
                    if response and hasattr(response, 'data'):
                        # Extract affected_users count from the response
                        if isinstance(response.data, dict) and 'affected_users' in response.data:
                            updated_count = response.data['affected_users']
                            return f"Service maintenance mode {'enabled' if service_maintenance else 'disabled'} for {updated_count} non-admin users."
                        else:
                            # If the response structure is unexpected but we got a response
                            return f"Service maintenance mode {'enabled' if service_maintenance else 'disabled'} for all non-admin users. Response: {response.data}"
                    else:
                        return f"Service maintenance mode update operation completed, but couldn't determine affected users."
                except Exception as e:
                    logger.error(f"Error setting service maintenance for all users: {str(e)}")
                    return f"Error setting service maintenance mode: {str(e)}"
            else:
                return "Error: To update all users, you must specify service_maintenance parameter."
        
        # Determine if user_identifier is a chat_id (numeric) or username
        is_chat_id = user_identifier.isdigit()
        
        # Perform the requested action
        if action.lower() == "check":
            # Check user by directly calling get_user function
            if is_chat_id:
                user_data = await supabase.get_user(chat_id=int(user_identifier))
            else:
                user_data = await supabase.get_user(user_name=user_identifier)
                
            if user_data:
                user = user_data[0]
                # Return all user data as a formatted string
                return f"User found:\n" + "\n".join([f"{key}: {value}" for key, value in user.items()])
            else:
                return f"User not found: {user_identifier}"
                
        elif action.lower() == "create":
            # Create user object
            user_create = UserCreate(role=role)
            
            if is_chat_id:
                user_create.chat_id = int(user_identifier)
                user_create.user_name = f"user_{user_identifier}"  # Default username
            else:
                user_create.user_name = user_identifier
            
            # Call user_service.create_user directly
            result = await user_service.create_user(user_create, supabase)
            if result:
                return f"User created successfully: {user_identifier}"
            else:
                return f"Error creating user: {user_identifier}"
                
        elif action.lower() == "delete":
            # Call user_service.delete_user directly
            if is_chat_id:
                result = await user_service.delete_user(chat_id=int(user_identifier), sb_client=supabase)
            else:
                result = await user_service.delete_user(user_name=user_identifier, sb_client=supabase)
                
            if result and result.data:
                return f"User deleted successfully: {user_identifier}"
            else:
                return f"No user found to delete with identifier: {user_identifier}"
                
        elif action.lower() == "update":
            # Log the action parameters
            logger.info(
                f"User management tool called by {admin_chat_id}, "
                f"action={action}, "
                f"target={user_identifier}, "
                f"role={role}, "
                f"tier={tier}, "
                f"suspended={suspended}, "
                f"service_maintenance={service_maintenance}, "
                f"expire_at={expire_at}"
            )
            # First find the user to get their ID
            if is_chat_id:
                user_data = await supabase.get_user(chat_id=int(user_identifier))
            else:
                user_data = await supabase.get_user(user_name=user_identifier)
                
            if not user_data:
                return f"User not found: {user_identifier}"
            
            user_id = user_data[0]["id"]
            
            # Create update data dictionary with provided fields
            update_data = {}
            
            if role:
                update_data["role"] = role
                
            if tier is not None:
                update_data["tier"] = tier
                
            if suspended is not None:
                update_data["suspended"] = suspended
                
            if service_maintenance is not None:
                update_data["service_maintenance"] = service_maintenance
                
            if expire_at:
                update_data["expire_at"] = expire_at
            
            if not update_data:
                return "No update data provided."
            
            # Update user
            result = await supabase.update_user(user_id, update_data)
            
            if result and result.data:
                updated_fields = ", ".join(update_data.keys())
                return f"User {user_identifier} updated successfully. Updated fields: {updated_fields}"
            else:
                return f"Error updating user: {user_identifier}"
        else:
            return f"Invalid action: {action}. Valid actions are 'check', 'create', 'delete', or 'update'."
            
    except Exception as e:
        logger.error(f"Error in user management tool: {str(e)}")
        return f"Error managing user: {str(e)}"

async def list_available_tools(
    *,
    config: Annotated[RunnableConfig, InjectedToolArg]
) -> str:
    """List all available tools that the user can access based on their tier.
    
    This tool returns a formatted list of all tools that the user has access to,
    along with descriptions. The availability is determined by the user's tier level.
    """
    configuration = Configuration.from_runnable_config(config)
    chat_id = configuration.user_id
    
    logger.info(f"Listing available tools for chat_id: {chat_id}")
    
    # Get the Supabase client
    supabase = get_supabase_client()
    
    try:
        # Call the RPC function to get available tools
        response = await supabase.call_rpc("get_available_tools", {
            "p_chat_id": int(chat_id)
        })
        
        # Process the response
        if response and hasattr(response, 'data') and response.data:
            tools_list = response.data
            
            # Format the tools as a nice list
            formatted_response = "# Tools Available to You\n\n"
            
            for tool in tools_list:
                tool_name = tool.get('tool_name', 'Unknown')
                tool_description = tool.get('tool_description', 'No description available')
                tool_tier = tool.get('tool_tier', 'All tiers')
                
                formatted_response += f"## {tool_name}\n"
                formatted_response += f"{tool_description}\n"
                formatted_response += f"*Required tier: {tool_tier}*\n\n"
            
            if not tools_list:
                formatted_response += "No tools are currently available to you."
                
            return formatted_response
        else:
            return "No tools are currently available or there was an error retrieving the tool list."
    except Exception as e:
        logger.error(f"Error retrieving available tools: {str(e)}")
        return f"Error retrieving available tools: {str(e)}"

async def manage_cron_prompts(
    action: str,
    prompt_text: Optional[str] = None,
    jobname: Optional[str] = None,
    schedule: Optional[str] = None,
    prompt_id: Optional[str] = None,
    *,
    config: Annotated[RunnableConfig, InjectedToolArg]
) -> str:
    """Manage scheduled prompt jobs (create, list, update, or delete cron prompts).
    
    This tool allows users to schedule prompts to be run periodically according to a cron schedule.
    Users can create new scheduled prompts, list their existing ones, update them, or delete them.
    IMPORTANT: The cron schedule is in UTC time!!!
    Always take this into account when setting the schedule as user timezone requests might be different.
    
    Args:
        action: The action to perform - "create", "list", "update", or "delete"
        prompt_text: For "create" and "update" actions - the prompt text to schedule
        jobname: For "create" action - a descriptive name for the job (e.g., "daily_weather")
        schedule: For "create" and "update" actions - cron schedule expression in UTC time
                 (e.g., "0 8 * * *" for daily at 8 AM - UTC time)
        prompt_id: For "update" and "delete" actions - the ID of the prompt to modify
    """
    configuration = Configuration.from_runnable_config(config)
    chat_id = configuration.user_id
    db_thread_id = configuration.thread_id
    
    # Check if user has access to this tool
    has_access = await check_tool_access(int(chat_id), "manage_cron_prompts")
    if not has_access:
        return "You don't have access to the cron scheduling feature."
    
    logger.info(f"Managing cron prompts for chat {chat_id}, action: {action}")
    
    # Get the Supabase client
    supabase = get_supabase_client()
    
    try:
        if action.lower() == "create":
            # Validate required parameters
            if not prompt_text:
                return "Error: prompt_text is required for creating a cron prompt."
            if not jobname:
                return "Error: jobname is required for creating a cron prompt."
            if not schedule:
                return "Error: schedule is required for creating a cron prompt."
            
            # Call the RPC function to create a cron prompt
            response = await supabase.call_rpc("create_cron_prompt_job", {
                "p_chat_id": int(chat_id),
                "p_prompt_text": prompt_text,
                "p_jobname": jobname,
                "p_schedule": schedule,
                "p_db_thread_id": db_thread_id
            })
            
            # Process the response
            if response and hasattr(response, 'data'):
                # Check if the response data has a "result" field (new format)
                if isinstance(response.data, list) and len(response.data) > 0 and "result" in response.data[0]:
                    # Extract the result object from the returned table
                    result = response.data[0]["result"]
                    
                    if result.get('success'):
                        prompt_id = result.get('prompt_id')
                        job_name = result.get('jobname')
                        return f"Successfully scheduled prompt '{job_name}' with ID {prompt_id}. It will run according to schedule: {schedule}"
                    else:
                        return f"Failed to create cron prompt: {result.get('message', 'Unknown error')}"
                # Handle the old format for backwards compatibility
                elif "success" in response.data:
                    if response.data.get('success'):
                        prompt_id = response.data.get('prompt_id')
                        job_name = response.data.get('jobname')
                        return f"Successfully scheduled prompt '{job_name}' with ID {prompt_id}. It will run according to schedule: {schedule}"
                    else:
                        return f"Failed to create cron prompt: {response.data.get('message', 'Unknown error')}"
                else:
                    return f"Unexpected response format: {response.data}"
            
            return "Failed to create cron prompt. No valid response from server."
                
        elif action.lower() == "list":
            # Call the RPC function to list cron prompts
            try:
                response = await supabase.call_rpc("list_cron_prompts_by_chat", {
                    "p_chat_id": int(chat_id)
                })
                
                if response and hasattr(response, 'data'):
                    if response.data and len(response.data) > 0:
                        prompts_list = response.data
                        
                        # Format the prompts as a nice list
                        formatted_response = "# Your Scheduled Prompts\n\n"
                        
                        for idx, prompt in enumerate(prompts_list, 1):
                            prompt_id = prompt.get('id', 'Unknown')
                            prompt_text = prompt.get('prompt_text', 'No prompt text available')
                            schedule = prompt.get('schedule', 'Unknown schedule')
                            
                            formatted_response += f"## {idx}. Prompt ID: {prompt_id}\n"
                            formatted_response += f"**Schedule**: `{schedule}`\n"
                            formatted_response += f"**Prompt**: {prompt_text}\n\n"
                        
                        return formatted_response
                    else:
                        return "You don't have any scheduled prompts yet."
            except Exception as e:
                # If it's a null response (empty list), that's normal
                if "null" in str(e).lower() or str(e) == "None":
                    return "You don't have any scheduled prompts yet."
                raise e
                
            return "Failed to retrieve scheduled prompts. No response from server."
                
        elif action.lower() == "update":
            # Validate required parameters
            if not prompt_id:
                return "Error: prompt_id is required for updating a cron prompt."
            if not prompt_text and not schedule:
                return "Error: At least one of prompt_text or schedule must be provided for updating."
            
            # Call the RPC function to update a cron prompt
            try:
                response = await supabase.call_rpc("update_cron_prompt", {
                    "p_id": prompt_id,
                    "p_chat_id": int(chat_id),
                    "p_prompt_text": prompt_text,
                    "p_schedule": schedule,
                    "p_db_thread_id": db_thread_id
                })
                
                if response and hasattr(response, 'data'):
                    # Check if the response data has a "result" field (new format)
                    if isinstance(response.data, list) and len(response.data) > 0 and "result" in response.data[0]:
                        # Extract the result object from the returned table
                        result = response.data[0]["result"]
                        
                        if result.get('success'):
                            updated_fields = []
                            if prompt_text:
                                updated_fields.append("prompt text")
                            if schedule:
                                updated_fields.append("schedule")
                            
                            return f"Successfully updated prompt {prompt_id}. Updated: {', '.join(updated_fields)}."
                        else:
                            return f"Failed to update cron prompt: {result.get('message', 'Unknown error')}"
                    # Handle the old format for backwards compatibility
                    elif "success" in response.data:
                        if response.data.get('success'):
                            updated_fields = []
                            if prompt_text:
                                updated_fields.append("prompt text")
                            if schedule:
                                updated_fields.append("schedule")
                            
                            return f"Successfully updated prompt {prompt_id}. Updated: {', '.join(updated_fields)}."
                        else:
                            return f"Failed to update cron prompt: {response.data.get('message', 'Unknown error')}"
                    else:
                        return f"Unexpected response format: {response.data}"
            except Exception as e:
                # Check if this is actually a success response being reported as an error
                error_str = str(e)
                if "'success': True" in error_str:
                    updated_fields = []
                    if prompt_text:
                        updated_fields.append("prompt text")
                    if schedule:
                        updated_fields.append("schedule")
                    
                    return f"Successfully updated prompt {prompt_id}. Updated: {', '.join(updated_fields)}."
                raise e
                
            return "Failed to update cron prompt. No response from server."
                 
        elif action.lower() == "delete":
            # Validate required parameters
            if not prompt_id:
                return "Error: prompt_id is required for deleting a cron prompt."
            
            # Call the RPC function to delete a cron prompt
            try:
                response = await supabase.call_rpc("delete_cron_prompt", {
                    "p_id": prompt_id,
                    "p_chat_id": int(chat_id)
                })
                
                if response and hasattr(response, 'data'):
                    # Check if the response data has a "result" field (new format)
                    if isinstance(response.data, list) and len(response.data) > 0 and "result" in response.data[0]:
                        # Extract the result object from the returned table
                        result = response.data[0]["result"]
                        
                        if result.get('success'):
                            return f"Successfully deleted scheduled prompt {prompt_id}."
                        else:
                            return f"Failed to delete cron prompt: {result.get('message', 'Unknown error')}"
                    # Handle the old format for backwards compatibility
                    elif "success" in response.data:
                        if response.data.get('success'):
                            return f"Successfully deleted scheduled prompt {prompt_id}."
                        else:
                            return f"Failed to delete cron prompt: {response.data.get('message', 'Unknown error')}"
                    else:
                        return f"Unexpected response format: {response.data}"
            except Exception as e:
                # Check if this is actually a success response being reported as an error
                error_str = str(e)
                if "'success': True" in error_str:
                    return f"Successfully deleted scheduled prompt {prompt_id}."
                if "Cron prompt not found" in error_str:
                    return f"No prompt found with ID {prompt_id}."
                raise e
                
            return "Failed to delete cron prompt. No response from server."
        else:
            return f"Invalid action: {action}. Valid actions are 'create', 'list', 'update', or 'delete'."
            
    except Exception as e:
        logger.error(f"Error in manage_cron_prompts tool: {str(e)}")
        return f"Error managing cron prompts: {str(e)}"

# Tools that are available to the agent
TOOLS = [search_tavily, 
         upsert_memory,
         test_tool,
         generate_market_report,
         manage_users,
         list_available_tools,
         manage_cron_prompts,
         ]

# List of names of tools that require human-in-the-loop approval
TOOLS_w_APPROVAL = [
    "test_tool",
    ]
