"""An option the model's adapter cannot honour is reported, not silently dropped."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import AgentOptions, build_agent


class _Plain:
    """An adapter with none of the Anthropic-only settings."""

    model = "gpt-5"

    def complete(self, **_: Any) -> LLMResponse:
        return LLMResponse(content="ok")


class _Capable(_Plain):
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.effort = None
        self.thinking = None
        self.cache_ttl = None
        self.thinking_budget_tokens = None
        self.betas: list[str] = []


@pytest.mark.parametrize(
    "option",
    [{"effort": "high"}, {"thinking": "adaptive"}, {"cache_ttl": "1h"}, {"max_thinking_tokens": 2048},
     {"betas": ["some-beta"]}],
)
def test_an_unsupported_option_is_warned_about(tmp_path: Path, caplog: pytest.LogCaptureFixture,
                                               option: dict[str, Any]) -> None:
    with caplog.at_level(logging.WARNING, logger="shipit_agent.sdk.build"):
        build_agent(AgentOptions(llm=_Plain(), cwd=tmp_path, tools=[], **option))
    name = next(iter(option))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert name in warnings[0].getMessage() and "gpt-5" in warnings[0].getMessage()


def test_a_supported_option_is_applied_without_a_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    llm = _Capable()
    with caplog.at_level(logging.WARNING, logger="shipit_agent.sdk.build"):
        build_agent(AgentOptions(llm=llm, cwd=tmp_path, tools=[], effort="high", cache_ttl="1h",
                                 max_thinking_tokens=2048, betas=["b"]))
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    assert (llm.effort, llm.cache_ttl, llm.thinking_budget_tokens, llm.betas) == ("high", "1h", 2048, ["b"])


def test_unset_options_say_nothing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="shipit_agent.sdk.build"):
        build_agent(AgentOptions(llm=_Plain(), cwd=tmp_path, tools=[], betas=[], max_thinking_tokens=0))
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
