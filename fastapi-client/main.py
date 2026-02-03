import os
from fastapi import FastAPI, HTTPException, Query, Request, Security, Depends
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from mcp_client import MCPClient
from dotenv import load_dotenv
from typing import Optional
from contextlib import asynccontextmanager
from anthropic import Anthropic
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend 
from fastapi_cache.decorator import cache
import conversation_store
import context_manager
import asyncio

load_dotenv()

# Define API Key security scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# MCP Server config
MCP_URL = os.environ.get("MCP_SERVER_URL")
MCP_API_KEY = os.environ.get("MCP_API_KEY")

# Create limiter
limiter = Limiter(key_func=get_remote_address)

# Initialize Anthropic client
anthropic = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Global MCP client
mcp_client = None

class ChatRequest(BaseModel):
    query: str = Field(
        ..., 
        min_length=1, 
        max_length=1000,
        description="User query"
    )
    session_id: str = None  # Optional session ID for conversation tracking

class ChatResponse(BaseModel):
    response: str
    tools_used: list = []

# Timeout helper
async def with_timeout(coro, seconds: int):
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Request timeout")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Connect to MCP server on startup, disconnect on shutdown."""
    global mcp_client
    mcp_client = MCPClient(url = MCP_URL, api_key = MCP_API_KEY)
    await mcp_client.connect()
    print("Connected to MCP server")
    FastAPICache.init(InMemoryBackend())
    print("Cache initialized")
    yield
    await mcp_client.disconnect()
    print("Disconnected from MCP server")
    


# API Key Middleware
class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):        
        # Skip auth for health check and root
        if request.url.path in ["/", "/health", "/docs", "/openapi.json"]:
            print("Skipping auth")
            return await call_next(request)
        
        api_key = request.headers.get("X-API-Key")
        expected_key = os.environ.get("FASTAPI_API_KEY")
        
        # No key configured = allow all (local dev)
        if not expected_key:
            print("No expected key set")
            return await call_next(request)
        
        if api_key != expected_key:
            print("Keys don't match - blocking")
            return Response("Unauthorized", status_code=401)
        
        print("Authorized")
        return await call_next(request)


app = FastAPI(
    title="Research API",
    description="API for searching academic papers",
    lifespan=lifespan
)

# Add middleware
app.add_middleware(APIKeyMiddleware)

# Add rate limit error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Request/Response models
class SearchRequest(BaseModel):
    topic: str = Field(
        ..., 
        min_length=1, 
        max_length=100,
        description="Topic to search for"
    )
    max_results: int = Field(
        default=5, 
        ge=1, 
        le=20,
        description="Number of results (1-20)"
    )

class SearchResponse(BaseModel):
    paper_ids: list
    message: str

class PaperResponse(BaseModel):
    paper_id: str
    info: dict


