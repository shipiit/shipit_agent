"""Sub-agent delegation tool for :class:`DeepAgent`.

When a user passes ``agents=[...]`` to :class:`DeepAgent`, we wrap them
in :class:`AgentDelegationTool` so the deep agent can call them by name
as if they were tools. This turns ``DeepAgent`` into a lightweight
supervisor: the main deep agent plans the work, then delegates focused
sub-tasks to specialised inner agents — each with its own tools, prompt,
RAG, and memory.

Each delegate can be:

* a :class:`shipit_agent.Agent`
* another :class:`DeepAgent`
* any deep-agent class (:class:`GoalAgent`, :class:`ReflectiveAgent`,
  :class:`Supervisor`, …)
* any object that exposes a ``run(prompt) -> AgentResult``-like method
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput


def _agent_name(agent: Any, fallback: str) -> str:
    """Resolve a friendly name for an agent passed via ``agents=``."""
    for attr in ("name", "agent_name"):
        value = getattr(agent, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    inner = getattr(agent, "agent", None)
    if inner is not None:
        for attr in ("name", "agent_name"):
            value = getattr(inner, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback


def _agent_description(agent: Any) -> str:
    for attr in ("description", "agent_description"):
        value = getattr(agent, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    inner = getattr(agent, "agent", None)
    if inner is not None:
        value = getattr(inner, "description", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{agent.__class__.__name__} sub-agent"


def _run_agent(
    agent: Any,
    task: str,
    *,
    capture_events: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Invoke any kind of inner agent and return ``(text, metadata)``.

    When ``capture_events`` is True the inner agent's ``stream()`` method
    is used (when available) so events flow into ``metadata['events']``,
    letting the parent surface what the sub-agent did. Falls back to
    ``run()`` if the inner agent has no ``stream()``.
    """
    metadata: dict[str, Any] = {}
    text: str | None = None

    if capture_events and hasattr(agent, "stream"):
        captured_events: list[dict[str, Any]] = []
        try:
            stream_iter = agent.stream(task)
        except TypeError:
            stream_iter = agent.stream()
        for event in stream_iter:
            captured_events.append(
                {
                    "type": getattr(event, "type", ""),
                    "message": getattr(event, "message", ""),
                    "payload": dict(getattr(event, "payload", {}) or {}),
                }
            )
            if getattr(event, "type", "") == "run_completed":
                payload = getattr(event, "payload", {}) or {}
                if isinstance(payload, dict) and payload.get("output"):
                    text = payload["output"]
        metadata["events"] = captured_events
        if text is not None:
            return text, metadata

    if hasattr(agent, "run"):
        try:
            result = agent.run(task)
        except TypeError:
            # Some deep agents (GoalAgent) take no prompt at run time.
            result = agent.run()
        text = getattr(result, "output", None)
        if text is None:
            text = str(result)
        metadata.update(dict(getattr(result, "metadata", {}) or {}))
        sources = getattr(result, "rag_sources", None)
        if sources:
            metadata["rag_sources"] = [
                src.to_dict() if hasattr(src, "to_dict") else src for src in sources
            ]
        return text, metadata
    raise TypeError(f"Sub-agent {agent.__class__.__name__} has no run() method")


