import json
from unittest import result
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from contextlib import AsyncExitStack

class MCPClient:
    def __init__(self, url: str, api_key: str):
        self.url = url
        self.api_key = api_key
        self.session = None
        self.exit_stack = AsyncExitStack()
    
    async def connect(self):
        """Connect to MCP server."""
        headers = {"X-API-Key": self.api_key}
        
        transport = await self.exit_stack.enter_async_context(
            streamablehttp_client(url=self.url, headers=headers)
        )
        read, write, _ = transport
        
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self.session.initialize()
    
    async def disconnect(self):
        """Disconnect from MCP server."""
        await self.exit_stack.aclose()
    
    async def call_tool(self, tool_name: str, arguments: dict):
        """Call a tool on the MCP server."""
        if not self.session:
            raise Exception("Not connected to MCP server")
        
        result = await self.session.call_tool(tool_name, arguments=arguments)
        
        
        # Use structuredContent if available (has the actual list/dict)
        if result.structuredContent:
            return result.structuredContent.get('result', result.structuredContent)
    
        
        # Fallback to content parsing
        if result.content:
            content = result.content[0]
            if hasattr(content, 'text'):
                try:
                    return json.loads(content.text)
                except json.JSONDecodeError:
                    return content.text
        return None
    
    async def read_resource(self, uri: str):
        """Read a resource from MCP server."""
        if not self.session:
            raise Exception("Not connected to MCP server")
        
        result = await self.session.read_resource(uri=uri)
        
        if result and result.contents:
            return result.contents[0].text
        return None

    async def get_prompt(self, name: str, arguments: dict):
        """Get a prompt from MCP server."""
        if not self.session:
            raise Exception("Not connected to MCP server")
        
        result = await self.session.get_prompt(name, arguments=arguments)
        
        if result and result.messages:
            content = result.messages[0].content
            if isinstance(content, str):
                return content
            elif hasattr(content, 'text'):
                return content.text
            else:
                return " ".join(item.text for item in content if hasattr(item, 'text'))
        return None
        
    async def list_prompts(self):
        """List all available prompts."""
        if not self.session:
            raise Exception("Not connected to MCP server")
        
        result = await self.session.list_prompts()
        
        prompts = []
        if result and result.prompts:
            for prompt in result.prompts:
                prompts.append({
                    "name": prompt.name,
                    "description": prompt.description,
                    "arguments": [
                        {"name": arg.name, "required": arg.required}
                        for arg in (prompt.arguments or [])
                    ]
                })
        return prompts
    
    async def list_tools(self):
        """List all available tools."""
        if not self.session:
            raise Exception("Not connected to MCP server")
        
        result = await self.session.list_tools()
        
        tools = []
        if result and result.tools:
            for tool in result.tools:
                tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema
                })
        return tools
    

    async def call_tool_raw(self, tool_name: str, arguments: dict):
        """Call tool and return raw content for LLM."""
        if not self.session:
            raise Exception("Not connected to MCP server")
        
        result = await self.session.call_tool(tool_name, arguments=arguments)
        return result.content


