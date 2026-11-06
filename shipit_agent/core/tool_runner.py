"""Executing tool calls: argument checks, safe event metadata and collected results.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterable, Iterable
from dataclasses import dataclass, field
from typing import Any, Callable

from shipit_agent.core.models import ToolCall, ToolResult
from shipit_agent.core.registry import ToolRegistry
from shipit_agent.core.tool_arguments import (
    declared_parameters,
    missing_argument,
    missing_argument_message,
)
from shipit_agent.tools import ToolContext, ToolOutput, ToolOutputChunk

ToolOutputCallback = Callable[[ToolOutputChunk], None]
_LIVE_OUTPUT_CHUNK_CHARS = 16_384
_HEAVY_EVENT_METADATA_KEYS = frozenset(
    {"raw_result", "content_blocks", "structured_content"}
)


def _metadata_is_error(metadata: dict[str, Any]) -> bool:
    """Honor the tool's explicit outcome marker.

    MCP tools report protocol failures as ordinary ``ToolOutput`` values so
    the model can recover.  Dropping that marker while converting to the
    runtime's ``ToolResult`` made a failed MCP call emit ``tool_completed``.
    """
    return bool(metadata.get("is_error") or metadata.get("ok") is False)


def safe_tool_event_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Keep live events informative without duplicating canonical payloads."""
    return {
        key: value
        for key, value in dict(metadata or {}).items()
        if key not in _HEAVY_EVENT_METADATA_KEYS
    }


@dataclass(slots=True)
class ToolRunnerResult:
    """The results of a batch of tool calls, and any tools that were not found."""
    results: list[ToolResult] = field(default_factory=list)
    missing_tools: list[str] = field(default_factory=list)


