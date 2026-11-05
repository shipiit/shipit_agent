"""``AgentClient``: a multi-turn session, like the Claude Agent SDK's client.

    async with AgentClient(AgentOptions(cwd=".")) as client:
        await client.query("Read app.py and find the bug")
        async for message in client.receive_response():
            print(message)
        await client.query("Now fix it")          # same conversation
        async for message in client.receive_response():
            ...

Each response starts with a ``UserMessage`` echoing the prompt; its
``uuid`` is what :meth:`rewind_files` takes.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

from .build import build_agent, llm_for_model
from .checkpoints import FileCheckpoints
from .options import AgentOptions
from .query import run_messages
from .status import context_usage, mcp_status
from .types import Message, ResultMessage, UserMessage

__all__ = ["AgentClient"]

_CLOSED = object()


class AgentClient:
    """One conversation with one agent, turn after turn."""

    def __init__(self, options: AgentOptions | None = None) -> None:
        self.options = options or AgentOptions()
        self._agent: Any = None
        self._primary_llm: Any = None
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._runs: list[asyncio.Task[None]] = []
        self._checkpoints: FileCheckpoints | None = None

    async def __aenter__(self) -> "AgentClient":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.disconnect()

    async def connect(self, prompt: str | None = None) -> None:
        """Build the agent; send *prompt* as the first turn if given."""
        if self._agent is None:
            self._agent = _session_agent(self.options)
            self._primary_llm = self._agent.llm
            if self.options.enable_file_checkpointing:
                self._checkpoints = FileCheckpoints(self._agent.project_root)
                self._agent.hooks.on_before_tool(self._checkpoints.before_tool)
        if prompt is not None:
            await self.query(prompt)

    async def query(self, prompt: str | AsyncIterable[dict[str, Any]]) -> None:
        """Start a turn; its messages arrive through :meth:`receive_response`.

        An async iterable of SDK user messages starts one turn per message.
        """
        await self.connect()
        if not isinstance(prompt, str):
            from .query import user_text

            async for item in prompt:
                await self.query(user_text(item))
            return
        message_id = str(uuid.uuid4())
        if self._checkpoints is not None:
            self._checkpoints.begin_turn(message_id)
        previous = self._runs[-1] if self._runs else None
        self._runs.append(asyncio.create_task(self._turn(prompt, message_id, previous)))

    async def _turn(self, prompt: str, message_id: str, previous: asyncio.Task[None] | None) -> None:
        if previous is not None:
            await asyncio.gather(previous, return_exceptions=True)
        await self._queue.put(UserMessage(content=prompt, uuid=message_id))
        async for message in run_messages(self._agent, prompt, self.options):
            await self._queue.put(message)

    async def receive_messages(self) -> AsyncIterator[Message]:
        """Every message from every turn, until :meth:`disconnect`."""
        while True:
            message = await self._queue.get()
            if message is _CLOSED:
                return
            yield message

    async def receive_response(self) -> AsyncIterator[Message]:
        """The messages of the current turn, up to and including its ``ResultMessage``."""
        async for message in self.receive_messages():
            yield message
            if isinstance(message, ResultMessage):
                return

    async def interrupt(self) -> None:
        """Stop the current turn between steps; it ends with its ``ResultMessage``."""
        if self._agent is not None:
            self._agent.cancel()

    async def set_permission_mode(self, mode: str) -> None:
        """Change the permission mode, for this turn's remaining calls and later turns."""
        agent = await self._connected()
        agent.permission_mode = mode
        engine_mode = "bypass" if mode == "bypassPermissions" else mode
        engines = [agent.permissions, agent._session_runtime_state.get("permission_engine"),
                   getattr(getattr(agent, "_active_runtime", None), "permissions", None)]
        for engine in engines:
            if engine is not None and hasattr(engine, "mode"):
                engine.mode = engine_mode

    async def set_model(self, model: str | None = None) -> None:
        """Use *model* from the next model call on; ``None`` goes back to the first one."""
        agent = await self._connected()
        if model is None:
            llm = self._primary_llm
        elif hasattr(self._primary_llm, "model") and self.options.llm is not None:
            from shipit_agent.llms.fallback import fallback_llms

            llm = fallback_llms(self._primary_llm, model)[0]
        else:
            llm = llm_for_model(model)
        agent.llm = llm
        runtime = getattr(agent, "_active_runtime", None)
        if runtime is not None:
            runtime.llm = llm

    async def rewind_files(self, user_message_id: str) -> list[str]:
        """Put files back as they were before that turn; needs ``enable_file_checkpointing``."""
        if self._checkpoints is None:
            raise RuntimeError("rewind_files needs AgentOptions(enable_file_checkpointing=True)")
        return [str(path) for path in self._checkpoints.rewind(user_message_id)]

    async def get_context_usage(self) -> dict[str, Any]:
        """How full the context window is: the fixed prefix and the conversation so far."""
        return context_usage(await self._connected())

    async def get_mcp_status(self) -> dict[str, Any]:
        """Each MCP server's state (``connected`` or ``failed``) and its tools."""
        return await asyncio.to_thread(mcp_status, await self._connected())

    async def stop_task(self, task_id: str) -> None:
        """Stop a background sub-agent task the agent started."""
        agent = await self._connected()
        candidates = [*agent.tools, getattr(agent, "_auto_sub_agent", None)]
        for candidate in candidates:
            stop = getattr(candidate, "stop_task", None)
            if callable(stop) and stop(task_id):
                return
        raise KeyError(f"no background task {task_id!r}")

    async def disconnect(self) -> None:
        """Stop any running turn and end :meth:`receive_messages`."""
        if self._agent is not None and any(not run.done() for run in self._runs):
            self._agent.cancel()
        await asyncio.gather(*self._runs, return_exceptions=True)
        self._runs.clear()
        await self._queue.put(_CLOSED)

    async def _connected(self) -> Any:
        await self.connect()
        return self._agent


def _session_agent(options: AgentOptions) -> Any:
    from shipit_agent.stores.session import InMemorySessionStore

    agent = build_agent(options)
    agent.session_id = agent.session_id or str(uuid.uuid4())
    if agent.session_store is None:
        agent.session_store = InMemorySessionStore()
    if agent.hooks is None:
        from shipit_agent.safety.hooks import AgentHooks

        agent.hooks = AgentHooks()
    return agent
