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
        self.prompt_instructions = "Use this to inspect source files, config files, logs, and artifacts in the local project."

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
        # Accept absolute paths inside root_dir as well as relative ones; use
        # is_relative_to so symlinked roots (/tmp -> /private/tmp) don't
        # trigger a false "escapes project root" rejection.
        candidate_path = Path(relative_path)
        if candidate_path.is_absolute():
            candidate = candidate_path.resolve()
        else:
            candidate = (self.root_dir / candidate_path).resolve()
        if not candidate.is_relative_to(self.root_dir):
            raise ValueError(
                f"Path escapes project root: {candidate} is not under {self.root_dir}"
            )
        return candidate

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        path = self._resolve(str(kwargs["path"]))
        if not path.exists():
            return ToolOutput(text=f"File not found: {path}")
        if path.is_dir():
            return ToolOutput(text=f"Path is a directory, not a file: {path}")

        # Decode lossily for display, but flag when invalid bytes were
        # replaced with U+FFFD so the caller knows the on-disk content is not
        # pure UTF-8 (and must not be edited as text — see edit_file).
        content = path.read_text(encoding="utf-8", errors="replace")
        had_replacement = "�" in content
        lines = content.splitlines()
        start_line = max(1, int(kwargs.get("start_line", 1)))
        max_lines = max(1, int(kwargs.get("max_lines", min(len(lines) or 1, 250))))
        start_index = start_line - 1
        sliced = lines[start_index : start_index + max_lines]
        numbered = "\n".join(
            f"{start_index + index + 1:>5}: {line}" for index, line in enumerate(sliced)
        )
        if len(numbered) > self.max_chars:
            numbered = numbered[: self.max_chars].rstrip() + "\n...[truncated]"
        state = getattr(context, "state", None)
        if isinstance(state, dict):
            read_files = list(state.get("read_files", []))
            if str(path) not in read_files:
                read_files.append(str(path))
            state["read_files"] = read_files
        body = numbered or "(file is empty)"
        if had_replacement:
            body = (
                "[warning: file is not valid UTF-8; invalid bytes shown as "
                "U+FFFD. Do not edit as text.]\n" + body
            )
        return ToolOutput(
            text=body,
            metadata={
                "path": str(path),
                "start_line": start_line,
                "returned_lines": len(sliced),
                "total_lines": len(lines),
                "utf8_replacement": had_replacement,
            },
        )