@app.get("/")
async def root():
    return {
        "message": "Research API",
        "endpoints": {
            "/search": "POST - Search for papers",
            "/paper/{paper_id}": "GET - Get paper info",
            "/health": "GET - Health check"
        }
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/search", response_model=SearchResponse)
@limiter.limit("10/minute") # expensive, creates data in GCS
async def search_papers(request: Request,search_request: SearchRequest, api_key: str = Depends(api_key_header)):
    """Search for academic papers on a topic."""
    try:
        result = await with_timeout(mcp_client.call_tool(
            "search_papers",
            {"topic": search_request.topic, "max_results": search_request.max_results}
        ), 10)
        return SearchResponse(
            paper_ids=result,
            message=f"Found papers on '{search_request.topic}'"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/paper/{paper_id}", response_model=PaperResponse)
@limiter.limit("30/minute") # Read only cheap
async def get_paper(request: Request, paper_id: str, api_key: str = Depends(api_key_header)):
    """Get information about a specific paper."""
    try:
        result = await with_timeout(mcp_client.call_tool(
            "extract_info",
            {"paper_id": paper_id}
        ), 10)
        # Handle "not found" string response
        if isinstance(result, str):
            raise HTTPException(status_code=404, detail=result)
        
        return {"paper_id": paper_id, "info": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/folders")
@cache(expire=300)  # 5 minutes cached
@limiter.limit("30/minute")
async def get_folders(request: Request, api_key: str = Depends(api_key_header)):
    """List all available topic folders."""
    try:
        result = await with_timeout(mcp_client.read_resource("papers://folders"), 10)
        return {"content": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/topics/{topic}")
@cache(expire=300)  # 5 minutes cached
@limiter.limit("30/minute")
async def get_topic_papers(request: Request, topic: str, api_key: str = Depends(api_key_header)):
    """Get papers for a specific topic."""
    try:
        result = await with_timeout(mcp_client.read_resource(f"papers://{topic}"), 10)
        return {"content": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/prompts/{prompt_name}")
@limiter.limit("20/minute")
async def get_prompt(
    request: Request,
    prompt_name: str,
    topic: str,
    num_papers: int = 5,
    api_key: str = Depends(api_key_header)
):
    """Get a generated prompt by name."""
    try:
        result = await with_timeout(mcp_client.get_prompt(
            prompt_name,
            {"topic": topic, "num_papers": str(num_papers)}
        ), 10)
        return {"prompt": result}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

        
@app.get("/prompts")
@cache(expire=600)  # 10 minutes cached
@limiter.limit("30/minute")
async def list_prompts(request: Request, api_key: str = Depends(api_key_header)):
    """List all available prompts."""
    try:
        prompts = await with_timeout(mcp_client.list_prompts(), 10)
        return {"prompts": prompts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/tools")
@cache(expire=600)  # 10 minutes cached
@limiter.limit("30/minute")
async def list_tools(request: Request, api_key: str = Depends(api_key_header)):
    """List all available tools."""
    try:
        tools = await with_timeout(mcp_client.list_tools(), 10)
        return {"tools": tools}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def process_chat(chat_request: ChatRequest, session_id: Optional[str] = None) -> ChatResponse:
    # Move your entire while True loop here
    try:
        # Get available tools from MCP server
        tools = await mcp_client.list_tools()
        
        # Format tools for Anthropic API
        anthropic_tools = [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["input_schema"]
            }
            for tool in tools
        ]

        # Get history if session exists
        if chat_request.session_id:
            session = conversation_store.get_session(chat_request.session_id)
            messages = session['messages']
            summary = session['summary']
        

            if context_manager.count_messages(messages) > 20:
                old_messages = messages[:-10]
                recent_messages = messages[-10:]
                summary = await context_manager.summarize_messages(old_messages)
                conversation_store.update_summary(chat_request.session_id, summary, len(old_messages))
            else:
                recent_messages = messages
            
            # # Build context with summary + recent + new query
            messages_for_llm = context_manager.build_context(summary, recent_messages, chat_request.query)
            tools_used = []

        else:
            messages_for_llm = [{"role": "user", "content": chat_request.query}]
            tools_used = []
        
        # Tool loop - keep going until LLM stops calling tools
        while True:
            response = anthropic.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                tools=anthropic_tools,
                messages=messages_for_llm
            )
            
            # Collect all tool uses first
            tool_calls = []
            final_text = ""

            for content in response.content:
                if content.type == "text":
                    final_text += content.text
                elif content.type == "tool_use":
                    tool_calls.append(content)
            
            # No tool calls - we're done
            if not tool_calls:
                break
            
            # Add assistant message with ALL content
            messages.append({"role": "assistant", "content": response.content})
            
            # Execute ALL tool calls and collect results
            tool_results = []
            for tool_call in tool_calls:
                tools_used.append({
                    "tool": tool_call.name,
                    "input": tool_call.input
                })
                
                # Call the tool via MCP
                result = await mcp_client.call_tool_raw(
                    tool_call.name,
                    arguments=tool_call.input
                )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": result
                })
            
            # Add ALL tool results in one message
            messages.append({"role": "user", "content": tool_results})
                    
        # Save updated messages
        if chat_request.session_id:
            conversation_store.add_messages(
                chat_request.session_id,
                [{"role": "user", "content": chat_request.query},
                {"role": "assistant", "content": final_text}]
            )
        
        return ChatResponse(
            response=final_text,
            tools_used=tools_used
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat", response_model=ChatResponse)
@limiter.limit("5/minute") # expensive llm calls
async def chat(request: Request, chat_request: ChatRequest, api_key: str = Depends(api_key_header)):
    """
    Chat endpoint - LLM decides whether to call tools or respond directly.
    """
    return await with_timeout(process_chat(chat_request), 90)

@app.post("/session")
@limiter.limit("5/minute")
async def create_session(request: Request, api_key: str = Depends(api_key_header)):
    session_id = conversation_store.create_session(api_key)
    return {"session_id": session_id}

@app.get("/sessions")
@limiter.limit("30/minute")
async def list_sessions(request: Request, api_key: str = Depends(api_key_header)):
    sessions = conversation_store.list_sessions(api_key)
    return {"sessions": sessions}