"""Provider omissions must not bypass task/session token budgets."""
from types import SimpleNamespace

import pytest

from shipit_agent.llms.base import LLMResponse
from shipit_agent.llms.openai_adapter import _usage_dict
from shipit_agent.llms.usage import has_complete_token_usage, normalize_token_usage


@pytest.mark.parametrize("wrap", [dict, lambda **kw: SimpleNamespace(**kw)])
@pytest.mark.parametrize("bad", [None, True, -1, "12", 1.5])
def test_invalid_counter_stays_unknown(wrap, bad):
    usage = normalize_token_usage(wrap(prompt_tokens=bad, completion_tokens=5))
    assert "prompt_tokens" not in usage
    assert not has_complete_token_usage(LLMResponse(content="", usage=usage))


def test_explicit_zero_is_valid():
    assert normalize_token_usage({"prompt_tokens": 0, "completion_tokens": 0}) == {
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
    }


def test_anthropic_field_names_preserve_omissions():
    assert normalize_token_usage(SimpleNamespace(input_tokens=8),
                                 input_key="input_tokens", output_key="output_tokens") == {
        "prompt_tokens": 8,
    }


def test_openai_cache_only_usage_does_not_invent_free_completion():
    usage = _usage_dict(SimpleNamespace(
        prompt_tokens_details=SimpleNamespace(cached_tokens=100), total_tokens=110,
    ))
    assert usage == {"total_tokens": 110, "cache_read_input_tokens": 100}
    assert not has_complete_token_usage(LLMResponse(content="", usage=usage))


@pytest.mark.parametrize("stream", [False, True])
def test_native_anthropic_missing_output_remains_unknown(monkeypatch, stream):
    import sys
    from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM
    from shipit_agent.models import Message

    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="answer")],
        usage=SimpleNamespace(input_tokens=15), stop_reason="end_turn",
    )
    class Stream:
        text_stream = ["answer"]
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get_final_message(self):
            return response
    messages = SimpleNamespace(create=lambda **kw: response, stream=lambda **kw: Stream())
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=lambda **kw:
        SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))))
    result = AnthropicChatLLM(model="fixture").complete(
        messages=[Message(role="user", content="hello")],
        text_delta_callback=(lambda text: None) if stream else None,
    )
    assert result.usage == {"prompt_tokens": 15}
    assert not has_complete_token_usage(result)


@pytest.mark.parametrize("provider", ["openai", "litellm"])
@pytest.mark.parametrize("stream", [False, True])
def test_adapter_omission_blocks_next_budgeted_run(monkeypatch, provider, stream):
    import sys
    from shipit_agent import Agent
    from shipit_agent.llms.openai_adapter import OpenAIChatLLM
    from shipit_agent.llms.litellm_adapter import LiteLLMChatLLM

    calls = []
    def complete(**kwargs):
        calls.append(kwargs)
        usage = SimpleNamespace(total_tokens=10)
        message = SimpleNamespace(content="answer", tool_calls=None)
        if kwargs.get("stream"):
            return iter([SimpleNamespace(choices=[SimpleNamespace(
                delta=message, finish_reason="stop")], usage=usage)])
        return SimpleNamespace(choices=[SimpleNamespace(message=message,
                               finish_reason="stop")], usage=usage)

    if provider == "openai":
        monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kw:
            SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))))
        llm = OpenAIChatLLM(model="fixture", api_key="fixture")
    else:
        monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=complete))
        llm = LiteLLMChatLLM(model="fixture")
    agent = Agent(llm=llm, max_session_tokens=100, auto_use_skills=False,
                  auto_project_memory=False, auto_project_skills=False)
    if stream:
        list(agent.stream("hello"))
    else:
        agent.run("hello")
    result = agent.run("continue")
    assert len(calls) == 1
    assert result.metadata["run_summary"]["incomplete_reason"] == "session_budget_usage_unavailable"
