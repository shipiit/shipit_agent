from __future__ import annotations

from pathlib import Path

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import FILE_READ_PROMPT


class FileReadTool:
    def __init__(
        self,
        *,
        root_dir: str | Path = "/tmp",
        name: str = "read_file",
        description: str = "Read a file from the local project with optional line ranges.",
        max_chars: int = 12000,
        prompt: str | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.name = name
        self.description = description
        self.max_chars = max_chars
        self.prompt = prompt or FILE_READ_PROMPT
        self.prompt_instructions = (
            "Use this to inspect source files, config files, logs, and artifacts in the local project."
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
                        "path": {"type": "string", "description": "Relative file path"},
                        "start_line": {
                            "type": "number",
                            "description": "1-based starting line number",
                        },
                        "max_lines": {
                            "type": "number",
                            "description": "Maximum number of lines to return",
                        },
                    },
                    "required": ["path"],
                },
            },
        }

    def _resolve(self, relative_path: str) -> Path:
        candidate = (self.root_dir / relative_path).resolve()
        if self.root_dir not in candidate.parents and candidate != self.root_dir:
            raise ValueError("Path escapes project root")
        return candidate

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        path = self._resolve(str(kwargs["path"]))
        if not path.exists():
            return ToolOutput(text=f"File not found: {path}")
        if path.is_dir():
            return ToolOutput(text=f"Path is a directory, not a file: {path}")

        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        start_line = max(1, int(kwargs.get("start_line", 1)))
        max_lines = max(1, int(kwargs.get("max_lines", min(len(lines) or 1, 250))))
        start_index = start_line - 1
        sliced = lines[start_index : start_index + max_lines]
        numbered = "\n".join(
            f"{start_index + index + 1:>5}: {line}"
            for index, line in enumerate(sliced)
        )
        if len(numbered) > self.max_chars:
            numbered = numbered[: self.max_chars].rstrip() + "\n...[truncated]"
        state = getattr(context, "state", None)
        if isinstance(state, dict):
            read_files = list(state.get("read_files", []))
            if str(path) not in read_files:
                read_files.append(str(path))
            state["read_files"] = read_files
        return ToolOutput(
            text=numbered or "(file is empty)",
            metadata={
                "path": str(path),
                "start_line": start_line,
                "returned_lines": len(sliced),
                "total_lines": len(lines),
            },
        )
