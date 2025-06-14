"""Configuration module for the CloudWatch Logs Analyzer Agent."""

import os
from dotenv import load_dotenv
from typing import Optional

# Load environment variables from .env file
load_dotenv()

# AWS Configuration
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-west-2")

# Knowledge Base Configuration
KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID")

# Model Configuration
MODEL_ID = os.getenv("MODEL_ID", "us.amazon.nova-premier-v1:0")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "32000"))
BUDGET_TOKENS = int(os.getenv("BUDGET_TOKENS", "2048"))

# Agent Configuration
AGENT_NAME = os.getenv("AGENT_NAME", "CloudWatchLogsAnalyzer")

# Default look back period for logs in hours
DEFAULT_HOURS_LOOK_BACK = int(os.getenv("DEFAULT_HOURS_LOOK_BACK", "1"))

def get_aws_config():
    """Get AWS configuration from environment variables."""
    return {
        "aws_access_key_id": AWS_ACCESS_KEY_ID,
        "aws_secret_access_key": AWS_SECRET_ACCESS_KEY,
        "region_name": AWS_REGION
    }

def get_model_config():
    """Get model configuration from environment variables."""
    return {
        "model_id": MODEL_ID,
        "max_tokens": MAX_TOKENS
        # Removed additional_request_fields as "thinking" is not supported by Nova Premier
    }

def get_knowledge_base_id() -> Optional[str]:
    """Get knowledge base ID from environment variables."""
    return KNOWLEDGE_BASE_ID

def get_default_hours_look_back() -> int:
    """
    Get the default number of hours to look back for logs.
    
    Returns:
        Default look back period in hours
    """
    return DEFAULT_HOURS_LOOK_BACK
