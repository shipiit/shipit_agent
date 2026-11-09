"""A system message in ``messages`` reaches Anthropic when no ``system_prompt`` is given.

Callers such as the verifier, the memory consolidator and the autopilot critic
send their instructions as a system message; the Anthropic API takes the system
prompt as a separate field, so the adapter must lift it out rather than drop it.
"""

from __future__ import annotations

from shipit_agent.llms import AnthropicChatLLM
from shipit_agent.models import Message


def build(messages: list, system_prompt: str | None = None) -> dict:
    llm = AnthropicChatLLM(model="claude-haiku-5-5", prompt_caching=False)
    return llm._build_request_kwargs(messages=messages, tools=None, system_prompt=system_prompt, documents=None)


def test_a_system_message_becomes_the_system_prompt() -> None:
    kwargs = build([Message(role="system", content="Reply in JSON."), Message(role="user", content="hi")])
    assert kwargs["system"] == "Reply in JSON."
    assert [m["role"] for m in kwargs["messages"]] == ["user"]


def test_dict_system_messages_work_too_and_several_are_joined() -> None:
    kwargs = build([
        {"role": "system", "content": "Be strict."},
        {"role": "system", "content": "Reply in JSON."},
        {"role": "user", "content": "hi"},
    ])
    assert kwargs["system"] == "Be strict.\n\nReply in JSON."


def test_an_explicit_system_prompt_still_wins() -> None:
    kwargs = build([Message(role="system", content="from messages"), Message(role="user", content="hi")], system_prompt="explicit")
    assert kwargs["system"] == "explicit"


def test_no_system_anywhere_sends_an_empty_system() -> None:
    assert build([Message(role="user", content="hi")])["system"] == ""


def test_empty_system_messages_are_ignored() -> None:
    assert build([Message(role="system", content=""), Message(role="user", content="hi")])["system"] == ""
