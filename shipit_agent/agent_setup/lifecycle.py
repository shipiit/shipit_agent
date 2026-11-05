"""An agent's lifecycle: cancel, close, use as a context manager, clone, or wrap as a tool.

Mixed into :class:`~shipit_agent.agent.Agent`; the methods run on the agent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shipit_agent.agent import Agent

# Moved methods log under the agent's own name, so filters and levels
# configured for it keep applying.
logger = logging.getLogger("shipit_agent.agent")


class AgentLifecycleMixin:
    """An agent's lifecycle: cancel, close, use as a context manager, clone, or wrap as a tool."""

    def cancel(self) -> None:
        """Cancel the in-flight ``run()`` / ``stream()`` (thread-safe).

        The loop stops at its next checkpoint — before the next LLM call or
        tool execution — emits ``run_cancelled``, and returns normally with
        whatever was produced so far. Call from another thread (e.g. a
        keyboard handler) while the agent is working; no-op when idle.
        """
        runtime = self._active_runtime
        if runtime is not None:
            runtime.cancel()

    def close(self) -> None:
        """Release MCP transports kept alive across this agent's turns."""
        if self._closed:
            return
        self._closed = True
        for mcp in self.mcps:
            close = getattr(mcp, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.debug("MCP close failed", exc_info=True)

    def __enter__(self) -> "Agent":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    async def __aenter__(self) -> "Agent":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Release provider/MCP resources without blocking an event loop."""
        await asyncio.to_thread(self.close)

    @property
    def session_token_usage(self) -> int:
        """Tokens spent across every run of this agent's session so far."""
        return int(self._session_runtime_state.get("session_tokens", 0))

    def reset_session_usage(self) -> None:
        """Start the session budget over — e.g. for a long-lived server agent
        at the start of a new billing window."""
        self._session_runtime_state.pop("session_tokens", None)
        self._session_runtime_state.pop("session_usage_complete", None)

    def clone(self, **changes: Any) -> "Agent":
        """Copy this agent with selected configuration overrides.

        Mutable configuration containers are copied, while LLMs and durable
        stores are intentionally shared unless explicitly replaced.
        """
        from dataclasses import fields, replace

        hooks = self.hooks
        if hooks is not None:
            hooks = replace(
                hooks,
                **{
                    item.name: list(getattr(hooks, item.name))
                    for item in fields(hooks)
                    if isinstance(getattr(hooks, item.name), list)
                },
            )

        defaults = {
            "tools": list(self.tools),
            "mcps": list(self.mcps),
            "required_tools": list(self.required_tools),
            "metadata": dict(self.metadata),
            "history": list(self.history),
            "skills": list(self.skills),
            "default_skill_ids": list(self.default_skill_ids),
            "rules": list(self.rules),
            "hooks": hooks,
            # Contributions are already present in tools/hooks. Re-activation
            # would duplicate tools and mutate callbacks on every chat turn.
            "plugins": [],
        }
        defaults.update(changes)
        cloned = replace(self, **defaults)
        if "plugins" not in changes:
            cloned.plugins = list(self.plugins)
        return cloned

    def as_tool(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        session_id: str | None = None,
        stream_events: bool = True,
    ) -> Any:
        """Expose this agent as a specialist tool for another agent."""
        from shipit_agent.tools.agent_tool import AgentTool

        return AgentTool(
            agent=self,
            name=name or self.name,
            description=description or self.description or f"Delegate to {self.name}.",
            session_id=session_id,
            stream_events=stream_events,
        )
