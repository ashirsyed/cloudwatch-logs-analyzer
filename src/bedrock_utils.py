"""Utility functions for handling Amazon Bedrock API calls."""

import time
import random
import logging
import functools
import botocore.exceptions

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def retry_with_exponential_backoff(
    max_retries: int = 5,
    initial_delay: float = 1.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retry_on_exceptions: tuple = (
        botocore.exceptions.EventStreamError,
        botocore.exceptions.ClientError
    )
):
    """
    Decorator that retries a function with exponential backoff when specific exceptions occur.
    
    Args:
        max_retries: Maximum number of retries
        initial_delay: Initial delay in seconds
        exponential_base: Base for the exponential backoff
        jitter: Whether to add random jitter to the delay
        retry_on_exceptions: Tuple of exceptions that trigger a retry
        
    Returns:
        Decorator function
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except retry_on_exceptions as e:
                    last_exception = e
                    
                    # Check if it's a rate limiting error
                    error_message = str(e).lower()
                    is_rate_limit_error = (
                        "too many requests" in error_message or
                        "throttling" in error_message or
                        "throttled" in error_message or
                        "rate exceeded" in error_message or
                        "serviceUnavailableException" in error_message
                    )
                    
                    # Only retry on rate limiting errors
                    if not is_rate_limit_error or attempt == max_retries - 1:
                        logger.error(f"Error not retriable or max retries reached: {e}")
                        raise
                    
                    # Calculate delay with exponential backoff
                    delay = initial_delay * (exponential_base ** attempt)
                    
                    # Add jitter if enabled
                    if jitter:
                        delay += random.random()
                    
                    logger.warning(
                        f"Rate limit exceeded. Attempt {attempt + 1}/{max_retries}. "
                        f"Retrying in {delay:.2f} seconds..."
                    )
                    
                    time.sleep(delay)
            
            # If we get here, we've exhausted all retries
            if last_exception:
                raise last_exception
            
            # This should never happen, but just in case
            raise RuntimeError("Unexpected error in retry logic")
        
        return wrapper
    
    return decorator
