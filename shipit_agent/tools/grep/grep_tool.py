"""Search file contents, grouped by file and bounded."""

from __future__ import annotations

import fnmatch
import re
from typing import Any

from shipit_agent.tools._shared import ToolBase, walk
from shipit_agent.tools.grep.prompt import DESCRIPTION, INSTRUCTIONS

__all__ = ["GrepTool"]


class GrepTool(ToolBase):
    name = "grep"
    description = DESCRIPTION
    prompt_instructions = INSTRUCTIONS

    def schema(self) -> dict[str, Any]:
        return self.build_schema(
            {
                "pattern": {"type": "string", "description": "Regular expression."},
                "glob": {"type": "string", "description": "Restrict to matching paths."},
                "limit": {"type": "integer", "description": "Maximum matching lines."},
                "ignore_case": {"type": "boolean", "description": "Case-insensitive."},
            },
            ["pattern"],
        )

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        pattern = str(kwargs.get("pattern", ""))
        if not pattern:
            return self.fail("No pattern given.")
        try:
            regex = re.compile(pattern, re.IGNORECASE if kwargs.get("ignore_case") else 0)
        except re.error as error:
            # A result, not a raise: the model rewrites the pattern next turn.
            return self.fail(f"Invalid regular expression: {error}")

        restrict = str(kwargs.get("glob") or "")
        limit = int(kwargs.get("limit") or 100)
        groups: dict[str, list[str]] = {}
        total = 0

        for path in walk(self.workspace.root):
            relative = self.workspace.relative(path)
            if restrict and not fnmatch.fnmatch(relative, restrict):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if not regex.search(line):
                    continue
                total += 1
                if total > limit:
                    break
                groups.setdefault(relative, []).append(f"{number:>5}  {line.strip()[:200]}")
            if total > limit:
                break

        if not groups:
            return self.ok(f"No matches for {pattern!r}.", matches=0)
        body = "\n\n".join(
            f"{name}\n" + "\n".join(lines) for name, lines in sorted(groups.items())
        )
        more = f"\n\n[stopped at {limit} matches]" if total > limit else ""
        return self.ok(
            body + more,
            hint="Narrow with a glob or a more specific pattern.",
            matches=total,
            files=len(groups),
        )