@dataclass
class AgentDelegationTool:
    """Tool that exposes a dict of named sub-agents to a deep agent.

    The deep agent calls ``delegate_to_agent(agent_name=..., task=...)``
    and the tool forwards the task to the matching agent's ``run``
    method, returning the rendered output back to the parent.

    Example::

        researcher = Agent.with_builtins(llm=llm, prompt="You research.")
        writer     = Agent.with_builtins(llm=llm, prompt="You write.")

        tool = AgentDelegationTool(agents={
            "researcher": researcher,
            "writer": writer,
        })

        out = tool.run(
            ToolContext(prompt=""),
            agent_name="researcher",
            task="Find python version",
        )
    """

    agents: dict[str, Any] = field(default_factory=dict)
    name: str = "delegate_to_agent"
    description: str = (
        "Delegate a focused sub-task to one of the named sub-agents you can "
        "see in `agent_name`. Use this when a sub-task is well-scoped and "
        "would benefit from a specialised agent's tools, prompt, or RAG."
    )
    prompt_instructions: str = (
        "Use this when a sub-task is well-scoped (research, summarisation, "
        "writing, code review). Pick the agent whose name and description best "
        "match the task. Pass the full task as `task`."
    )
    # When True, the tool uses each inner agent's ``stream()`` so the
    # parent's ``tool_completed`` event carries the inner events list in
    # ``metadata['events']`` — useful for live UIs that want to surface
    # what each sub-agent is doing.
    capture_events: bool = True

    def __post_init__(self) -> None:
        # Defensive copy + validate that every agent exposes ``.run``.
        cleaned: dict[str, Any] = {}
        for raw_name, agent in (self.agents or {}).items():
            name = (raw_name or _agent_name(agent, "agent")).strip()
            if not name:
                continue
            if not hasattr(agent, "run"):
                raise TypeError(
                    f"Sub-agent {name!r} ({agent.__class__.__name__}) "
                    "must expose a run() method"
                )
            cleaned[name] = agent
        self.agents = cleaned

    # ---- Tool protocol -------------------------------------------------

    def schema(self) -> dict[str, Any]:
        roster = (
            "\n".join(
                f"- {name}: {_agent_description(agent)}"
                for name, agent in self.agents.items()
            )
            or "(no sub-agents registered)"
        )
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    f"{self.description}\n\nAvailable sub-agents:\n{roster}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "Which sub-agent to delegate to.",
                            "enum": list(self.agents.keys()) or None,
                        },
                        "task": {
                            "type": "string",
                            "description": "The task for the sub-agent to complete.",
                        },
                        "context": {
                            "type": "string",
                            "description": "Optional supporting context for the sub-agent.",
                        },
                    },
                    "required": ["agent_name", "task"],
                },
            },
        }

    def run(
        self,
        context: ToolContext,
        *,
        agent_name: str = "",
        task: str = "",
        context_text: str = "",
        **kwargs: Any,
    ) -> ToolOutput:
        # Accept ``context=`` from the LLM as well — but the ToolContext
        # positional kwarg also exists, so the LLM-supplied value comes
        # in via ``kwargs`` when the runtime forwards it.
        supplied_context = kwargs.get("context", context_text) or ""

        if not self.agents:
            return ToolOutput(text=json.dumps({"error": "no sub-agents registered"}))

        if not agent_name:
            return ToolOutput(text=json.dumps({"error": "agent_name is required"}))

        if agent_name not in self.agents:
            return ToolOutput(
                text=json.dumps(
                    {
                        "error": f"unknown sub-agent: {agent_name!r}",
                        "available": list(self.agents.keys()),
                    }
                )
            )

        if not task:
            return ToolOutput(text=json.dumps({"error": "task is required"}))

        prompt = task
        if supplied_context:
            prompt = f"{task}\n\nContext:\n{supplied_context}"

        try:
            text, metadata = _run_agent(
                self.agents[agent_name],
                prompt,
                capture_events=self.capture_events,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return ToolOutput(
                text=json.dumps({"error": f"sub-agent {agent_name} failed: {exc}"})
            )

        payload = {
            "agent": agent_name,
            "task": task,
            "output": text,
        }
        return ToolOutput(
            text=json.dumps(payload, indent=2),
            metadata={"sub_agent": agent_name, **metadata},
        )

    # ---- Helpers --------------------------------------------------------

    def names(self) -> list[str]:
        return list(self.agents.keys())

    def add(self, name: str, agent: Any) -> None:
        if not hasattr(agent, "run"):
            raise TypeError(f"Sub-agent {name!r} must expose a run() method")
        self.agents[name] = agent


def build_delegation_tool(
    agents: list[Any] | dict[str, Any] | None,
) -> AgentDelegationTool | None:
    """Convert a user-supplied ``agents=`` value into an :class:`AgentDelegationTool`.

    Accepts:

    * ``None`` → returns ``None`` (no tool wired)
    * ``dict[str, agent]`` → uses the keys as names verbatim
    * ``list[agent]`` → derives names from each agent's ``.name`` attribute,
      falling back to ``f"agent_{idx}"`` for unnamed agents
    """
    if not agents:
        return None
    if isinstance(agents, dict):
        return AgentDelegationTool(agents=dict(agents))
    if isinstance(agents, list):
        named: dict[str, Any] = {}
        for idx, agent in enumerate(agents):
            name = _agent_name(agent, fallback=f"agent_{idx}")
            # Avoid collisions by suffixing duplicates.
            unique = name
            counter = 2
            while unique in named:
                unique = f"{name}_{counter}"
                counter += 1
            named[unique] = agent
        return AgentDelegationTool(agents=named)
    raise TypeError(f"agents= must be a list or dict, got {type(agents).__name__}")


__all__ = ["AgentDelegationTool", "build_delegation_tool"]
