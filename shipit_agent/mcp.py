from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Callable, Protocol
from urllib import request

from shipit_agent.tools.base import ToolContext, ToolOutput


MCP_PROTOCOL_VERSION = "2025-11-25"
_MAX_TOOL_NAME_LENGTH = 64


def _sanitize_tool_name(raw: str) -> str:
    """A provider-safe tool name: ``[A-Za-z0-9_-]``, ≤64 chars, non-empty.

    Applied to EVERY exposed MCP tool name, prefixed or not. Servers report
    whatever they like — ``deepwiki**ask_question`` was observed live and
    forwarded verbatim to Bedrock, which rejects it. ``remote_name`` keeps
    the server's exact string for the wire call, so sanitizing the exposed
    name costs nothing in correctness.
    """
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_-") or "mcp_tool"
    if safe[0].isdigit():
        safe = f"mcp_{safe}"
    if len(safe) <= _MAX_TOOL_NAME_LENGTH:
        return safe
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"{safe[: _MAX_TOOL_NAME_LENGTH - 9]}_{digest}"


def _namespaced_mcp_tool_name(server_name: str, tool_name: str) -> str:
    """Return a deterministic provider-safe exposed MCP tool name."""
    return _sanitize_tool_name(f"{server_name}__{tool_name}")


class MCPTransport(Protocol):
    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    def close(self) -> None: ...


class MCPError(RuntimeError):
    pass


