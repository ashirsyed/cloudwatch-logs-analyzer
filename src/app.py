"""Streamlit frontend for the CloudWatch Logs Analyzer Agent."""

import streamlit as st
import logging
import re
import sys
import os
from typing import List, Dict, Any, Optional
import time
from datetime import datetime, timedelta

# Import agent components
from strands import Agent
from custom_bedrock_model import RetryBedrockModel
from cloudwatch_tools import list_cloudwatch_log_groups, get_cloudwatch_logs, analyze_logs_for_errors
from knowledge_base_tools import set_knowledge_base, query_knowledge_base, get_error_solutions_from_kb
from config import get_model_config, get_knowledge_base_id, get_default_hours_look_back

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize session state variables if they don't exist
if 'agent' not in st.session_state:
    st.session_state.agent = None
if 'log_groups' not in st.session_state:
    st.session_state.log_groups = []
if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = None
if 'use_kb' not in st.session_state:
    st.session_state.use_kb = False
if 'is_analyzing' not in st.session_state:
    st.session_state.is_analyzing = False

def filter_thinking_output(text: str) -> str:
    """
    Filter out thinking output from the model's response.
    
    Args:
        text: The text to filter
        
    Returns:
        Filtered text without thinking sections
    """
    # If no thinking indicators are present, return the original text
    if not any(indicator in text.lower() for indicator in ["thinking:", "thinking about", "<thinking>", "[thinking]"]):
        return text
    
    # Try to extract just the final answer after thinking
    thinking_patterns = [
        r'(?i).*?thinking:.*?\n\n(.*)',
        r'(?i).*?thinking about.*?\n\n(.*)',
        r'(?i).*?<thinking>.*?</thinking>(.*)',
        r'(?i).*?\[thinking\].*?\[/thinking\](.*)',
        r'(?i).*?I\'ll think through.*?\n\n(.*)',
        r'(?i).*?Let me analyze.*?\n\n(.*)',
        r'(?i).*?Let\'s analyze.*?\n\n(.*)'
    ]
    
    for pattern in thinking_patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            filtered_text = match.group(1).strip()
            logger.info("Filtered thinking output from response")
            return filtered_text
    
    # If no pattern matched but thinking indicators were found,
    # try a more aggressive approach - find the last paragraph
    if "\n\n" in text:
        paragraphs = text.split("\n\n")
        # Return the last non-empty paragraph
        for p in reversed(paragraphs):
            if p.strip():
                return p.strip()
    
    # If all else fails, return the original text
    return text

