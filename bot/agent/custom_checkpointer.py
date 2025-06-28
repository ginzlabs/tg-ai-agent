from typing import Any, Dict, Optional
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata, CheckpointTuple
from utils.logger import logger

class LatestOnlyAsyncPostgresSaver(AsyncPostgresSaver):
    """
    Custom PostgreSQL checkpointer that keeps only the latest checkpoint for each thread.
    This helps manage database size by removing older checkpoints.
    """
    
    async def aput(
        self,
        config: Dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Optional[Dict[str, str]] = None
    ) -> CheckpointTuple:
        """
        Save only the latest checkpoint, overwriting any previous checkpoints for the thread.
        
        Args:
            config: Configuration dictionary containing thread_id
            checkpoint: The checkpoint to save
            metadata: Metadata for the checkpoint
            new_versions: Optional dictionary of new versions
            
        Returns:
            CheckpointTuple containing the saved checkpoint
        """
        thread_id = config["configurable"]["thread_id"]
        logger.debug(f"Saving checkpoint for thread_id: {thread_id}")
        
        try:
            # If using a connection pool, get a connection
            if hasattr(self.conn, "connection"):
                async with self.conn.connection() as conn:
                    async with conn.cursor() as cur:
                        # Delete previous checkpoints for this thread
                        await cur.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))
                        await cur.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,))
                        await cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread_id,))
                    await conn.commit()
            # If using a direct connection
            else:
                async with self.conn.cursor() as cur:
                    # Delete previous checkpoints for this thread
                    await cur.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))
                    await cur.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,))
                    await cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread_id,))
                await self.conn.commit()
                
            logger.debug(f"Deleted previous checkpoints for thread_id: {thread_id}")
        except Exception as e:
            logger.error(f"Error deleting previous checkpoints: {str(e)}")
            # Continue with saving the new checkpoint even if deletion fails
        
        # Call the parent class method to save the checkpoint
        return await super().aput(config, checkpoint, metadata, new_versions) 