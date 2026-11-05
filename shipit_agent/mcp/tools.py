"""MCP tools as shipit tools: names, the tool wrappers, and rendering their results."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from shipit_agent.tools.base import ToolContext, ToolOutput

from .transport import _MAX_TOOL_NAME_LENGTH, MCPError, MCPTransport


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
    """A tool implemented in this process and served through an :class:`MCPServer`."""

    name: str
    description: str
    handler: Callable[..., Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    read_only: bool | None = None
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
    """A tool that lives on a remote MCP server and is called through its transport."""

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
    tool_meta_resolver: (
        Callable[[ToolContext, str, dict[str, Any]], dict[str, Any] | None] | None
    ) = None
    #: Called once before the first `tools/call` to guarantee the server's
    #: `initialize` handshake has run — the seam that lets a tool be registered
    #: from a schema cache without spawning the process, and that re-handshakes
    #: after a transport respawn. Idempotent; ``None`` means "already ready".
    ensure_ready: Callable[[], None] | None = None

    @property
    def read_only(self) -> bool:
        return bool(self.annotations.get("readOnlyHint", False))

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
        if not rendered:
            rendered = (
                f"MCP tool '{self.name}' returned an error without details."
                if is_error
                else f"MCP tool '{self.name}' completed but returned no content."
            )
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
