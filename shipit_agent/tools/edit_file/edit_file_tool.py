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
        # Some models like to call this tool with `file_path` / `filepath`
        # instead of the documented `path`. Rather than crashing the whole
        # run on a KeyError, accept the common aliases and return a
        # friendly error if none of them are present.
        raw = (
            kwargs.get("path")
            or kwargs.get("file_path")
            or kwargs.get("filepath")
            or kwargs.get("filename")
        )
        if not raw:
            return ToolOutput(
                text=(
                    "Edit failed: missing required argument `path`. "
                    "Call edit_file with path, old_text, and new_text."
                )
            )
        path = self._resolve(str(raw))
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
        # External-change detection: if the file's mtime moved since the last
        # read_file, the patch may be based on stale contents.
        recorded_mtime = (state.get("read_file_mtimes") or {}).get(str(path))
        if recorded_mtime is not None:
            try:
                current_mtime = path.stat().st_mtime_ns
            except OSError:
                current_mtime = None
            if current_mtime is not None and current_mtime != recorded_mtime:
                return ToolOutput(
                    text=(
                        "Edit blocked: the file changed on disk after it was "
                        "read (external modification). Re-read it with "
                        "read_file, then retry the edit against the current "
                        "contents."
                    ),
                    metadata={"path": str(path), "error": "stale_read"},
                )

        old_text = str(kwargs.get("old_text", ""))
        new_text = str(kwargs.get("new_text", ""))
        replace_all = bool(kwargs.get("replace_all", False))

        # Read raw bytes and decode strictly. Reading with errors="replace"
        # would turn invalid bytes into U+FFFD, and writing the result back
        # would silently corrupt a non-UTF-8 file while reporting success.
        # Refuse to edit anything we can't round-trip losslessly.
        raw = path.read_bytes()
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            return ToolOutput(
                text=(
                    "Edit refused: file is not valid UTF-8 "
                    f"({exc.reason} at byte {exc.start}). Editing it as text "
                    "would corrupt its contents, so no changes were made."
                ),
                metadata={
                    "path": str(path),
                    "error": "not_utf8",
                    "encoding_error": str(exc),
                },
            )
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

        # Keep the recorded mtime current so sequential edits to the same
        # file don't trip the external-change guard.
        if isinstance(state, dict) and "read_file_mtimes" in state:
            try:
                state["read_file_mtimes"][str(path)] = path.stat().st_mtime_ns
            except OSError:
                pass

        # A compact unified diff so reviewers (and the model) see exactly
        # what changed without re-reading the file.
        import difflib

        diff_lines = list(
            difflib.unified_diff(
                content.splitlines(),
                updated.splitlines(),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
                lineterm="",
                n=2,
            )
        )
        diff_text = "\n".join(diff_lines)
        if len(diff_text) > 4000:
            diff_text = diff_text[:4000].rstrip() + "\n… (diff truncated)"

        replaced = occurrences if replace_all else 1
        return ToolOutput(
            text=(
                f"File patched: {path} "
                f"({replaced} occurrence{'s' if replaced != 1 else ''} replaced)\n"
                f"{diff_text}"
            ),
            metadata={
                "path": str(path),
                "replace_all": replace_all,
                "occurrences": occurrences,
                "size": path.stat().st_size,
                "diff": diff_text,
            },
        )
