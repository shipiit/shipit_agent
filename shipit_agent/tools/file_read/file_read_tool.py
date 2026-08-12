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
        # Read up to ~2000 lines by default; a small window
        # forces the model to page and risks edits against unseen regions.
        max_chars: int = 80_000,
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

    #: Files read as VISION, not text — the model gets the actual pixels.
    _IMAGE_TYPES = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    #: Keep an image readable without flooding a request: ~4MB on disk
    #: (≈5.3MB as base64) is beyond what any provider needs for legibility.
    _MAX_MEDIA_BYTES = 4_000_000

    def _read_media(self, path: Path) -> ToolOutput | None:
        """Vision output for image/PDF files, or None for text files.

        Reading a PNG with ``read_text`` produces U+FFFD soup; the useful
        rendering of an image is the image. The base64 rides in metadata
        under the ``image_base64`` convention, which the runtime bridges
        into a user-turn image block on the next step. PDFs surface as an
        Anthropic ``document`` block where supported, falling back to a
        pointer at the pdf tool for text extraction elsewhere.
        """
        import base64

        suffix = path.suffix.lower()
        media_type = self._IMAGE_TYPES.get(suffix)
        is_pdf = suffix == ".pdf"
        if media_type is None and not is_pdf:
            return None
        size = path.stat().st_size
        if size > self._MAX_MEDIA_BYTES:
            return ToolOutput(
                text=(
                    f"{path.name} is {size:,} bytes — too large to attach "
                    f"whole. Use a smaller copy, or (for PDFs) the `pdf` "
                    f"tool to extract text page by page."
                ),
                metadata={"path": str(path), "media_too_large": True},
            )
        data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
        if is_pdf:
            return ToolOutput(
                text=(
                    f"[PDF file: {path.name}, {size:,} bytes — attached for "
                    "reading. Use the `pdf` tool for page-level text "
                    "extraction if needed.]"
                ),
                metadata={
                    "path": str(path),
                    "document_base64": data,
                    "media_type": "application/pdf",
                },
            )
        return ToolOutput(
            text=f"[image file: {path.name}, {size:,} bytes — attached]",
            metadata={
                "path": str(path),
                "image_base64": data,
                "media_type": media_type,
                "vision": True,
            },
        )

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        path = self._resolve(str(kwargs["path"]))
        if not path.exists():
            return ToolOutput(text=f"File not found: {path}")
        if path.is_dir():
            return ToolOutput(text=f"Path is a directory, not a file: {path}")

        media = self._read_media(path)
        if media is not None:
            return media

        # Decode lossily for display, but flag when invalid bytes were
        # replaced with U+FFFD so the caller knows the on-disk content is not
        # pure UTF-8 (and must not be edited as text — see edit_file).
        content = path.read_text(encoding="utf-8", errors="replace")
        had_replacement = "�" in content
        lines = content.splitlines()
        start_line = max(1, int(kwargs.get("start_line", 1)))
        max_lines = max(1, int(kwargs.get("max_lines", min(len(lines) or 1, 2000))))
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
            # Record the mtime at read time so edit_file can detect the file
            # changing underneath the agent between read and edit.
            mtimes = dict(state.get("read_file_mtimes", {}))
            try:
                mtimes[str(path)] = path.stat().st_mtime_ns
            except OSError:
                pass
            state["read_file_mtimes"] = mtimes
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
