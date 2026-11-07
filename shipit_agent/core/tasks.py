"""Background tasks across tools: what is running, and what just finished.

A tool that starts work in the background (the bash tool's jobs, the
sub-agent tool's background delegations) reports it through two methods:

    list_background_tasks() -> list[TaskInfo]
    stop_background_task(task_id) -> TaskInfo | None

The runtime asks every tool between steps, so the model hears when a task
it started has finished, as the Claude Agent SDK's task notifications do,
and ``task_stop`` stops any of them by id.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

__all__ = ["TaskInfo", "TaskStatus", "background_tasks", "notification_text", "stop_background_task"]

TaskStatus = Literal["running", "completed", "failed", "stopped"]


@dataclass(frozen=True, slots=True)
class TaskInfo:
    task_id: str
    #: ``local_bash`` or ``local_agent``, as the SDK names them.
    task_type: str
    description: str
    status: TaskStatus
    output_file: str | None = None
    summary: str = ""
    exit_code: int | None = None

    @property
    def finished(self) -> bool:
        return self.status != "running"

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "task_type": self.task_type, "description": self.description,
                "status": self.status, "output_file": self.output_file, "summary": self.summary,
                "exit_code": self.exit_code}


def background_tasks(tools: Iterable[Any]) -> list[TaskInfo]:
    """Every background task the given tools know about."""
    found: list[TaskInfo] = []
    for tool in tools:
        lister = getattr(tool, "list_background_tasks", None)
        if callable(lister):
            found.extend(lister())
    return found


def stop_background_task(tools: Iterable[Any], task_id: str) -> TaskInfo | None:
    """Stop *task_id* through whichever tool owns it; ``None`` if none does."""
    for tool in tools:
        stopper = getattr(tool, "stop_background_task", None)
        if callable(stopper):
            stopped = stopper(task_id)
            if stopped is not None:
                return stopped
    return None


def notification_text(task: TaskInfo) -> str:
    """What the model is told when a task it started finishes."""
    lines = [f"Background task {task.task_id} ({task.description}) {task.status}."]
    if task.exit_code not in (None, 0):
        lines.append(f"Exit code: {task.exit_code}.")
    if task.output_file:
        lines.append(f"Its output is in {task.output_file}; read it if you need the details.")
    if task.summary:
        lines.append(f"Summary: {task.summary}")
    return "<task-notification>\n" + "\n".join(lines) + "\n</task-notification>"
