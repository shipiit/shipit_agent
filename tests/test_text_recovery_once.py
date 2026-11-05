"""Text-only recovery happens once per turn; its reply is the answer.

A model whose replies look like tool calls but parse as none used to cycle:
nudge, switch to text-only, the reply still looks like a call, switch again.
Under a step limit that ended at the limit; with no limit it never ended.
"""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent
from shipit_agent.llms.base import LLMResponse


class _EchoesItsPrompt:
    """Replies with its system prompt, which is full of tool-call examples."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, system_prompt: str | None = None, **_: Any) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content=system_prompt or "")


def test_recovery_runs_once_and_the_turn_ends(tmp_path) -> None:
    llm = _EchoesItsPrompt()
    agent = Agent.with_builtins(llm=llm, project_root=str(tmp_path))

    result = agent.run("hello world")

    switches = [e for e in result.events if e.payload.get("recovery") == "text_only"]
    assert len(switches) == 1
    assert llm.calls <= 4
    assert result.output.strip()
