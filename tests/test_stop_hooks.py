"""Stop hooks: keep the agent working until the job is really done.

A hook sees the answer the agent is about to give and may send it back with a
reason. The cap keeps a hook that never relents from looping a run forever.
"""

from __future__ import annotations

import asyncio

from shipit_agent.async_runtime import AsyncAgentRuntime
from shipit_agent.hooks import AgentHooks
from shipit_agent.llms.base import LLMResponse
from shipit_agent.runtime import AgentRuntime


class ScriptedLLM:
    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.seen: list[list] = []

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None, **_):
        self.seen.append(list(messages))
        return LLMResponse(content=self.answers.pop(0) if self.answers else "final")


def runtime(llm, hooks, cls=AgentRuntime):
    return cls(llm=llm, prompt="You are helpful.", max_iterations=8, hooks=hooks)


def kinds(state):
    return [event.type for event in state.events]


def test_a_stop_hook_sends_the_agent_back_until_satisfied():
    hooks = AgentHooks()

    @hooks.on_stop
    def needs_summary(answer):
        return None if "Summary:" in answer else "End with a 'Summary:' line."

    llm = ScriptedLLM("Here is the plan.", "Here is the plan.\nSummary: ship Friday.")
    state, response = runtime(llm, hooks).run("Plan the release")
    assert response.content.endswith("Summary: ship Friday.")
    assert kinds(state).count("stop_blocked") == 1
    blocked = next(e for e in state.events if e.type == "stop_blocked")
    assert blocked.payload["reason"] == "End with a 'Summary:' line."
    nudge = llm.seen[1][-1]
    assert nudge.role == "user" and nudge.content.startswith("Not done yet: End with")
    assert nudge.metadata["kind"] == "stop_hook"
    assert llm.seen[1][-2].content == "Here is the plan."


def test_the_dict_form_and_an_allowing_hook():
    hooks = AgentHooks()
    calls = []
    hooks.on_stop(lambda answer: calls.append(answer))
    hooks.on_stop(lambda answer: {"decision": "block", "reason": "Cite a source."}
                  if "http" not in answer else {"decision": "allow"})
    state, response = runtime(ScriptedLLM("No link", "See https://e.x"), hooks).run("q")
    assert response.content == "See https://e.x"
    assert calls == ["No link", "See https://e.x"]
    assert kinds(state).count("stop_blocked") == 1


def test_a_hook_that_never_relents_is_capped():
    hooks = AgentHooks()
    hooks.on_stop(lambda answer: "Never good enough.")
    llm = ScriptedLLM(*[f"attempt {i}" for i in range(10)])
    state, response = runtime(llm, hooks).run("q")
    assert kinds(state).count("stop_blocked") == AgentRuntime.MAX_STOP_CONTINUATIONS
    assert kinds(state).count("stop_unresolved") == 1
    assert response.content == f"attempt {AgentRuntime.MAX_STOP_CONTINUATIONS}"


def test_a_broken_hook_lets_the_run_finish():
    hooks = AgentHooks()

    def broken(answer):
        raise RuntimeError("bug in hook")

    hooks.on_stop(broken)
    state, response = runtime(ScriptedLLM("done"), hooks).run("q")
    assert response.content == "done"
    assert "stop_hook_error" in kinds(state)


def test_no_stop_hooks_changes_nothing():
    llm = ScriptedLLM("done")
    state, response = runtime(llm, AgentHooks()).run("q")
    assert response.content == "done" and len(llm.seen) == 1
    assert "stop_blocked" not in kinds(state)


def test_the_async_runtime_honours_stop_hooks_too():
    hooks = AgentHooks()
    hooks.on_stop(lambda answer: None if "OK" in answer else "Say OK.")
    llm = ScriptedLLM("Nope", "OK now")
    state, response = asyncio.run(runtime(llm, hooks, AsyncAgentRuntime).run("q"))
    assert response.content == "OK now"
    assert kinds(state).count("stop_blocked") == 1
