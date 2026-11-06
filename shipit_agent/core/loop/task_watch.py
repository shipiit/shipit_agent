"""Watching background tasks between steps, so the model hears when one finishes.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from shipit_agent.core.models import Message
from shipit_agent.core.state import RuntimeState
from shipit_agent.core.tasks import background_tasks, notification_text


class TaskWatchMixin:
    """Watching background tasks between steps, so the model hears when one finishes."""

    def watch_background_tasks(self, state: RuntimeState, tools: Iterable[Any]) -> None:
        """Emit ``task_started`` / ``task_notification`` for changes since the last look.

        A task that completed or failed is also told to the model, as the
        SDK's task notifications are; statuses persist for the session, so a
        task started in one turn is reported in the next.
        """
        seen: dict[str, str] = self._session_runtime_state.setdefault("background_task_status", {})
        for task in background_tasks(tools):
            before = seen.get(task.task_id)
            seen[task.task_id] = task.status
            if before is None:
                self.emit(state, "task_started", f"Background task started: {task.description}", **task.to_dict())
            if not task.finished or before not in (None, "running"):
                continue
            self.emit(state, "task_notification", f"Background task {task.status}: {task.description}",
                      **task.to_dict())
            if task.status in ("completed", "failed"):
                state.messages.append(Message(role="user", content=notification_text(task),
                                              metadata={"internal": True, "kind": "task_notification"}))
