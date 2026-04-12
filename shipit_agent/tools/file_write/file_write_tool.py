from __future__ import annotations

from pathlib import Path

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import FILE_WRITE_PROMPT


class FileWriteTool:
    def __init__(
        self,
        *,
        root_dir: str | Path = "/tmp",
        name: str = "write_file",
        description: str = "Create or overwrite a file in the local project.",
        prompt: str | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.name = name
        self.description = description
        self.prompt = prompt or FILE_WRITE_PROMPT
        self.prompt_instructions = (
            "Use this to create or update project files when the task requires direct file output."
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
                        "content": {"type": "string", "description": "File contents"},
                        "mode": {
                            "type": "string",
                            "enum": ["overwrite", "append"],
                            "description": "Write mode",
                        },
                    },
                    "required": ["path", "content"],
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
        path.parent.mkdir(parents=True, exist_ok=True)
        content = str(kwargs.get("content", ""))
        mode = str(kwargs.get("mode", "overwrite"))
        if mode == "append":
            with path.open("a", encoding="utf-8") as handle:
                handle.write(content)
        else:
            path.write_text(content, encoding="utf-8")
        return ToolOutput(
            text=f"File updated: {path}",
            metadata={"path": str(path), "mode": mode, "size": path.stat().st_size},
        )
