from __future__ import annotations

from pathlib import Path

from shipit_agent.tools.base import ToolContext, ToolOutput

from .prompt import EDIT_FILE_PROMPT


class EditFileTool:
    def __init__(
        self,
        *,
        root_dir: str | Path = "/tmp",
        name: str = "edit_file",
        description: str = "Apply an exact string replacement patch to an existing file.",
        prompt: str | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.name = name
        self.description = description
        self.prompt = prompt or EDIT_FILE_PROMPT
        self.prompt_instructions = "Use this for surgical edits after reading the file. Prefer exact replacements over full rewrites."

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
                        "old_text": {
                            "type": "string",
                            "description": "Exact existing text to replace",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Replacement text",
                        },
                        "replace_all": {
                            "type": "boolean",
                            "description": "Replace all matches instead of exactly one",
                        },
                    },
                    "required": ["path", "old_text", "new_text"],
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

        state = getattr(context, "state", {}) or {}
        prior_reads = set(state.get("read_files", []))
        if str(path) not in prior_reads:
            return ToolOutput(
                text=(
                    "Edit blocked: read the file first with read_file so the patch is based on current contents."
                )
            )

        old_text = str(kwargs.get("old_text", ""))
        new_text = str(kwargs.get("new_text", ""))
        replace_all = bool(kwargs.get("replace_all", False))

        content = path.read_text(encoding="utf-8", errors="replace")
        occurrences = content.count(old_text)
        if occurrences == 0:
            return ToolOutput(text="Edit failed: old_text was not found in the file.")
        if occurrences > 1 and not replace_all:
            return ToolOutput(
                text=(
                    "Edit failed: old_text is not unique in the file. Provide a more specific block or set replace_all=true."
                )
            )

        updated = (
            content.replace(old_text, new_text)
            if replace_all
            else content.replace(old_text, new_text, 1)
        )
        path.write_text(updated, encoding="utf-8")
        return ToolOutput(
            text=f"File patched: {path}",
            metadata={
                "path": str(path),
                "replace_all": replace_all,
                "occurrences": occurrences,
                "size": path.stat().st_size,
            },
        )
