"""max_session_tokens — one budget across every run of an agent or chat."""

from __future__ import annotations

import asyncio

import pytest

from shipit_agent import Agent
from shipit_agent.llms.base import LLMResponse

USAGE = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}


class Model:
    def __init__(self, usage: dict | None = None) -> None:
        self.calls, self.usage = 0, USAGE if usage is None else usage

    def complete(self, **_kw) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content="answer", usage=dict(self.usage))


def make(model: Model, **kwargs) -> Agent:
    return Agent(llm=model, auto_use_skills=False, auto_project_memory=False,
                 auto_project_skills=False, **kwargs)


def summary(result) -> dict:
    return result.metadata["run_summary"]


@pytest.mark.parametrize("async_run", [False, True])
def test_the_budget_spans_runs_and_stops_before_spending(async_run):
    model = Model()
    agent = make(model, max_session_tokens=250)
    go = (lambda p: asyncio.run(agent.arun(p))) if async_run else agent.run
    go("a")
    go("b")
    third = go("c")
    assert model.calls == 3  # 110, 220, then 220 < 250 still allowed one step
    assert summary(third).get("incomplete_reason") is None

    fourth = go("d")
    assert model.calls == 3  # exhausted: no model call at all
    assert summary(fourth)["incomplete_reason"] == "session_token_budget"
    assert "session" in fourth.output.lower()
    assert agent.session_token_usage == 330


def test_usage_is_reported_on_every_run():
    agent = make(Model(), max_session_tokens=10_000)
    agent.run("a")
    diagnostics = summary(agent.run("b"))["usage_diagnostics"]
    assert diagnostics["session_token_limit"] == 10_000
    assert diagnostics["session_tokens_used"] == 220


def test_a_chat_session_shares_one_budget_across_turns():
    model = Model()
    chat = make(model, max_session_tokens=200).chat_session(session_id="s1")
    chat.send("a")
    chat.send("b")
    third = chat.send("c")
    assert model.calls == 2
    assert summary(third)["incomplete_reason"] == "session_token_budget"


def test_separate_chats_have_separate_budgets():
    model = Model()
    agent = make(model, max_session_tokens=150)
    agent.chat_session(session_id="one").send("a")
    agent.chat_session(session_id="two").send("a")
    assert model.calls == 2


def test_a_clone_starts_with_a_fresh_budget():
    model = Model()
    agent = make(model, max_session_tokens=100)
    agent.run("a")
    agent.run("b")
    assert model.calls == 1
    agent.clone().run("c")
    assert model.calls == 2


def test_reset_session_usage_reopens_the_budget():
    model = Model()
    agent = make(model, max_session_tokens=100)
    agent.run("a")
    agent.reset_session_usage()
    assert agent.session_token_usage == 0
    agent.run("b")
    assert model.calls == 2


def test_without_a_limit_usage_is_still_tracked_and_nothing_stops():
    model = Model()
    agent = make(model)
    for prompt in "abcd":
        agent.run(prompt)
    assert model.calls == 4
    assert agent.session_token_usage == 440


def test_missing_usage_does_not_let_a_budgeted_session_run_blind():
    model = Model(usage={})
    agent = make(model, max_session_tokens=1_000)
    result = agent.run("a")
    assert model.calls == 1 and summary(result).get("incomplete_reason") is None
    blocked = agent.run("b")
    assert model.calls == 1
    assert summary(blocked)["incomplete_reason"] == "session_budget_usage_unavailable"


@pytest.mark.parametrize("limit", [0, -1, True, 2.5, "100"])
def test_invalid_session_budget(limit):
    with pytest.raises(ValueError, match="max_session_tokens"):
        make(Model(), max_session_tokens=limit)
