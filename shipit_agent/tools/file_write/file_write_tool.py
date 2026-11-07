"""The ``write_file`` tool: create or overwrite a file in the local project."""

from __future__ import annotations

from pathlib import Path

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.file_state import record_file_seen
from .prompt import FILE_WRITE_PROMPT
from shipit_agent.tools.paths import resolve_in_roots, shown_path


class FileWriteTool:
    """The ``write_file`` tool: create or overwrite a file in the local project."""
    def __init__(
        self,
        *,
        root_dir: str | Path = "/tmp",
        name: str = "write_file",
        description: str = "Create or overwrite a file in the local project.",
        prompt: str | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        #: Folders beside the project this tool may also use (AgentOptions.add_dirs).
        self.extra_roots: tuple[Path, ...] = ()
        self.name = name
        self.description = description
        self.prompt = prompt or FILE_WRITE_PROMPT
        self.prompt_instructions = "Use this to create or update project files when the task requires direct file output."

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
        return resolve_in_roots(relative_path, self.root_dir, self.extra_roots)

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        try:
            path = self._resolve(str(kwargs["path"]))
        except ValueError:
            return ToolOutput.error(
                f"Not written: {kwargs['path']} is outside the project. Write "
                f"files inside the project ({self.root_dir}), using a path "
                "relative to it.",
                path=str(kwargs["path"]),
                error="outside_project",
            )
        existed = path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        content = str(kwargs.get("content", ""))
        mode = str(kwargs.get("mode", "overwrite"))
        if mode == "append":
            with path.open("a", encoding="utf-8") as handle:
                handle.write(content)
        else:
            path.write_text(content, encoding="utf-8")
            # A full write means the agent knows the exact contents, so it may
            # edit next without re-reading. An append does not: what was
            # already in the file is still unseen.
            record_file_seen(getattr(context, "state", None), path)
        shown = shown_path(path, self.root_dir)
        lines = content.count("\n") + (0 if content.endswith("\n") or not content else 1)
        verb = "Appended to" if mode == "append" else "Overwrote" if existed else "Created"
        return ToolOutput(
            text=f"{verb} {shown} ({lines} line{'s' if lines != 1 else ''}).",
            metadata={
                "path": str(path),
                "mode": mode,
                "created": not existed,
                "size": path.stat().st_size,
            },
        )
