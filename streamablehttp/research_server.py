import arxiv
import json
import os
from typing import List
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from google.cloud import storage

BUCKET_NAME = "research-server-bucket-225547455314"
storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET_NAME)

security = TransportSecuritySettings(enable_dns_rebinding_protection=True,
    allowed_hosts=[
        "localhost",
        "localhost:8000",
        "127.0.0.1",
        "127.0.0.1:8000",
        "0.0.0.0:8000",
        "research-server-run-225547455314.us-central1.run.app"
    ])
PAPER_DIR = "papers"

# Initialize FastMCP server
mcp = FastMCP("research", transport_security=security)

@mcp.tool()
def search_papers(topic: str, max_results: int = 5) -> List[str]:
    """
    Search for papers on arXiv based on a topic and store their information.
    
    Args:
        topic: The topic to search for
        max_results: Maximum number of results to retrieve (default: 5)
        
    Returns:
        List of paper IDs found in the search
    """
    
    # Use arxiv to find the papers 
    client = arxiv.Client()

    # Search for the most relevant articles matching the queried topic
    search = arxiv.Search(
        query = topic,
        max_results = max_results,
        sort_by = arxiv.SortCriterion.Relevance
    )

    papers = client.results(search)
    
    # GCS path: papers/{topic}/papers_info.json
    topic_folder = topic.lower().replace(" ", "_")
    blob_path = f"papers/{topic_folder}/papers_info.json"
    blob = bucket.blob(blob_path)

    # Try to load existing papers info from GCS
    try:
        existing_data = blob.download_as_text()
        papers_info = json.loads(existing_data)
    except Exception:
        papers_info = {}
    
    # Process each paper and add to papers_info  
    paper_ids = []
    for paper in papers:
        paper_ids.append(paper.get_short_id())
        paper_info = {
            'title': paper.title,
            'authors': [author.name for author in paper.authors],
            'summary': paper.summary,
            'pdf_url': paper.pdf_url,
            'published': str(paper.published.date())
        }
        papers_info[paper.get_short_id()] = paper_info
    
    # Save to GCS
    blob.upload_from_string(
        json.dumps(papers_info, indent=2),
        content_type='application/json'
    )

    print(f"Results saved to: gs://{BUCKET_NAME}/{blob_path}")
    
    return paper_ids

@mcp.tool()
def extract_info(paper_id: str) -> str:
    """
    Search for information about a specific paper across all topic directories.
    """
    # List all blobs with papers/ prefix
    blobs = bucket.list_blobs(prefix="papers/")
    
    for blob in blobs:
        # Only check papers_info.json files
        if blob.name.endswith("papers_info.json"):
            try:
                data = blob.download_as_text()
                papers_info = json.loads(data)
                
                if paper_id in papers_info:
                    return json.dumps(papers_info[paper_id], indent=2)
                    
            except Exception as e:
                print(f"Error reading {blob.name}: {str(e)}")
                continue
    
    return f"There's no saved information related to paper {paper_id}."

@mcp.resource("papers://folders")
def get_available_folders() -> str:
    """
    List all available topic folders in the papers directory.
    
    This resource provides a simple list of all available topic folders.
    """
    folders = set()

    # List all blobs with papers/ prefix
    blobs = bucket.list_blobs(prefix="papers/")
    
    for blob in blobs:
        # Extract folder name from path: papers/{topic}/papers_info.json
        parts = blob.name.split("/")
        if len(parts) >= 2 and parts[1]:
            folders.add(parts[1])
    
    # Create markdown list
    content = "# Available Topics\n\n"
    if folders:
        for folder in sorted(folders):
            content += f"- {folder}\n"
        content += f"\nUse @<topic> to access papers in that topic.\n"
    else:
        content += "No topics found.\n"
    
    return content

@mcp.resource("papers://{topic}")
def get_topic_papers(topic: str) -> str:
    """
    Get detailed information about papers on a specific topic.
    
    Args:
        topic: The research topic to retrieve papers for
    """
    topic_dir = topic.lower().replace(" ", "_")
    blob_path = f"papers/{topic_dir}/papers_info.json"
    blob = bucket.blob(blob_path)

    # Check if exists
    if not blob.exists():
        return f"# No papers found for topic: {topic}\n\nTry searching for papers on this topic first."
    

    try:
        data = blob.download_as_text()
        papers_data = json.loads(data)
        
        # Create markdown content
        content = f"# Papers on {topic.replace('_', ' ').title()}\n\n"
        content += f"Total papers: {len(papers_data)}\n\n"
        
        for paper_id, paper_info in papers_data.items():
            content += f"## {paper_info['title']}\n"
            content += f"- **Paper ID**: {paper_id}\n"
            content += f"- **Authors**: {', '.join(paper_info['authors'])}\n"
            content += f"- **Published**: {paper_info['published']}\n"
            content += f"- **PDF URL**: [{paper_info['pdf_url']}]({paper_info['pdf_url']})\n\n"
            content += f"### Summary\n{paper_info['summary'][:500]}...\n\n"
            content += "---\n\n"
        
        return content
        
    except json.JSONDecodeError:
        return f"# Error reading papers data for {topic}\n\nThe papers data file is corrupted."


@mcp.prompt()
def generate_search_prompt(topic: str, num_papers: int = 5) -> str:
    """Generate a prompt for Claude to find and discuss academic papers on a specific topic."""
    return f"""Search for {num_papers} academic papers about '{topic}' using the search_papers tool. 

    Follow these instructions:
    1. First, search for papers using search_papers(topic='{topic}', max_results={num_papers})
    2. For each paper found, extract and organize the following information:
       - Paper title
       - Authors
       - Publication date
       - Brief summary of the key findings
       - Main contributions or innovations
       - Methodologies used
       - Relevance to the topic '{topic}'
    
    3. Provide a comprehensive summary that includes:
       - Overview of the current state of research in '{topic}'
       - Common themes and trends across the papers
       - Key research gaps or areas for future investigation
       - Most impactful or influential papers in this area
    
    4. Organize your findings in a clear, structured format with headings and bullet points for easy readability.
    
    Please present both detailed information about each paper and a high-level synthesis of the research landscape in {topic}."""


# API Key Middleware
class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Skip auth for health checks
        if request.url.path == "/health":
            return await call_next(request)
        
        api_key = request.headers.get("X-API-Key")
        expected_key = os.environ.get("MCP_API_KEY")
        
        if not expected_key:
            # No key configured = allow all (for local dev)
            return await call_next(request)
        
        if api_key != expected_key:
            return Response("Unauthorized", status_code=401)
        
        return await call_next(request)


if __name__ == "__main__":
    # Initialize and run the server
    port = int(os.environ.get("PORT", 8000))
    
    # Get the ASGI app and run with uvicorn
    app = mcp.streamable_http_app()
    # Add API key middleware
    app.add_middleware(APIKeyMiddleware)
    uvicorn.run(app, host='0.0.0.0', port=port)