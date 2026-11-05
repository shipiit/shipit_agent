"""shipit's agent, with the Claude Agent SDK's API.

The same names and shapes as the SDK's Python package, on top of shipit's
one agent loop, so SDK-style code runs on any provider shipit supports::

    from shipit_agent.sdk import AgentOptions, ResultMessage, query

    async for message in query(
        prompt="Fix the failing test in tests/test_api.py",
        options=AgentOptions(
            model="claude-opus-5-5",
            allowed_tools=["Read", "Grep", "Bash(pytest *)"],
            permission_mode="acceptEdits",
            cwd="/path/to/repo",
        ),
    ):
        if isinstance(message, ResultMessage):
            print(message.result, message.total_cost_usd)

Custom tools use :func:`tool` and :func:`create_sdk_mcp_server`; hooks use
:class:`HookMatcher`; approvals use ``can_use_tool`` with
:class:`PermissionResultAllow` / :class:`PermissionResultDeny`.
"""

from __future__ import annotations

from .build import build_agent
from .client import AgentClient
from .hooks import HOOK_EVENTS, HookMatcher
from .options import AgentOptions
from .permissions import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext
from .query import query
from .tools import SdkMcpTool, create_sdk_mcp_server, tool
from .types import (
    AssistantMessage,
    ContentBlock,
    Message,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

__all__ = [
    "HOOK_EVENTS",
    "AgentClient",
    "AgentOptions",
    "AssistantMessage",
    "ContentBlock",
    "HookMatcher",
    "Message",
    "PermissionResultAllow",
    "PermissionResultDeny",
    "ResultMessage",
    "SdkMcpTool",
    "StreamEvent",
    "SystemMessage",
    "TextBlock",
    "ThinkingBlock",
    "ToolPermissionContext",
    "ToolResultBlock",
    "ToolUseBlock",
    "UserMessage",
    "build_agent",
    "create_sdk_mcp_server",
    "query",
    "tool",
]
