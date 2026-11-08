"""An agent that breaks a goal into steps, checks success criteria and corrects course.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .goal_prompts import (
    DECOMPOSE_PROMPT as DECOMPOSE_PROMPT,
)
from .goal_prompts import (
    EVALUATE_PROMPT as EVALUATE_PROMPT,
)
from .goal_steps import _GoalSteps
from .goal_stream import _GoalStream


@dataclass(slots=True)
class Goal:
    """A structured goal with success criteria."""

    objective: str
    success_criteria: list[str] = field(default_factory=list)
    max_steps: int = 20


@dataclass(slots=True)
class GoalResult:
    """Result of a goal-directed agent run."""

    goal: Goal
    output: str
    goal_status: str = "unknown"  # "completed" | "partial" | "failed"
    criteria_met: list[bool] = field(default_factory=list)
    steps_taken: int = 0
    step_outputs: list[dict[str, Any]] = field(default_factory=list)
    #: ``usage`` (tokens summed over the step runs), ``model`` and ``tool_calls``:
    #: what Autopilot's budget meters read.
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.goal.objective,
            "status": self.goal_status,
            "criteria_met": self.criteria_met,
            "steps_taken": self.steps_taken,
            "output": self.output[:500],
        }


class GoalAgent(_GoalSteps, _GoalStream):
    """Autonomous agent that decomposes goals, tracks progress, and self-corrects.

    Unlike a regular agent that follows instructions, a GoalAgent:
    1. Decomposes the goal into sub-tasks
    2. Executes each sub-task
    3. Self-evaluates after each step
    4. Continues until all success criteria are met

    Example::

        agent = GoalAgent(
            llm=llm, tools=[code_exec, file_writer],
            goal=Goal(
                objective="Build a calculator CLI",
                success_criteria=["Handles +, -, *, /", "Has error handling", "Has tests"],
            ),
        )
        result = agent.run()
        print(result.goal_status)  # "completed"
        print(result.criteria_met)  # [True, True, True]
    """

    def __init__(
        self,
        *,
        llm: Any,
        tools: list[Any] | None = None,
        mcps: list[Any] | None = None,
        goal: Goal,
        use_builtins: bool = False,
        prompt: str = "You are a helpful assistant. Complete the task thoroughly.",
        memory: Any = None,
        rag: Any = None,
        **agent_kwargs: Any,
    ) -> None:
        self.llm = llm
        self.tools = tools or []
        self.mcps = mcps or []
        self.goal = goal
        self.use_builtins = use_builtins
        self.prompt = prompt
        self.memory = memory
        self.rag = rag
        self.agent_kwargs = agent_kwargs

    def _build_agent(self) -> Any:
        """Build the inner agent with full capabilities."""
        from shipit_agent.agent import Agent

        extra = dict(self.agent_kwargs)
        if self.memory:
            # AgentMemory.knowledge is a SemanticMemory, not a MemoryStore —
            # they have different interfaces. Only hydrate the conversation
            # history here; users pass memory_store= explicitly if they
            # want the runtime's memory tool wired up too.
            if hasattr(self.memory, "get_conversation_messages"):
                extra.setdefault("history", self.memory.get_conversation_messages())
        if self.rag is not None:
            extra.setdefault("rag", self.rag)
        if self.use_builtins:
            return Agent.with_builtins(
                llm=self.llm,
                prompt=self.prompt,
                mcps=self.mcps,
                **extra,
            )
        return Agent(
            llm=self.llm,
            prompt=self.prompt,
            tools=list(self.tools),
            mcps=self.mcps,
            **extra,
        )

    def _save_to_memory(self, role: str, content: str) -> None:
        """Store a message in memory if memory is attached."""
        if self.memory and hasattr(self.memory, "add_message"):
            from shipit_agent.core.models import Message

            self.memory.add_message(Message(role=role, content=content))

    @classmethod
    def with_builtins(
        cls,
        *,
        llm: Any,
        goal: Goal,
        mcps: list[Any] | None = None,
        rag: Any = None,
        **kwargs: Any,
    ) -> "GoalAgent":
        """Create a GoalAgent with all built-in tools (web search, code exec, etc.)."""
        return cls(llm=llm, goal=goal, mcps=mcps, use_builtins=True, rag=rag, **kwargs)

    def run(self) -> GoalResult:
        agent = self._build_agent()
        self._save_to_memory("user", f"Goal: {self.goal.objective}")
        subtasks = self._decompose()
        work_done: list[str] = []
        step_outputs: list[dict[str, Any]] = []
        meter = _UsageMeter(model=str(getattr(self.llm, "model", "") or ""))

        for step_num, task in enumerate(subtasks[: self.goal.max_steps], 1):
            result = agent.run(task)
            meter.add(result)
            work_done.append(result.output)
            self._save_to_memory("assistant", f"Step {step_num}: {result.output[:500]}")
            step_outputs.append(
                {"step": step_num, "task": task, "output": result.output[:300]}
            )

            evaluation = self._evaluate(work_done)
            criteria_met = evaluation.get("criteria_met", [])

            if evaluation.get("all_done"):
                return GoalResult(
                    goal=self.goal,
                    output=result.output,
                    goal_status="completed",
                    criteria_met=criteria_met,
                    steps_taken=step_num,
                    step_outputs=step_outputs,
                    metadata=meter.metadata(),
                )

        final_eval = self._evaluate(work_done)
        criteria_met = final_eval.get(
            "criteria_met", [False] * len(self.goal.success_criteria)
        )
        met_count = sum(1 for c in criteria_met if c)
        status = (
            "completed"
            if met_count == len(self.goal.success_criteria)
            else ("partial" if met_count > 0 else "failed")
        )

        return GoalResult(
            goal=self.goal,
            output=work_done[-1] if work_done else "",
            goal_status=status,
            criteria_met=criteria_met,
            steps_taken=len(work_done),
            step_outputs=step_outputs,
            metadata=meter.metadata(),
        )


class _UsageMeter:
    """Token usage and tool calls summed over a goal's step runs."""

    _KEYS = ("prompt_tokens", "completion_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")

    def __init__(self, *, model: str) -> None:
        self.model = model
        self.usage = dict.fromkeys(self._KEYS, 0)
        self.tool_calls = 0

    def add(self, result: Any) -> None:
        usage = (getattr(result, "metadata", None) or {}).get("usage") or {}
        for key in self._KEYS:
            value = usage.get(key)
            if isinstance(value, int):
                self.usage[key] += value
        self.tool_calls += len(getattr(result, "tool_results", None) or [])

    def metadata(self) -> dict[str, Any]:
        usage = {**self.usage, "total_tokens": self.usage["prompt_tokens"] + self.usage["completion_tokens"]}
        return {"usage": usage, "model": self.model, "tool_calls": self.tool_calls}
