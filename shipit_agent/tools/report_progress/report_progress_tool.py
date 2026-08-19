"""A structured checkpoint the model writes as it works.

Two jobs at once. It gives a watching person a readable status without reading
the whole trace, and it marks a natural point to persist a resumable run — a
place where the work is in a coherent state rather than mid-edit.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from shipit_agent.tools._shared import ToolBase
from shipit_agent.tools.report_progress.prompt import DESCRIPTION, INSTRUCTIONS

logger = logging.getLogger(__name__)

__all__ = ["ReportProgressTool"]


class ReportProgressTool(ToolBase):
    name = "report_progress"
    description = DESCRIPTION
    prompt_instructions = INSTRUCTIONS

    def __init__(
        self,
        on_report: Callable[[dict[str, Any]], None] | None = None,
        workspace: Any = None,
    ) -> None:
        super().__init__(workspace)
        self._on_report = on_report
        self.reports: list[dict[str, Any]] = []

    def schema(self) -> dict[str, Any]:
        return self.build_schema(
            {
                "done": {"type": "string", "description": "What was completed."},
                "next": {"type": "string", "description": "The next step."},
                "blocked_by": {
                    "type": "string",
                    "description": "What is preventing progress, if anything.",
                },
            },
            ["done"],
        )

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        report = {
            "done": str(kwargs.get("done", "")).strip(),
            "next": str(kwargs.get("next", "")).strip(),
            "blocked_by": str(kwargs.get("blocked_by", "")).strip(),
            "at": time.time(),
        }
        if not report["done"]:
            return self.fail("Say what was completed.")

        self.reports.append(report)
        if self._on_report is not None:
            try:
                self._on_report(report)
            except Exception:  # noqa: BLE001 — a listener must not fail the run
                logger.exception("Progress listener failed")

        lines = [f"Recorded step {len(self.reports)}: {report['done']}"]
        if report["next"]:
            lines.append(f"Next: {report['next']}")
        if report["blocked_by"]:
            lines.append(f"Blocked by: {report['blocked_by']}")
        return self.ok("\n".join(lines), step=len(self.reports), **report)
