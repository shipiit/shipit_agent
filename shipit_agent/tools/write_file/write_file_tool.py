"""Create a file. Refuses to overwrite one that already exists."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools._shared import ToolBase
from shipit_agent.tools.write_file.prompt import DESCRIPTION, INSTRUCTIONS

__all__ = ["WriteFileTool"]


class WriteFileTool(ToolBase):
    name = "write_file"
    description = DESCRIPTION
    prompt_instructions = INSTRUCTIONS

    def schema(self) -> dict[str, Any]:
        return self.build_schema(
            {
                "path": {"type": "string", "description": "Path for the new file."},
                "content": {"type": "string", "description": "Full file content."},
            },
            ["path", "content"],
        )

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        try:
            target = self.workspace.resolve(str(kwargs.get("path", "")))
        except ValueError as error:
            return self.fail(str(error))

        if target.exists():
            # The whole contract: a write that silently replaces a file destroys
            # work with no trace, and the model has no way to know it happened.
            return self.fail(
                f"{self.workspace.relative(target)} already exists. Read it and "
                "use edit_file, or choose a different path."
            )

        content = str(kwargs.get("content", ""))
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as error:
            return self.fail(f"Could not write {target.name}: {error}")

        # A file this session created is a file this session has seen, so a
        # follow-up edit needs no separate read.
        self.workspace.reads.record_read(target, content)
        return self.ok(
            f"Created {self.workspace.relative(target)} "
            f"({len(content.splitlines())} lines).",
            path=self.workspace.relative(target),
        )
