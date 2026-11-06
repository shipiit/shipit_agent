"""Stop a background task by id, whichever tool started it (a bash job, a sub-agent)."""

from __future__ import annotations

from typing import Any

from shipit_agent.core.tasks import background_tasks, stop_background_task
from shipit_agent.tools.base import ToolContext, ToolOutput


class TaskStopTool:
    """The Claude Agent SDK's ``TaskStop``: one way to stop any background task."""

    name = "task_stop"
    description = "Stop a background task (a command or a sub-agent) by its task id."
    prompt_instructions = (
        "Stop background work you no longer need: a dev server you are done with, "
        "or a delegation that went the wrong way. Ids come from the tool that started it."
    )
    read_only = False

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", "properties": {
                "task_id": {"type": "string", "description": "The background task's id"}},
                "required": ["task_id"]},
        }}

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        from shipit_agent.tools.sub_agent.result import PARENT_STATE_KEY

        task_id = str(kwargs.get("task_id") or kwargs.get("shell_id") or "").strip()
        tools = list((context.state.get(PARENT_STATE_KEY) or {}).get("tools") or [])
        if not task_id:
            return ToolOutput.error("Pass `task_id`: the id of the background task to stop.")
        stopped = stop_background_task(tools, task_id)
        if stopped is None:
            known = ", ".join(t.task_id for t in background_tasks(tools) if not t.finished) or "none running"
            return ToolOutput.error(f"No background task {task_id!r}. Running: {known}.")
        return ToolOutput(text=f"Stopped {stopped.task_id} ({stopped.description}).",
                          metadata={"task_id": stopped.task_id, "task_type": stopped.task_type,
                                    "command": stopped.description, "status": stopped.status})
