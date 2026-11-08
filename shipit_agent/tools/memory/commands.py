"""The memory tool's file commands: view, create, str_replace, insert, delete, rename."""

from __future__ import annotations

from shipit_agent.tools.base import ToolOutput

from .errors import MemoryToolError


class _MemoryCommands:
    """The memory tool's file commands: view, create, str_replace, insert, delete, rename."""

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
