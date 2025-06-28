import os
from fastapi import Header, HTTPException, Security
import secrets
import string
from utils.logger import logger
from utils.error_handler import AuthenticationError, http_exception_handler
from fastapi.security import APIKeyHeader
from typing import Optional

# Define the header field name for the API key
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_secret_token(x_secret_token: str = Header(...)):
    """
    Dependency to verify that the incoming request contains the correct secret token.
    """
    expected_token = os.getenv("OUR_SECRET_TOKEN")
    if not expected_token:
        logger.error("OUR_SECRET_TOKEN is not set in environment variables")
        raise http_exception_handler(500, "Server configuration error - secret token not set")
        
    if x_secret_token != expected_token:
        logger.warning(f"Invalid secret token attempt: {x_secret_token[:5]}...{x_secret_token[-5:] if len(x_secret_token) > 10 else ''}")
        raise http_exception_handler(401, "Invalid secret token")
    
    logger.debug("Secret token verified successfully")


async def verify_tgagent_secret(x_telegram_bot_api_secret_token: str = Header(...)):
    """
    Dependency to verify that the incoming Telegram webhook request contains the correct secret token.
    Checks the header 'X-Telegram-Bot-Api-Secret-Token'.
    """
    expected_token = os.getenv("OUR_SECRET_TOKEN")
    if not expected_token:
        logger.error("OUR_SECRET_TOKEN is not set in environment variables")
        raise http_exception_handler(500, "Server configuration error - secret token not set")
        
    if x_telegram_bot_api_secret_token != expected_token:
        logger.warning("Invalid Telegram webhook secret token attempt")
        raise http_exception_handler(401, "Invalid TG agent secret")
    
    logger.debug("Telegram webhook secret token verified successfully")


def generate_random_string(length=10):
    """
    Generate a random string of specified length using secure random number generation.
    
    Args:
        length (int): Length of the random string to generate
        
    Returns:
        str: A random string of the specified length
    """
    try:
        characters = string.ascii_letters + string.digits  # A-Z, a-z, 0-9
        random_string = ''.join(secrets.choice(characters) for _ in range(length))
        logger.debug(f"Generated random string of length {length}")
        return random_string
    except Exception as e:
        logger.error(f"Error generating random string: {str(e)}", exc_info=True)
        raise AuthenticationError(f"Failed to generate random string: {str(e)}", {"length": length})


def get_api_key() -> str:
    """Get the API key from environment variables."""
    api_key = os.getenv("OUR_SECRET_TOKEN")
    if not api_key:
        raise ValueError("OUR_SECRET_TOKEN environment variable is not set")
    return api_key

async def verify_api_key(api_key_header: Optional[str] = Security(API_KEY_HEADER)) -> None:
    """
    Verify that the API key in the header matches the one in environment variables.
    This function is used as a dependency in FastAPI routes.
    """
    if not api_key_header:
        raise HTTPException(
            status_code=401,
            detail="Missing API key in X-API-Key header"
        )
    
    try:
        api_key = get_api_key()
    except ValueError as e:
        raise HTTPException(
            status_code=500,
            detail="Server configuration error: API key not set"
        )
    
    if api_key_header != api_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key"
        )


if __name__ == "__main__":
    # Set up basic logging for standalone execution
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Generate and print a random string
    print(generate_random_string(32))  # Example: 'G5kX8Lz9Q2Tf'