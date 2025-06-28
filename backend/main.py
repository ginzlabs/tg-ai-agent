import os, sys, asyncio
from dotenv import load_dotenv

# Load .env from the parent directory
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
# Configure event loop policy for Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    logger.info("Using WindowsProactorEventLoopPolicy for Windows platform")
    load_dotenv(env_path, override=True)
else:
    load_dotenv(env_path)
    

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from api import endpoints
from utils.limiter import limiter
from utils.logger import logger
from utils.error_handler import handle_exception, AppBaseException
from services.supabase_client import initialize_global_supabase_client
from services.task_manager import cancel_all_tasks

from config import DEFAULT_LOG_LEVEL



# Get port from environment variable or use default
PORT = int(os.getenv("BACKEND01_PORT", 9002))
HOST = os.getenv("BACKEND01_HOST", "0.0.0.0")
ENV = os.getenv("ENV", "dev")
RELOAD = True if ENV == "dev" else False
 
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    On startup, initialize the global Supabase client and query the
    'endpoint_rate_limits' table from Supabase to load the rate limit settings
    into the global endpoint_rate_limits dictionary.
    """
    logger.info("Starting Waiter Server...")
    logger.info(f"Log level set to: {os.getenv('LOG_LEVEL', DEFAULT_LOG_LEVEL)}")

    # Log webhook configuration
    webhook_url = os.getenv("BACKEND01_WEBHOOK_URL")
    webhook_secret = os.getenv("OUR_SECRET_TOKEN")
    if webhook_secret is None:
        raise EnvironmentError("Environment variable OUR_SECRET_TOKEN must be set")
    logger.info(f"Webhook URL: {webhook_url if webhook_url else 'Not configured'}")
    logger.info(f"Webhook Secret: {'Configured' if webhook_secret else 'Not configured'}")
     
    try:
        # Initialize Supabase client for database operations
        sb_client = await initialize_global_supabase_client()
        logger.info("Supabase client initialized successfully")
         
        # Test connection by fetching some chat IDs
        try:
            chat_ids = await sb_client.get_chat_ids(limit=5)
            if chat_ids:
                logger.info(f"Database connection test successful. Found {len(chat_ids)} chat IDs.")
            else:
                logger.info("Database connection test successful, but no chat IDs found.")
        except Exception as e:
            logger.warning(f"Could not fetch chat IDs: {str(e)}")
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}", exc_info=True)
        # We still allow the app to start even if there's an error
    
    yield
    
    # Shutdown logic
    logger.info("Shutting down Waiter Server...")

        # Cancel any pending tasks
    try:
        logger.info("Cancelling any pending background tasks...")
        await cancel_all_tasks()
    except Exception as e:
        logger.error(f"Error cancelling tasks during shutdown: {str(e)}", exc_info=True)
    


app = FastAPI(title="Backend Server", lifespan=lifespan)


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

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Include API routes
app.include_router(endpoints.router)
app.include_router(endpoints.webhook_router)

@app.get("/")
async def root():
    """Root endpoint that confirms the server is running"""
    logger.info("Root endpoint accessed")
    return {
        "status": "running",
        "message": "Backend Server is operational",
        "docs_url": "/docs",
        "port": PORT
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=RELOAD,
    )
