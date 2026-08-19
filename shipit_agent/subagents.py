"""Delegating work to a child run that keeps its own context.

Delegation is worth having for one reason: an agent that reads twenty files into
one context and an agent that reads twenty files in twenty contexts and keeps
only the summaries do the same work, and the second one can still think
afterwards. The saving is real only if three things hold, and each is easy to
lose:

**The child's context does not come back.** Only its final answer joins the
parent's history. If transcripts merge, delegation costs more than doing the
work inline — the parent pays for the child's reading *and* its own.

**The child's tools are narrower, not inherited.** A researcher gets read-only
tools. Passing the parent's full set down means a child can take actions the
delegation was never scoped for, and it inflates every child's prompt with
schemas it will not use.

**The child's tokens are counted.** Child runs happen outside the parent's
streaming loop, so a tracker wired only to that loop reports a fraction of the
real cost — and reports it lowest on exactly the runs that cost most, because
delegation is what multiplies calls. The ledger is shared, tagged by purpose.

Child events are re-emitted on the parent's stream wrapped as ``subagent_event``
so a UI can show progress without the two runs' output interleaving.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

from shipit_agent.graph import AgentGraph, RunSpec
from shipit_agent.models import AgentEvent, ToolResult
from shipit_agent.usage import Purpose, UsageLedger

logger = logging.getLogger(__name__)

__all__ = ["SubagentSpec", "SubagentTool", "run_subagent", "READ_ONLY_TOOLS"]

#: A sensible default narrowing: a delegated investigation reads and reports.
#: Anything that writes, executes or calls out belongs to the parent, which has
#: the context to judge whether it should happen.
READ_ONLY_TOOLS = frozenset(
    {
        "file_read",
        "glob_search",
        "grep_search",
        "web_search",
        "open_url",
        "file_extract",
        "vision",
        "pdf",
    }
)

DEFAULT_SUBAGENT_PROMPT = (
    "You are a focused sub-agent. Complete exactly the task you were given and "
    "nothing beyond it. Your reply is the only thing that reaches the parent "
    "agent, so make it self-contained: state findings and their sources, and "
    "leave out your process. Be concise — the parent pays for every word."
)


@dataclass
class SubagentSpec:
    """How to build a child run from a parent's resources."""

    llm: Any
    model: str
    tools: Sequence[Any] = ()
    system_prompt: str = DEFAULT_SUBAGENT_PROMPT
    max_iterations: int = 6
    max_tool_output_chars: int = 8_000
    #: Names the child may use. Defaults to the read-only set.
    allowed_tools: frozenset[str] = READ_ONLY_TOOLS
    #: Depth guard. A child that can spawn children can recurse forever.
    max_depth: int = 2
    depth: int = 0
    skills: Sequence[Any] = field(default_factory=tuple)

    def narrowed_tools(self) -> list[Any]:
        """The parent's tools, filtered to what this child is scoped for."""
        return [t for t in self.tools if getattr(t, "name", "") in self.allowed_tools]

    def child(self) -> "SubagentSpec":
        """A spec one level deeper, for a child that may itself delegate."""
        return SubagentSpec(
            llm=self.llm,
            model=self.model,
            tools=self.tools,
            system_prompt=self.system_prompt,
            max_iterations=self.max_iterations,
            max_tool_output_chars=self.max_tool_output_chars,
            allowed_tools=self.allowed_tools,
            max_depth=self.max_depth,
            depth=self.depth + 1,
            skills=self.skills,
        )


