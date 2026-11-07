"""DelegationPolicy: when to tell the model to delegate, and the tool it delegates with."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .advice import DelegationAdvice
from .model import ModelAssessor

# ── policy ────────────────────────────────────────────────────────────────


@dataclass
class DelegationPolicy:
    """When to push the agent toward sub-agents, and how hard.

    ``assessor`` decides whether a task decomposes — :class:`ModelAssessor`
    by default (one cheap call, cached), :class:`StructuralAssessor` for a
    zero-cost approximation, or anything implementing :class:`Assessor`.

    ``attach_tool`` builds a ``sub_agent`` when the agent has none; turn it
    off to supply your own — a narrower toolset, a cheaper model for the
    children, a lower iteration cap.
    """

    enabled: bool = True
    min_items: int = 2
    attach_tool: bool = True
    max_iterations: int = 6
    max_workers: int = 4
    assessor: Any = None
    # Children get read-only tools by default: a sub-agent that can write is
    # a side effect you did not review, from a decision you did not see.
    child_tools: list[Any] | None = None
    read_only_children: bool = True

    def __post_init__(self) -> None:
        if self.assessor is None:
            self.assessor = ModelAssessor(min_items=self.min_items)

    # ── assessment ───────────────────────────────────────────────────────

    def assess(self, prompt: str, *, llm: Any = None) -> DelegationAdvice:
        """Read the task and decide whether it wants delegating."""
        if not self.enabled or not prompt:
            return DelegationAdvice(False)
        advice = self.assessor.assess(prompt, llm=llm)
        if advice.items and advice.items < self.min_items:
            return DelegationAdvice(False, items=advice.items,
                                    reasons=advice.reasons, source=advice.source)
        return advice

    # ── the directive ────────────────────────────────────────────────────

    def directive(self, advice: DelegationAdvice) -> str:
        """The instruction appended to the *task* for this run.

        Appended to the task rather than the system prompt on purpose: a
        small model reads the system prompt as background and the task as
        instructions, and the difference is measurable (see the module
        docstring).
        """
        if not advice:
            return ""
        because = "; ".join(advice.reasons) or "it has independent parts"
        count = f"about {advice.items}" if advice.items > 1 else "several"
        return (
            "\n\n---\n"
            f"This task has {count} separable pieces — {because}. "
            "Work it that way:\n"
            "- Send **each piece** to `sub_agent`, with a task naming the one "
            "thing it must do and the exact shape of the answer you want back.\n"
            "- Run independent pieces at once: `background=true` starts one, "
            '`collect="<id>"` fetches its result. Collect every one of them '
            "before you answer — the run ends with your answer, so a task "
            "left uncollected is simply lost, and promising the user a "
            "later report is promising something that cannot happen.\n"
            "- Do not read the material yourself. The point of a sub-agent is "
            "that what it read never enters your context — only its answer does.\n"
            "- Combine the answers yourself; do not delegate the combining."
        )

    def apply(self, task: str, *, llm: Any = None) -> str:
        """The task, with the directive appended when it is warranted."""
        return task + self.directive(self.assess(task, llm=llm))

    # ── tool ─────────────────────────────────────────────────────────────

    def build_tool(self, llm: Any, tools: list[Any]) -> Any | None:
        """A ``sub_agent`` for this agent, or ``None`` if one is unwarranted."""
        if not self.enabled or not self.attach_tool or llm is None:
            return None
        from shipit_agent.tools.sub_agent import SubAgentTool

        child_tools = self.child_tools
        if child_tools is None and self.read_only_children:
            from shipit_agent.safety.permissions import PermissionEngine

            engine = PermissionEngine()
            child_tools = [
                tool
                for tool in tools
                if engine.is_read_only(getattr(tool, "name", ""), tool)
            ] or None
        return SubAgentTool(
            llm=llm,
            tools=child_tools,
            max_iterations=self.max_iterations,
            max_workers=self.max_workers,
        )


def coerce_delegation(spec: Any) -> DelegationPolicy | None:
    """Normalize ``delegation=`` — a policy, ``True``, a dict, or ``None``."""
    if spec is None or spec is False:
        return None
    if isinstance(spec, DelegationPolicy):
        return spec if spec.enabled else None
    if spec is True:
        return DelegationPolicy()
    if isinstance(spec, dict):
        return DelegationPolicy(**spec)
    raise TypeError(f"Unsupported delegation spec: {type(spec)!r}")