def create_agent(use_knowledge_base: bool = True) -> Agent:
    """
    Create and configure the CloudWatch Logs Analyzer Agent.
    
    Args:
        use_knowledge_base: Whether to use the knowledge base
        
    Returns:
        Configured Agent instance
    """
    # Ensure AWS credentials are properly set
    from config import get_aws_config
    import os
    
    aws_config = get_aws_config()
    os.environ['AWS_ACCESS_KEY_ID'] = aws_config.get('aws_access_key_id', '')
    os.environ['AWS_SECRET_ACCESS_KEY'] = aws_config.get('aws_secret_access_key', '')
    os.environ['AWS_REGION'] = aws_config.get('region_name', 'us-west-2')
    
    logger.info(f"Setting AWS environment variables with region: {aws_config.get('region_name')}")
    
    # Force reinitialization of CloudWatch client
    import importlib
    import cloudwatch_tools
    importlib.reload(cloudwatch_tools)
    
    # Define the tools to use
    tools = [
        # CloudWatch tools
        list_cloudwatch_log_groups,
        get_cloudwatch_logs,
        analyze_logs_for_errors,
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
    
    # Create the agent with system prompt
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
    
    IMPORTANT: Do not include your thinking process in your responses. Only provide the final analysis and recommendations.
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

def fetch_log_groups():
    """Fetch and display available CloudWatch log groups."""
    with st.spinner("Fetching available log groups..."):
        try:
            # Reset the agent's conversation state before making a new request
            if hasattr(st.session_state.agent.model, 'reset_conversation'):
                st.session_state.agent.model.reset_conversation()
                logger.info("Reset conversation state before fetching log groups")
            
            # Get log groups
            response = st.session_state.agent("List all available CloudWatch log groups and return only the names without additional text")
            
            # Extract log group names
            st.session_state.log_groups = extract_log_groups(response)
            
            if not st.session_state.log_groups:
                st.warning("No log groups found. Make sure your AWS credentials have the necessary permissions.")
        except Exception as e:
            logger.error(f"Error listing log groups: {e}")
            st.error(f"Error listing log groups: {e}")
            
            # If there's an error, try to recover by resetting the agent
            try:
                logger.info("Attempting to recover by resetting the agent")
                use_kb = st.session_state.use_kb
                st.session_state.agent = create_agent(use_knowledge_base=use_kb)
                st.warning("Agent has been reset due to an error. Please try again.")
            except Exception as reset_error:
                logger.error(f"Error resetting agent: {reset_error}")
                st.error("Failed to reset agent. Please refresh the page and try again.")

def analyze_logs(log_group: str, hours: int, filter_pattern: str, use_kb: bool):
    """
    Analyze logs from the specified log group.
    
    Args:
        log_group: The log group to analyze, or "ALL" for all log groups
        hours: Number of hours to look back
        filter_pattern: Filter pattern for logs
        use_kb: Whether to use the knowledge base
    """
    # Validate log group name
    if not log_group or (log_group != "ALL" and log_group.strip() == ""):
        st.error("Please enter a valid log group name or select 'ALL' to analyze all log groups.")
        return
        
    st.session_state.is_analyzing = True
    
    try:
        analyze_all = log_group.upper() == "ALL"
        
        # Reset the agent's conversation state before making a new request
        if hasattr(st.session_state.agent.model, 'reset_conversation'):
            st.session_state.agent.model.reset_conversation()
            logger.info("Reset conversation state before analyzing logs")
        
        # Test CloudWatch access explicitly before proceeding
        if not analyze_all:
            with st.spinner("Testing CloudWatch access..."):
                from cloudwatch_tools import cloudwatch_client
                from datetime import datetime, timedelta
                
                logger.info(f"Testing CloudWatch access for {log_group}")
                try:
                    # Force reinitialization of CloudWatch client
                    import importlib
                    import cloudwatch_tools
                    importlib.reload(cloudwatch_tools)
                    from cloudwatch_tools import cloudwatch_client
                    
                    # Test with a wider time range to ensure we find logs if they exist
                    test_logs = cloudwatch_client.get_logs(
                        log_group_name=log_group,
                        start_time=datetime.now() - timedelta(hours=max(hours, 24)),  # Use at least 24 hours
                        end_time=datetime.now(),
                        limit=10
                    )
                    if not test_logs:
                        logger.info(f"No logs found in {log_group} for the past {max(hours, 24)} hours")
                        st.info(f"Note: No logs found in {log_group} for the past {max(hours, 24)} hours. Analysis will continue but may not find any issues.")
                except Exception as e:
                    logger.error(f"Test fetch failed: {e}")
                    st.error(f"Error accessing CloudWatch logs: {e}")
                    st.session_state.is_analyzing = False
                    return
        
        with st.spinner(f"Analyzing {'all log groups' if analyze_all else f'logs from {log_group}'}... This may take a while."):
            if analyze_all:
                # If we have the log groups list, use it directly
                if st.session_state.log_groups:
                    log_groups_str = ", ".join([f"'{lg}'" for lg in st.session_state.log_groups])
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
                    
                    IMPORTANT INSTRUCTIONS:
                    - If no logs are found for a log group in the specified time period, report that the log group is INACTIVE or has no recent activity. Do NOT report this as an issue or error.
                    - Only report actual errors or issues found in the logs.
                    - If there are no errors in the logs, report that the log group is healthy.
                    - Do not suggest possible reasons for empty logs unless specifically asked.
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
                    
                    IMPORTANT INSTRUCTIONS:
                    - If no logs are found for a log group in the specified time period, report that the log group is INACTIVE or has no recent activity. Do NOT report this as an issue or error.
                    - Only report actual errors or issues found in the logs.
                    - If there are no errors in the logs, report that the log group is healthy.
                    - Do not suggest possible reasons for empty logs unless specifically asked.
                    """
            else:
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
                
                IMPORTANT INSTRUCTIONS:
                - If no logs are found for the specified time period, report that the log group is INACTIVE or has no recent activity. Do NOT report this as an issue or error.
                - Only report actual errors or issues found in the logs.
                - If there are no errors in the logs, report that the log group is healthy.
                - Do not suggest possible reasons for empty logs unless specifically asked.
                - Try to find logs even if they're outside the specified time range, but mention when logs are from a different time period.
                """
            
            # Add instruction to not include thinking
            prompt += "\n\nIMPORTANT: Do not include your thinking process in your response. Only provide the final analysis and recommendations."
            
            # Add instruction about inactive log groups
            prompt += "\n\nREMEMBER: Log groups with no logs in the specified time period should be marked as INACTIVE, not as having issues."
            
            # Run the analysis
            try:
                # Use a simplified prompt first to avoid tool call complexity
                simplified_prompt = f"""
                I need to analyze CloudWatch logs {f"for log group '{log_group}'" if log_group != "ALL" else "for all available log groups"}.
                Please help me with this task.
                """
                
                # Make a simple request first to establish a clean conversation state
                st.session_state.agent(simplified_prompt)
                
                # Now reset the conversation and make the actual request
                if hasattr(st.session_state.agent.model, 'reset_conversation'):
                    st.session_state.agent.model.reset_conversation()
                
                # Now send the detailed prompt
                response = st.session_state.agent(prompt)
                
                # Filter out thinking output and store the result
                if isinstance(response, str):
                    filtered_response = filter_thinking_output(response)
                    st.session_state.analysis_results = filtered_response
                else:
                    # If response is an object with attributes, convert to string and filter
                    filtered_response = filter_thinking_output(str(response))
                    st.session_state.analysis_results = filtered_response
            except Exception as e:
                logger.error(f"Error during analysis: {e}")
                error_message = str(e)
                
                # Check for tool ID mismatch error
                if "toolresult blocks" in error_message.lower() or "tooluse blocks" in error_message.lower():
                    logger.warning("Tool mismatch detected. Resetting agent and retrying with simplified prompt...")
                    
                    # Reset the agent completely
                    use_kb = st.session_state.use_kb
                    st.session_state.agent = create_agent(use_knowledge_base=use_kb)
                    
                    # Simplify the prompt significantly
                    simplified_prompt = f"""
                    Analyze logs from CloudWatch {f"for log group '{log_group}'" if log_group != "ALL" else "for all available log groups"}.
                    Look for errors and issues in the past {hours} hours.
                    {f"Use filter pattern: '{filter_pattern}'" if filter_pattern else ""}
                    
                    Provide a clear, structured analysis of any issues found.
                    """
                    
                    try:
                        # Try again with simplified prompt
                        response = st.session_state.agent(simplified_prompt)
                        
                        # Filter and store result
                        if isinstance(response, str):
                            filtered_response = filter_thinking_output(response)
                            st.session_state.analysis_results = filtered_response
                        else:
                            filtered_response = filter_thinking_output(str(response))
                            st.session_state.analysis_results = filtered_response
                    except Exception as retry_error:
                        logger.error(f"Error during retry: {retry_error}")
                        st.error("Analysis failed. Please try again with a simpler query or refresh the agent.")
                        st.session_state.analysis_results = None
                else:
                    st.error(f"Error analyzing logs: {e}")
                    st.session_state.analysis_results = None
    except Exception as e:
        logger.error(f"Error analyzing logs: {e}")
        st.error(f"Error analyzing logs: {e}")
    finally:
        st.session_state.is_analyzing = False

def main():
    """Main function for the Streamlit app."""
    st.set_page_config(
        page_title="CloudWatch Logs Analyzer",
        page_icon="📊",
        layout="wide"
    )
    
    st.title("📊 CloudWatch Logs Analyzer")
    st.markdown("""
    This tool helps you analyze AWS CloudWatch logs, identify errors and issues, and provide solutions.
    """)
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("Configuration")
        
        # Knowledge Base Configuration
        st.subheader("Knowledge Base")
        use_kb = st.checkbox("Use Knowledge Base", value=st.session_state.use_kb)
        
        # Hide the knowledge base ID input - use the one from environment variables
        if use_kb:
            kb_id = get_knowledge_base_id()
            if not kb_id:
                st.warning("No Knowledge Base ID configured in environment. Knowledge base features may not work properly.")
        
        # Initialize or reinitialize agent if needed
        if (use_kb != st.session_state.use_kb) or (st.session_state.agent is None):
            st.session_state.use_kb = use_kb
            with st.spinner("Initializing agent..."):
                # Force AWS credential refresh before creating agent
                from config import get_aws_config
                import os
                
                aws_config = get_aws_config()
                os.environ['AWS_ACCESS_KEY_ID'] = aws_config.get('aws_access_key_id', '')
                os.environ['AWS_SECRET_ACCESS_KEY'] = aws_config.get('aws_secret_access_key', '')
                os.environ['AWS_REGION'] = aws_config.get('region_name', 'us-west-2')
                
                # Force reinitialization of CloudWatch client
                import importlib
                import cloudwatch_tools
                importlib.reload(cloudwatch_tools)
                
                # Create the agent
                st.session_state.agent = create_agent(use_knowledge_base=use_kb)
                
                # Set knowledge base if using it
                if use_kb:
                    kb_id = get_knowledge_base_id()
                    if kb_id:
                        try:
                            # Use a simple prompt to set the knowledge base
                            simple_kb_prompt = f"Please set the knowledge base ID to {kb_id}"
                            st.session_state.agent(simple_kb_prompt)
                            st.success(f"Knowledge base connected successfully")
                        except Exception as e:
                            logger.error(f"Error setting knowledge base ID: {e}")
                            st.error(f"Error connecting to knowledge base: {e}")
                            
                            # Try an alternative approach
                            try:
                                logger.info("Trying alternative approach to set knowledge base")
                                # Direct tool call to set knowledge base
                                from knowledge_base_tools import set_knowledge_base
                                set_knowledge_base(kb_id)
                                st.success("Knowledge base connected using alternative method!")
                            except Exception as alt_e:
                                logger.error(f"Alternative knowledge base connection also failed: {alt_e}")
                                st.error("Could not connect to knowledge base. Continuing without knowledge base...")
                                st.session_state.use_kb = False
                            
                # Verify AWS credentials are working
                if use_kb:
                    try:
                        from cloudwatch_tools import cloudwatch_client
                        cloudwatch_client.list_log_groups()
                        logger.info("Successfully verified AWS credentials after knowledge base initialization")
                    except Exception as e:
                        logger.error(f"AWS credential verification failed after knowledge base initialization: {e}")
                        st.error("AWS credentials issue detected. Please click 'Refresh Agent' to resolve.")
                        
                # Force another reload of CloudWatch tools to ensure credentials are set
                importlib.reload(cloudwatch_tools)
        
        # Refresh button
        if st.button("Refresh Agent"):
            # Complete reset of the agent and all state
            st.session_state.agent = None
            st.session_state.log_groups = []
            st.session_state.analysis_results = None
            
            # Force reload of all modules to ensure clean state
            import importlib
            import cloudwatch_tools
            importlib.reload(cloudwatch_tools)
            
            # Create a fresh agent
            st.session_state.agent = create_agent(use_knowledge_base=use_kb)
            
            # Set knowledge base if using it
            if use_kb:
                kb_id = get_knowledge_base_id()
                if kb_id:
                    try:
                        # Use a simple prompt to set the knowledge base to avoid tool call issues
                        simple_kb_prompt = f"Please set the knowledge base ID to {kb_id}"
                        st.session_state.agent(simple_kb_prompt)
                        st.success("Agent refreshed and knowledge base connected successfully!")
                    except Exception as e:
                        logger.error(f"Error setting knowledge base ID after refresh: {e}")
                        st.error(f"Agent refreshed but knowledge base connection failed: {e}")
                        # Try an alternative approach
                        try:
                            logger.info("Trying alternative approach to set knowledge base")
                            # Direct tool call to set knowledge base
                            from knowledge_base_tools import set_knowledge_base
                            set_knowledge_base(kb_id)
                            st.success("Knowledge base connected using alternative method!")
                        except Exception as alt_e:
                            logger.error(f"Alternative knowledge base connection also failed: {alt_e}")
                            st.error("Could not connect to knowledge base. Try using the agent without knowledge base.")
                else:
                    st.success("Agent refreshed successfully!")
            else:
                st.success("Agent refreshed successfully!")
    
    # Main content area
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.header("Log Group Selection")
        
        # Button to fetch log groups
        if st.button("Show All Log Groups"):
            fetch_log_groups()
        
        # Display log groups if available
        if st.session_state.log_groups:
            st.subheader("Available Log Groups:")
            for log_group in st.session_state.log_groups:
                st.write(f"- {log_group}")
        
        # Log group selection
        log_group_selection = st.radio(
            "Select log group option:",
            ["Specific Log Group", "All Log Groups"]
        )
        
        if log_group_selection == "Specific Log Group":
            if st.session_state.log_groups:
                log_group = st.selectbox(
                    "Select a log group:",
                    options=st.session_state.log_groups
                )
            else:
                log_group = st.text_input("Enter log group name:")
                if not log_group.strip():
                    st.warning("Please enter a log group name or click 'Show All Log Groups' first.")
        else:
            log_group = "ALL"
        
        # Analysis parameters
        st.subheader("Analysis Parameters")
        
        hours = st.number_input(
            "Hours to look back:",
            min_value=1,
            max_value=168,  # 1 week
            value=get_default_hours_look_back(),
            step=1
        )
        
        filter_pattern = st.text_input(
            "Filter pattern (e.g., 'ERROR', 'Exception'):",
            placeholder="Leave empty for no filter"
        )
        
        # Help text for filter patterns
        st.info("""
        **Filter Pattern Tips:**
        - For single terms: `ERROR` or `Exception`
        - For multiple terms: `ERROR OR Exception`
        - For exact phrases: `"failed to connect"`
        - Avoid using commas to separate terms
        """)
        
        # Analyze button
        analyze_button_disabled = st.session_state.is_analyzing or (
            log_group_selection == "Specific Log Group" and 
            not st.session_state.log_groups and 
            (not 'log_group' in locals() or not log_group.strip())
        )
        
        if st.button("Analyze Logs", type="primary", disabled=analyze_button_disabled):
            analyze_logs(log_group, hours, filter_pattern, use_kb)
    
    with col2:
        st.header("Analysis Results")
        
        if st.session_state.is_analyzing:
            st.info("Analysis in progress... Please wait.")
            
            # Add a progress placeholder
            progress_placeholder = st.empty()
            progress_bar = progress_placeholder.progress(0)
            
            # Simulate progress while waiting for results
            for i in range(100):
                time.sleep(0.1)
                progress_bar.progress(i + 1)
            
            progress_placeholder.empty()
        
        if st.session_state.analysis_results:
            # The thinking output should already be filtered at this point,
            # but we'll do one more check just to be sure
            result_text = str(st.session_state.analysis_results)
            if "thinking:" in result_text.lower() or "thinking about" in result_text.lower():
                logger.info("Found thinking output in results display - applying additional filtering")
                result_text = filter_thinking_output(result_text)
            
            st.markdown(result_text)
        else:
            st.info("No analysis results yet. Click 'Analyze Logs' to start.")

if __name__ == "__main__":
    main()
