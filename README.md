# CloudWatch Logs Analyzer Agent

This agent uses Amazon Agent Strands to analyze CloudWatch logs, identify errors, and provide solutions based on either its own knowledge or a connected knowledge base.

## Features

- Fetch CloudWatch logs from specified log groups
- Analyze logs to identify errors and issues
- Provide solutions from built-in knowledge or from a knowledge base
- Option to use or bypass the knowledge base
- Configurable via environment variables
- Available as both CLI and web interface (Streamlit)

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Configure the `.env` file with your AWS credentials and knowledge base ID:
   ```
   # AWS Credentials
   AWS_ACCESS_KEY_ID=your_access_key_id
   AWS_SECRET_ACCESS_KEY=your_secret_access_key
   AWS_REGION=us-west-2

   # Knowledge Base Configuration
   KNOWLEDGE_BASE_ID=your_knowledge_base_id

   # Model Configuration
   MODEL_ID=us.amazon.nova-premier-v1:0
   MAX_TOKENS=32000
   BUDGET_TOKENS=2048
   ```

## Usage

### Command Line Interface

Run the agent in command line mode:
```
./run.sh
```

### Web Interface (Streamlit)

Run the agent with the Streamlit web interface:
```
./run_streamlit.sh
```

Then open your browser at http://localhost:8501


<img width="1511" alt="Screenshot 2025-06-14 at 9 41 39 PM" src="https://github.com/user-attachments/assets/6cf0001a-0a34-4019-9eb2-8ac12735a30c" />


## Web Interface Features

The Streamlit interface provides:

1. **Configuration Panel**:
   - Toggle knowledge base usage
   - Refresh agent button (resets the agent's state and reinitializes it)
   - AWS credentials status

2. **Log Group Selection**:
   - Button to show all available log groups
   - Option to select specific log group or analyze all
   - Dropdown selection for log groups

3. **Analysis Parameters**:
   - Hours to look back (default: 1, up to 168 hours/1 week)
   - Filter pattern input with syntax guidance
   - Analyze button

4. **Results Display**:
   - Formatted analysis results
   - Progress indicator during analysis
   - Error handling and recovery options
