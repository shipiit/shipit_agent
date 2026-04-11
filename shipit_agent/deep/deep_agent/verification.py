"""Verification step used by ``DeepAgent(verify=True)``.

A thin wrapper around :class:`VerifierTool` that scores a final answer
against a set of success criteria. Used both by the synchronous
``run()`` path (attaches the verdict to ``result.metadata['verification']``)
and by the streaming path (emits a final ``run_completed`` event with
type ``verification_completed``).
"""
from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.verifier import VerifierTool

from ..goal_agent import Goal


def verify_text(text: str, *, goal: Goal | None = None) -> dict[str, Any]:
    """Score ``text`` against the goal's success criteria.

    When ``goal`` is ``None`` we fall back to a single generic
    criterion ("Answer is concrete and addresses the user's question.").
    """
    criteria = list(goal.success_criteria) if goal is not None else []
    if not criteria:
        criteria = ["Answer is concrete and addresses the user's question."]

    verifier = VerifierTool()
    output = verifier.run(
        ToolContext(prompt=text, metadata={}, state={}),
        content=text,
        criteria=criteria,
    )
    return {"text": output.text, "metadata": dict(output.metadata)}


__all__ = ["verify_text"]
