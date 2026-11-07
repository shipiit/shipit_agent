"""A run's usage reads the same whichever way the provider counts cache.

Anthropic reports `prompt_tokens` without cached input and the cache
counters beside it; OpenAI-style adapters include cached input in
`prompt_tokens` (and say so). The usage of a run, as the SDK's
ResultMessage carries it, now also has the SDK's shape: `input_tokens`
(uncached), the two cache counters, `output_tokens`. Total input is their
sum for every provider. Before, a benchmark of Claude counted only the
uncached remainder: 8 input tokens for a request of thousands.
"""

from __future__ import annotations

import asyncio

import pytest

from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import AgentOptions, ResultMessage, query


class Reports:
    model = "m"

    def __init__(self, usage: dict, inclusive: bool) -> None:
        self.usage, self.inclusive = usage, inclusive

    def complete(self, **_):
        metadata = {"prompt_tokens_include_cache": True} if self.inclusive else {}
        return LLMResponse(content="done", usage=dict(self.usage), metadata=metadata)


def _usage(llm) -> dict:
    async def run():
        async for message in query(prompt="hi", options=AgentOptions(llm=llm)):
            if isinstance(message, ResultMessage):
                return message.usage
    return asyncio.run(run())


@pytest.mark.parametrize("usage, inclusive", [
    ({"prompt_tokens": 8, "completion_tokens": 50, "cache_read_input_tokens": 3000,
      "cache_creation_input_tokens": 500}, False),               # Anthropic's way
    ({"prompt_tokens": 3508, "completion_tokens": 50, "cache_read_input_tokens": 3000,
      "cache_creation_input_tokens": 500}, True),                # OpenAI's way
], ids=["anthropic", "openai"])
def test_usage_has_the_sdk_shape_for_every_provider(usage: dict, inclusive: bool) -> None:
    got = _usage(Reports(usage, inclusive))
    assert got["input_tokens"] == 8
    assert got["cache_read_input_tokens"] == 3000 and got["cache_creation_input_tokens"] == 500
    assert got["output_tokens"] == 50


def test_the_benchmark_counts_all_input(tmp_path) -> None:
    from scripts.bench.run import _row
    from scripts.bench.run import TASKS
    from scripts.bench.tasks_basic import Run

    run = Run(root=tmp_path)
    run.record(ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                             session_id="s", usage={"input_tokens": 8, "cache_read_input_tokens": 3000,
                                                    "cache_creation_input_tokens": 500, "output_tokens": 50,
                                                    "prompt_tokens": 8, "completion_tokens": 50}))
    row = _row(TASKS[0], run, True, "ok", 0.0)
    assert row["input_tokens"] == 3508 and row["output_tokens"] == 50
    assert row["cached_input_tokens"] == 3000
