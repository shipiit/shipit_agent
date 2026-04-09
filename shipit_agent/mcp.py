from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Callable, Protocol
from urllib import request

from shipit_agent.tools.base import ToolContext, ToolOutput


class MCPTransport(Protocol):
    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def close(self) -> None: ...


class MCPError(RuntimeError):
    pass


@dataclass(slots=True)
class MCPTool:
    name: str
    description: str
    handler: Callable[..., Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    input_schema: dict[str, Any] = field(default_factory=dict)
    prompt: str = "Use this MCP tool when the remote capability is the right fit for the task."
    prompt_instructions: str = "Use this when the attached MCP server exposes the capability you need."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema or {"type": "object", "properties": {}, "required": []},
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        result = self.handler(context=context, **kwargs)
        if isinstance(result, ToolOutput):
            return result
        return ToolOutput(text=str(result), metadata=dict(self.metadata))


@dataclass(slots=True)
class MCPRemoteTool:
    server_name: str
    transport: MCPTransport
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}, "required": []})
    metadata: dict[str, Any] = field(default_factory=dict)
    prompt: str = "Use this MCP tool when the remote server provides the best capability for the task."
    prompt_instructions: str = "Remote MCP capability discovered dynamically from the attached server."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        result = self.transport.request(
            "tools/call",
            {
                "name": self.name,
                "arguments": kwargs,
            },
        )
        content = result.get("content", [])
        text_parts = []
        for item in content:
            if isinstance(item, dict):
                if "text" in item:
                    text_parts.append(str(item["text"]))
                else:
                    text_parts.append(json.dumps(item, sort_keys=True))
            else:
                text_parts.append(str(item))
        return ToolOutput(
            text="\n".join(part for part in text_parts if part).strip(),
            metadata={
                "server": self.server_name,
                "raw_result": result,
                **self.metadata,
            },
        )


@dataclass(slots=True)
class MCPServer:
    name: str
    tools: list[MCPTool | MCPRemoteTool] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def register(self, tool: MCPTool | MCPRemoteTool) -> "MCPServer":
        self.tools.append(tool)
        return self

    def register_many(self, tools: list[MCPTool | MCPRemoteTool]) -> "MCPServer":
        self.tools.extend(tools)
        return self

    def discover_tools(self) -> list[MCPTool | MCPRemoteTool]:
        return list(self.tools)


class MCPSubprocessTransport:
    def __init__(self, command: list[str], *, env: dict[str, str] | None = None) -> None:
        self.command = command
        self.env = env
        self._id_counter = count(1)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._id_counter),
            "method": method,
            "params": params or {},
        }
        completed = subprocess.run(
            self.command,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        if completed.returncode != 0:
            raise MCPError(completed.stderr.strip() or f"MCP subprocess failed with exit code {completed.returncode}")
        output = completed.stdout.strip()
        if not output:
            return {}
        response = json.loads(output)
        if "error" in response:
            raise MCPError(str(response["error"]))
        return dict(response.get("result", {}))

    def close(self) -> None:
        return None


class PersistentMCPSubprocessTransport:
    def __init__(self, command: list[str], *, env: dict[str, str] | None = None) -> None:
        self.command = command
        self.env = {**os.environ, **(env or {})}
        self._id_counter = count(1)
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        self._process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env,
        )
        return self._process

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            process = self._ensure_process()
            if process.stdin is None or process.stdout is None:
                raise MCPError("Persistent MCP subprocess did not expose stdio pipes.")
            payload = {
                "jsonrpc": "2.0",
                "id": next(self._id_counter),
                "method": method,
                "params": params or {},
            }
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
            if not line:
                stderr = process.stderr.read() if process.stderr is not None else ""
                raise MCPError(stderr.strip() or "Persistent MCP subprocess exited without a response.")
            response = json.loads(line)
            if "error" in response:
                raise MCPError(str(response["error"]))
            return dict(response.get("result", {}))

    def close(self) -> None:
        with self._lock:
            if self._process is None:
                return
            if self._process.stdin is not None:
                try:
                    self._process.stdin.close()
                except Exception:
                    pass
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            self._process = None


class MCPHTTPTransport:
    def __init__(self, endpoint: str, *, headers: dict[str, str] | None = None, timeout: float = 20.0) -> None:
        self.endpoint = endpoint
        self.headers = headers or {}
        self.timeout = timeout
        self._id_counter = count(1)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": next(self._id_counter),
                "method": method,
                "params": params or {},
            }
        ).encode("utf-8")
        req = request.Request(
            self.endpoint,
            data=payload,
            headers={"content-type": "application/json", **self.headers},
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout) as response:  # nosec B310
            body = response.read().decode("utf-8")
        parsed = json.loads(body) if body else {}
        if "error" in parsed:
            raise MCPError(str(parsed["error"]))
        return dict(parsed.get("result", {}))

    def close(self) -> None:
        return None


@dataclass(slots=True)
class RemoteMCPServer(MCPServer):
    transport: MCPTransport | None = None
    _discovered: bool = False

    def initialize(self) -> None:
        if self.transport is None:
            raise MCPError("RemoteMCPServer requires a transport.")
        self.transport.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "shipit_agent", "version": "1.0.0"},
            },
        )

    def discover_tools(self) -> list[MCPTool | MCPRemoteTool]:
        if self._discovered:
            return list(self.tools)
        if self.transport is None:
            raise MCPError("RemoteMCPServer requires a transport.")
        self.initialize()
        result = self.transport.request("tools/list", {})
        resolved_tools: list[MCPTool | MCPRemoteTool] = []
        for item in result.get("tools", []):
            resolved_tools.append(
                MCPRemoteTool(
                    server_name=self.name,
                    transport=self.transport,
                    name=str(item["name"]),
                    description=str(item.get("description", "")),
                    input_schema=dict(item.get("inputSchema") or {"type": "object", "properties": {}, "required": []}),
                    metadata={"server": self.name},
                )
            )
        self.tools = resolved_tools
        self._discovered = True
        return list(self.tools)

    def close(self) -> None:
        if self.transport is not None and hasattr(self.transport, "close"):
            self.transport.close()


def discover_mcp_tools(server: MCPServer) -> list[MCPTool | MCPRemoteTool]:
    return server.discover_tools()
