"""Goal and reflective run modes for DeepAgent."""

from __future__ import annotations

from typing import Any

from shipit_agent.core.models import AgentEvent, AgentResult

from ..goal_agent import GoalAgent, GoalResult
from ..reflective_agent import ReflectionResult, ReflectiveAgent
from .verification import verify_text


class _DeepAgentModes:
    """Goal and reflective run modes for DeepAgent."""

    def _inner_agent_extras(self) -> dict[str, Any]:
        """Kwargs forwarded to GoalAgent/ReflectiveAgent so the inner Agent
        gets the factory's ``history`` and ``verifier`` (memory is passed
        explicitly via ``memory=``). Only non-empty values are forwarded so we
        don't override the inner agent's memory-derived history with an empty
        list."""
        extras: dict[str, Any] = {}
        if self.history:
            extras["history"] = list(self.history)
        if self.verifier is not None:
            extras["verifier"] = self.verifier
        return extras

    def _build_goal_agent(self) -> GoalAgent:
        return GoalAgent(
            llm=self.llm,
            tools=list(self._agent.tools),
            mcps=list(self.mcps),
            goal=self.goal,
            prompt=self.prompt,
            rag=self.rag,
            memory=self.memory,
            **self._inner_agent_extras(),
        )

    def _run_goal(self) -> GoalResult:
        return self._build_goal_agent().run()

    def _stream_goal(self):
        yield from self._build_goal_agent().stream()

    def _build_reflective_agent(self) -> ReflectiveAgent:
        return ReflectiveAgent(
            llm=self.llm,
            tools=list(self._agent.tools),
            mcps=list(self.mcps),
            quality_threshold=self.reflect_threshold,
            max_reflections=self.reflect_max_iterations,
            prompt=self.prompt,
            rag=self.rag,
            memory=self.memory,
            **self._inner_agent_extras(),
        )

    def _run_reflective(self, user_prompt: str) -> ReflectionResult:
        return self._build_reflective_agent().run(user_prompt)

    def _stream_reflective(self, user_prompt: str):
        agent = self._build_reflective_agent()
        if hasattr(agent, "stream"):
            yield from agent.stream(user_prompt)
            return
        result = agent.run(user_prompt)
        yield AgentEvent(
            type="run_completed",
            message="reflective run completed",
            payload={"output": getattr(result, "output", str(result))},
        )

    def _post_verify(self, result: AgentResult) -> None:
        result.metadata["verification"] = verify_text(
            result.output or "", goal=self.goal
        )