class ToolRunner:
    """Execute tool calls against a registry and collect their results."""
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    # Argument names reserved by the runtime's tool-calling convention.
    # If the LLM happens to emit any of these as tool arguments (observed with
    # `gpt-oss-120b` and a few other models that hallucinate a `context` or
    # `self` key), they would collide with Python's positional parameter and
    # raise `TypeError: run() got multiple values for argument 'context'`.
    # We strip them before forwarding so the tool receives only real args.
    _RESERVED_ARG_NAMES: frozenset[str] = frozenset({"context", "self"})

    @staticmethod
    def _collect_output(
        name: str,
        output: Any,
        output_callback: ToolOutputCallback | None,
    ) -> ToolResult:
        # Keep compatibility with third-party tools that historically returned
        # a lightweight object exposing the ToolOutput shape without importing
        # or subclassing shipit's dataclass.
        if isinstance(output, ToolOutput) or hasattr(output, "text"):
            output_metadata = dict(getattr(output, "metadata", {}) or {})
            chunk = ToolOutputChunk(
                str(output.text), output_metadata
            )
            if output_callback is not None and chunk.text:
                # Remote tools often return one very large ToolOutput object.
                # Keep the canonical result intact, but publish bounded live
                # deltas so terminal/browser consumers stay responsive.
                for offset in range(0, len(chunk.text), _LIVE_OUTPUT_CHUNK_CHARS):
                    output_callback(
                        ToolOutputChunk(
                            chunk.text[offset : offset + _LIVE_OUTPUT_CHUNK_CHARS],
                            dict(chunk.metadata),
                        )
                    )
            return ToolResult(
                name=name,
                output=chunk.text,
                metadata=chunk.metadata,
                model_text=getattr(output, "model_text", None),
                is_error=_metadata_is_error(output_metadata),
            )

        # Plain text was the original and remains the most common return shape
        # for lightweight tools and in-process MCP adapters. Treat it as a
        # complete successful result instead of iterating characters or
        # rejecting a tool that already did its work successfully.
        if isinstance(output, (str, bytes)):
            text = (
                output.decode("utf-8", errors="replace")
                if isinstance(output, bytes)
                else output
            )
            if output_callback is not None and text:
                for offset in range(0, len(text), _LIVE_OUTPUT_CHUNK_CHARS):
                    output_callback(ToolOutputChunk(
                        text[offset : offset + _LIVE_OUTPUT_CHUNK_CHARS]
                    ))
            return ToolResult(name=name, output=text)

        if not isinstance(output, Iterable):
            raise TypeError(
                f"Tool '{name}' returned {type(output).__name__}; expected "
                "ToolOutput or an iterable of ToolOutputChunk values"
            )

        parts: list[str] = []
        metadata: dict[str, Any] = {}
        chunk_count = 0
        for item in output:
            if isinstance(item, ToolOutputChunk | ToolOutput):
                chunk = ToolOutputChunk(str(item.text), dict(item.metadata))
            elif isinstance(item, str):
                chunk = ToolOutputChunk(item)
            else:
                raise TypeError(
                    f"Streaming tool '{name}' yielded {type(item).__name__}; "
                    "expected ToolOutputChunk, ToolOutput, or str"
                )
            chunk_count += 1
            parts.append(chunk.text)
            metadata.update(chunk.metadata)
            if output_callback is not None:
                output_callback(chunk)
        metadata.setdefault("streamed", True)
        metadata.setdefault("stream_chunk_count", chunk_count)
        return ToolResult(
            name=name,
            output="".join(parts),
            metadata=metadata,
            is_error=_metadata_is_error(metadata),
        )

    def run_tool_call(
        self,
        tool_call: ToolCall,
        context: ToolContext,
        output_callback: ToolOutputCallback | None = None,
    ) -> ToolResult:
        tool = self.registry.get(tool_call.name)
        if tool is None:
            raise KeyError(f"Unknown tool: {tool_call.name}")

        # Deferred tool loading: a direct call to a deferred tool counts as
        # loading it — its schema is advertised on every later step. Shared
        # by both loops because every execution funnels through here.
        loaded = context.state.get("loaded_tool_names")
        if isinstance(loaded, set):
            loaded.add(tool_call.name)

        # Filter out reserved argument names that would collide with the
        # positional `context` parameter passed by the runner.
        safe_arguments = {
            k: v
            for k, v in tool_call.arguments.items()
            if k not in self._RESERVED_ARG_NAMES
        }
        try:
            output = tool.run(context, **safe_arguments)
        except (KeyError, TypeError) as exc:
            # A tool that reads `kwargs["path"]` raises KeyError when the
            # model omits it, and one with a typed signature raises TypeError.
            # Both surface as a crash the model cannot act on — and the retry
            # policy then retries an identical call that fails identically.
            #
            # Models omit arguments constantly; that is why tool_healing
            # exists. Turn it into a result that names what is missing, so the
            # next turn can supply it.
            declared, required = declared_parameters(tool)
            missing = missing_argument(exc, safe_arguments, declared)
            if missing is None:
                raise
            result = ToolResult(
                name=tool_call.name,
                output=missing_argument_message(tool_call.name, missing, required),
                metadata={"error": "missing_argument", "argument": missing},
            )
            if output_callback is not None:
                output_callback(ToolOutputChunk(result.output, dict(result.metadata)))
            return result
        return self._collect_output(tool_call.name, output, output_callback)

    async def run_tool_call_async(
        self,
        tool_call: ToolCall,
        context: ToolContext,
        output_callback: ToolOutputCallback | None = None,
    ) -> ToolResult:
        """Run a native async tool when available, else preserve context in a thread.

        Tools may expose ``arun`` or ``run_async`` without changing the existing
        synchronous Tool protocol. This keeps old integrations compatible while
        allowing HTTP/MCP/database tools to avoid occupying executor threads.
        """
        tool = self.registry.get(tool_call.name)
        if tool is None:
            raise KeyError(f"Unknown tool: {tool_call.name}")
        loaded = context.state.get("loaded_tool_names")
        if isinstance(loaded, set):
            loaded.add(tool_call.name)
        safe_arguments = {
            k: v
            for k, v in tool_call.arguments.items()
            if k not in self._RESERVED_ARG_NAMES
        }
        async_runner = getattr(tool, "arun", None) or getattr(tool, "run_async", None)
        try:
            if callable(async_runner):
                output = async_runner(context, **safe_arguments)
                if inspect.isawaitable(output):
                    output = await output
            else:
                return await asyncio.to_thread(
                    self.run_tool_call, tool_call, context, output_callback
                )
        except (KeyError, TypeError) as exc:
            declared, required = declared_parameters(tool)
            missing = missing_argument(exc, safe_arguments, declared)
            if missing is None:
                raise
            result = ToolResult(
                name=tool_call.name,
                output=missing_argument_message(tool_call.name, missing, required),
                metadata={"error": "missing_argument", "argument": missing},
            )
            if output_callback is not None:
                output_callback(ToolOutputChunk(result.output, dict(result.metadata)))
            return result

        if isinstance(output, AsyncIterable):
            items: list[Any] = []
            async for item in output:
                items.append(item)
            output = items
        return self._collect_output(tool_call.name, output, output_callback)

    def run_many(
        self, tool_calls: list[ToolCall], context: ToolContext
    ) -> ToolRunnerResult:
        result = ToolRunnerResult()
        for tool_call in tool_calls:
            tool = self.registry.get(tool_call.name)
            if tool is None:
                result.missing_tools.append(tool_call.name)
                continue
            result.results.append(self.run_tool_call(tool_call, context))
        return result
