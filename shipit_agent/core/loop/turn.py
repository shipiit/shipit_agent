"""What one turn carries from its setup, through its steps, to its finish.

A turn has three phases: :meth:`~shipit_agent.core.async_runtime.AsyncAgentRuntime._begin_turn`
prepares everything the model needs, ``_run_steps`` calls the model and runs
tools until it answers, and ``_finish_turn`` saves the session and reports the
result. :class:`Turn` is the hand-off between them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shipit_agent.context.session_facts import FactLedger
from shipit_agent.core.models import Message
from shipit_agent.core.registry import ToolRegistry
from shipit_agent.core.state import RuntimeState
from shipit_agent.core.tool_runner import ToolRunner
from shipit_agent.llms.base import LLMResponse


@dataclass
class Turn:
    """The state one turn passes between its setup, steps and finish."""

    #: The user's prompt after prompt hooks and guardrails have rewritten it.
    user_prompt: str
    state: RuntimeState
    registry: ToolRegistry
    tool_runner: ToolRunner
    tool_schemas: list[dict[str, Any]]
    #: The system prompt for this turn, tools section included.
    base_prompt: str
    #: Mutable tool state shared by every tool call in the turn.
    shared_state: dict[str, Any]
    #: The stored session this turn continues, if any.
    existing_session: Any
    fact_ledger: FactLedger
    #: Earlier turns' messages as stored, before any per-request trimming.
    original_prior: list[Message] = field(default_factory=list)
    #: The model's latest response; the final answer once the steps finish.
    response: LLMResponse = field(default_factory=lambda: LLMResponse(content=""))
    #: ``id()`` of the response already added to the transcript, so the finish
    #: phase doesn't append the same answer twice.
    appended_response_id: int | None = None
