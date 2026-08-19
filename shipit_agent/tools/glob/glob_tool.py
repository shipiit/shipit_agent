"""Find files by name, newest first, skipping the directories nobody means."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools._shared import ToolBase, is_ignored
from shipit_agent.tools.glob.prompt import DESCRIPTION, INSTRUCTIONS

__all__ = ["GlobTool"]


class GlobTool(ToolBase):
    name = "glob"
    description = DESCRIPTION
    prompt_instructions = INSTRUCTIONS

    def schema(self) -> dict[str, Any]:
        return self.build_schema(
            {
                "pattern": {"type": "string", "description": "Glob pattern."},
                "limit": {"type": "integer", "description": "Maximum paths to return."},
            },
            ["pattern"],
        )

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        pattern = str(kwargs.get("pattern", "")).strip()
        if not pattern:
            return self.fail("No pattern given.")
        limit = int(kwargs.get("limit") or 200)

        matches = [
            path
            for path in self.workspace.root.glob(pattern)
            if path.is_file() and not is_ignored(path, self.workspace.root)
        ]
        # Most recently modified first: in a live codebase, recency is the best
        # cheap proxy for relevance.
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        shown = matches[:limit]

        if not shown:
            return self.ok(f"No files match {pattern!r}.", matches=0)
        body = "\n".join(self.workspace.relative(p) for p in shown)
        more = f"\n\n[{len(matches) - len(shown)} more]" if len(matches) > len(shown) else ""
        return self.ok(body + more, matches=len(matches))
