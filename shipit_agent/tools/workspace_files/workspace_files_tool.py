from __future__ import annotations

from pathlib import Path

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import WORKSPACE_FILES_PROMPT


class WorkspaceFilesTool:
    def __init__(
        self,
        *,
        root_dir: str | Path = ".shipit_workspace",
        name: str = "workspace_files",
        description: str = "Read, write, list, and inspect files in the local shipit workspace.",
        prompt: str | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.name = name
        self.description = description
        self.prompt = prompt or WORKSPACE_FILES_PROMPT
        self.prompt_instructions = (
            "Use this for file-based workflows, artifact staging, notes, and intermediate outputs. "
            "Keep writes scoped to the workspace."
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
                        "action": {
                            "type": "string",
                            "description": "Operation to perform",
                            "enum": ["list", "read", "write", "append", "mkdir"],
                        },
                        "path": {
                            "type": "string",
                            "description": "Relative path inside the workspace",
                        },
                        "content": {
                            "type": "string",
                            "description": "Content for write or append",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    def _resolve(self, relative_path: str | None) -> Path:
        relative = Path(relative_path or ".")
        candidate = (self.root_dir / relative).resolve()
        root = self.root_dir.resolve()
        if root not in candidate.parents and candidate != root:
            raise ValueError("Path escapes workspace root")
        return candidate

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        action = str(kwargs["action"])
        path = self._resolve(kwargs.get("path"))

        if action == "mkdir":
            path.mkdir(parents=True, exist_ok=True)
            return ToolOutput(text=f"Directory created: {path}")

        if action == "list":
            target = path if path.exists() else self.root_dir
            items = (
                sorted(
                    str(item.relative_to(self.root_dir)) for item in target.iterdir()
                )
                if target.exists()
                else []
            )
            return ToolOutput(
                text="\n".join(items) if items else "Workspace is empty.",
                metadata={"items": items},
            )

        if action == "read":
            if not path.exists():
                return ToolOutput(text=f"File not found: {path}")
            return ToolOutput(
                text=path.read_text(encoding="utf-8"), metadata={"path": str(path)}
            )

        if action in {"write", "append"}:
            path.parent.mkdir(parents=True, exist_ok=True)
            content = str(kwargs.get("content", ""))
            if action == "write":
                path.write_text(content, encoding="utf-8")
            else:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(content)
            return ToolOutput(
                text=f"File updated: {path}",
                metadata={"path": str(path), "size": path.stat().st_size},
            )

        raise ValueError(f"Unsupported action: {action}")
