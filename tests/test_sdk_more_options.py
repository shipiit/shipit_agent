"""More of the Claude Agent SDK's options: continue_conversation, env, betas, max_thinking_tokens."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from shipit_agent.llms import LLMResponse
from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM
from shipit_agent.sdk import AgentOptions, ResultMessage, build_agent, query
from shipit_agent.stores.session import InMemorySessionStore


class Echo:
    model = "m"

    def complete(self, *, messages, **_):
        return LLMResponse(content=f"seen {sum(m.role == 'user' for m in messages)} user turns")


def _run(prompt: str, **options) -> ResultMessage:
    async def run():
        async for message in query(prompt=prompt, options=AgentOptions(llm=Echo(), tools=[], **options)):
            if isinstance(message, ResultMessage):
                return message
    return asyncio.run(run())


def test_continue_conversation_picks_up_the_most_recent_session() -> None:
    store = InMemorySessionStore()
    _run("first", session_store=store, session_id="older")
    _run("second", session_store=store, session_id="newer")
    _run("third", session_store=store, session_id="older")         # older is now the latest
    result = _run("again", session_store=store, continue_conversation=True)
    assert result.session_id == "older"
    assert result.result == "seen 3 user turns"                     # first, third and this one


def test_continue_conversation_with_no_session_yet_starts_one() -> None:
    store = InMemorySessionStore()
    assert _run("hello", session_store=store, continue_conversation=True).result == "seen 1 user turns"


def test_continue_conversation_needs_a_session_store() -> None:
    with pytest.raises(ValueError, match="session_store"):
        build_agent(AgentOptions(llm=Echo(), continue_conversation=True))


def test_env_reaches_the_tools_commands_only(tmp_path: Path) -> None:
    agent = build_agent(AgentOptions(llm=Echo(), cwd=tmp_path, env={"SHIPIT_TEST_TOKEN": "abc"}))
    shells = [t for t in agent.tools if t.name in ("bash", "run_code")]
    assert shells and all(t.extra_env.get("SHIPIT_TEST_TOKEN") == "abc" for t in shells)
    bash = next(t for t in shells if t.name == "bash")
    assert bash._child_env()["SHIPIT_TEST_TOKEN"] == "abc"


def _anthropic_kwargs(options: AgentOptions) -> dict:
    agent = build_agent(options)
    from shipit_agent.core.models import Message

    return agent.llm._build_request_kwargs(messages=[Message(role="user", content="hi")], tools=None,
                                           system_prompt="s", documents=None)


def test_betas_are_sent_to_anthropic() -> None:
    llm = AnthropicChatLLM(model="claude-sonnet-5-5", prompt_caching=False)
    kwargs = _anthropic_kwargs(AgentOptions(llm=llm, tools=[], betas=["context-1m-2025-08-07"]))
    assert "context-1m-2025-08-07" in kwargs["betas"]


@pytest.mark.parametrize("model, expected", [
    ("claude-sonnet-4", {"type": "enabled", "budget_tokens": 4000}),  # takes a budget
    ("claude-sonnet-5-5", {"type": "adaptive"}),                      # rejects budgets
])
def test_max_thinking_tokens_sets_a_thinking_budget(model: str, expected: dict) -> None:
    llm = AnthropicChatLLM(model=model, prompt_caching=False)
    assert _anthropic_kwargs(AgentOptions(llm=llm, tools=[], max_thinking_tokens=4000))["thinking"] == expected
