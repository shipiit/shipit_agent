"""Read a file, recording it so an edit can check its freshness."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools._shared import ToolBase
from shipit_agent.tools.read_file.prompt import DESCRIPTION, INSTRUCTIONS

__all__ = ["ReadFileTool"]


class ReadFileTool(ToolBase):
    name = "read_file"
    description = DESCRIPTION
    prompt_instructions = INSTRUCTIONS

    def schema(self) -> dict[str, Any]:
        return self.build_schema(
            {
                "path": {"type": "string", "description": "Path to the file."},
                "offset": {"type": "integer", "description": "First line (1-based)."},
                "limit": {"type": "integer", "description": "How many lines to read."},
            },
            ["path"],
        )

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        try:
            target = self.workspace.resolve(str(kwargs.get("path", "")))
        except ValueError as error:
            return self.fail(str(error))
        if not target.is_file():
            return self.fail(f"{kwargs.get('path')} is not a file.")

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            return self.fail(f"Could not read {target.name}: {error}")

        # Recorded whole, always. The freshness check compares the file on disk,
        # so recording only the window read would make every partial read look
        # like an external modification.
        self.workspace.reads.record_read(target, content)

        lines = content.splitlines()
        offset = max(1, int(kwargs.get("offset") or 1))
        limit = int(kwargs.get("limit") or len(lines))
        window = lines[offset - 1 : offset - 1 + limit]

        width = len(str(offset + len(window)))
        body = "\n".join(f"{offset + i:>{width}}  {line}" for i, line in enumerate(window))
        footer = (
            f"\n\n[lines {offset}–{offset + len(window) - 1} of {len(lines)}]"
            if len(window) < len(lines)
            else ""
        )
        return self.ok(
            (body or "(empty file)") + footer,
            hint="Read a narrower range with offset and limit.",
            path=self.workspace.relative(target),
            lines=len(lines),
        )
