import os
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from dotenv import load_dotenv
import codecs

# Load environment variables to get logging level
load_dotenv()

# Create logs directory if it doesn't exist
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

# Map string log levels to logging module constants
LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL
}

def safe_str(obj, max_length=200):
    """
    Safely convert an object to a string, handling large objects and Unicode characters.
    Truncates long strings and handles special cases.
    """
    if isinstance(obj, (dict, list)):
        return str(obj)[:max_length] + "..." if len(str(obj)) > max_length else str(obj)
    elif hasattr(obj, 'to_string'):  # Handle pandas DataFrames
        return obj.to_string()[:max_length] + "..." if len(obj.to_string()) > max_length else obj.to_string()
    else:
        return str(obj)[:max_length] + "..." if len(str(obj)) > max_length else str(obj)

# Get log level from environment or default to INFO
def get_log_level():
    """Get the log level from environment variable or default to INFO."""
    env_level = os.getenv("LOG_LEVEL", "INFO").upper()
    return LOG_LEVEL_MAP.get(env_level, logging.INFO)

# Configure the logger
def setup_logger():
    """
    Set up a central logger with file and console handlers.
    Returns a configured logger instance.
    """
    # Get log level from environment
    log_level = get_log_level()
    
    # Set root logger level to affect all loggers
    logging.getLogger().setLevel(log_level)
    
    # Configure basic logging with the same level
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Create the logger
    logger = logging.getLogger("tg_agent")
    logger.setLevel(log_level)
    
    # Prevent propagation to root logger to avoid double logging
    logger.propagate = False
    
    # Remove existing handlers if any
    if logger.handlers:
        logger.handlers.clear()
    
    # Create a formatter that includes timestamp, level, module, and message
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(module)s:%(funcName)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Create a file handler for the log file with rotation (max 10MB, keep 5 backup files)
    file_handler = RotatingFileHandler(
        logs_dir / "tg_agent.log", 
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'  # Explicitly set UTF-8 encoding for file handler
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)
    
    # Create a console handler for stdout with UTF-8 encoding
    console_handler = logging.StreamHandler(codecs.getwriter('utf-8')(sys.stdout.buffer))
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)
    
    # Add the handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Log the current logging level
    logger.info(f"Logger initialized with level: {logging.getLevelName(log_level)}")
    
    return logger

# Create and export the logger
logger = setup_logger()

# Helper function to dynamically change log level
def set_log_level(level_name):
    """
    Dynamically change the log level of all handlers.
    
    Args:
        level_name (str): Name of the log level: 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
    """
    level_name = level_name.upper()
    if level_name not in LOG_LEVEL_MAP:
        logger.warning(f"Invalid log level: {level_name}. Using INFO instead.")
        level = logging.INFO
    else:
        level = LOG_LEVEL_MAP[level_name]
    
    # Set root logger level
    logging.getLogger().setLevel(level)
    
    # Set our logger level
    logger.setLevel(level)
    for handler in logger.handlers:
        handler.setLevel(level)
    
    logger.info(f"Log level changed to: {logging.getLevelName(level)}")
    
    return level 