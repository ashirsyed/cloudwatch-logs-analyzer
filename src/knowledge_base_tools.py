"""Knowledge base tools for the agent."""

import boto3
import json
import logging
import os
from typing import List, Dict, Any, Optional
from strands import tool
from config import get_aws_config, get_knowledge_base_id

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class KnowledgeBaseClient:
    """Client for interacting with Amazon Bedrock Knowledge Base."""
    
    def __init__(self, knowledge_base_id: Optional[str] = None):
        """
        Initialize the Knowledge Base client.
        
        Args:
            knowledge_base_id: ID of the knowledge base to use
        """
        aws_config = get_aws_config()
        
        # Ensure AWS credentials are set in environment variables
        os.environ['AWS_ACCESS_KEY_ID'] = aws_config.get('aws_access_key_id', '')
        os.environ['AWS_SECRET_ACCESS_KEY'] = aws_config.get('aws_secret_access_key', '')
        os.environ['AWS_REGION'] = aws_config.get('region_name', 'us-west-2')
        
        logger.info(f"Initializing Knowledge Base client with region: {aws_config.get('region_name')}")
        self.client = boto3.client('bedrock-agent-runtime', **aws_config)
        self.knowledge_base_id = knowledge_base_id or get_knowledge_base_id()
        
        if self.knowledge_base_id:
            logger.info(f"Using Knowledge Base ID: {self.knowledge_base_id}")
        else:
            logger.warning("No Knowledge Base ID provided")
    
    def retrieve(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve information from the knowledge base.
        
        Args:
            query: Query to search for in the knowledge base
            max_results: Maximum number of results to return
            
        Returns:
            List of retrieved results
        """
        if not self.knowledge_base_id:
            logger.warning("No knowledge base ID configured")
            return [{"error": "No knowledge base ID configured"}]
        
        try:
            logger.info(f"Querying knowledge base with: '{query}'")
            
            # Verify AWS credentials before making the API call
            self._verify_aws_credentials()
            
            response = self.client.retrieve(
                knowledgeBaseId=self.knowledge_base_id,
                retrievalQuery={
                    'text': query
                },
                maxResults=max_results
            )
            
            results = []
            for result in response.get('retrievalResults', []):
                content = result.get('content', {})
                results.append({
                    'text': content.get('text', ''),
                    'location': content.get('location', ''),
                    'score': result.get('score', 0)
                })
            
            logger.info(f"Retrieved {len(results)} results from knowledge base")
            return results
        except Exception as e:
            logger.error(f"Error retrieving from knowledge base: {e}")
            return [{"error": str(e)}]
    
    def _verify_aws_credentials(self):
        """Verify that AWS credentials are properly set."""
        # Check environment variables
        access_key = os.environ.get('AWS_ACCESS_KEY_ID')
        secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
        region = os.environ.get('AWS_REGION')
        
        if not access_key or not secret_key:
            logger.warning("AWS credentials not found in environment variables")
            
            # Try to get from boto3 session
            session = boto3.Session()
            credentials = session.get_credentials()
            
            if credentials:
                logger.info("Using AWS credentials from boto3 session")
            else:
                logger.error("No AWS credentials found. Knowledge Base operations will likely fail.")

# Initialize the Knowledge Base client with None (will be set later if needed)
knowledge_base_client = KnowledgeBaseClient()

@tool
def set_knowledge_base(knowledge_base_id: str) -> str:
    """
    Set the knowledge base ID to use.
    
    Args:
        knowledge_base_id: ID of the knowledge base to use
        
    Returns:
        Confirmation message
    """
    global knowledge_base_client
    
    logger.info(f"Setting knowledge base ID to: {knowledge_base_id}")
    knowledge_base_client = KnowledgeBaseClient(knowledge_base_id)
    
    # Ensure AWS credentials are properly set
    from config import get_aws_config
    aws_config = get_aws_config()
    os.environ['AWS_ACCESS_KEY_ID'] = aws_config.get('aws_access_key_id', '')
    os.environ['AWS_SECRET_ACCESS_KEY'] = aws_config.get('aws_secret_access_key', '')
    os.environ['AWS_REGION'] = aws_config.get('region_name', 'us-west-2')
    
    return f"Knowledge base set to {knowledge_base_id}"

@tool
def query_knowledge_base(query: str, max_results: int = 5) -> str:
    """
    Query the knowledge base for information.
    
    Args:
        query: Query to search for in the knowledge base
        max_results: Maximum number of results to return
        
    Returns:
        JSON string containing retrieved results
    """
    # Reinitialize the Knowledge Base client to ensure fresh credentials
    global knowledge_base_client
    kb_id = knowledge_base_client.knowledge_base_id
    knowledge_base_client = KnowledgeBaseClient(kb_id)
    
    results = knowledge_base_client.retrieve(query, max_results)
    return json.dumps(results, indent=2)

@tool
def get_error_solutions_from_kb(error_description: str, max_results: int = 3) -> str:
    """
    Get solutions for an error from the knowledge base.
    
    Args:
        error_description: Description of the error
        max_results: Maximum number of solutions to return
        
    Returns:
        JSON string containing solutions
    """
    # Reinitialize the Knowledge Base client to ensure fresh credentials
    global knowledge_base_client
    kb_id = knowledge_base_client.knowledge_base_id
    knowledge_base_client = KnowledgeBaseClient(kb_id)
    
    query = f"solution for: {error_description}"
    results = knowledge_base_client.retrieve(query, max_results)
    return json.dumps(results, indent=2)
