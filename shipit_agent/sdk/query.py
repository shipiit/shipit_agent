"""``query()``: one prompt in, the run's messages out, as in the Claude Agent SDK.

    async for message in query(prompt="Find the flaky test", options=AgentOptions(cwd=".")):
        if isinstance(message, ResultMessage):
            print(message.result)
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from .build import build_agent
from .convert import MessageStream, error_result
from .options import AgentOptions
from .tools import HOME_LOOP
from .types import Message, ResultMessage

__all__ = ["query", "run_messages"]


async def query(*, prompt: str, options: AgentOptions | None = None) -> AsyncIterator[Message]:
    """Run *prompt* with a new agent built from *options*; yield each message."""
    options = options or AgentOptions()
    async for message in run_messages(build_agent(options), prompt, options):
        yield message


async def run_messages(agent: Any, prompt: str, options: AgentOptions) -> AsyncIterator[Message]:
    """One run of *agent* as SDK messages; shared by :func:`query` and the client.

    The run never raises: an error ends it with an ``error_during_execution``
    ``ResultMessage``, as the SDK's stream does.
    """
    schema = options.output_schema()
    text = prompt
    if schema is not None:
        from shipit_agent.core.structured import build_schema_prompt

        text = prompt + build_schema_prompt(schema)
    stream = MessageStream(init=_init_data(agent, options), partial=options.include_partial_messages)
    started = time.monotonic()
    try:
        async for event in _events(agent, text):
            for message in stream.feed(event):
                if isinstance(message, ResultMessage) and schema is not None:
                    await _parse_structured(agent, message, schema)
                yield message
    except Exception as error:
        yield error_result(
            error, session_id=stream.session_id, duration_ms=int((time.monotonic() - started) * 1000)
        )


async def _events(agent: Any, prompt: str) -> AsyncIterator[Any]:
    """The run's events, with the run on a worker thread.

    The caller's loop stays free, so async callbacks, hooks and tools can
    await work that loop does; :data:`HOME_LOOP` sends their coroutines here.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Any] = asyncio.Queue()
    done = object()

    def produce() -> None:
        try:
            for event in agent.stream(prompt):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except BaseException as error:
            loop.call_soon_threadsafe(queue.put_nowait, error)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, done)

    token = HOME_LOOP.set(loop)
    try:
        worker = asyncio.ensure_future(asyncio.to_thread(produce))
    finally:
        HOME_LOOP.reset(token)
    try:
        while (item := await queue.get()) is not done:
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        if not worker.done():
            agent.cancel()
        await asyncio.gather(worker, return_exceptions=True)


def _init_data(agent: Any, options: AgentOptions) -> dict[str, Any]:
    return {
        "model": str(getattr(agent.llm, "model", "") or ""),
        "tools": sorted(str(getattr(tool, "name", "")) for tool in agent.tools),
        "mcp_servers": [str(getattr(server, "name", "")) for server in agent.mcps],
        "agents": sorted(options.agents or {}),
        "permission_mode": options.permission_mode,
        "cwd": str(agent.project_root),
        "session_id": options.session_id or "",
        **(agent.harness.info() if agent.harness is not None else
           {"plugins": [], "plugin_errors": [], "skills": [], "slash_commands": []}),
    }


async def _parse_structured(agent: Any, message: ResultMessage, schema: dict[str, Any]) -> None:
    """Fill ``structured_output``; one that never parses becomes an error result."""
    from shipit_agent.core.structured_output import validate_with_retry

    parsed, text, _, _ = await asyncio.to_thread(
        validate_with_retry, llm=agent.llm, raw_text=message.result or "", schema=schema, history=[]
    )
    if parsed is None:
        message.subtype = "error_max_structured_output_retries"
        message.is_error = True
        message.errors.append("the answer did not match output_format")
        return
    message.structured_output = parsed
    message.result = text or message.result
