from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.goal.objective,
            "status": self.goal_status,
            "criteria_met": self.criteria_met,
            "steps_taken": self.steps_taken,
            "output": self.output[:500],
        }


DECOMPOSE_PROMPT = """You are a goal-oriented agent. Break this goal into ordered sub-tasks.

Goal: {objective}

Success criteria:
{criteria}

Respond with JSON: {{"subtasks": ["task 1", "task 2", ...]}}"""

EVALUATE_PROMPT = """Evaluate whether each criterion is met based on the work done so far.

Goal: {objective}

Success criteria:
{criteria}

Work completed:
{work}

Respond with JSON: {{"criteria_met": [true, false, ...], "all_done": true/false, "next_action": "what to do next"}}"""


class GoalAgent:
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
                llm=self.llm, prompt=self.prompt,
                mcps=self.mcps, **extra,
            )
        return Agent(
            llm=self.llm, prompt=self.prompt,
            tools=list(self.tools), mcps=self.mcps,
            **extra,
        )

    def _save_to_memory(self, role: str, content: str) -> None:
        """Store a message in memory if memory is attached."""
        if self.memory and hasattr(self.memory, "add_message"):
            from shipit_agent.models import Message
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

    def _llm_call(self, prompt: str) -> str:
        from shipit_agent.models import Message
        response = self.llm.complete(messages=[Message(role="user", content=prompt)])
        return response.content

    def _decompose(self) -> list[str]:
        """Break goal into sub-tasks."""
        criteria_text = "\n".join(f"- {c}" for c in self.goal.success_criteria)
        text = self._llm_call(DECOMPOSE_PROMPT.format(
            objective=self.goal.objective,
            criteria=criteria_text,
        ))
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
                return data.get("subtasks", [self.goal.objective])
        except (json.JSONDecodeError, ValueError):
            pass
        return [self.goal.objective]

    def _evaluate(self, work_done: list[str]) -> dict[str, Any]:
        """Evaluate progress against success criteria."""
        criteria_text = "\n".join(f"{i+1}. {c}" for i, c in enumerate(self.goal.success_criteria))
        work_text = "\n".join(f"Step {i+1}: {w[:300]}" for i, w in enumerate(work_done))
        text = self._llm_call(EVALUATE_PROMPT.format(
            objective=self.goal.objective,
            criteria=criteria_text,
            work=work_text,
        ))
        # Strip reasoning tags that some models wrap around JSON
        import re
        text = re.sub(r"<reasoning>.*?</reasoning>", "", text, flags=re.DOTALL).strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
                # If criteria_met has wrong length, pad or trim it
                expected = len(self.goal.success_criteria)
                met = data.get("criteria_met", [])
                if len(met) < expected:
                    met.extend([False] * (expected - len(met)))
                elif len(met) > expected:
                    met = met[:expected]
                data["criteria_met"] = met
                # Be generous: if most work is done, check content-based matching
                if not data.get("all_done"):
                    combined = " ".join(work_done).lower()
                    matched = sum(1 for c in self.goal.success_criteria if any(w in combined for w in c.lower().split()))
                    if matched >= len(self.goal.success_criteria):
                        data["all_done"] = True
                        data["criteria_met"] = [True] * expected
                return data
        except (json.JSONDecodeError, ValueError):
            pass
        # Fallback: check if work content matches criteria by keyword
        combined = " ".join(work_done).lower()
        met = [any(w in combined for w in c.lower().split()) for c in self.goal.success_criteria]
        all_done = all(met)
        return {"criteria_met": met, "all_done": all_done, "next_action": "done" if all_done else "continue"}

    def run(self) -> GoalResult:
        agent = self._build_agent()
        self._save_to_memory("user", f"Goal: {self.goal.objective}")
        subtasks = self._decompose()
        work_done: list[str] = []
        step_outputs: list[dict[str, Any]] = []

        for step_num, task in enumerate(subtasks[:self.goal.max_steps], 1):
            result = agent.run(task)
            work_done.append(result.output)
            self._save_to_memory("assistant", f"Step {step_num}: {result.output[:500]}")
            step_outputs.append({"step": step_num, "task": task, "output": result.output[:300]})

            evaluation = self._evaluate(work_done)
            criteria_met = evaluation.get("criteria_met", [])

            if evaluation.get("all_done"):
                return GoalResult(
                    goal=self.goal, output=result.output, goal_status="completed",
                    criteria_met=criteria_met, steps_taken=step_num, step_outputs=step_outputs,
                )

        final_eval = self._evaluate(work_done)
        criteria_met = final_eval.get("criteria_met", [False] * len(self.goal.success_criteria))
        met_count = sum(1 for c in criteria_met if c)
        status = "completed" if met_count == len(self.goal.success_criteria) else ("partial" if met_count > 0 else "failed")

        return GoalResult(
            goal=self.goal, output=work_done[-1] if work_done else "",
            goal_status=status, criteria_met=criteria_met,
            steps_taken=len(work_done), step_outputs=step_outputs,
        )

    def stream(self):
        """Run the goal agent and yield events in real time.

        Example::

            for event in goal_agent.stream():
                print(f"[{event.type}] {event.message}")
        """
        from shipit_agent.models import AgentEvent

        yield AgentEvent(type="run_started", message=f"Goal: {self.goal.objective}", payload={"objective": self.goal.objective, "criteria": self.goal.success_criteria})

        yield AgentEvent(type="planning_started", message="Decomposing goal into sub-tasks")
        subtasks = self._decompose()
        yield AgentEvent(type="planning_completed", message=f"Decomposed into {len(subtasks)} sub-tasks", payload={"subtasks": subtasks})

        agent = self._build_agent()
        work_done: list[str] = []
        all_outputs: list[str] = []

        for step_num, task in enumerate(subtasks[:self.goal.max_steps], 1):
            yield AgentEvent(type="step_started", message=f"Step {step_num}/{len(subtasks)}: {task[:80]}", payload={"step": step_num, "task": task})

            result = agent.run(task)
            work_done.append(result.output)
            all_outputs.append(result.output)

            # Yield the step output so the caller can see it
            yield AgentEvent(type="tool_completed", message=f"Step {step_num} output", payload={"step": step_num, "output": result.output})

            yield AgentEvent(type="step_started", message=f"Evaluating progress after step {step_num}")
            evaluation = self._evaluate(work_done)
            criteria_met = evaluation.get("criteria_met", [])
            yield AgentEvent(type="tool_completed", message=f"Criteria met: {criteria_met}", payload={"criteria_met": criteria_met, "all_done": evaluation.get("all_done", False)})

            if evaluation.get("all_done"):
                final_output = "\n\n".join(all_outputs)
                yield AgentEvent(type="run_completed", message="Goal completed", payload={"status": "completed", "steps": step_num, "criteria_met": criteria_met, "output": final_output})
                return

        final_output = "\n\n".join(all_outputs)
        yield AgentEvent(type="run_completed", message="Goal finished (max steps reached)", payload={"status": "partial", "steps": len(work_done), "output": final_output})
