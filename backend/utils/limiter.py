from slowapi import Limiter
from slowapi.util import get_remote_address
from config import RATE_LIMITS

# Instantiate the SlowAPI limiter.
limiter = Limiter(key_func=get_remote_address)

def get_rate_limit(endpoint: str) -> str:
    """Get the rate limit for a specific endpoint from config."""
    return RATE_LIMITS.get(endpoint, RATE_LIMITS["default"])
