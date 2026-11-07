"""The ``edit_file`` tool: apply an exact string replacement patch to an existing file.
"""

from __future__ import annotations

from pathlib import Path

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.file_state import changed_on_disk, missing_text_hint

from .prompt import EDIT_FILE_PROMPT
from shipit_agent.tools.paths import resolve_in_roots


class EditFileTool:
    """The ``edit_file`` tool: apply an exact string replacement patch to an existing file.
    """
    def __init__(
        self,
        *,
        root_dir: str | Path = "/tmp",
        name: str = "edit_file",
        description: str = "Apply an exact string replacement patch to an existing file.",
        prompt: str | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        #: Folders beside the project this tool may also use (AgentOptions.add_dirs).
        self.extra_roots: tuple[Path, ...] = ()
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
        return resolve_in_roots(relative_path, self.root_dir, self.extra_roots)

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
            return ToolOutput.error(
                "Edit failed: missing required argument `path`. "
                "Call edit_file with path, old_text, and new_text.",
                error="missing_path",
            )
        path = self._resolve(str(raw))
        if not path.exists():
            return ToolOutput.error(
                f"File not found: {path}. Check the path with glob_files, or create "
                "the file with write_file.",
                path=str(path), error="not_found",
            )
        if path.is_dir():
            return ToolOutput.error(
                f"Path is a directory, not a file: {path}", path=str(path), error="is_directory"
            )

        state = getattr(context, "state", {}) or {}
        prior_reads = set(state.get("read_files", []))
        if str(path) not in prior_reads:
            return ToolOutput.error(
                "Edit blocked: read the file first with read_file so the patch is "
                "based on current contents.",
                path=str(path), error="not_read",
            )
        # An outside change (a formatter, another tool) is no reason to refuse
        # an exact-text edit: it is applied to the file as it is now. Only a
        # target that no longer matches needs a fresh read.
        changed_since_read = changed_on_disk(state, path)

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
                    "is_error": True,
                    "error": "not_utf8",
                    "encoding_error": str(exc),
                },
            )
        occurrences = content.count(old_text)
        if occurrences == 0 and changed_since_read:
            return ToolOutput.error(
                f"Edit blocked: {path.name} changed on disk after it was read and "
                "old_text is no longer in it. Re-read the file with read_file, "
                "then retry against its current contents. No changes were made.",
                path=str(path), error="stale_read",
            )
        if occurrences == 0:
            return ToolOutput.error(
                f"Edit failed: old_text was not found in {path.name}."
                + (
                    missing_text_hint(old_text, content)
                    or " Re-read the file and copy the exact text to replace, "
                    "including whitespace and indentation."
                )
                + " No changes were made.",
                path=str(path), error="old_text_not_found",
            )
        if occurrences > 1 and not replace_all:
            return ToolOutput.error(
                f"Edit failed: old_text matches {occurrences} places in {path.name}. "
                "Include more surrounding lines so it matches exactly one, or set "
                "replace_all=true to change every match. No changes were made.",
                path=str(path), error="old_text_not_unique", occurrences=occurrences,
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
                ("(The file had changed on disk since it was read; the edit was applied to its current contents.)\n" if changed_since_read else "")
                + f"File patched: {path} "
                f"({replaced} occurrence{'s' if replaced != 1 else ''} replaced)\n"
                f"{diff_text}"
            ),
            metadata={
                "path": str(path),
                "replace_all": replace_all,
                "occurrences": occurrences,
                "changed_since_read": changed_since_read,
                "size": path.stat().st_size,
                "diff": diff_text,
            },
        )
