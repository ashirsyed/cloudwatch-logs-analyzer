"""Custom Bedrock model with retry logic for rate limiting."""

import sys
import json
import logging
import re
from typing import Dict, Any, Iterator, Optional, List
from strands.models.bedrock import BedrockModel
import botocore.exceptions
import time
import random

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RetryBedrockModel:
    """
    A wrapper around BedrockModel that adds retry logic for rate limiting errors.
    """
    
    def __init__(self, **kwargs):
        """Initialize with a standard BedrockModel instance."""
        self.model = BedrockModel(**kwargs)
        self.model_id = kwargs.get('model_id', 'unknown')
        self.conversation_history = []
        self.tool_calls = []
        self.tool_results = []
        logger.info(f"Initialized RetryBedrockModel with model_id: {self.model_id}")
    
    def __getattr__(self, name):
        """Forward all other attribute access to the wrapped model."""
        return getattr(self.model, name)
    
    def reset_conversation(self):
        """Reset the conversation state."""
        self.conversation_history = []
        self.tool_calls = []
        self.tool_results = []
        logger.info("Conversation state reset")
    
    def converse(self, *args, **kwargs):
        """
        Add retry logic to the converse method.
        
        This method accepts any number of arguments and forwards them to the underlying model.
        """
        logger.info(f"Calling converse with retry logic for model {self.model_id}")
        logger.debug(f"converse args: {args}, kwargs: {kwargs}")
        
        # Check if this is being called from Streamlit
        is_streamlit = 'streamlit' in sys.modules
        
        # Check for potential tool mismatch issues
        if args and isinstance(args[0], list) and self._detect_potential_tool_mismatch(args[0]):
            logger.warning("Potential tool mismatch detected, resetting conversation state")
            self.reset_conversation()
            
            # If there are multiple messages, keep only the last user message
            if len(args[0]) > 1:
                for i in range(len(args[0])-1, -1, -1):
                    if args[0][i].get('role') == 'user':
                        new_args = ([args[0][i]],) + args[1:]
                        args = new_args
                        break
        
        # Track this conversation turn
        if args and isinstance(args[0], list):
            for msg in args[0]:
                if msg.get('role') == 'user':
                    self.conversation_history.append({
                        'role': 'user',
                        'content': msg.get('content', '')
                    })
        
        # Get the original response with retries
        response = self._with_retry(self.model.converse, *args, **kwargs)
        
        # For Streamlit, we want to filter out thinking output
        if is_streamlit:
            # Log thinking to terminal only
            logger.info("Model thinking output is being filtered from Streamlit UI")
            
            # If response is a string, try to filter out thinking sections
            if isinstance(response, str):
                response_text = response
                # Check for common thinking patterns and remove them
                if "thinking:" in response_text.lower() or "thinking about" in response_text.lower():
                    logger.info("Detected thinking output in response, filtering for Streamlit")
                    # This will be further processed in the app.py display logic
        
        # Track the assistant's response
        if isinstance(response, str):
            self.conversation_history.append({
                'role': 'assistant',
                'content': response
            })
        
        return response
    
    def stream(self, *args, **kwargs):
        """Add retry logic to the stream method."""
        logger.info(f"Calling stream with retry logic for model {self.model_id}")
        logger.debug(f"stream args: {args}, kwargs: {kwargs}")
        return self._with_retry(self.model.stream, *args, **kwargs)
    
    def _detect_potential_tool_mismatch(self, messages) -> bool:
        """
        Detect potential tool mismatches in the conversation.
        
        Args:
            messages: The messages to check
            
        Returns:
            True if a potential mismatch is detected, False otherwise
        """
        if not isinstance(messages, list):
            return False
        
        tool_use_count = 0
        tool_result_count = 0
        
        for msg in messages:
            content = msg.get('content', '')
            if isinstance(content, str):
                tool_use_count += content.count('toolUse')
                tool_result_count += content.count('toolResult')
        
        # If we have more tool results than tool uses, that's a problem
        if tool_result_count > tool_use_count:
            logger.warning(f"Tool mismatch detected: {tool_result_count} results for {tool_use_count} uses")
            return True
        
        return False
    
    def _with_retry(self, func, *args, **kwargs):
        """Apply retry logic to any function."""
        max_retries = 5
        initial_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except (botocore.exceptions.EventStreamError, botocore.exceptions.ClientError) as e:
                error_message = str(e).lower()
                
                # Check for tool mismatch errors
                is_tool_mismatch = (
                    "toolresult blocks" in error_message or
                    "tooluse blocks" in error_message or
                    "exceeds the number" in error_message
                )
                
                if is_tool_mismatch:
                    if attempt < max_retries - 1:
                        logger.warning(f"Tool mismatch error detected. Resetting conversation and retrying...")
                        
                        # Reset conversation state
                        self.reset_conversation()
                        
                        # Reset the arguments to just the last user message if possible
                        if len(args) > 0 and isinstance(args[0], list) and len(args[0]) > 0:
                            # Find the last user message
                            for i in range(len(args[0])-1, -1, -1):
                                if args[0][i].get('role') == 'user':
                                    # Keep only the last user message to reset context
                                    new_args = ([args[0][i]],) + args[1:]
                                    args = new_args
                                    break
                        
                        delay = initial_delay * (2 ** attempt) + random.random()
                        logger.warning(f"Retrying with simplified context in {delay:.2f} seconds...")
                        time.sleep(delay)
                        continue
                    else:
                        logger.error(f"Tool mismatch error persisted after {max_retries} retries")
                
                # Handle rate limiting errors
                is_rate_limit_error = (
                    "too many requests" in error_message or
                    "throttling" in error_message or
                    "throttled" in error_message or
                    "rate exceeded" in error_message or
                    "serviceUnavailableException" in error_message
                )
                
                if is_rate_limit_error and attempt < max_retries - 1:
                    delay = initial_delay * (2 ** attempt) + random.random()
                    logger.warning(f"Rate limit exceeded. Attempt {attempt + 1}/{max_retries}. "
                                  f"Retrying in {delay:.2f} seconds...")
                    time.sleep(delay)
                    continue
                
                # If we get here, the error is not retriable or we've exhausted retries
                logger.error(f"Error not retriable or max retries reached: {e}")
                raise
        
        # This should never happen, but just in case
        raise RuntimeError("Unexpected error in retry logic")
