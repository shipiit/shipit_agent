"""System messages a caller passes in ``history=`` reach the model.

A conversation summary (``ConversationMemory(strategy="summary")``) arrives as a
system message. The runtime drops system messages from earlier turns so a stored
session doesn't stack old prompts, but a caller's own history must keep them.
"""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, InMemorySessionStore
from shipit_agent.llms import LLMResponse
from shipit_agent.models import Message


class Spy:
    model = "spy"

    def __init__(self) -> None:
        self.calls: list[list[Message]] = []
        self.system_prompts: list[str] = []

    def complete(self, *, messages: list[Message], system_prompt: str | None = None, **_: Any) -> LLMResponse:
        self.calls.append(list(messages))
        self.system_prompts.append(system_prompt or "")
        return LLMResponse(content="ok")


def _system(messages: list[Message]) -> list[str]:
    return [m.content for m in messages if m.role == "system"]


def test_a_history_system_message_is_kept_in_the_one_system_message() -> None:
    spy = Spy()
    history = [Message(role="system", content="Summary: Ada is vegetarian."), Message(role="user", content="hi"),
               Message(role="assistant", content="hello")]
    Agent(llm=spy, prompt="BASE", history=history).run("q")
    (system,) = _system(spy.calls[0])
    assert system.startswith("BASE")
    assert "Summary: Ada is vegetarian." in system
    # Adapters that take the system prompt as its own field (Anthropic) get it too.
    assert "Summary: Ada is vegetarian." in spy.system_prompts[0]


def test_a_history_copy_of_the_prompt_is_not_repeated() -> None:
    spy = Spy()
    Agent(llm=spy, prompt="BASE", history=[Message(role="system", content="BASE"), Message(role="user", content="hi")]).run("q")
    assert _system(spy.calls[0]) == ["BASE"]


def test_stored_session_prompts_still_do_not_stack() -> None:
    spy, store = Spy(), InMemorySessionStore()
    agent = Agent(llm=spy, prompt="BASE", session_store=store, session_id="s")
    agent.run("one")
    agent.run("two")
    agent.run("three")
    assert _system(spy.calls[-1]) == ["BASE"]
