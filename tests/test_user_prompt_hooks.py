"""on_user_prompt hooks were documented but never called by any run path."""

from __future__ import annotations

import asyncio

from shipit_agent.async_runtime import AsyncAgentRuntime
from shipit_agent.hooks import AgentHooks
from shipit_agent.llms.base import LLMResponse
from shipit_agent.runtime import AgentRuntime


class Echo:
    def __init__(self):
        self.seen: list[str] = []

    def complete(self, *, messages, tools=None, **_):
        user = [m for m in messages if m.role == "user"]
        self.seen.append(user[-1].content if user else "")
        return LLMResponse(content="ok")


def test_a_rewrite_reaches_the_model():
    hooks = AgentHooks()
    hooks.on_user_prompt(lambda prompt: prompt.replace("SECRET-123", "[redacted]"))
    llm = Echo()
    AgentRuntime(llm=llm, prompt="p", hooks=hooks).run("my key is SECRET-123")
    assert "SECRET-123" not in llm.seen[0] and "[redacted]" in llm.seen[0]


def test_a_deny_blocks_the_run_before_the_model():
    hooks = AgentHooks()
    hooks.on_user_prompt(lambda prompt: {"decision": "deny", "reason": "no secrets"} if "key" in prompt else None)
    llm = Echo()
    state, response = AgentRuntime(llm=llm, prompt="p", hooks=hooks).run("my key")
    assert llm.seen == [] and response.content == "Request blocked: no secrets"
    assert any(e.type == "prompt_blocked" for e in state.events)


def test_no_hooks_and_observe_only_hooks_change_nothing():
    hooks = AgentHooks()
    hooks.on_user_prompt(lambda prompt: None)
    llm = Echo()
    AgentRuntime(llm=llm, prompt="p", hooks=hooks).run("hello")
    assert llm.seen[0].startswith("hello")


def test_the_async_runtime_calls_them_too():
    hooks = AgentHooks()
    hooks.on_user_prompt(lambda prompt: "rewritten: " + prompt)
    llm = Echo()
    asyncio.run(AsyncAgentRuntime(llm=llm, prompt="p", hooks=hooks).run("hello"))
    assert llm.seen[0].startswith("rewritten: hello")
