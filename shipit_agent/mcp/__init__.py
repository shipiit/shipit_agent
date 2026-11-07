"""Model Context Protocol (MCP) client: connect to MCP servers and use their tools.

:class:`MCPServer` holds local tools; :class:`RemoteMCPServer` talks to a
real MCP server through a transport (stdio subprocess, persistent
subprocess, HTTP or streamable HTTP) and exposes the server's tools,
resources and prompts to an agent."""

from __future__ import annotations

# Kept as an attribute: callers (and tests) patch shipit_agent.mcp.request.urlopen.
from urllib import request

from .http import MCPHTTPTransport, MCPStreamableHTTPTransport
from .sse import MCPSSETransport
from .server import MCPServer, RemoteMCPServer, discover_mcp_tools
from .server_resources import MCPPrompt, MCPResource
from .stdio import (
    MCPStdioTransport,
    MCPSubprocessTransport,
    PersistentMCPSession,
    PersistentMCPSubprocessTransport,
)
from .tools import (
    MCPRemoteTool,
    MCPTool,
    _namespaced_mcp_tool_name,
    _sanitize_tool_name,
)
from .transport import MCP_PROTOCOL_VERSION, MCPError, MCPTransport

__all__ = [
    "MCPError",
    "MCPHTTPTransport",
    "MCPPrompt",
    "MCPRemoteTool",
    "MCPResource",
    "MCPServer",
    "MCPStdioTransport",
    "MCPStreamableHTTPTransport",
    "MCPSSETransport",
    "MCPSubprocessTransport",
    "MCPTool",
    "MCPTransport",
    "MCP_PROTOCOL_VERSION",
    "PersistentMCPSession",
    "PersistentMCPSubprocessTransport",
    "RemoteMCPServer",
    "_namespaced_mcp_tool_name",
    "_sanitize_tool_name",
    "discover_mcp_tools",
    "request",
]
