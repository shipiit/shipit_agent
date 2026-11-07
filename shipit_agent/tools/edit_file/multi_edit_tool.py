"""``multi_edit`` — a batch of edits applied to one file, atomically.

On a multi-hunk change, one string-replace per
tool call is slow (a round-trip per hunk) and unsafe (an earlier edit can
invalidate a later hunk's ``old_text``). This applies every edit to an
in-memory copy in order and writes once — all succeed or nothing is written.
Same read-before-edit gate, mtime staleness check, and UTF-8 refusal as
``edit_file``.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.file_state import changed_on_disk, missing_text_hint


class MultiEditTool:
    """The ``multi_edit`` tool: apply several exact string-replacement edits to ONE file atomically.
    """
    read_only = False

    def __init__(
        self,
        *,
        root_dir: str | Path = "/tmp",
        name: str = "multi_edit",
        description: str = (
            "Apply several exact string-replacement edits to ONE file "
            "atomically. Edits apply in order to the same file; if any "
            "old_text is missing or ambiguous, nothing is written."
        ),
        prompt: str | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.name = name
        self.description = description
        self.prompt = prompt or (
            "Use multi_edit when you have several changes to the same file — "
            "it applies them together, so a later edit never breaks on text an "
            "earlier edit changed, and you pay one tool call instead of many. "
            "Read the file first."
        )
        self.prompt_instructions = (
            "Batch edits to one file: pass path and edits=[{old_text, "
            "new_text, replace_all?}]. Order matters; each edit sees the "
            "result of the ones before it."
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
                        "path": {"type": "string", "description": "File to edit."},
                        "edits": {
                            "type": "array",
                            "description": (
                                "Edits applied in order. Each: old_text (exact "
                                "text to find), new_text (replacement), and "
                                "optional replace_all (default false)."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "old_text": {"type": "string"},
                                    "new_text": {"type": "string"},
                                    "replace_all": {"type": "boolean"},
                                },
                                "required": ["old_text", "new_text"],
                            },
                        },
                    },
                    "required": ["path", "edits"],
                },
            },
        }

    def _resolve(self, relative_path: str) -> Path:
        candidate_path = Path(relative_path)
        candidate = (
            candidate_path.resolve()
            if candidate_path.is_absolute()
            else (self.root_dir / candidate_path).resolve()
        )
        if not candidate.is_relative_to(self.root_dir):
            raise ValueError(
                f"Path escapes project root: {candidate} is not under {self.root_dir}"
            )
        return candidate

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        raw = kwargs.get("path") or kwargs.get("file_path")
        if not raw:
            return ToolOutput.error("multi_edit failed: missing required argument `path`.", error="missing_path")
        edits = kwargs.get("edits")
        if not isinstance(edits, list) or not edits:
            return ToolOutput.error(
                "multi_edit failed: `edits` must be a non-empty array of "
                "{old_text, new_text} objects.",
                error="invalid_edits",
            )
        try:
            path = self._resolve(str(raw))
        except ValueError as exc:
            return ToolOutput.error(str(exc), error="invalid_path")
        if not path.exists():
            return ToolOutput.error(f"File not found: {path}", path=str(path), error="not_found")
        if path.is_dir():
            return ToolOutput.error(f"Path is a directory, not a file: {path}", path=str(path), error="is_directory")

        state = getattr(context, "state", {}) or {}
        if str(path) not in set(state.get("read_files", [])):
            return ToolOutput.error(
                "multi_edit blocked: read the file first with read_file so "
                "the edits are based on current contents.",
                path=str(path), error="not_read",
            )
        # Applied to the file as it is now; only a target that no longer
        # matches after an outside change needs a fresh read.
        changed_since_read = changed_on_disk(state, path)

        try:
            content = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            return ToolOutput(
                text=f"multi_edit refused: file is not valid UTF-8 ({exc.reason}).",
                metadata={"path": str(path), "error": "not_utf8", "is_error": True},
            )

        # Apply to an in-memory copy first — all-or-nothing. A single bad
        # edit aborts the whole batch with nothing written, naming which
        # edit failed so the model can fix just that one.
        working = content
        applied = 0
        for index, edit in enumerate(edits, start=1):
            if not isinstance(edit, dict):
                return ToolOutput.error(f"multi_edit failed: edit #{index} is not an object.", error="invalid_edits")
            old_text = str(edit.get("old_text", ""))
            new_text = str(edit.get("new_text", ""))
            replace_all = bool(edit.get("replace_all", False))
            count = working.count(old_text)
            if count == 0 and changed_since_read:
                return ToolOutput(
                    text=f"multi_edit blocked at edit #{index}: {path.name} changed "
                    "on disk after it was read and that old_text is no longer in "
                    "it. Re-read the file, then retry (no changes written).",
                    metadata={
                        "path": str(path),
                        "error": "stale_read",
                        "failed_edit": index,
                        "is_error": True,
                    },
                )
            if count == 0:
                return ToolOutput(
                    text=f"multi_edit failed at edit #{index}: old_text not found "
                    "(no changes written)."
                    + (
                        missing_text_hint(old_text, working)
                        or " It may have been altered by an earlier edit in this "
                        "batch, or never existed."
                    ),
                    metadata={"path": str(path), "failed_edit": index, "is_error": True},
                )
            if count > 1 and not replace_all:
                return ToolOutput(
                    text=f"multi_edit failed at edit #{index}: old_text is not "
                    "unique (no changes written). Make it specific or set "
                    "replace_all=true for that edit.",
                    metadata={"path": str(path), "failed_edit": index, "is_error": True},
                )
            working = (
                working.replace(old_text, new_text)
                if replace_all
                else working.replace(old_text, new_text, 1)
            )
            applied += 1

        path.write_text(working, encoding="utf-8")
        if isinstance(state, dict) and "read_file_mtimes" in state:
            try:
                state["read_file_mtimes"][str(path)] = path.stat().st_mtime_ns
            except OSError:
                pass

        diff = "\n".join(
            difflib.unified_diff(
                content.splitlines(),
                working.splitlines(),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
                lineterm="",
                n=2,
            )
        )
        if len(diff) > 6000:
            diff = diff[:6000].rstrip() + "\n… (diff truncated)"
        return ToolOutput(
            text=("(The file had changed on disk since it was read; the edit was applied to its current contents.)\n" if changed_since_read else "")
            + f"File patched: {path} ({applied} edits applied)\n{diff}",
            metadata={
                "path": str(path),
                "edits_applied": applied,
                "changed_since_read": changed_since_read,
            },
        )

