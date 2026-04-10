from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class AgentHooks:
    """Lightweight callback hooks for agent lifecycle events.

    Attach callbacks to run before/after LLM calls and tool calls.
    Useful for cost tracking, rate limiting, content filtering,
    custom logging, and guardrails.

    Example::

        hooks = AgentHooks()

        @hooks.on_before_llm
        def log_llm_call(messages, tools):
            print(f"LLM call with {len(messages)} messages")

        @hooks.on_after_tool
        def log_tool_result(name, result):
            print(f"Tool {name} returned: {result.output[:50]}")

        agent = Agent(llm=llm, hooks=hooks)
    """

    before_llm: list[Callable[..., None]] = field(default_factory=list)
    after_llm: list[Callable[..., None]] = field(default_factory=list)
    before_tool: list[Callable[..., None]] = field(default_factory=list)
    after_tool: list[Callable[..., None]] = field(default_factory=list)

    def on_before_llm(self, fn: Callable[..., None]) -> Callable[..., None]:
        """Decorator to register a before-LLM hook."""
        self.before_llm.append(fn)
        return fn

    def on_after_llm(self, fn: Callable[..., None]) -> Callable[..., None]:
        """Decorator to register an after-LLM hook."""
        self.after_llm.append(fn)
        return fn

    def on_before_tool(self, fn: Callable[..., None]) -> Callable[..., None]:
        """Decorator to register a before-tool hook."""
        self.before_tool.append(fn)
        return fn

    def on_after_tool(self, fn: Callable[..., None]) -> Callable[..., None]:
        """Decorator to register an after-tool hook."""
        self.after_tool.append(fn)
        return fn

    def run_before_llm(self, messages: list[Any], tools: list[Any]) -> None:
        for fn in self.before_llm:
            fn(messages, tools)

    def run_after_llm(self, response: Any) -> None:
        for fn in self.after_llm:
            fn(response)

    def run_before_tool(self, name: str, arguments: dict[str, Any]) -> None:
        for fn in self.before_tool:
            fn(name, arguments)

    def run_after_tool(self, name: str, result: Any) -> None:
        for fn in self.after_tool:
            fn(name, result)
