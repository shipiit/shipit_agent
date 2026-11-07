"""Streamed text is emitted before anything that follows the model call.

Text deltas are handed to the event loop to emit; the turn carried on and
could emit assistant_message, final_answer and run_completed first, so a
stream or transcript saw the answer after the run had ended (and the
transcript showed it twice: once from run_completed, once from the late
deltas). It surfaced as a flaky test_streaming_frames test.
"""

from __future__ import annotations

from shipit_agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.narrate import ProseRow


class StreamsThenReturns:
    """An async adapter that streams its answer and returns without yielding."""

    model = "m"

    async def acomplete(self, *, messages, tools=None, system_prompt=None, metadata=None,
                        text_delta_callback=None, **_):
        for chunk in ("Login ", "has no ", "MFA."):
            text_delta_callback(chunk)
        return LLMResponse(content="Login has no MFA.")

    def complete(self, **kwargs):  # pragma: no cover - the async path is used
        raise AssertionError("expected acomplete")


def test_every_text_delta_comes_before_the_run_completes() -> None:
    kinds = [e.type for e in Agent(llm=StreamsThenReturns(), auto_use_skills=False).stream("go")]
    deltas = [i for i, k in enumerate(kinds) if k == "text_delta"]
    assert len(deltas) == 3
    assert max(deltas) < kinds.index("assistant_message") < kinds.index("run_completed")


def test_the_answer_appears_once_in_the_transcript() -> None:
    rows = list(Agent(llm=StreamsThenReturns(), auto_use_skills=False).narrate("go"))
    assert [r.text for r in rows if isinstance(r, ProseRow)] == ["Login has no MFA."]
