from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

_VALID_STATUSES = ("pending", "in_progress", "completed")

_STATUS_GLYPHS = {
    "pending": "☐",  # ☐
    "in_progress": "▶",  # ▶
    "completed": "☑",  # ☑
}

_PROMPT_INSTRUCTIONS = (
    "Maintain a live task checklist for any multi-step task so the run stays "
    "observable. Write ALL the steps up front as todo items, then keep the list "
    "current as you work: mark exactly ONE item as 'in_progress' at a time, and "
    "flip an item to 'completed' the moment you finish it. Every call REPLACES "
    "the entire list, so always pass the full, updated set of todos (not just the "
    "delta). Each item is {content, status} where status is one of "
    "'pending' | 'in_progress' | 'completed' (defaults to 'pending')."
)


class TodoTool:
    """Live task checklist — the SHIPIT equivalent of Claude Code's TodoWrite.

    The model calls this to maintain an observable, always-current to-do list
    while it works through a multi-step task. Each call replaces the whole list
    (replace semantics). The normalized list is stored on
    ``context.state["todos"]`` so the runtime / UI can render progress.
    """

    def __init__(
        self,
        *,
        name: str = "todo",
        description: str = (
            "Maintain a live, replace-on-write checklist of tasks for a "
            "multi-step job so progress is observable. Pass the full updated "
            "list each call; mark exactly one item in_progress and flip items "
            "to completed as you finish them."
        ),
    ) -> None:
        self.name = name
        self.description = description
        self.prompt_instructions = _PROMPT_INSTRUCTIONS

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todos": {
                            "type": "array",
                            "description": (
                                "The FULL updated checklist. Replaces any "
                                "previous list."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content": {
                                        "type": "string",
                                        "description": "What the task is.",
                                    },
                                    "status": {
                                        "type": "string",
                                        "enum": list(_VALID_STATUSES),
                                        "description": (
                                            "Task state; defaults to "
                                            "'pending' if omitted."
                                        ),
                                    },
                                },
                                "required": ["content"],
                            },
                        },
                    },
                    "required": ["todos"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        raw = kwargs.get("todos")
        if not isinstance(raw, list):
            return ToolOutput(
                text=(
                    "Invalid todos: expected an array of "
                    "{content, status} objects."
                ),
                metadata={"error": "todos must be a list", "persist": False},
            )

        normalized: list[dict[str, str]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                return ToolOutput(
                    text=f"Invalid todo at index {index}: expected an object.",
                    metadata={
                        "error": f"todo at index {index} is not an object",
                        "persist": False,
                    },
                )

            content = str(item.get("content", "")).strip()
            if not content:
                return ToolOutput(
                    text=(
                        f"Invalid todo at index {index}: "
                        "'content' is required and must be non-empty."
                    ),
                    metadata={
                        "error": f"todo at index {index} has empty content",
                        "persist": False,
                    },
                )

            status = item.get("status")
            if status is None or status == "":
                status = "pending"
            status = str(status)
            if status not in _VALID_STATUSES:
                return ToolOutput(
                    text=(
                        f"Invalid todo at index {index}: unknown status "
                        f"{status!r}. Must be one of "
                        f"{', '.join(_VALID_STATUSES)}."
                    ),
                    metadata={
                        "error": (
                            f"todo at index {index} has invalid status "
                            f"{status!r}"
                        ),
                        "persist": False,
                    },
                )

            normalized.append({"content": content, "status": status})

        context.state["todos"] = normalized

        summary = {
            "total": len(normalized),
            "completed": sum(1 for t in normalized if t["status"] == "completed"),
            "in_progress": sum(
                1 for t in normalized if t["status"] == "in_progress"
            ),
            "pending": sum(1 for t in normalized if t["status"] == "pending"),
        }

        text = self._render(normalized, summary)

        return ToolOutput(
            text=text,
            metadata={
                "todos": normalized,
                "summary": summary,
                "persist": False,
            },
        )

    @staticmethod
    def _render(todos: list[dict[str, str]], summary: dict[str, int]) -> str:
        if not todos:
            return "No todos."
        lines = [
            f"{_STATUS_GLYPHS[t['status']]} {t['content']}" for t in todos
        ]
        lines.append(
            f"({summary['completed']}/{summary['total']} completed, "
            f"{summary['in_progress']} in progress, "
            f"{summary['pending']} pending)"
        )
        return "\n".join(lines)
