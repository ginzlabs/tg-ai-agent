# This module ensures tasks for users are executed in order, one at a time per user.

import asyncio
from collections import defaultdict, deque
from utils.logger import logger
import config

# Dictionary to store queues of pending tasks per user
user_task_queues = defaultdict(deque)
# Dictionary to store currently running tasks per user
user_running_tasks = {}
# Dictionary to store cancel request messages for users
user_cancel_messages = {}

async def queue_task(user_id: str, task_func, message_id: int = None):
    """
    Queue a task for a specific user. Behavior depends on config.ENABLE_TASK_QUEUING:
    - If True: Queue tasks to run one after another
    - If False: Only allow one task at a time, with option to cancel
    
    Args:
        user_id (str): Unique identifier for the user
        task_func (callable): Async function to execute
        message_id (int, optional): ID of the message that requested this task
        
    Returns:
        If queueing enabled: Queue position (0 = running now)
        If queueing disabled and task already running: Message ID of the cancel confirmation message
        If queueing disabled and no task running: 0 (task will run)
    """
    logger.info(f"Processing task request for user {user_id}")
    
    # If task queueing is enabled, use the original queue mechanism
    if config.ENABLE_TASK_QUEUING:
        return await queue_task_with_queueing(user_id, task_func)
    else:
        # Single task mode - only allow one task at a time
        return await queue_task_single_mode(user_id, task_func, message_id)

async def queue_task_with_queueing(user_id: str, task_func):
    """
    Queue a task for a specific user, ensuring tasks run one at a time per user in order.
    
    Args:
        user_id (str): Unique identifier for the user
        task_func (callable): Async function to execute
        
    Returns:
        int: Queue position (0 means running now)
    """
    logger.info(f"Queuing task for user {user_id} in queue mode")
    
    # Create the task wrapper that will be executed
    async def wrapped_task():
        try:
            logger.info(f"Starting task for user {user_id}")
            await task_func()
            logger.info(f"Task completed for user {user_id}")
        except asyncio.CancelledError:
            logger.warning(f"Task for user {user_id} was cancelled")
            raise
        except Exception as e:
            logger.error(f"Task for user {user_id} failed: {str(e)}", exc_info=True)
            # Re-raise to ensure task is marked as done with error
            raise
        finally:
            logger.debug(f"Task cleanup for user {user_id}")
            
            # Process the next task in queue for this user if any
            user_running_tasks.pop(user_id, None)
            if user_task_queues[user_id]:
                next_task = user_task_queues[user_id].popleft()
                user_running_tasks[user_id] = asyncio.create_task(next_task())
            elif not user_task_queues[user_id]:
                # Clean up empty queues
                user_task_queues.pop(user_id, None)
    
    # If there's no running task for this user, execute immediately
    if user_id not in user_running_tasks or user_running_tasks[user_id].done():
        user_running_tasks[user_id] = asyncio.create_task(wrapped_task())
        return 0  # Running immediately (position 0)
    else:
        # Otherwise add to the queue
        logger.info(f"Task added to queue for user {user_id}, position: {len(user_task_queues[user_id]) + 1}")
        user_task_queues[user_id].append(wrapped_task)
        return len(user_task_queues[user_id])  # Return queue position

async def queue_task_single_mode(user_id: str, task_func, message_id: int = None):
    """
    Handle task request in single task mode. If a task is already running,
    we don't queue and return a message ID that indicates a cancel message was sent.
    
    Args:
        user_id (str): Unique identifier for the user
        task_func (callable): Async function to execute
        message_id (int, optional): ID of the message that requested this task
        
    Returns:
        int: 0 if task will run, > 0 if a cancel message was sent (message ID)
    """
    # If there's already a running task for this user
    if user_id in user_running_tasks and not user_running_tasks[user_id].done():
        logger.info(f"Task already running for user {user_id}, not queuing new task")
        # Return flag to indicate task was not queued (cancel message will be sent by caller)
        return -1
    
    # Create the task wrapper that will be executed
    async def wrapped_task():
        try:
            logger.info(f"Starting task for user {user_id}")
            # Remove any previous cancel message for this user
            user_cancel_messages.pop(user_id, None)
            
            await task_func()
            logger.info(f"Task completed for user {user_id}")
        except asyncio.CancelledError:
            logger.warning(f"Task for user {user_id} was cancelled")
            raise
        except Exception as e:
            logger.error(f"Task for user {user_id} failed: {str(e)}", exc_info=True)
            # Re-raise to ensure task is marked as done with error
            raise
        finally:
            logger.debug(f"Task cleanup for user {user_id}")
            user_running_tasks.pop(user_id, None)
    
    # Create and start the task
    user_running_tasks[user_id] = asyncio.create_task(wrapped_task())
    return 0  # Task will run

async def cancel_user_task(user_id: str):
    """
    Cancel a task for a specific user.
    
    Args:
        user_id (str): Unique identifier for the user
        
    Returns:
        bool: True if task was cancelled, False if no task found
    """
    if user_id in user_running_tasks and not user_running_tasks[user_id].done():
        logger.info(f"Cancelling task for user {user_id}")
        user_running_tasks[user_id].cancel()
        
        try:
            await user_running_tasks[user_id]
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error during task cancellation for user {user_id}: {str(e)}", exc_info=True)
        
        # Remove the task
        user_running_tasks.pop(user_id, None)
        return True
    
    return False

def set_cancel_message(user_id: str, message_id: int, task_message_id: int):
    """
    Store the message ID of a cancel confirmation message for a user.
    
    Args:
        user_id (str): Unique identifier for the user
        message_id (int): Message ID of the cancel confirmation message
        task_message_id (int): Message ID of the task request message
    """
    user_cancel_messages[user_id] = (message_id, task_message_id)

def get_cancel_message(user_id: str):
    """
    Get the message IDs for a user's cancel confirmation message.
    
    Args:
        user_id (str): Unique identifier for the user
        
    Returns:
        tuple: (cancel_message_id, task_message_id) or None if not found
    """
    return user_cancel_messages.get(user_id)

def is_task_running(user_id: str):
    """
    Check if a task is currently running for a user.
    
    Args:
        user_id (str): Unique identifier for the user
        
    Returns:
        bool: True if a task is running, False otherwise
    """
    return user_id in user_running_tasks and not user_running_tasks[user_id].done()

# Clean up function to cancel all pending tasks
async def cancel_all_tasks():
    """Cancel all pending and running tasks"""
    logger.info(f"Cancelling all tasks (running: {len(user_running_tasks)}, queued: {sum(len(q) for q in user_task_queues.values())})")
    
    # Clear all queued tasks
    user_task_queues.clear()
    
    # Cancel all running tasks
    for user_id, task in user_running_tasks.items():
        if not task.done():
            logger.info(f"Cancelling running task for user {user_id}")
            task.cancel()
    
    # Wait for all tasks to be cancelled
    for user_id, task in user_running_tasks.items():
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error during task cancellation for user {user_id}: {str(e)}", exc_info=True)
    
    # Clear the tasks dictionary
    user_running_tasks.clear()
    user_cancel_messages.clear()
    logger.info("All tasks cancelled")
