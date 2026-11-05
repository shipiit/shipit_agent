"""An MCP server's own instructions reach the model, labelled as the server's.

MCP servers may send usage guidance in their initialize handshake. Only the
retired graph loop showed it to the model; the one loop now does, under the
server's name, so it reads as the server's advice and not the agent's.
"""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent
from shipit_agent.llms.base import LLMResponse


class _Server:
    def __init__(self, name: str, instructions: str) -> None:
        self.name = name
        self.instructions = instructions

    def discover_tools(self) -> list[Any]:
        return []


class _Records:
    def __init__(self) -> None:
        self.system = ""

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.system = next(m.content for m in messages if m.role == "system")
        return LLMResponse(content="ok")


def test_server_instructions_reach_the_prompt_under_the_servers_name() -> None:
    llm = _Records()
    Agent(llm=llm, mcps=[_Server("tickets", "Always pass project_id.")]).run("hi")
    assert "Always pass project_id." in llm.system
    assert "tickets" in llm.system


def test_a_server_without_instructions_adds_nothing() -> None:
    llm = _Records()
    Agent(llm=llm, mcps=[_Server("quiet", "")]).run("hi")
    assert "Instructions from MCP servers" not in llm.system


def test_the_section_is_stable_across_steps() -> None:
    llm = _Records()
    agent = Agent(llm=llm, mcps=[_Server("tickets", "Always pass project_id.")])
    agent.run("one")
    first = llm.system
    agent.run("two")
    assert llm.system == first
