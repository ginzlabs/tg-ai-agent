import os
import logging
from dotenv import load_dotenv
# Load .env from the parent directory
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from api import endpoints
from utils.limiter import limiter, endpoint_rate_limits
from utils.logger import logger, set_log_level, get_log_level
from utils.error_handler import handle_exception, AppBaseException
from services.supabase_client import initialize_global_supabase_client
from services.task_manager import cancel_all_tasks
from utils.security import verify_secret_token
from psycopg_pool import AsyncConnectionPool
from agent.custom_checkpointer import LatestOnlyAsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore



# Get port from environment variable or use default
PORT = int(os.getenv("TGAGENT_PORT", 9001))
HOST = os.getenv("TGAGENT_HOST", "0.0.0.0")
# Get prod or dev from environment variable
ENV = os.getenv("ENV", "dev")
# If ENV is dev, then RELOAD is true, otherwise false
RELOAD = os.getenv("true" if ENV == "dev" else "false")
# PostgreSQL connection details
DB_URI = os.getenv("DB_URI", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")
 
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    On startup, initialize the global Supabase client, PostgreSQL connection pool,
    and query the 'endpoint_rate_limits' table from Supabase to load the rate limit settings
    into the global endpoint_rate_limits dictionary.
    """
    logger.info("Starting Telegram Bot Server...")
    logger.debug(f"Log level set to: {os.getenv('LOG_LEVEL', 'INFO')}")
    
    pool = None
    try:
        supabase = await initialize_global_supabase_client()
        logger.info("Supabase client initialized successfully")

        # Initialize PostgreSQL connection pool
        logger.info("Initializing PostgreSQL connection pool...")
        connection_kwargs = {
            "autocommit": True,
            "prepare_threshold": 0,
        }
        
        async with AsyncConnectionPool(
            conninfo=DB_URI,
            max_size=20,
            kwargs=connection_kwargs
        ) as pool:
            # Store the pool in the app state
            app.state.pool = pool
            logger.info("PostgreSQL connection pool initialized successfully")
            
            # Initialize checkpointer and log it
            checkpointer = LatestOnlyAsyncPostgresSaver(pool)
            logger.info("LangGraph PostgreSQL checkpointer initialized successfully")

            # Setup tables if they don't exist
            try:
                await checkpointer.setup()
                logger.info("LangGraph PostgreSQL checkpointer tables setup completed")
            except Exception as e:
                logger.warning(f"LangGraph PostgreSQL checkpointer tables setup error (they might already exist): {str(e)}")

            # Initialize memory store and log it
            mem_store = AsyncPostgresStore(pool)
            logger.info("LangGraph PostgreSQL memory store initialized successfully")

            # Setup tables if they don't exist
            try:
                await mem_store.setup()
                logger.info("LangGraph PostgreSQL memory store tables setup completed")
            except Exception as e:
                logger.warning(f"LangGraph PostgreSQL memory store tables setup error (they might already exist): {str(e)}")

            # Add the checkpointer to the app state
            app.state.checkpointer = checkpointer
            app.state.mem_store = mem_store
            
            # Insert server settings into the server_settings table
            logger.debug("Inserting server settings into database...")
            
            # Parse ALLOWED_LLM_MODELS from string to array
            allowed_llms_str = os.getenv("ALLOWED_LLM_MODELS", "")
            allowed_llms = [model.strip() for model in allowed_llms_str.split(",")] if allowed_llms_str else []
            
            # Upsert server settings into the server_settings table
            try:
                server_settings = {
                    "id": 1,
                    "our_secret_token": os.getenv("OUR_SECRET_TOKEN", ""),
                    "bot_server_url": os.getenv("TGAGENT_EXTERNAL_URL", ""),
                    "description": os.getenv("TAGENT_SERVER_NAME", ""),
                    "allowed_llms": allowed_llms
                }
                
                result = await supabase.sb_client.table("server_settings").upsert(
                    server_settings
                ).execute()
                
                logger.info("Server settings inserted/updated successfully")
            except Exception as e:
                logger.error(f"Error inserting server settings: {str(e)}", exc_info=True)

            # Load dynamic rate limits from the Supabase table.
            logger.debug("Fetching endpoint rate limits from database...")
            result = await supabase.sb_client.table("endpoint_rate_limits").select("*").execute()
            if result.data:
                for row in result.data:
                    # Each row should contain: endpoint, call_limit, and interval_seconds.
                    endpoint_name = row["endpoint"]
                    limit_val = row["call_limit"]
                    interval_seconds = row["interval_seconds"]
                    rate_limit_str = f"{limit_val}/{interval_seconds} second"
                    endpoint_rate_limits[endpoint_name] = rate_limit_str
                    logger.info(f"Loaded rate limit for {endpoint_name}: {rate_limit_str}")
                logger.debug(f"Total of {len(result.data)} rate limits loaded")
            else:
                logger.warning("No rate limits found in the database.")
                
            yield
            
            # The pool will be automatically closed when exiting the async with block
            
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}", exc_info=True)
        yield  # Still yield to allow FastAPI to start even with errors
    
    # Shutdown logic
    logger.info("Shutting down Telegram Bot Server...")
    
    # Cancel any pending tasks
    try:
        logger.info("Cancelling any pending background tasks...")
        await cancel_all_tasks()
    except Exception as e:
        logger.error(f"Error cancelling tasks during shutdown: {str(e)}", exc_info=True)


app = FastAPI(title="Telegram Bot Server", lifespan=lifespan)

# Add exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled exceptions"""
    error_response = handle_exception(exc, f"Unhandled error on {request.url.path}")
    return JSONResponse(status_code=500, content=error_response)

@app.exception_handler(AppBaseException)
async def app_exception_handler(request: Request, exc: AppBaseException):
    """Exception handler for application-specific exceptions"""
    error_response = handle_exception(exc)
    return JSONResponse(status_code=400, content=error_response)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Exception handler for request validation errors"""
    error_details = {"validation_errors": exc.errors()}
    error_response = handle_exception(
        exc, 
        f"Validation error on {request.url.path}"
    )
    error_response["error"]["details"] = error_details
    return JSONResponse(status_code=422, content=error_response)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(endpoints.router)

@app.get("/")
async def root():
    logger.info("Root endpoint accessed")
    return {"message": "Telegram Bot Server is running"}

@app.get("/debug/log-level", dependencies=[Depends(verify_secret_token)])
async def get_logging_level():
    """Get the current logging level"""
    level_name = logging.getLevelName(logger.level)
    logger.info(f"Log level requested: currently {level_name}")
    return {"current_level": level_name}

@app.post("/debug/log-level/{level}", dependencies=[Depends(verify_secret_token)])
async def set_logging_level(level: str):
    """Set the logging level dynamically"""
    try:
        if level.upper() not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            logger.warning(f"Invalid log level requested: {level}")
            return {"error": f"Invalid log level: {level}. Use DEBUG, INFO, WARNING, ERROR, or CRITICAL."}
        
        new_level_name = set_log_level(level)
        logger.info(f"Log level changed to {new_level_name}")
        return {"success": True, "new_level": new_level_name}
    except Exception as e:
        logger.error(f"Error changing log level: {str(e)}", exc_info=True)
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=RELOAD,
    )
