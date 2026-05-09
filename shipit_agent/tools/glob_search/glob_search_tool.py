from __future__ import annotations

import glob
from pathlib import Path

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import GLOB_SEARCH_PROMPT


class GlobSearchTool:
    def __init__(
        self,
        *,
        root_dir: str | Path = "/tmp",
        name: str = "glob_files",
        description: str = "Find files in the local project by glob pattern.",
        prompt: str | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.name = name
        self.description = description
        self.prompt = prompt or GLOB_SEARCH_PROMPT
        self.prompt_instructions = (
            "Use this to discover files before reading, editing, or reviewing them."
        )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Glob pattern such as **/*.py or src/**/*.ts",
                        },
                        "path": {
                            "type": "string",
                            "description": "Optional relative directory to search from",
                        },
                        "limit": {
                            "type": "number",
                            "description": "Maximum number of results to return",
                        },
                    },
                    "required": ["pattern"],
                },
            },
        }

    def _resolve(self, relative_path: str | None) -> Path:
        # Accept either a relative path (joined to root_dir) or an
        # absolute path that already lives inside root_dir. Use
        # is_relative_to() instead of "in parents" so symlinked
        # workspace roots (/tmp -> /private/tmp on macOS, .shipit
        # workspaces) don't trip a false "escapes project root" when
        # the LLM passes back the absolute path the engagement created.
        rel = relative_path or "."
        candidate_path = Path(rel)
        if candidate_path.is_absolute():
            candidate = candidate_path.resolve()
        else:
            candidate = (self.root_dir / candidate_path).resolve()
        try:
            candidate.relative_to(self.root_dir)
        except ValueError:
            raise ValueError(
                f"Path escapes project root: {candidate} is not under {self.root_dir}"
            ) from None
        return candidate

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        base = self._resolve(kwargs.get("path"))
        pattern = str(kwargs["pattern"])
        limit = max(1, int(kwargs.get("limit", 200)))
        matches = sorted(
            Path(match).resolve()
            for match in glob.glob(str(base / pattern), recursive=True)
        )
        # Use is_relative_to so symlinked workspace roots (/tmp -> /private/tmp
        # on macOS) don't drop legitimate matches when the symlink isn't on
        # the parents chain. _resolve already enforces containment.
        filtered = [
            str(match.relative_to(self.root_dir))
            for match in matches
            if match.is_relative_to(self.root_dir)
        ][:limit]
        return ToolOutput(
            text="\n".join(filtered) if filtered else "No matching files found.",
            metadata={"matches": filtered, "count": len(filtered), "pattern": pattern},
        )
