from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Reflection:
    """A single reflection on agent output."""

    feedback: str
    quality_score: float
    revision_needed: bool


@dataclass(slots=True)
class ReflectionResult:
    """Result of a reflective agent run."""

    output: str
    reflections: list[Reflection] = field(default_factory=list)
    revisions: list[str] = field(default_factory=list)
    final_quality: float = 0.0
    iterations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "final_quality": self.final_quality,
            "iterations": self.iterations,
            "reflections": [
                {"feedback": r.feedback[:200], "score": r.quality_score}
                for r in self.reflections
            ],
        }


REFLECT_PROMPT = """You are a critical reviewer. Evaluate this output.

## Task
{task}

## Reflection criteria
{criteria}

## Output to evaluate
{output}

Respond with JSON:
{{"feedback": "what needs improvement", "quality_score": 0.0 to 1.0, "revision_needed": true/false}}"""

REVISE_PROMPT = """Revise your previous output based on this feedback.

## Original task
{task}

## Previous output
{output}

## Feedback
{feedback}

Write an improved version:"""


class ReflectiveAgent:
    """Agent that evaluates its own output and improves it through reflection.

    The agent produces output, reflects on it critically, and revises
    until the quality threshold is met or max_reflections is reached.

    Example::

        agent = ReflectiveAgent(
            llm=llm,
            reflection_prompt="Check for accuracy and completeness.",
            max_reflections=3,
            quality_threshold=0.8,
        )
        result = agent.run("Explain quantum entanglement")
        print(result.final_quality)  # 0.9
        print(len(result.revisions))  # 2
    """

    def __init__(
        self,
        *,
        llm: Any,
        tools: list[Any] | None = None,
        mcps: list[Any] | None = None,
        reflection_prompt: str = "Check for accuracy, completeness, and clarity.",
        max_reflections: int = 3,
        quality_threshold: float = 0.8,
        use_builtins: bool = False,
        prompt: str = "You are a helpful assistant.",
        memory: Any = None,
        **agent_kwargs: Any,
    ) -> None:
        self.llm = llm
        self.tools = tools or []
        self.mcps = mcps or []
        self.reflection_prompt = reflection_prompt
        self.max_reflections = max_reflections
        self.quality_threshold = quality_threshold
        self.use_builtins = use_builtins
        self.prompt = prompt
        self.memory = memory
        self.agent_kwargs = agent_kwargs

    def _build_agent(self) -> Any:
        from shipit_agent.agent import Agent

        extra = dict(self.agent_kwargs)
        if self.memory and hasattr(self.memory, "get_conversation_messages"):
            extra.setdefault("history", self.memory.get_conversation_messages())
        if self.use_builtins:
            return Agent.with_builtins(
                llm=self.llm, prompt=self.prompt, mcps=self.mcps, **extra
            )
        return Agent(
            llm=self.llm, prompt=self.prompt, tools=self.tools, mcps=self.mcps, **extra
        )

    def _save_to_memory(self, role: str, content: str) -> None:
        if self.memory and hasattr(self.memory, "add_message"):
            from shipit_agent.models import Message

            self.memory.add_message(Message(role=role, content=content))

    @classmethod
    def with_builtins(
        cls, *, llm: Any, mcps: list[Any] | None = None, **kwargs: Any
    ) -> "ReflectiveAgent":
        """Create a ReflectiveAgent with all built-in tools."""
        return cls(llm=llm, mcps=mcps, use_builtins=True, **kwargs)

    def _llm_call(self, prompt: str) -> str:
        from shipit_agent.models import Message

        response = self.llm.complete(messages=[Message(role="user", content=prompt)])
        return response.content

    def _reflect(self, task: str, output: str) -> Reflection:
        text = self._llm_call(
            REFLECT_PROMPT.format(
                task=task,
                criteria=self.reflection_prompt,
                output=output,
            )
        )
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
                return Reflection(
                    feedback=data.get("feedback", ""),
                    quality_score=float(data.get("quality_score", 0.5)),
                    revision_needed=bool(data.get("revision_needed", True)),
                )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        return Reflection(feedback=text, quality_score=0.5, revision_needed=True)

    def _revise(self, task: str, output: str, feedback: str) -> str:
        return self._llm_call(
            REVISE_PROMPT.format(
                task=task,
                output=output,
                feedback=feedback,
            )
        )

    def run(self, task: str) -> ReflectionResult:
        agent = self._build_agent()
        self._save_to_memory("user", task)
        initial_result = agent.run(task)
        current_output = initial_result.output

        result = ReflectionResult(output=current_output)
        result.revisions.append(current_output)

        for i in range(self.max_reflections):
            reflection = self._reflect(task, current_output)
            result.reflections.append(reflection)
            result.final_quality = reflection.quality_score

            if (
                not reflection.revision_needed
                or reflection.quality_score >= self.quality_threshold
            ):
                break

            current_output = self._revise(task, current_output, reflection.feedback)
            result.revisions.append(current_output)

        result.output = current_output
        result.iterations = len(result.reflections)
        self._save_to_memory("assistant", current_output[:500])
        return result

    def stream(self, task: str):
        """Run the reflective agent and yield events in real time.

        Example::

            for event in reflective_agent.stream("Write an explanation"):
                print(f"[{event.type}] {event.message}")
        """
        from shipit_agent.agent import Agent
        from shipit_agent.models import AgentEvent

        yield AgentEvent(
            type="run_started",
            message=f"ReflectiveAgent: {task[:80]}",
            payload={
                "task": task,
                "max_reflections": self.max_reflections,
                "threshold": self.quality_threshold,
            },
        )

        agent = Agent(llm=self.llm, tools=self.tools)

        yield AgentEvent(type="step_started", message="Generating initial output")
        initial_result = agent.run(task)
        current_output = initial_result.output
        yield AgentEvent(
            type="tool_completed",
            message="Initial output generated",
            payload={"output": current_output},
        )

        for i in range(self.max_reflections):
            yield AgentEvent(
                type="reasoning_started",
                message=f"Reflection {i + 1}/{self.max_reflections}",
            )
            reflection = self._reflect(task, current_output)
            yield AgentEvent(
                type="reasoning_completed",
                message=f"Quality: {reflection.quality_score:.2f} — {reflection.feedback[:100]}",
                payload={
                    "quality": reflection.quality_score,
                    "feedback": reflection.feedback,
                    "revision_needed": reflection.revision_needed,
                },
            )

            if (
                not reflection.revision_needed
                or reflection.quality_score >= self.quality_threshold
            ):
                yield AgentEvent(
                    type="run_completed",
                    message=f"Quality threshold met: {reflection.quality_score:.2f}",
                    payload={
                        "quality": reflection.quality_score,
                        "iterations": i + 1,
                        "output": current_output,
                    },
                )
                return

            yield AgentEvent(
                type="step_started", message=f"Revising (iteration {i + 2})"
            )
            current_output = self._revise(task, current_output, reflection.feedback)
            yield AgentEvent(
                type="tool_completed",
                message=f"Revision {i + 2} complete",
                payload={"output": current_output},
            )

        yield AgentEvent(
            type="run_completed",
            message="Max reflections reached",
            payload={"iterations": self.max_reflections, "output": current_output},
        )
