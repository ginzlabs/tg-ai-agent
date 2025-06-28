from slowapi import Limiter
from slowapi.util import get_remote_address

# Instantiate the SlowAPI limiter.
limiter = Limiter(key_func=get_remote_address)

# Global dictionary to hold dynamic rate limits keyed by endpoint name.
endpoint_rate_limits = {}

def dynamic_rate_limit(endpoint_name: str, default_limit: str):
    """
    Returns a decorator applying a rate limit from the dynamic configuration if available.
    Otherwise, uses the provided default_limit.
    """
    # Look up the dynamic rate limit for this endpoint, defaulting if not set.
    rate_limit_str = endpoint_rate_limits.get(endpoint_name, default_limit)
    return limiter.limit(rate_limit_str)
