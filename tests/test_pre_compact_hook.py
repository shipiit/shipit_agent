"""A pre-compact hook sees the conversation before it is summarized, and can steer the summary.

Like Claude's PreCompact hook: the host is told compaction is about to run
(to archive the full transcript, say), and text it returns is added to the
summarizer's instructions, for what the handoff must keep.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.context.compaction import Compactor
from shipit_agent.core.models import Message
from shipit_agent.core.runtime import AgentRuntime
from shipit_agent.core.state import RuntimeState
from shipit_agent.llms.base import LLMResponse
from shipit_agent.safety.hooks import AgentHooks


class _Summarizer:
    def __init__(self) -> None:
        self.system_prompts: list[str] = []

    def complete(self, *, system_prompt: str | None = None, **_: Any) -> LLMResponse:
        self.system_prompts.append(system_prompt or "")
        return LLMResponse(content="handoff")


def _history(turns: int) -> list[Message]:
    messages: list[Message] = []
    for index in range(turns):
        messages.append(Message(role="user", content=f"question {index} " + "x" * 400))
        messages.append(
            Message(role="assistant", content=f"answer {index} " + "y" * 400)
        )
    return messages


def test_instructions_reach_the_summarizer() -> None:
    llm = _Summarizer()
    compactor = Compactor(llm=llm, context_window_tokens=1_000)
    compactor.compact(
        _history(20), force=True, instructions="Keep every file path mentioned."
    )
    assert "Keep every file path mentioned." in llm.system_prompts[-1]


def test_the_runtime_calls_the_hook_before_compacting() -> None:
    seen: list[dict[str, Any]] = []

    def archive(messages: list[Message], info: dict[str, Any]) -> str:
        seen.append({"count": len(messages), **info})
        return "Keep the customer's order number."

    hooks = AgentHooks()
    hooks.on_pre_compact(archive)
    llm = _Summarizer()
    runtime = AgentRuntime(
        llm=llm, prompt="p", context_window_tokens=1_000, hooks=hooks
    )
    runtime.compact(RuntimeState(), _history(20), 1)

    assert len(seen) == 1
    assert seen[0]["count"] == 40
    assert seen[0]["trigger"] == "auto"
    assert seen[0]["budget_tokens"] > 0
    assert any("order number" in prompt for prompt in llm.system_prompts)


def test_no_hook_runs_when_nothing_needs_compacting() -> None:
    calls: list[int] = []
    hooks = AgentHooks()
    hooks.on_pre_compact(lambda messages, info: calls.append(1))
    runtime = AgentRuntime(llm=_Summarizer(), prompt="p", hooks=hooks)
    runtime.compact(RuntimeState(), _history(1), 1)
    assert calls == []


def test_a_hook_returning_nothing_changes_nothing() -> None:
    hooks = AgentHooks()
    hooks.on_pre_compact(lambda messages, info: None)
    assert hooks.run_pre_compact([], {"trigger": "auto"}) == ""
