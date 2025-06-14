"""Conversation state management for the CloudWatch Logs Analyzer Agent."""

import logging
import json
from typing import List, Dict, Any, Optional

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ConversationManager:
    """
    Manages conversation state to prevent tool usage and tool results mismatches.
    """
    
    def __init__(self):
        """Initialize the conversation manager."""
        self.reset()
    
    def reset(self):
        """Reset the conversation state."""
        self.tool_calls = []
        self.tool_results = []
        self.conversation_history = []
        logger.info("Conversation state reset")
    
    def track_tool_call(self, tool_name: str, tool_id: str, args: Dict[str, Any]):
        """
        Track a tool call.
        
        Args:
            tool_name: Name of the tool being called
            tool_id: ID of the tool call
            args: Arguments passed to the tool
        """
        self.tool_calls.append({
            "tool_name": tool_name,
            "tool_id": tool_id,
            "args": args
        })
        logger.info(f"Tracked tool call: {tool_name} (ID: {tool_id})")
    
    def track_tool_result(self, tool_id: str, result: Any):
        """
        Track a tool result.
        
        Args:
            tool_id: ID of the tool call
            result: Result of the tool call
        """
        self.tool_results.append({
            "tool_id": tool_id,
            "result": result
        })
        logger.info(f"Tracked tool result for ID: {tool_id}")
    
    def validate_conversation_state(self) -> bool:
        """
        Validate the conversation state to ensure tool calls and results match.
        
        Returns:
            True if the state is valid, False otherwise
        """
        # Check if we have more tool results than tool calls
        if len(self.tool_results) > len(self.tool_calls):
            logger.error(f"Tool results ({len(self.tool_results)}) exceed tool calls ({len(self.tool_calls)})")
            return False
        
        # Check if all tool results have matching tool calls
        tool_call_ids = {call["tool_id"] for call in self.tool_calls}
        tool_result_ids = {result["tool_id"] for result in self.tool_results}
        
        if not tool_result_ids.issubset(tool_call_ids):
            logger.error(f"Found tool results without matching tool calls: {tool_result_ids - tool_call_ids}")
            return False
        
        logger.info("Conversation state validation passed")
        return True
    
    def prepare_safe_message(self, message: str) -> str:
        """
        Prepare a message that's safe to send to the model.
        
        Args:
            message: The original message
            
        Returns:
            A safe message that won't cause tool usage/result mismatches
        """
        # If the message contains tool calls or results, it might be risky
        if "toolUse" in message or "toolResult" in message:
            logger.warning("Message contains tool references, using simplified version")
            # Extract just the text content without tool references
            # This is a simplified approach - in a real system you'd parse the JSON properly
            return "Please help with the following request: " + message.split(":")[-1]
        
        return message
    
    def add_to_history(self, role: str, content: str):
        """
        Add a message to the conversation history.
        
        Args:
            role: The role (user, assistant, system)
            content: The message content
        """
        self.conversation_history.append({
            "role": role,
            "content": content
        })
    
    def get_safe_history(self, max_turns: int = 5) -> List[Dict[str, str]]:
        """
        Get a safe version of the conversation history.
        
        Args:
            max_turns: Maximum number of turns to include
            
        Returns:
            A safe version of the conversation history
        """
        # If the history is too long, truncate it
        if len(self.conversation_history) > max_turns * 2:
            # Keep the first system message if present
            first_message = []
            if self.conversation_history and self.conversation_history[0]["role"] == "system":
                first_message = [self.conversation_history[0]]
            
            # Keep the most recent messages
            recent_messages = self.conversation_history[-(max_turns * 2):]
            
            # Combine them
            safe_history = first_message + recent_messages
        else:
            safe_history = self.conversation_history.copy()
        
        # Ensure there are no tool mismatches
        for i, message in enumerate(safe_history):
            if "toolUse" in str(message.get("content", "")) or "toolResult" in str(message.get("content", "")):
                # Replace with a simplified version
                safe_history[i]["content"] = self.prepare_safe_message(message["content"])
        
        return safe_history

# Global instance
conversation_manager = ConversationManager()
