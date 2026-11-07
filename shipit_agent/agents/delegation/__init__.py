"""Automatic delegation — the agent reaches for sub-agents on its own.

Handing work to a sub-agent is the difference between an agent that reads
twenty files into one context and an agent that reads twenty files in twenty
contexts and keeps only the summaries. Left to a plain prompt, a model does
this rarely: the tool exists, the guidance is a paragraph in the system
prompt, and the straight path is right there.

This module makes it a policy::

    agent = Agent(llm=llm, tools=[...], delegation=True)
    agent.run("Summarize each of the twelve incident reports in reports/.")

Three decisions, each of which was measured rather than assumed:

**The tool is guaranteed to exist.** If the agent has no ``sub_agent``, one
is built from the agent's own LLM and its read-only tools.

**The task is assessed by a model, not by a word list.** A keyword table is a
guess about one language's phrasing that goes stale the moment someone writes
"handle these tickets" instead of "for each ticket". :class:`ModelAssessor`
asks the LLM a single cheap question about the task and gets back a count and
a reason. :class:`StructuralAssessor` is the fallback when there is no model
to ask: it counts *structure* — enumerated lists, distinct concrete targets,
explicit quantities — never vocabulary.

**The directive goes in the task, not the system prompt.** Measured against
Gemma 4 on Bedrock with three reports to summarize: system prompt → 0
delegations, same text appended to the task → 6. A small model treats the
system prompt as background and the task as instructions.

What this deliberately does **not** do is delegate behind the model's back.
The runtime cannot know which parts of a task are independent, and guessing
would spawn sub-agents working on halves of an indivisible problem. The model
still decides — with the tool present and the case put in the right place.

The package: ``advice``, ``structural`` and ``model`` (the two assessors),
and ``policy`` (DelegationPolicy and coerce_delegation).
"""

from __future__ import annotations

from .advice import Assessor, DelegationAdvice
from .model import ModelAssessor
from .policy import DelegationPolicy, coerce_delegation
from .structural import StructuralAssessor

__all__ = [
    "Assessor",
    "DelegationAdvice",
    "DelegationPolicy",
    "ModelAssessor",
    "StructuralAssessor",
    "coerce_delegation",
]
