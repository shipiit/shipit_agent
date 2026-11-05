"""Custom tools the Claude Agent SDK way: ``@tool`` and an in-process MCP server.

    @tool("add", "Add two numbers", {"a": float, "b": float})
    async def add(args):
        return {"content": [{"type": "text", "text": str(args["a"] + args["b"])}]}

    calc = create_sdk_mcp_server("calc", tools=[add])
    options = AgentOptions(mcp_servers={"calc": calc}, allowed_tools=["mcp__calc__add"])

A tool from server ``calc`` is exposed as ``calc__add``; rules may name it
either way (``mcp__calc__add`` or ``calc__add``).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from shipit_agent.mcp import MCPServer, MCPTool
from shipit_agent.tools.base import ToolContext, ToolOutput

__all__ = ["SdkMcpTool", "create_sdk_mcp_server", "run_maybe_async", "tool"]

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


@dataclass(slots=True)
class SdkMcpTool:
    """A tool made with :func:`tool`, to serve from :func:`create_sdk_mcp_server`."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler
    annotations: dict[str, Any] = field(default_factory=dict)


def tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    annotations: dict[str, Any] | None = None,
) -> Callable[[Handler], SdkMcpTool]:
    """Make a function (sync or async, taking the arguments dict) a tool."""

    def decorator(handler: Handler) -> SdkMcpTool:
        return SdkMcpTool(name, description, json_schema(input_schema), handler, dict(annotations or {}))

    return decorator


def create_sdk_mcp_server(
    name: str, version: str = "1.0.0", tools: list[SdkMcpTool] | None = None
) -> dict[str, Any]:
    """An MCP server that runs in this process, as an ``mcp_servers`` entry."""
    server = MCPServer(name=name, metadata={"version": version})
    for item in tools or []:
        server.register(
            MCPTool(
                name=f"{name}__{item.name}",
                description=item.description,
                handler=_bind(item.handler),
                input_schema=item.input_schema,
                read_only=bool(item.annotations.get("readOnlyHint", item.annotations.get("read_only_hint", False))),
                metadata={"server": name, "remote_name": item.name},
            )
        )
    return {"type": "sdk", "name": name, "instance": server}


def json_schema(spec: dict[str, Any]) -> dict[str, Any]:
    """A JSON Schema from a full schema, or from a ``{"name": type}`` mapping."""
    if spec.get("type") == "object" or "properties" in spec:
        return dict(spec)
    properties = {key: {"type": _JSON_TYPES.get(value, "string")} for key, value in spec.items()}
    return {"type": "object", "properties": properties, "required": list(spec)}


def _bind(handler: Handler) -> Callable[..., ToolOutput]:
    def run(context: ToolContext, **arguments: Any) -> ToolOutput:
        return _to_output(run_maybe_async(handler, dict(arguments)))

    return run


def _to_output(result: Any) -> ToolOutput:
    if not isinstance(result, dict):
        return ToolOutput(text=str(result))
    parts = []
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    text = "\n".join(parts)
    return ToolOutput.error(text) if result.get("is_error") else ToolOutput(text=text)


def run_maybe_async(fn: Callable[..., Any], *args: Any) -> Any:
    """Call *fn*; if it returns a coroutine, run it to completion.

    Tools and permission checks run in plain functions, sometimes on a thread
    whose event loop is already running, so a coroutine then runs on a
    short-lived thread of its own.
    """
    value = fn(*args)
    if not inspect.isawaitable(value):
        return value

    async def _await() -> Any:
        return await value

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_await())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _await()).result()
