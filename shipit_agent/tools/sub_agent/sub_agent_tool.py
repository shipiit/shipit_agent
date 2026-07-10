from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from itertools import count

from shipit_agent.llms.base import LLM
from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import SUB_AGENT_PROMPT


class SubAgentTool:
    """Delegate a focused sub-task — synchronously or in the background.

    Background mode works like Claude Code's task tool: pass
    ``background=true`` to start the sub-agent and get a task id back
    immediately, keep working, then call again with ``collect="<id>"``
    (blocking) to fetch the result.
    """

    def __init__(
        self,
        llm: LLM,
        *,
        name: str = "sub_agent",
        description: str = "Delegate a focused sub-task to a lightweight sub-agent.",
        prompt: str | None = None,
        max_workers: int = 4,
    ) -> None:
        self.llm = llm
        self.name = name
        self.description = description
        self.prompt = prompt or SUB_AGENT_PROMPT
        self.prompt_instructions = (
            "Use this for side tasks like summarization, analysis, translation, "
            "or focused research. Pass background=true to run it while you "
            "continue, then collect='<task id>' to fetch the result."
        )
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="sub_agent"
        )
        self._tasks: dict[str, Future[str]] = {}
        self._task_ids = count(1)

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
                        "background": {
                            "type": "boolean",
                            "description": (
                                "Start the sub-agent in the background and "
                                "return a task id immediately."
                            ),
                            "default": False,
                        },
                        "collect": {
                            "type": "string",
                            "description": (
                                "A task id from a previous background call — "
                                "waits for and returns that task's result."
                            ),
                        },
                    },
                    "required": [],
                },
            },
        }

    def _complete(self, task: str, task_context: str, parent_prompt: str) -> str:
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
            metadata={"parent_prompt": parent_prompt},
        )
        return response.content or prompt

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        collect = str(kwargs.get("collect", "")).strip()
        if collect:
            future = self._tasks.get(collect)
            if future is None:
                known = ", ".join(sorted(self._tasks)) or "none"
                return ToolOutput(
                    text=f"No background task '{collect}'. Known tasks: {known}.",
                    metadata={"ok": False, "collect": collect},
                )
            try:
                text = future.result()
            except Exception as exc:
                return ToolOutput(
                    text=f"Background task '{collect}' failed: {exc}",
                    metadata={"ok": False, "collect": collect, "error": str(exc)},
                )
            self._tasks.pop(collect, None)
            return ToolOutput(
                text=text,
                metadata={"collect": collect, "delegated": True, "background": True},
            )

        task = str(kwargs.get("task", "")).strip()
        if not task:
            return ToolOutput(
                text="Provide `task` to delegate, or `collect` to fetch a background result.",
                metadata={"ok": False},
            )
        task_context = str(kwargs.get("context", "")).strip()

        if kwargs.get("background"):
            task_id = f"task-{next(self._task_ids)}"
            self._tasks[task_id] = self._executor.submit(
                self._complete, task, task_context, context.prompt
            )
            return ToolOutput(
                text=(
                    f"Background sub-agent started: {task_id}. Continue with "
                    f'other work, then call this tool with collect="{task_id}" '
                    "to fetch the result."
                ),
                metadata={"task_id": task_id, "background": True, "task": task},
            )

        text = self._complete(task, task_context, context.prompt)
        return ToolOutput(text=text, metadata={"task": task, "delegated": True})
