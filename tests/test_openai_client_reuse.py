"""The OpenAI adapter reuses one client across calls instead of one per call."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from shipit_agent.core.models import Message
from shipit_agent.llms.openai_adapter import OpenAIChatLLM

_RESPONSE = types.SimpleNamespace(
    choices=[
        types.SimpleNamespace(
            message=types.SimpleNamespace(content="ok", tool_calls=None),
            finish_reason="stop",
        )
    ],
    usage=None,
)


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    sink: dict[str, Any] = {"clients": 0, "with_options": []}

    class _Completions:
        def create(self, **kwargs: Any) -> Any:
            sink["created"] = kwargs
            return _RESPONSE

    class OpenAI:
        def __init__(self, **options: Any) -> None:
            sink["clients"] += 1
            self.chat = types.SimpleNamespace(completions=_Completions())

        def with_options(self, **options: Any) -> "OpenAI":
            sink["with_options"].append(options)
            return self

    fake = types.ModuleType("openai")
    fake.OpenAI = OpenAI
    monkeypatch.setitem(sys.modules, "openai", fake)
    return sink


def _ask(llm: OpenAIChatLLM, **extra: Any) -> Any:
    return llm.complete(messages=[Message(role="user", content="hi")], **extra)


def test_one_client_serves_every_call(sdk: dict[str, Any]) -> None:
    llm = OpenAIChatLLM(model="gpt-5.5", api_key="k")
    assert _ask(llm).content == "ok"
    _ask(llm)
    assert sdk["clients"] == 1


def test_a_per_call_timeout_uses_the_same_client(sdk: dict[str, Any]) -> None:
    llm = OpenAIChatLLM(model="gpt-5.5", api_key="k")
    _ask(llm, timeout=9.0)
    assert sdk["clients"] == 1
    assert sdk["with_options"] == [{"timeout": 9.0}]
