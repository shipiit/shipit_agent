from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.sub_agent.sub_agent_tool import (
    DEPTH_STATE_KEY,
    EVENT_SINK_KEY,
    MAX_DEPTH,
)


@dataclass(slots=True)
class AgentTool:
    """Expose an Agent-compatible object as one focused callable tool."""

    agent: Any
    name: str
    description: str
    session_id: str | None = None
    stream_events: bool = True
    prompt_instructions: str = (
        "Delegate a bounded specialist task when this agent's description "
        "matches the work better than the parent agent."
    )

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
                            "description": "Complete task for the specialist agent.",
                        },
                        "details": {
                            "type": "string",
                            "description": (
                                "Supporting paths, constraints, evidence, or expected "
                                "output. The child does not see the parent transcript."
                            ),
                        },
                    },
                    "required": ["task"],
                },
            },
        }

    def run(
        self,
        context: ToolContext,
        *,
        task: str = "",
        details: str = "",
        **_kwargs: Any,
    ) -> ToolOutput:
        if not task.strip():
            return ToolOutput(
                text="task is required",
                metadata={"ok": False, "error": "missing_argument", "argument": "task"},
            )
        prompt = task.strip()
        if details.strip():
            prompt = f"{prompt}\n\nSupporting context:\n{details.strip()}"

        # An agent holding a tool that wraps an agent holding the same
        # tool recurses until something runs out. `sub_agent` caps this
        # already; an AgentTool is the same hazard by another name, so it
        # shares the counter rather than keeping its own.
        depth = int((context.state or {}).get(DEPTH_STATE_KEY, 0) or 0)
        if depth >= MAX_DEPTH:
            return ToolOutput(
                text=(f"Delegation is capped at {MAX_DEPTH} levels and this "
                      f"is level {depth}. Do this task yourself."),
                metadata={"ok": False, "error": "max_depth", "depth": depth},
            )

        target = self.agent
        if self.session_id is not None and hasattr(target, "chat_session"):
            target = target.chat_session(session_id=self.session_id)

        events: list[dict[str, Any]] = []
        output = ""
        sink = context.state.get(EVENT_SINK_KEY)
        try:
            output, events = self._invoke(target, prompt, sink)
        except Exception as exc:                          # noqa: BLE001
            return ToolOutput(
                text=(f"{self.name} could not complete the task: {exc}"),
                metadata={"ok": False, "error": "child_failed",
                          "agent": self.name},
            )

        return ToolOutput(
            text=output or f"{self.name} returned nothing.",
            metadata={
                "ok": bool(output),
                "delegated": True,
                "agent": self.name,
                "session_id": self.session_id,
                "task": task,
                "events": events,
            },
        )

    def _invoke(self, target: Any, prompt: str,
                sink: Any) -> tuple[str, list[dict[str, Any]]]:
        events: list[dict[str, Any]] = []
        output = ""
        if self.stream_events and hasattr(target, "stream"):
            for event in target.stream(prompt):
                serialized = (
                    event.to_dict()
                    if hasattr(event, "to_dict")
                    else {
                        "type": getattr(event, "type", ""),
                        "message": getattr(event, "message", ""),
                        "payload": dict(getattr(event, "payload", {}) or {}),
                    }
                )
                events.append(serialized)
                if callable(sink):
                    sink(event, self.name, prompt)
                if getattr(event, "type", "") == "run_completed":
                    output = str(getattr(event, "payload", {}).get("output", ""))
        else:
            if hasattr(target, "send"):
                result = target.send(prompt)
            else:
                result = target.run(prompt)
            output = str(getattr(result, "output", result))
            events = [
                event.to_dict() if hasattr(event, "to_dict") else dict(event)
                for event in (getattr(result, "events", []) or [])
            ]

        return output, events
