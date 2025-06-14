"""Main module for the CloudWatch Logs Analyzer Agent."""

import sys
import json
import logging
import re
from typing import List, Dict, Any, Union
from datetime import datetime, timedelta

from strands import Agent
from strands.models import BedrockModel
from strands_tools import calculator, python_repl

# Import custom tools and models
from cloudwatch_tools import list_cloudwatch_log_groups, get_cloudwatch_logs, analyze_logs_for_errors
from knowledge_base_tools import set_knowledge_base, query_knowledge_base, get_error_solutions_from_kb
from custom_bedrock_model import RetryBedrockModel
from config import get_model_config, get_knowledge_base_id, get_default_hours_look_back

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_agent(use_knowledge_base: bool = True) -> Agent:
    """
    Create and configure the CloudWatch Logs Analyzer Agent.
    
    Args:
        use_knowledge_base: Whether to use the knowledge base
        
    Returns:
        Configured Agent instance
    """
    # Define the tools to use
    tools = [
        # CloudWatch tools
        list_cloudwatch_log_groups,
        get_cloudwatch_logs,
        analyze_logs_for_errors,
        
        # Utility tools
        calculator,
        python_repl
    ]
    
    # Add knowledge base tools if requested
    if use_knowledge_base:
        tools.extend([
            set_knowledge_base,
            query_knowledge_base,
            get_error_solutions_from_kb
        ])
    
    # Configure the model with retry logic
    model_config = get_model_config()
    model = RetryBedrockModel(**model_config)
    logger.info(f"Created RetryBedrockModel with model_id: {model_config.get('model_id')}")
    
    # Create the agent with Nova-specific system prompt
    agent = Agent(
        model=model,
        tools=tools,
        system_prompt=get_system_prompt(use_knowledge_base)
    )
    
    return agent

def get_system_prompt(use_knowledge_base: bool) -> str:
    """
    Get the system prompt for the agent.
    
    Args:
        use_knowledge_base: Whether the knowledge base is being used
        
    Returns:
        System prompt string
    """
    kb_text = ""
    if use_knowledge_base:
        kb_id = get_knowledge_base_id() or "[Not configured]"
        kb_text = f"""
        You have access to a knowledge base (ID: {kb_id}) that contains solutions for common errors.
        Use the knowledge base tools to find solutions when appropriate.
        """
    
    return f"""
    You are CloudWatchLogsAnalyzer, an AI agent specialized in analyzing AWS CloudWatch logs,
    identifying errors and issues, and providing solutions.
    
    Your capabilities:
    1. Fetch CloudWatch logs from specified log groups
    2. Analyze logs to identify errors, exceptions, and issues
    3. Categorize and prioritize issues by severity
    4. Provide detailed explanations of identified problems
    5. Recommend solutions based on best practices and/or knowledge base
    {kb_text}
    
    When analyzing logs:
    - Look for error messages, exceptions, timeouts, and other indicators of problems
    - Identify patterns across multiple log entries
    - Consider the timestamp and sequence of events
    - Focus on the most severe and recent issues first
    
    When providing solutions:
    - Be specific and actionable
    - Include code examples when appropriate
    - Reference AWS documentation or knowledge base articles
    - Consider the AWS service context
    
    Your responses should be structured, clear, and focused on helping the user
    understand and resolve the issues in their CloudWatch logs.
    """

def extract_log_groups(response) -> List[str]:
    """
    Extract log group names from the agent's response.
    
    Args:
        response: The agent's response containing log group names (string or AgentResult)
        
    Returns:
        List of log group names
    """
    log_groups = []
    
    # Convert response to string if it's not already
    response_text = str(response)
    
    # Look for lines that start with a dash or bullet point
    for line in response_text.split('\n'):
        line = line.strip()
        if line.startswith('-') or line.startswith('*'):
            # Extract the log group name (remove the dash/bullet and trim)
            log_group = line[1:].strip()
            # If there are any quotes around the name, remove them
            log_group = re.sub(r'^[\'"`]|[\'"`]$', '', log_group)
            log_groups.append(log_group)
    
    return log_groups

