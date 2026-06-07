from __future__ import annotations

from pathlib import Path

from shipit_agent.tools.base import ToolContext, ToolOutput

CLAUDE_MEMORY_TOOL_PROMPT = """

## memory

Read and write a persistent memory directory that survives across sessions.
Use it to build up durable notes, intermediate results, and learnings on
long-horizon tasks so future runs can pick up where you left off.

**Commands** (pass via the ``command`` argument):
- ``view`` — list a directory or show a file (with line numbers).
- ``create`` — create or overwrite a file with ``file_text``.
- ``str_replace`` — replace a single unique occurrence of ``old_str`` with ``new_str``.
- ``insert`` — insert ``insert_text`` after line ``insert_line`` (0 = start of file).
- ``delete`` — delete a file.
- ``rename`` — move/rename a file from ``old_path`` to ``new_path``.

**Rules:**
- Check memory (``view``) at the start of a task before redoing work.
- Keep entries concise and factual; prefer small, well-named files.
- All paths are confined to the memory sandbox root — paths that escape it
  are rejected.
""".strip()


class MemoryToolError(Exception):
    """Raised internally for handled, user-facing memory tool errors."""


class ClaudeMemoryTool:
    """Anthropic-style ``memory_20250818`` tool.

    A single tool the model invokes with a ``command`` argument to read and
    write a persistent, sandboxed memory directory. Every command is confined
    to ``root_dir``; paths that resolve outside it are rejected.
    """

    def __init__(
        self,
        *,
        root_dir: str | Path = ".shipit_workspace/memories",
        name: str = "claude_memory",
        description: str = (
            "Read and write a persistent memory directory (Anthropic memory tool)."
        ),
        prompt: str | None = None,
    ) -> None:
        # Resolve but do NOT create the directory eagerly — keep construction
        # side-effect free so importing/instantiating doesn't litter the repo.
        self.root_dir = Path(root_dir).resolve()
        self.name = name
        self.description = description
        self.prompt = prompt or CLAUDE_MEMORY_TOOL_PROMPT
        self.prompt_instructions = (
            "Use this to persist notes, intermediate results, and learnings "
            "across sessions in a sandboxed memory directory."
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
                        "command": {
                            "type": "string",
                            "enum": [
                                "view",
                                "create",
                                "str_replace",
                                "insert",
                                "delete",
                                "rename",
                            ],
                            "description": "The memory command to run.",
                        },
                        "path": {
                            "type": "string",
                            "description": (
                                "Target path relative to the memory root "
                                "(used by view/create/str_replace/insert/delete)."
                            ),
                        },
                        "file_text": {
                            "type": "string",
                            "description": "File contents for the create command.",
                        },
                        "old_str": {
                            "type": "string",
                            "description": "Unique string to replace (str_replace).",
                        },
                        "new_str": {
                            "type": "string",
                            "description": "Replacement string (str_replace).",
                        },
                        "insert_line": {
                            "type": "integer",
                            "description": (
                                "Line number to insert after (insert); 0 inserts "
                                "at the start of the file."
                            ),
                        },
                        "insert_text": {
                            "type": "string",
                            "description": "Text to insert (insert).",
                        },
                        "old_path": {
                            "type": "string",
                            "description": "Source path for the rename command.",
                        },
                        "new_path": {
                            "type": "string",
                            "description": "Destination path for the rename command.",
                        },
                    },
                    "required": ["command"],
                },
            },
        }

    # ── path confinement ──────────────────────────────────────────────────

    def _resolve(self, relative_path: str) -> Path:
        """Resolve *relative_path* inside the sandbox root.

        Accepts relative paths (joined onto ``root_dir``) and absolute paths
        that already live under the root. Anything that escapes the root after
        resolution is rejected, so ``..`` traversal and absolute paths outside
        the sandbox cannot reach the wider filesystem.
        """
        if relative_path is None or str(relative_path).strip() == "":
            raise MemoryToolError("a path is required")
        candidate_path = Path(str(relative_path))
        if candidate_path.is_absolute():
            candidate = candidate_path.resolve()
        else:
            candidate = (self.root_dir / candidate_path).resolve()
        if candidate != self.root_dir and not candidate.is_relative_to(self.root_dir):
            raise MemoryToolError(
                f"path escapes the memory root: {candidate} is not under {self.root_dir}"
            )
        return candidate

    def _rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root_dir)) or "."
        except ValueError:
            return str(path)

    # ── dispatch ──────────────────────────────────────────────────────────

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        command = str(kwargs.get("command", "")).strip()
        try:
            if command == "view":
                return self._view(str(kwargs.get("path", "")))
            if command == "create":
                return self._create(
                    str(kwargs.get("path", "")), str(kwargs.get("file_text", ""))
                )
            if command == "str_replace":
                return self._str_replace(
                    str(kwargs.get("path", "")),
                    str(kwargs.get("old_str", "")),
                    str(kwargs.get("new_str", "")),
                )
            if command == "insert":
                return self._insert(
                    str(kwargs.get("path", "")),
                    kwargs.get("insert_line", 0),
                    str(kwargs.get("insert_text", "")),
                )
            if command == "delete":
                return self._delete(str(kwargs.get("path", "")))
            if command == "rename":
                return self._rename(
                    str(kwargs.get("old_path", "")),
                    str(kwargs.get("new_path", "")),
                )
            return ToolOutput(text=f"Error: unsupported memory command: {command!r}")
        except MemoryToolError as exc:
            return ToolOutput(text=f"Error: {exc}")
        except OSError as exc:
            return ToolOutput(text=f"Error: {exc}")

    # ── commands ──────────────────────────────────────────────────────────

    def _view(self, path: str) -> ToolOutput:
        target = self._resolve(path)
        if target.is_dir():
            entries = sorted(
                target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            )
            if not entries:
                return ToolOutput(
                    text=f"Directory {self._rel(target)}/ is empty.",
                    metadata={"path": self._rel(target), "kind": "dir", "count": 0},
                )
            lines = [
                f"{p.name}/" if p.is_dir() else p.name for p in entries
            ]
            body = "\n".join(lines)
            return ToolOutput(
                text=f"Directory {self._rel(target)}/:\n{body}",
                metadata={
                    "path": self._rel(target),
                    "kind": "dir",
                    "count": len(entries),
                },
            )
        if not target.exists():
            raise MemoryToolError(f"no such file or directory: {self._rel(target)}")
        content = target.read_text(encoding="utf-8")
        numbered = "\n".join(
            f"{i:>6}\t{line}"
            for i, line in enumerate(content.splitlines(), start=1)
        )
        return ToolOutput(
            text=numbered if numbered else "(empty file)",
            metadata={"path": self._rel(target), "kind": "file"},
        )

    def _create(self, path: str, file_text: str) -> ToolOutput:
        target = self._resolve(path)
        if target.is_dir():
            raise MemoryToolError(
                f"cannot create file; {self._rel(target)} is a directory"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file_text, encoding="utf-8")
        return ToolOutput(
            text=f"Created {self._rel(target)} ({len(file_text)} bytes).",
            metadata={"path": self._rel(target), "size": len(file_text)},
        )

    def _str_replace(self, path: str, old_str: str, new_str: str) -> ToolOutput:
        target = self._resolve(path)
        if not target.is_file():
            raise MemoryToolError(f"no such file: {self._rel(target)}")
        if old_str == "":
            raise MemoryToolError("old_str must not be empty")
        content = target.read_text(encoding="utf-8")
        occurrences = content.count(old_str)
        if occurrences == 0:
            raise MemoryToolError(
                f"old_str not found in {self._rel(target)}"
            )
        if occurrences > 1:
            raise MemoryToolError(
                f"old_str is not unique in {self._rel(target)} "
                f"({occurrences} matches); provide more context"
            )
        content = content.replace(old_str, new_str, 1)
        target.write_text(content, encoding="utf-8")
        return ToolOutput(
            text=f"Replaced 1 occurrence in {self._rel(target)}.",
            metadata={"path": self._rel(target)},
        )

    def _insert(self, path: str, insert_line, insert_text: str) -> ToolOutput:
        target = self._resolve(path)
        if not target.is_file():
            raise MemoryToolError(f"no such file: {self._rel(target)}")
        try:
            line_no = int(insert_line)
        except (TypeError, ValueError):
            raise MemoryToolError("insert_line must be an integer") from None
        lines = target.read_text(encoding="utf-8").splitlines()
        if line_no < 0 or line_no > len(lines):
            raise MemoryToolError(
                f"insert_line {line_no} out of range (0..{len(lines)})"
            )
        # Insert AFTER line `line_no` (0 == start of file).
        new_lines = lines[:line_no] + insert_text.splitlines() + lines[line_no:]
        target.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return ToolOutput(
            text=f"Inserted text after line {line_no} in {self._rel(target)}.",
            metadata={"path": self._rel(target), "insert_line": line_no},
        )

    def _delete(self, path: str) -> ToolOutput:
        target = self._resolve(path)
        if target == self.root_dir:
            raise MemoryToolError("refusing to delete the memory root")
        if not target.exists():
            raise MemoryToolError(f"no such file or directory: {self._rel(target)}")
        if target.is_dir():
            raise MemoryToolError(
                f"{self._rel(target)} is a directory; only files can be deleted"
            )
        target.unlink()
        return ToolOutput(
            text=f"Deleted {self._rel(target)}.",
            metadata={"path": self._rel(target)},
        )

    def _rename(self, old_path: str, new_path: str) -> ToolOutput:
        source = self._resolve(old_path)
        dest = self._resolve(new_path)
        if not source.exists():
            raise MemoryToolError(f"no such file or directory: {self._rel(source)}")
        if dest.exists():
            raise MemoryToolError(f"destination already exists: {self._rel(dest)}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        source.rename(dest)
        return ToolOutput(
            text=f"Renamed {self._rel(source)} -> {self._rel(dest)}.",
            metadata={"old_path": self._rel(source), "new_path": self._rel(dest)},
        )
