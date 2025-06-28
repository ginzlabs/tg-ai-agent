from fastapi import HTTPException, status
from typing import Dict, Any, Optional
from .logger import logger

class AppBaseException(Exception):
    """Base exception class for application-specific exceptions."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)
        
    def __str__(self):
        return f"{self.message} - Details: {self.details}"

class DatabaseError(AppBaseException):
    """Exception raised for database-related errors."""
    pass

class TelegramAPIError(AppBaseException):
    """Exception raised for Telegram API-related errors."""
    pass

class RateLimitExceededError(AppBaseException):
    """Exception raised when a rate limit is exceeded."""
    pass

class AuthenticationError(AppBaseException):
    """Exception raised for authentication-related errors."""
    pass

class ValidationError(AppBaseException):
    """Exception raised for data validation errors."""
    pass

def handle_exception(exception: Exception, log_message: str = None) -> Dict[str, Any]:
    """
    Handle exceptions in a uniform way.
    
    Args:
        exception: The exception to handle
        log_message: Optional custom log message
        
    Returns:
        A dictionary with error details suitable for API responses
    """
    error_message = str(exception)
    error_type = type(exception).__name__
    
    # Log the error with appropriate level based on exception type
    if log_message:
        message = f"{log_message}: {error_message}"
    else:
        message = error_message
    
    # Different logging levels based on exception type
    if isinstance(exception, (ValidationError, RateLimitExceededError)):
        logger.warning(f"{error_type}: {message}")
    else:
        logger.error(f"{error_type}: {message}", exc_info=True)
    
    # Create a standardized error response
    response = {
        "success": False,
        "error": {
            "type": error_type,
            "message": error_message
        }
    }
    
    # Add additional details for AppBaseException subclasses
    if isinstance(exception, AppBaseException) and exception.details:
        response["error"]["details"] = exception.details
    
    return response

def http_exception_handler(status_code: int, detail: str) -> HTTPException:
    """
    Create an HTTPException with a standardized format.
    
    Args:
        status_code: HTTP status code
        detail: Error message
        
    Returns:
        HTTPException object
    """
    logger.warning(f"HTTP {status_code}: {detail}")
    return HTTPException(
        status_code=status_code,
        detail={
            "success": False,
            "error": {
                "type": "HTTPException",
                "message": detail
            }
        }
    ) 