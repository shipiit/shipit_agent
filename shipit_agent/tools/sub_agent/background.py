"""Background delegations: waiting with a timeout, and collecting one or all results.

Mixed into :class:`~shipit_agent.tools.sub_agent.sub_agent_tool.SubAgentTool`.
"""

from __future__ import annotations

from concurrent.futures import Future
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any

from shipit_agent.tools.base import ToolOutput

from .result import (
    SubAgentResult,
)


class BackgroundTasksMixin:
    """Background delegations: waiting with a timeout, and collecting one or all results."""

    def _result_with_timeout(self, future: Future[SubAgentResult]) -> SubAgentResult:
        """``future.result()`` bounded by ``self.timeout``.

        On expiry the future is cancelled and a failed ``SubAgentResult`` is
        returned rather than raised, so one slow child degrades to a reported
        failure the parent can reason about instead of hanging the run.
        """
        try:
            return future.result(timeout=self.timeout)
        except FuturesTimeout:
            future.cancel()
            return SubAgentResult(
                task="",
                output=(
                    f"Sub-agent exceeded its {self.timeout:.0f}s time limit "
                    "and was abandoned."
                ),
                error="timeout",
            )

    def _collect(self, collect: str) -> ToolOutput:
        if collect.lower() == "all":
            return self._collect_all()

        with self._lock:
            future = self._tasks.get(collect)
            known = ", ".join(sorted(self._tasks)) or "none"
        if future is None:
            return ToolOutput(
                text=f"No background task '{collect}'. Outstanding: {known}.",
                metadata={"ok": False, "collect": collect},
            )
        try:
            result = self._result_with_timeout(future)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._tasks.pop(collect, None)
                self._meta.pop(collect, None)
            return ToolOutput(
                text=f"Background task '{collect}' failed: {exc}",
                metadata={"ok": False, "collect": collect, "error": str(exc)},
            )
        with self._lock:
            self._tasks.pop(collect, None)
            self._meta.pop(collect, None)
        return ToolOutput(
            text=result.report(),
            metadata={**result.to_dict(), "collect": collect, "background": True},
        )

    def _collect_all(self) -> ToolOutput:
        """Wait for every outstanding task and return one combined report."""
        with self._lock:
            outstanding = list(self._tasks.items())
        if not outstanding:
            return ToolOutput(
                text="No background tasks are outstanding.",
                metadata={"ok": True, "collected": 0},
            )

        sections: list[str] = []
        results: list[dict[str, Any]] = []
        for task_id, future in outstanding:
            try:
                result = self._result_with_timeout(future)
                sections.append(f"## {task_id}: {result.task}\n{result.report()}")
                results.append(result.to_dict())
            except Exception as exc:  # noqa: BLE001
                sections.append(f"## {task_id}\nFailed: {exc}")
                results.append({"task_id": task_id, "ok": False, "error": str(exc)})
            with self._lock:
                self._tasks.pop(task_id, None)
                self._meta.pop(task_id, None)

        return ToolOutput(
            text="\n\n".join(sections),
            metadata={"collected": len(results), "results": results},
        )
