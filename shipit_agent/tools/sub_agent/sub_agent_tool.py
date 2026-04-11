from __future__ import annotations

from shipit_agent.llms.base import LLM
from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import SUB_AGENT_PROMPT


class SubAgentTool:
    def __init__(
        self,
        llm: LLM,
        *,
        name: str = "sub_agent",
        description: str = "Delegate a focused sub-task to a lightweight sub-agent.",
        prompt: str | None = None,
    ) -> None:
        self.llm = llm
        self.name = name
        self.description = description
        self.prompt = prompt or SUB_AGENT_PROMPT
        self.prompt_instructions = "Use this for side tasks like summarization, analysis, translation, or focused research."

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "Delegated task"},
                        "context": {
                            "type": "string",
                            "description": "Optional supporting context",
                        },
                    },
                    "required": ["task"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        task = str(kwargs["task"]).strip()
        task_context = str(kwargs.get("context", "")).strip()
        prompt = f"Sub-agent task:\n{task}"
        if task_context:
            prompt += f"\n\nContext:\n{task_context}"
        response = self.llm.complete(
            messages=[],
            tools=[],
            system_prompt=(
                "You are a focused sub-agent. Complete the assigned task clearly and directly.\n\n"
                f"{prompt}"
            ),
            metadata={"parent_prompt": context.prompt},
        )
        text = response.content or prompt
        return ToolOutput(text=text, metadata={"task": task, "delegated": True})