def _mcp_result_summary(result: dict[str, Any], rendered: str) -> str:
    """Use only a summary the MCP server explicitly supplied.

    A short, single-line result is already a factual server response and is
    safe to display as-is. Large payloads are never pattern-matched for counts
    or meaning; doing that would make the runtime invent semantics.
    """
    metadata = result.get("_meta")
    structured = result.get("structuredContent")
    for source in (metadata, structured):
        if isinstance(source, dict):
            summary = source.get("summary")
            if isinstance(summary, str) and summary.strip():
                return " ".join(summary.split())[:240]
    compact = " ".join(rendered.split())
    return compact if "\n" not in rendered and len(compact) <= 160 else ""


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
    output_schema: dict[str, Any] = field(default_factory=dict)
    title: str = ""
    annotations: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    remote_name: str = ""
    tool_meta_resolver: Callable[
        [ToolContext, str, dict[str, Any]], dict[str, Any] | None
    ] | None = None
    #: Called once before the first `tools/call` to guarantee the server's
    #: `initialize` handshake has run — the seam that lets a tool be registered
    #: from a schema cache without spawning the process, and that re-handshakes
    #: after a transport respawn. Idempotent; ``None`` means "already ready".
    ensure_ready: Callable[[], None] | None = None
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
        declared = set((self.input_schema.get("properties") or {}).keys())
        ignored_arguments: list[str] = []
        if declared and self.input_schema.get("additionalProperties") is not True:
            ignored_arguments = sorted(set(kwargs) - declared)
            kwargs = {key: value for key, value in kwargs.items() if key in declared}
        call_params: dict[str, Any] = {
            "name": self.remote_name or self.name,
            "arguments": kwargs,
        }
        if self.tool_meta_resolver is not None:
            call_metadata = self.tool_meta_resolver(context, self.name, dict(kwargs))
            if call_metadata:
                call_params["_meta"] = dict(call_metadata)
        try:
            # For a cache-registered (lazy) server this is where the process
            # actually spawns and handshakes; kept inside the try so a dead
            # server surfaces as a tool result, not a crashed run.
            if self.ensure_ready is not None:
                self.ensure_ready()
            result = self.transport.request(
                "tools/call",
                call_params,
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
        content = list(result.get("content", []))
        text_parts = _render_mcp_content(content)
        is_error = bool(result.get("isError", False))
        rendered = "\n".join(part for part in text_parts if part).strip()
        summary = _mcp_result_summary(result, rendered)
        # An MCP tool that returned an image gets it in front of the model,
        # not a "[image: image/png]" placeholder: the first image block's
        # data rides the runtime's vision-bridge convention.
        image = next(
            (
                item
                for item in content
                if isinstance(item, dict)
                and item.get("type") == "image"
                and item.get("data")
            ),
            None,
        )
        vision_metadata = (
            {
                "image_base64": str(image.get("data", "")),
                "media_type": str(image.get("mimeType") or "image/png"),
                "vision": True,
            }
            if image is not None
            else {}
        )
        return ToolOutput(
            text=rendered,
            metadata={
                **vision_metadata,
                "server": self.server_name,
                "ok": not is_error,
                "is_error": is_error,
                "structured_content": result.get("structuredContent"),
                "content_blocks": content,
                "output_schema": dict(self.output_schema),
                "annotations": dict(self.annotations),
                "raw_result": result,
                **(
                    {"ignored_arguments": ignored_arguments}
                    if ignored_arguments
                    else {}
                ),
                **({"summary": summary} if summary else {}),
                **self.metadata,
            },
        )


def _render_mcp_content(content: list[Any]) -> list[str]:
    """Render MCP content for the model without discarding rich blocks."""
    rendered: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            rendered.append(str(item))
            continue
        kind = str(item.get("type", ""))
        if kind == "text" or "text" in item:
            rendered.append(str(item.get("text", "")))
        elif kind == "image":
            rendered.append(f"[image: {item.get('mimeType', 'image/unknown')}]")
        elif kind == "audio":
            rendered.append(f"[audio: {item.get('mimeType', 'audio/unknown')}]")
        elif kind == "resource_link":
            label = item.get("title") or item.get("name") or "resource"
            rendered.append(f"[{label}: {item.get('uri', '')}]")
        elif kind == "resource":
            resource = item.get("resource", {})
            if isinstance(resource, dict) and "text" in resource:
                rendered.append(str(resource["text"]))
            elif isinstance(resource, dict):
                rendered.append(
                    f"[embedded resource: {resource.get('uri', '')} "
                    f"{resource.get('mimeType', '')}]".strip()
                )
        else:
            rendered.append(json.dumps(item, sort_keys=True))
    return rendered


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


#: Per-request ceiling for MCP servers. A wedged server without one hangs
#: the whole run forever — cancel() only takes effect between steps.
_MCP_DEFAULT_TIMEOUT = 60.0


class MCPSubprocessTransport:
    def __init__(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout: float = _MCP_DEFAULT_TIMEOUT,
    ) -> None:
        self.command = command
        self.env = env
        self.timeout = timeout
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
        try:
            completed = subprocess.run(
                self.command,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                env=self.env,
                check=False,
                timeout=self.timeout or None,
            )
        except subprocess.TimeoutExpired as exc:
            raise MCPError(
                f"MCP subprocess timed out after {self.timeout:.0f}s "
                f"on {method!r}"
            ) from exc
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
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout: float = _MCP_DEFAULT_TIMEOUT,
    ) -> None:
        self.command = command
        self.env = {**os.environ, **(env or {})}
        self.timeout = timeout
        self._id_counter = count(1)
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        #: Bumped on every (re)spawn. RemoteMCPServer compares it against the
        #: generation it handshook with — a crashed-and-respawned server must
        #: be re-`initialize`d before it can serve `tools/call`.
        self.generation = 0

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
        self.generation += 1
        return self._process

    def _readline_with_deadline(self, process: subprocess.Popen[str]) -> str:
        """A readline that cannot wedge the run.

        ``process.stdout.readline()`` under ``self._lock`` with no deadline
        turns one hung MCP server into a hung agent — observed shape, and
        ``cancel()`` cannot interrupt it. The read runs on a worker thread;
        on expiry the process is killed (its pipe state is undefined mid-
        message, so respawn-next-request is the only safe recovery) and a
        readable MCPError surfaces to the model.
        """
        if not self.timeout:
            return process.stdout.readline()  # type: ignore[union-attr]
        result: list[str] = []

        def _read() -> None:
            result.append(process.stdout.readline())  # type: ignore[union-attr]

        reader = threading.Thread(target=_read, daemon=True)
        reader.start()
        reader.join(self.timeout)
        if reader.is_alive():
            process.kill()
            raise MCPError(
                f"Persistent MCP subprocess timed out after "
                f"{self.timeout:.0f}s; the process was killed and will be "
                "respawned on the next request."
            )
        return result[0] if result else ""

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
            line = self._readline_with_deadline(process)
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
        # HTTP servers commonly use CRLF framing. Splitting the raw body on
        # ``\n\n`` merges every CRLF event into one invalid JSON blob, which
        # made long-running MCP calls fail while short JSON responses worked.
        normalized = body.replace("\r\n", "\n").replace("\r", "\n")
        for chunk in normalized.split("\n\n"):
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
    protocol_version: str = MCP_PROTOCOL_VERSION
    allowed_tools: set[str] | None = None
    blocked_tools: set[str] = field(default_factory=set)
    tool_filter: Callable[[dict[str, Any]], bool] | None = None
    include_server_in_tool_names: bool = False
    tool_meta_resolver: Callable[
        [ToolContext, str, dict[str, Any]], dict[str, Any] | None
    ] | None = None
    server_capabilities: dict[str, Any] = field(default_factory=dict)
    server_info: dict[str, Any] = field(default_factory=dict)
    #: The server's own usage guidance from the `initialize` handshake.
    instructions: str = ""
    #: Opt-in warm start: persist the tool schema to disk and, on a later run,
    #: rebuild the tools from that cache without spawning the process until a
    #: tool is actually called. Off by default — it moves connect-time errors to
    #: first-call time, so a caller asks for it explicitly.
    #:
    #: Trade-off worth knowing: within one ``cache_ttl`` window a tool removed
    #: server-side stays offered from the cache; calling it returns a normal MCP
    #: error (handled, not a crash), and the next cold discovery after the TTL
    #: drops it. Shorten ``cache_ttl`` if a server's toolset changes often.
    cache: bool = False
    #: Warm-start freshness window (seconds). A cache older than this is a miss.
    cache_ttl: float = 24 * 60 * 60
    _discovered: bool = False
    _initialized: bool = False
    _handshook_generation: int = 0
    #: True when tools were built from the cache and the process has not been
    #: spawned yet — the flag that keeps every-turn re-discovery from eagerly
    #: initializing before the first real tool call.
    _lazy_pending: bool = False

    def initialize(self) -> None:
        if self.transport is None:
            raise MCPError("RemoteMCPServer requires a transport.")
        # A transport that respawned its process (crash mid-run) bumps its
        # generation; the new process has never seen `initialize`, and most
        # servers reject or misbehave on `tools/call` without the handshake.
        generation = getattr(self.transport, "generation", None)
        if self._initialized and generation not in (None, 0):
            if generation != self._handshook_generation:
                self._initialized = False
        if self._initialized:
            return
        result = self.transport.request(
            "initialize",
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "clientInfo": {"name": "shipit_agent", "version": "1.0.0"},
            },
        )
        self.protocol_version = str(
            result.get("protocolVersion") or self.protocol_version
        )
        self.server_capabilities = dict(result.get("capabilities", {}))
        self.server_info = dict(result.get("serverInfo", {}))
        # The spec's `instructions` field is the server telling the model
        # how to use it — dropping it wasted the server author's one channel.
        self.instructions = str(result.get("instructions") or "")
        self._initialized = True
        self._handshook_generation = getattr(self.transport, "generation", 0)

    def _tool_allowed(self, item: dict[str, Any]) -> bool:
        name = str(item.get("name", ""))
        if self.allowed_tools is not None and name not in self.allowed_tools:
            return False
        if name in self.blocked_tools:
            return False
        return self.tool_filter(item) if self.tool_filter is not None else True

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
                f"{r.uri} — {r.name or r.description or r.mime_type}" for r in resources
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

    def _ensure_ready(self) -> None:
        """Run the handshake before the first cached tool call; clean up on fail.

        Passed to every :class:`MCPRemoteTool` as its ``ensure_ready``. On a
        cache-warm server this is where the process finally spawns. If it fails
        we close the transport (matching the live-discovery path) so a
        half-spawned subprocess never leaks, then re-raise for ``run`` to surface.
        """
        try:
            self.initialize()
        except Exception:
            self.close()
            raise
        self._lazy_pending = False

    def _cache_fingerprint(self) -> str:
        # Computed *before* initialize() so protocol negotiation can't shift the
        # key between the load (cold) and save (post-handshake) within a run.
        from shipit_agent import mcp_schema_cache

        return mcp_schema_cache.fingerprint(
            name=self.name,
            identity=mcp_schema_cache.transport_identity(self.transport),
            protocol_version=self.protocol_version,
            allowed=self.allowed_tools,
            blocked=self.blocked_tools,
            include_server_in_tool_names=self.include_server_in_tool_names,
            env=getattr(self.transport, "env", None),
        )

    def _descriptor(self, item: dict[str, Any], exposed_name: str, remote_name: str) -> dict[str, Any]:
        """A resolved, JSON-serialisable tool descriptor — the cache unit."""
        return {
            "name": exposed_name,
            "remote_name": remote_name,
            "description": str(item.get("description", "")),
            "input_schema": dict(
                item.get("inputSchema")
                or {"type": "object", "properties": {}, "required": []}
            ),
            "output_schema": dict(item.get("outputSchema") or {}),
            "title": str(item.get("title", "")),
            "annotations": dict(item.get("annotations") or {}),
            "execution": dict(item.get("execution") or {}),
        }

    def _tool_from_descriptor(self, descriptor: dict[str, Any]) -> MCPRemoteTool:
        """Build a live tool from a descriptor — the one place both the live and
        the cache paths construct an :class:`MCPRemoteTool`, so they can't drift."""
        return MCPRemoteTool(
            server_name=self.name,
            transport=self.transport,
            name=str(descriptor["name"]),
            remote_name=str(descriptor.get("remote_name", "")),
            description=str(descriptor.get("description", "")),
            input_schema=dict(
                descriptor.get("input_schema")
                or {"type": "object", "properties": {}, "required": []}
            ),
            output_schema=dict(descriptor.get("output_schema") or {}),
            title=str(descriptor.get("title", "")),
            annotations=dict(descriptor.get("annotations") or {}),
            metadata={
                "server": self.name,
                "remote_name": str(descriptor.get("remote_name", "")),
                "title": str(descriptor.get("title", "")),
                "annotations": dict(descriptor.get("annotations") or {}),
                "execution": dict(descriptor.get("execution") or {}),
            },
            tool_meta_resolver=self.tool_meta_resolver,
            ensure_ready=self._ensure_ready,
        )

    def discover_tools(self) -> list[MCPTool | MCPRemoteTool]:
        if self._discovered:
            if self._lazy_pending:
                # Built from cache, process not yet spawned. Every-turn
                # re-discovery must NOT initialize here — that would defeat the
                # laziness. Return the cached tools with zero transport traffic;
                # the first tool call spawns and handshakes via ensure_ready.
                return list(self.tools)
            # A prior agent turn may have closed the transport. Persistent
            # transports can reopen themselves, but the new MCP session must
            # complete the protocol handshake before cached tools are reused.
            self.initialize()
            return list(self.tools)
        if self.transport is None:
            raise MCPError("RemoteMCPServer requires a transport.")

        # Warm start: rebuild from the on-disk schema cache without spawning.
        # Skipped when a callable tool_filter is set — it can't be fingerprinted,
        # so a cached schema could include tools the filter would now exclude.
        fingerprint: str | None = None
        if self.cache and self.tool_filter is None:
            from shipit_agent import mcp_schema_cache

            fingerprint = self._cache_fingerprint()
            cached = mcp_schema_cache.load(self.name, fingerprint, ttl=self.cache_ttl)
            if cached is not None:
                self.tools = [self._tool_from_descriptor(d) for d in cached]
                self._discovered = True
                self._lazy_pending = True
                return list(self.tools)

        # Cold path: live discovery (spawn + handshake + tools/list).
        try:
            self.initialize()
            result = self.transport.request("tools/list", {})
            descriptors: list[dict[str, Any]] = []
            exposed_names: set[str] = set()
            for item in result.get("tools", []):
                if not self._tool_allowed(item):
                    continue
                remote_name = str(item["name"])
                # Sanitization is unconditional — only the server prefix is
                # opt-in. The raw name still goes on the wire via
                # ``remote_name``; providers only ever see the safe one.
                exposed_name = (
                    _namespaced_mcp_tool_name(self.name, remote_name)
                    if self.include_server_in_tool_names
                    else _sanitize_tool_name(remote_name)
                )
                if exposed_name in exposed_names:
                    digest = hashlib.sha256(remote_name.encode("utf-8")).hexdigest()[:8]
                    exposed_name = (
                        f"{exposed_name[: _MAX_TOOL_NAME_LENGTH - 9]}_{digest}"
                    )
                exposed_names.add(exposed_name)
                descriptors.append(self._descriptor(item, exposed_name, remote_name))
            resolved_tools: list[MCPTool | MCPRemoteTool] = [
                self._tool_from_descriptor(descriptor) for descriptor in descriptors
            ]
        except Exception:
            # Discovery opened the connection/subprocess; if it fails we must
            # close the transport so we don't leak a live process or socket.
            self.close()
            raise
        self.tools = resolved_tools
        self._discovered = True
        self._lazy_pending = False
        # Persist for the next warm start (best-effort; never raises). Uses the
        # pre-initialize fingerprint so it matches what a future load computes.
        if fingerprint is not None:
            from shipit_agent import mcp_schema_cache

            mcp_schema_cache.save(self.name, fingerprint, descriptors)
        return list(self.tools)

    def close(self) -> None:
        if self.transport is not None and hasattr(self.transport, "close"):
            self.transport.close()
        # Closing ends the MCP protocol session even when the transport object
        # is reusable. Keep discovered schemas, but handshake again next turn.
        self._initialized = False
        # `close_mcps()` runs at the end of EVERY turn. For a cache-registered
        # server, return to the lazy state so the next turn re-registers its
        # tools from memory without respawning — an unused server then costs
        # nothing, turn after turn, which is the entire point of the cache.
        # (A plain server stays eager, exactly as before.)
        if self.cache and self._discovered:
            self._lazy_pending = True


def discover_mcp_tools(server: MCPServer) -> list[MCPTool | MCPRemoteTool]:
    return server.discover_tools()


# Friendly aliases matching MCP ecosystem naming (and our docs).
MCPStdioTransport = MCPSubprocessTransport
PersistentMCPSession = PersistentMCPSubprocessTransport
