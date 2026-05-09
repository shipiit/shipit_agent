"""Verifier network — process supervision for agent runs.

Two complementary checks, both opt-in, both backed by a (typically cheap)
verifier LLM:

* **Pre-tool veto** — before each tool fires, the verifier sees the proposed
  call (name + args + recent history) and returns ``allow``, ``veto``, or
  ``rewrite``. Vetoed calls become synthetic error tool-results so the agent
  re-plans without the bad action having actually executed.

* **Progress check** — after each agent iteration, the verifier rates
  "did we make progress?" 0-1. If the score drops below a threshold for N
  consecutive iterations, the agent gets a synthetic "you're stalling, try
  a different angle" hint injected as a user message.

Both modes can run with the same model as the main agent (cheaper hops) or
a different one (e.g. Haiku verifying Opus's plans). They're designed to be
used together but each works standalone.

Quick start::

    from shipit_agent import Agent
    from shipit_agent.verifier import VerifierNetwork

    verifier = VerifierNetwork(
        llm=cheap_llm,
        veto_enabled=True,
        progress_enabled=True,
        progress_threshold=0.4,
    )
    agent = Agent(llm=main_llm, tools=tools, verifier=verifier)
"""

from __future__ import annotations

from .models import (
    PreToolDecision,
    ProgressCheck,
    VerifierConfig,
    VerifierVerdict,
)
from .progress import ProgressVerifier
from .pre_tool import PreToolVerifier, wrap_tool_with_verifier
from .verifier_network import VerifierNetwork

__all__ = [
    "PreToolDecision",
    "PreToolVerifier",
    "ProgressCheck",
    "ProgressVerifier",
    "VerifierConfig",
    "VerifierNetwork",
    "VerifierVerdict",
    "wrap_tool_with_verifier",
]
