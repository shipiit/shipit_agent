"""Compaction uses each Claude model's real context window.

The compaction table had several current Claude models at 128K or 200K when
they take 1M, so long runs compacted (and lost detail) far too early. Claude
limits now come from the one Claude model table.
"""

from __future__ import annotations

import pytest

from shipit_agent.context.compaction import get_model_limits
from shipit_agent.llms.claude_models import STREAMING_OUTPUT_CAP


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "claude-fable-5-1",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "us.anthropic.claude-sonnet-5-5",
        "bedrock/anthropic.claude-opus-5-5",
    ],
)
def test_current_claude_models_get_a_million_tokens(model: str) -> None:
    limits = get_model_limits(model)
    assert limits.context_window == 1_000_000
    assert limits.max_output_tokens == STREAMING_OUTPUT_CAP


def test_haiku_4_5_keeps_its_200k_window() -> None:
    assert get_model_limits("claude-haiku-4-5").context_window == 200_000


def test_other_models_still_use_the_table() -> None:
    assert get_model_limits("gpt-5.5").context_window == 400_000
    assert get_model_limits("totally-unknown").context_window == 128_000