def run_subagent(
    spec: SubagentSpec,
    task: str,
    *,
    ledger: UsageLedger | None = None,
    label: str = "subagent",
) -> Iterator[AgentEvent]:
    """Run a child and yield its events wrapped for the parent's stream.

    The child's answer is delivered in the final ``subagent_completed`` event.
    Its transcript is deliberately not returned: keeping it out of the parent's
    history is the entire point of delegating.
    """
    if spec.depth >= spec.max_depth:
        yield AgentEvent(
            type="subagent_completed",
            message="Delegation depth limit reached.",
            payload={
                "label": label,
                "answer": (
                    "Delegation depth limit reached; this task must be handled "
                    "directly rather than delegated further."
                ),
                "depth": spec.depth,
                "refused": True,
            },
        )
        return

    yield AgentEvent(
        type="subagent_started",
        message=task[:200],
        payload={"label": label, "depth": spec.depth, "task": task},
    )

    child_ledger = ledger or UsageLedger()
    graph = AgentGraph(
        RunSpec(
            llm=spec.llm,
            model=spec.model,
            system_prompt=spec.system_prompt,
            tools=spec.narrowed_tools(),
            skills=spec.skills,
            max_iterations=spec.max_iterations,
            max_tool_output_chars=spec.max_tool_output_chars,
            ledger=child_ledger,
        )
    )

    answer = ""
    for event in graph.run(task):
        if event.type in ("final_answer", "run_completed") and event.payload.get("text"):
            answer = str(event.payload["text"])
        # Wrapped, not forwarded: a parent UI can nest these under one row
        # instead of interleaving two runs' text.
        yield AgentEvent(
            type="subagent_event",
            message=event.display_message,
            payload={"label": label, "depth": spec.depth, "event": event.to_dict()},
        )

    # Attribute the child's tokens to the parent's ledger, tagged so the run
    # summary shows where they went.
    if ledger is None:
        for event_usage in child_ledger.events:
            logger.debug("Sub-agent usage: %s", event_usage)

    yield AgentEvent(
        type="subagent_completed",
        message=answer[:200],
        payload={
            "label": label,
            "depth": spec.depth,
            "answer": answer,
            "usage": child_ledger.totals(),
        },
    )


class SubagentTool:
    """The tool a parent calls to delegate.

    Returns only the child's answer. The parent's context grows by one summary
    rather than by a whole investigation, which is the saving delegation exists
    to produce.
    """

    name = "sub_agent"
    description = (
        "Delegate a self-contained sub-task to a focused agent with its own "
        "context. Use this for work that requires reading a lot of material to "
        "produce a short conclusion — investigating several files, summarising "
        "many documents, or researching one question — so the detail stays out "
        "of this conversation. Give a complete, standalone task description; "
        "the sub-agent cannot see this conversation."
    )
    prompt_instructions = (
        "Delegate when a task is self-contained and detail-heavy. Give the "
        "sub-agent everything it needs in the task text — it sees nothing else."
    )

    def __init__(
        self,
        spec: SubagentSpec,
        *,
        ledger: UsageLedger | None = None,
        emit: Any = None,
    ) -> None:
        self._spec = spec
        self._ledger = ledger
        self._emit = emit

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": (
                                "Complete, standalone description of the work. "
                                "The sub-agent has no other context."
                            ),
                        },
                        "label": {
                            "type": "string",
                            "description": "Short name for this sub-task, for the trace.",
                        },
                    },
                    "required": ["task"],
                },
            },
        }

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        from shipit_agent.tools_compat import make_output

        task = str(kwargs.get("task", "")).strip()
        if not task:
            return make_output("No task given. Describe the work in full.")

        label = str(kwargs.get("label") or "subagent")
        answer = ""
        usage: dict[str, Any] = {}
        for event in run_subagent(
            self._spec.child(), task, ledger=self._ledger, label=label
        ):
            if self._emit is not None:
                self._emit(event)
            if event.type == "subagent_completed":
                answer = str(event.payload.get("answer", ""))
                usage = dict(event.payload.get("usage", {}) or {})

        if self._ledger is not None and usage:
            self._ledger.sink(Purpose.SUBAGENT, self._spec.model, agent=label)(
                {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                }
            )

        return make_output(
            answer or "The sub-agent produced no answer.",
            metadata={"label": label, "usage": usage, "depth": self._spec.depth + 1},
        )
