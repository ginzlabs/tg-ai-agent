# This module ensures that only one long‑running task (e.g. process_message) is executed at a time per user.

import asyncio
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Dict, Optional, Callable, Tuple, List, DefaultDict
from collections import defaultdict
from utils.logger import logger
from config import TASK_RETENTION_MINUTES, TASK_CONCURRENCY_LIMITS, QUEUE_CHECK_INTERVAL
import uuid

class TaskStatus(Enum):
    QUEUED = "queued"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_FOUND = "not_found"

class TaskType(Enum):
    TRANSCRIPTION = "transcription"
    REPORT = "report"
    DEFAULT = "default"

class Task:
    def __init__(self, task_id: str, coroutine: Callable, task_type: TaskType = TaskType.DEFAULT):
        self.task_id = task_id
        self.status = TaskStatus.QUEUED
        self.task_type = task_type
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.created_at = datetime.now(UTC)
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.task: Optional[asyncio.Task] = None
        self._coroutine = coroutine
        self.queue_position: Optional[int] = None

    async def run(self):
        """Execute the task and handle its lifecycle."""
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now(UTC)
        try:
            self.result = await self._coroutine()
            self.status = TaskStatus.COMPLETED
        except Exception as e:
            logger.error(f"Task {self.task_id} failed: {str(e)}", exc_info=True)
            self.error = str(e)
            self.status = TaskStatus.FAILED
        finally:
            self.completed_at = datetime.now(UTC)

    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary for API responses."""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "task_type": self.task_type.value,
            "result": self.result,
            "error": self.error,
            "queue_position": self.queue_position,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }

class TaskManager:
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.task_queues: DefaultDict[TaskType, List[str]] = defaultdict(list)
        self.running_tasks: DefaultDict[TaskType, set] = defaultdict(set)
        self._cleanup_task: Optional[asyncio.Task] = None
        self._queue_processor_task: Optional[asyncio.Task] = None
        self._retention_minutes = TASK_RETENTION_MINUTES
        
        # Configure concurrency limits per task type
        self.concurrency_limits = {
            TaskType.TRANSCRIPTION: TASK_CONCURRENCY_LIMITS["transcription"],
            TaskType.REPORT: TASK_CONCURRENCY_LIMITS["report"],
            TaskType.DEFAULT: TASK_CONCURRENCY_LIMITS["default"]
        }

    async def add_task(self, coroutine: Callable, task_type: TaskType = TaskType.DEFAULT, task_id: Optional[str] = None) -> str:
        """
        Add a new task to the manager.
        
        Args:
            coroutine: The async function to execute
            task_type: Type of task for concurrency management
            task_id: Optional task ID. If not provided, one will be generated.
            
        Returns:
            task_id: The ID of the created task
        """
        task_id = task_id or str(uuid.uuid4())
        task = Task(task_id, coroutine, task_type)
        self.tasks[task_id] = task
        
        # Check if we can run the task immediately or need to queue it
        if len(self.running_tasks[task_type]) < self.concurrency_limits[task_type]:
            await self._start_task(task)
        else:
            # Queue the task
            self.task_queues[task_type].append(task_id)
            task.queue_position = len(self.task_queues[task_type])
            logger.info(f"Task {task_id} queued (position {task.queue_position})")
        
        # Start cleanup and queue processor if not running
        if not self._cleanup_task or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_old_tasks())
        if not self._queue_processor_task or self._queue_processor_task.done():
            self._queue_processor_task = asyncio.create_task(self._process_queues())
        
        return task_id

    async def _start_task(self, task: Task):
        """Start a task and set up completion callback."""
        task.status = TaskStatus.PENDING
        self.running_tasks[task.task_type].add(task.task_id)
        
        # Create and start the task
        task.task = asyncio.create_task(task.run())
        task.task.add_done_callback(lambda _: asyncio.create_task(self._handle_task_completion(task)))
        
        logger.info(f"Started task {task.task_id} of type {task.task_type.value}")

    async def _handle_task_completion(self, task: Task):
        """Handle task completion and process queued tasks."""
        self.running_tasks[task.task_type].remove(task.task_id)
        await self._process_queue_for_type(task.task_type)

    async def _process_queue_for_type(self, task_type: TaskType):
        """Process queued tasks for a specific task type."""
        if self.task_queues[task_type]:
            # Get next task from queue
            next_task_id = self.task_queues[task_type].pop(0)
            task = self.tasks.get(next_task_id)
            
            if task and task.status == TaskStatus.QUEUED:
                # Update queue positions for remaining tasks
                for i, queued_id in enumerate(self.task_queues[task_type]):
                    if queued_task := self.tasks.get(queued_id):
                        queued_task.queue_position = i + 1
                
                # Start the task
                await self._start_task(task)

    async def _process_queues(self):
        """Continuously process all task queues."""
        while True:
            try:
                for task_type in TaskType:
                    if len(self.running_tasks[task_type]) < self.concurrency_limits[task_type]:
                        await self._process_queue_for_type(task_type)
                
                await asyncio.sleep(QUEUE_CHECK_INTERVAL)  # Check queues based on config interval
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing task queues: {str(e)}", exc_info=True)
                await asyncio.sleep(QUEUE_CHECK_INTERVAL)

    async def get_task_status(self, task_id: str) -> Tuple[TaskStatus, Optional[Dict[str, Any]]]:
        """
        Get the current status and result of a task.
        
        Args:
            task_id: The ID of the task to check
            
        Returns:
            Tuple of (TaskStatus, Optional[result])
        """
        task = self.tasks.get(task_id)
        if not task:
            return TaskStatus.NOT_FOUND, None
        
        return task.status, task.to_dict()

    async def get_queue_status(self, task_type: Optional[TaskType] = None) -> Dict[str, Any]:
        """
        Get the current status of task queues.
        
        Args:
            task_type: Optional task type to check specific queue
            
        Returns:
            Dict containing queue information
        """
        if task_type:
            return {
                "running": len(self.running_tasks[task_type]),
                "queued": len(self.task_queues[task_type]),
                "limit": self.concurrency_limits[task_type]
            }
        
        return {
            task_type.value: {
                "running": len(self.running_tasks[task_type]),
                "queued": len(self.task_queues[task_type]),
                "limit": self.concurrency_limits[task_type]
            }
            for task_type in TaskType
        }

    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a running task or remove it from queue.
        
        Args:
            task_id: The ID of the task to cancel
            
        Returns:
            bool: True if task was cancelled, False if not found or already completed
        """
        task = self.tasks.get(task_id)
        if not task:
            return False
        
        # If task is queued, remove from queue
        if task.status == TaskStatus.QUEUED:
            if task_id in self.task_queues[task.task_type]:
                self.task_queues[task.task_type].remove(task_id)
                # Update queue positions
                for i, queued_id in enumerate(self.task_queues[task.task_type]):
                    if queued_task := self.tasks.get(queued_id):
                        queued_task.queue_position = i + 1
                task.status = TaskStatus.FAILED
                task.error = "Task was cancelled while in queue"
                task.completed_at = datetime.now(UTC)
                return True
            return False
        
        # If task is running, cancel it
        if task.task and not task.task.done():
            task.task.cancel()
            try:
                await task.task
            except asyncio.CancelledError:
                task.status = TaskStatus.FAILED
                task.error = "Task was cancelled"
                task.completed_at = datetime.now(UTC)
                if task_id in self.running_tasks[task.task_type]:
                    self.running_tasks[task.task_type].remove(task_id)
                return True
        return False

    async def cancel_all_tasks(self):
        """Cancel all running and queued tasks."""
        # Clear all queues
        for task_type in TaskType:
            for task_id in self.task_queues[task_type]:
                if task := self.tasks.get(task_id):
                    task.status = TaskStatus.FAILED
                    task.error = "Task was cancelled during shutdown"
                    task.completed_at = datetime.now(UTC)
            self.task_queues[task_type].clear()
        
        # Cancel running tasks
        running_tasks = []
        for task_type in TaskType:
            running_tasks.extend(list(self.running_tasks[task_type]))
        
        for task_id in running_tasks:
            await self.cancel_task(task_id)
        
        logger.info("All tasks cancelled")

    async def _cleanup_old_tasks(self):
        """Periodically clean up completed tasks older than retention period."""
        while True:
            try:
                current_time = datetime.now(UTC)
                to_remove = []
                
                for task_id, task in self.tasks.items():
                    if task.completed_at:
                        minutes_old = (current_time - task.completed_at).total_seconds() / 60
                        if minutes_old > self._retention_minutes:
                            to_remove.append(task_id)
                
                for task_id in to_remove:
                    del self.tasks[task_id]
                
                if to_remove:
                    logger.info(f"Cleaned up {len(to_remove)} old tasks")
                
                await asyncio.sleep(300)  # Check every 5 minutes
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {str(e)}", exc_info=True)
                await asyncio.sleep(300)  # Wait before retrying

# Global task manager instance
task_manager = TaskManager()

# Convenience functions to use the global task manager
async def add_task(coroutine: Callable, task_type: TaskType = TaskType.DEFAULT, task_id: Optional[str] = None) -> str:
    return await task_manager.add_task(coroutine, task_type, task_id)

async def get_task_status(task_id: str) -> Tuple[TaskStatus, Optional[Dict[str, Any]]]:
    return await task_manager.get_task_status(task_id)

async def get_queue_status(task_type: Optional[TaskType] = None) -> Dict[str, Any]:
    return await task_manager.get_queue_status(task_type)

async def cancel_task(task_id: str) -> bool:
    return await task_manager.cancel_task(task_id)

async def cancel_all_tasks():
    await task_manager.cancel_all_tasks()