def interactive_mode():
    """Run the agent in interactive mode."""
    print("=== CloudWatch Logs Analyzer Agent ===")
    print("This agent will help you analyze CloudWatch logs and find solutions for errors.")
    
    try:
        # Ask if the user wants to use the knowledge base
        use_kb = input("Do you want to use the knowledge base for solutions? (y/n): ").lower() == 'y'
        
        # Create the agent
        logger.info("Creating agent...")
        agent = create_agent(use_knowledge_base=use_kb)
        
        # Set knowledge base if using it
        if use_kb:
            kb_id = get_knowledge_base_id()
            if kb_id:
                logger.info(f"Setting knowledge base ID to {kb_id}")
                try:
                    agent(f"Set the knowledge base ID to {kb_id}")
                    print(f"Knowledge base set to {kb_id}")
                except Exception as e:
                    logger.error(f"Error setting knowledge base ID: {e}")
                    print(f"Error setting knowledge base ID: {e}")
                    print("Continuing without knowledge base...")
                    use_kb = False
            else:
                print("No knowledge base ID configured in .env file.")
                kb_id = input("Please enter a knowledge base ID (or leave empty to continue without): ")
                if kb_id:
                    logger.info(f"Setting knowledge base ID to {kb_id}")
                    try:
                        agent(f"Set the knowledge base ID to {kb_id}")
                        print(f"Knowledge base set to {kb_id}")
                    except Exception as e:
                        logger.error(f"Error setting knowledge base ID: {e}")
                        print(f"Error setting knowledge base ID: {e}")
                        print("Continuing without knowledge base...")
                        use_kb = False
        
        # Fetch available log groups
        print("\nFetching available log groups...")
        log_groups = []
        try:
            logger.info("Listing CloudWatch log groups")
            
            # Get log groups but don't print the full response
            response = agent("List all available CloudWatch log groups and return only the names without additional text")
            
            # Extract log group names
            log_groups = extract_log_groups(response)
            
            # Print the log groups in a clean format -- duplication
            #print("\nAvailable CloudWatch log groups:")
            #for log_group in log_groups:
            #    print(f"- {log_group}")
            
            # Now ask if the user wants to analyze a specific log group or all of them
            log_group = input("\nEnter the log group name to analyze (or 'ALL' to analyze all groups): ")
        except Exception as e:
            logger.error(f"Error listing log groups: {e}")
            print(f"Error listing log groups: {e}")
            log_group = input("\nEnter the log group name to analyze: ")
        
        # Check if user wants to analyze all log groups
        analyze_all = log_group.upper() == "ALL"
        
        hours = input("How many hours of logs to analyze (default: 1): ")
        hours = int(hours) if hours.isdigit() else get_default_hours_look_back()
        
        filter_pattern = input("Enter filter pattern (e.g., 'ERROR', 'Exception') or leave empty: ")
        
        # Get and analyze logs
        if analyze_all:
            print("\nAnalyzing all log groups... This may take a while.")
            logger.info(f"Analyzing all log groups for the past {hours} hours")
            
            # If we have the log groups list, use it directly instead of asking the agent to list them again
            if log_groups:
                log_groups_str = ", ".join([f"'{lg}'" for lg in log_groups])
                prompt = f"""
                Analyze the following CloudWatch log groups: {log_groups_str}
                
                For each log group, get logs for the past {hours} hours
                {f"with filter pattern '{filter_pattern}'" if filter_pattern else ""}.
                
                Analyze these logs to identify errors and issues.
                
                For each identified issue:
                1. Provide a clear description of the problem
                2. Assess the severity (Critical, High, Medium, Low)
                3. Recommend solutions to fix the issue
                {"4. Reference relevant knowledge base articles if available" if use_kb else ""}
                
                Group your findings by log group and organize your response in a clear, structured format.
                If a log group has no issues, simply note that it's healthy.
                """
            else:
                prompt = f"""
                First, list all available CloudWatch log groups.
                
                Then, for each log group, get logs for the past {hours} hours
                {f"with filter pattern '{filter_pattern}'" if filter_pattern else ""}.
                
                Analyze these logs to identify errors and issues.
                
                For each identified issue:
                1. Provide a clear description of the problem
                2. Assess the severity (Critical, High, Medium, Low)
                3. Recommend solutions to fix the issue
                {"4. Reference relevant knowledge base articles if available" if use_kb else ""}
                
                Group your findings by log group and organize your response in a clear, structured format.
                If a log group has no issues, simply note that it's healthy.
                """
        else:
            print(f"\nAnalyzing logs from {log_group}... This may take a moment.")
            logger.info(f"Analyzing logs from {log_group} for the past {hours} hours")
            
            prompt = f"""
            Get logs from the CloudWatch log group '{log_group}' for the past {hours} hours
            {f"with filter pattern '{filter_pattern}'" if filter_pattern else ""}.
            
            Then analyze these logs to identify errors and issues.
            
            For each identified issue:
            1. Provide a clear description of the problem
            2. Assess the severity (Critical, High, Medium, Low)
            3. Recommend solutions to fix the issue
            {"4. Reference relevant knowledge base articles if available" if use_kb else ""}
            
            Organize your response in a clear, structured format.
            """
        
        try:
            response = agent(prompt)
            print("\n=== Analysis Results ===")
            print(response)
        except Exception as e:
            logger.error(f"Error analyzing logs: {e}")
            print(f"Error analyzing logs: {e}")
            print("Please try again later or with different parameters.")
    
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"An unexpected error occurred: {e}")
        print("Please check the logs for more details.")

if __name__ == "__main__":
    interactive_mode()
