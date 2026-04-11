from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shipit_agent.construction import construct_tool_registry
from shipit_agent.models import AgentEvent, ToolCall, ToolResult
from shipit_agent.tool_runner import ToolRunner
from shipit_agent.tools import ToolContext


@dataclass(slots=True)
class ReasoningResult:
    prompt: str
    outputs: dict[str, ToolResult] = field(default_factory=dict)
    events: list[AgentEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "outputs": {
                name: result.to_dict() for name, result in self.outputs.items()
            },
            "events": [event.to_dict() for event in self.events],
        }


class ReasoningRuntime:
    def __init__(self, agent) -> None:
        self.agent = agent

    def run(
        self,
        prompt: str,
        *,
        observations: list[str] | None = None,
        options: list[str] | None = None,
        criteria: list[str] | None = None,
        constraints: list[str] | None = None,
    ) -> ReasoningResult:
        registry = construct_tool_registry(tools=self.agent.tools, mcps=self.agent.mcps)
        tool_runner = ToolRunner(registry)
        shared_state = {
            "memory_store": self.agent.memory_store,
            "credential_store": self.agent.credential_store,
            "workspace_root": self.agent.metadata.get(
                "workspace_root", ".shipit_workspace"
            ),
            "artifact_workspace_root": self.agent.metadata.get(
                "artifact_workspace_root", ".shipit_workspace/artifacts"
            ),
        }
        context = ToolContext(
            prompt=prompt,
            system_prompt=self.agent.prompt,
            metadata=dict(self.agent.metadata),
            state=shared_state,
            session_id=self.agent.session_id,
        )
        result = ReasoningResult(prompt=prompt)
        result.events.append(
            AgentEvent(
                type="reasoning_started",
                message="Reasoning runtime started",
                payload={"prompt": prompt},
            )
        )

        def maybe_run(tool_name: str, arguments: dict[str, Any]) -> None:
            tool = registry.get(tool_name)
            if tool is None:
                return
            result.events.append(
                AgentEvent(
                    type="tool_called",
                    message=f"Tool called: {tool_name}",
                    payload={"arguments": dict(arguments), "reasoning": True},
                )
            )
            tool_result = tool_runner.run_tool_call(
                ToolCall(name=tool_name, arguments=arguments), context
            )
            result.outputs[tool_name] = tool_result
            result.events.append(
                AgentEvent(
                    type="tool_completed",
                    message=f"Tool completed: {tool_name}",
                    payload={"output": tool_result.output, "reasoning": True},
                )
            )

        maybe_run("plan_task", {"goal": prompt, "constraints": list(constraints or [])})
        maybe_run(
            "decompose_problem",
            {
                "problem": prompt,
                "objective": prompt,
                "constraints": list(constraints or []),
            },
        )
        if observations:
            maybe_run(
                "synthesize_evidence",
                {"observations": list(observations), "question": prompt},
            )
        if options and criteria:
            maybe_run(
                "decision_matrix",
                {
                    "decision": prompt,
                    "options": list(options),
                    "criteria": list(criteria),
                },
            )

        result.events.append(
            AgentEvent(
                type="reasoning_completed",
                message="Reasoning runtime completed",
                payload={"steps": list(result.outputs.keys())},
            )
        )
        return result
