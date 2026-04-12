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
        candidate = (self.root_dir / (relative_path or ".")).resolve()
        if self.root_dir not in candidate.parents and candidate != self.root_dir:
            raise ValueError("Path escapes project root")
        return candidate

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        base = self._resolve(kwargs.get("path"))
        pattern = str(kwargs["pattern"])
        limit = max(1, int(kwargs.get("limit", 200)))
        matches = sorted(
            Path(match).resolve()
            for match in glob.glob(str(base / pattern), recursive=True)
        )
        filtered = [
            str(match.relative_to(self.root_dir))
            for match in matches
            if self.root_dir in match.parents or match == self.root_dir
        ][:limit]
        return ToolOutput(
            text="\n".join(filtered) if filtered else "No matching files found.",
            metadata={"matches": filtered, "count": len(filtered), "pattern": pattern},
        )
