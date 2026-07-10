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
    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

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
    prompt: str = (
        "Use this MCP tool when the remote capability is the right fit for the task."
    )
    prompt_instructions: str = (
        "Use this when the attached MCP server exposes the capability you need."
    )

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema
                or {"type": "object", "properties": {}, "required": []},
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
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []}
    )
    metadata: dict[str, Any] = field(default_factory=dict)
    prompt: str = "Use this MCP tool when the remote server provides the best capability for the task."
    prompt_instructions: str = (
        "Remote MCP capability discovered dynamically from the attached server."
    )

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
        try:
            result = self.transport.request(
                "tools/call",
                {
                    "name": self.name,
                    "arguments": kwargs,
                },
            )
        except (MCPError, OSError, TimeoutError) as exc:
            # Surface transport/server failures as a readable tool result the
            # model can react to, instead of crashing the whole agent run.
            return ToolOutput(
                text=(
                    f"MCP tool '{self.name}' on server '{self.server_name}' "
                    f"failed: {exc}"
                ),
                metadata={
                    "server": self.server_name,
                    "ok": False,
                    "error": str(exc),
                    **self.metadata,
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
    def __init__(
        self, command: list[str], *, env: dict[str, str] | None = None
    ) -> None:
        self.command = command
        self.env = env
        self._id_counter = count(1)

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
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
            raise MCPError(
                completed.stderr.strip()
                or f"MCP subprocess failed with exit code {completed.returncode}"
            )
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
    def __init__(
        self, command: list[str], *, env: dict[str, str] | None = None
    ) -> None:
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

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
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
                raise MCPError(
                    stderr.strip()
                    or "Persistent MCP subprocess exited without a response."
                )
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
    def __init__(
        self,
        endpoint: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
        bearer_token: str | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.headers = dict(headers or {})
        if bearer_token:
            self.headers.setdefault("authorization", f"Bearer {bearer_token}")
        self.timeout = timeout
        self._id_counter = count(1)

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
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


class MCPStreamableHTTPTransport(MCPHTTPTransport):
    """Streamable-HTTP MCP transport (the 2025 spec revision).

    POSTs JSON-RPC like :class:`MCPHTTPTransport`, but also handles servers
    that answer with ``text/event-stream`` — the JSON-RPC response arrives
    as SSE ``data:`` lines. Also carries the ``Mcp-Session-Id`` header the
    spec uses for session affinity. Pass ``bearer_token=`` for servers
    behind OAuth/bearer auth.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._session_id: str | None = None

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": next(self._id_counter),
                "method": method,
                "params": params or {},
            }
        ).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            **self.headers,
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        req = request.Request(
            self.endpoint, data=payload, headers=headers, method="POST"
        )
        with request.urlopen(req, timeout=self.timeout) as response:  # nosec B310
            session_id = response.headers.get("Mcp-Session-Id")
            if session_id:
                self._session_id = session_id
            content_type = (response.headers.get("Content-Type") or "").lower()
            body = response.read().decode("utf-8")
        if "text/event-stream" in content_type:
            parsed = self._parse_sse(body)
        else:
            parsed = json.loads(body) if body else {}
        if "error" in parsed:
            raise MCPError(str(parsed["error"]))
        return dict(parsed.get("result", {}))

    @staticmethod
    def _parse_sse(body: str) -> dict[str, Any]:
        """Extract the JSON-RPC response from SSE `data:` lines."""
        for chunk in body.split("\n\n"):
            data_lines = [
                line[5:].strip()
                for line in chunk.splitlines()
                if line.startswith("data:")
            ]
            if not data_lines:
                continue
            try:
                parsed = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                continue
            # The response to our request carries an id (notifications don't).
            if isinstance(parsed, dict) and ("result" in parsed or "error" in parsed):
                return parsed
        raise MCPError("No JSON-RPC response found in SSE stream.")


@dataclass(slots=True)
class MCPResource:
    """A resource exposed by an MCP server (a file, table, doc, …)."""

    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""


@dataclass(slots=True)
class MCPPrompt:
    """A prompt template exposed by an MCP server."""

    name: str
    description: str = ""
    arguments: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class RemoteMCPServer(MCPServer):
    transport: MCPTransport | None = None
    _discovered: bool = False
    _initialized: bool = False

    def initialize(self) -> None:
        if self.transport is None:
            raise MCPError("RemoteMCPServer requires a transport.")
        if self._initialized:
            return
        self.transport.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "clientInfo": {"name": "shipit_agent", "version": "1.0.0"},
            },
        )
        self._initialized = True

    # ── resources ─────────────────────────────────────────────────────
    def list_resources(self) -> list[MCPResource]:
        """Resources the server exposes. Empty if unsupported."""
        try:
            self.initialize()
            result = self.transport.request("resources/list", {})
        except MCPError:
            return []  # server doesn't implement resources
        return [
            MCPResource(
                uri=str(item.get("uri", "")),
                name=str(item.get("name", "")),
                description=str(item.get("description", "")),
                mime_type=str(item.get("mimeType", "")),
            )
            for item in result.get("resources", [])
        ]

    def read_resource(self, uri: str) -> str:
        """Read one resource's content (text parts joined; blobs noted)."""
        self.initialize()
        result = self.transport.request("resources/read", {"uri": uri})
        parts: list[str] = []
        for item in result.get("contents", []):
            if "text" in item:
                parts.append(str(item["text"]))
            elif "blob" in item:
                parts.append(f"[binary content: {item.get('mimeType', 'unknown')}]")
        return "\n".join(parts)

    # ── prompts ───────────────────────────────────────────────────────
    def list_prompts(self) -> list[MCPPrompt]:
        """Prompt templates the server exposes. Empty if unsupported."""
        try:
            self.initialize()
            result = self.transport.request("prompts/list", {})
        except MCPError:
            return []  # server doesn't implement prompts
        return [
            MCPPrompt(
                name=str(item.get("name", "")),
                description=str(item.get("description", "")),
                arguments=list(item.get("arguments", [])),
            )
            for item in result.get("prompts", [])
        ]

    def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """Render a prompt template to plain text (role-prefixed)."""
        self.initialize()
        result = self.transport.request(
            "prompts/get", {"name": name, "arguments": arguments or {}}
        )
        lines: list[str] = []
        for message in result.get("messages", []):
            content = message.get("content", "")
            if isinstance(content, dict):
                content = content.get("text", "")
            role = message.get("role", "user")
            lines.append(f"[{role}] {content}" if role != "user" else str(content))
        return "\n".join(lines)

    def resource_tool(self) -> MCPTool:
        """A tool that lets the model browse/read this server's resources.

        Call with no ``uri`` to list what's available; pass ``uri`` to read
        one. Attach it alongside the server's tools::

            server = connect_mcp("filesystem", args=["."])
            agent = Agent(llm=llm, mcps=[server],
                          tools=[server.resource_tool()])
        """

        def handler(context: Any = None, uri: str = "", **_ignored: Any) -> str:
            if uri:
                return self.read_resource(uri)
            resources = self.list_resources()
            if not resources:
                return f"MCP server '{self.name}' exposes no resources."
            return "\n".join(
                f"{r.uri} — {r.name or r.description or r.mime_type}"
                for r in resources
            )

        return MCPTool(
            name=f"{self.name}_resources",
            description=(
                f"Browse and read resources exposed by the '{self.name}' MCP "
                "server. Call without arguments to list resource URIs; pass "
                "`uri` to read one."
            ),
            handler=handler,
            input_schema={
                "type": "object",
                "properties": {
                    "uri": {
                        "type": "string",
                        "description": "Resource URI to read (omit to list all)",
                    }
                },
                "required": [],
            },
            metadata={"server": self.name},
        )

    def discover_tools(self) -> list[MCPTool | MCPRemoteTool]:
        if self._discovered:
            return list(self.tools)
        if self.transport is None:
            raise MCPError("RemoteMCPServer requires a transport.")
        try:
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
                        input_schema=dict(
                            item.get("inputSchema")
                            or {"type": "object", "properties": {}, "required": []}
                        ),
                        metadata={"server": self.name},
                    )
                )
        except Exception:
            # Discovery opened the connection/subprocess; if it fails we must
            # close the transport so we don't leak a live process or socket.
            self.close()
            raise
        self.tools = resolved_tools
        self._discovered = True
        return list(self.tools)

    def close(self) -> None:
        if self.transport is not None and hasattr(self.transport, "close"):
            self.transport.close()


def discover_mcp_tools(server: MCPServer) -> list[MCPTool | MCPRemoteTool]:
    return server.discover_tools()


# Friendly aliases matching MCP ecosystem naming (and our docs).
MCPStdioTransport = MCPSubprocessTransport
PersistentMCPSession = PersistentMCPSubprocessTransport
