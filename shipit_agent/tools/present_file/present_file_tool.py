"""``present_file`` — hand a finished file to the user as a deliverable.

The agent generates or saves a file (an image, a spoken clip, a rendered PDF, a
CSV) and then *presents* it: the user gets a **downloadable, previewable card**,
the way ChatGPT/Codex surface an artifact — not a path buried in prose.

It's a thin, deliberate tool. The runtime already turns any existing path a tool
declares in its metadata into a tracked artifact (``note_artifacts`` /
``_declared_paths``); this tool's job is to let the model *choose* what counts as
a finished deliverable and label it. For an image it also rides the vision bridge
(``image_base64``) so the card previews inline, and it emits the ``MEDIA:<path>``
tag a send pipeline turns into an inline attachment.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

from .prompt import PRESENT_FILE_PROMPT

#: What a file extension means to a person — the label on the download card.
_KINDS = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".webp": "image", ".svg": "image",
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".ogg": "audio",
    ".mp4": "video", ".mov": "video", ".webm": "video",
    ".pdf": "pdf", ".docx": "document", ".doc": "document", ".pptx": "slides",
    ".xlsx": "spreadsheet", ".csv": "spreadsheet", ".tsv": "spreadsheet",
    ".md": "document", ".txt": "document", ".html": "page", ".json": "data",
    ".zip": "archive",
}
_IMAGE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
}
#: Images above this aren't inlined for preview — the download still works.
_MAX_INLINE_BYTES = 6_000_000


class PresentFileTool:
    """Surface an existing file to the user as a downloadable deliverable."""

    name = "present_file"
    description = (
        "Present a file you created or have (image, audio, video, PDF, document, "
        "spreadsheet, data) to the user as a downloadable, previewable deliverable. "
        "Use after you generate or save a file the user should receive — pass the "
        "path. This does not create the file; the file must already exist."
    )
    prompt_instructions = PRESENT_FILE_PROMPT

    def __init__(self, *, root_dir: str | Path | None = None) -> None:
        # Optional sandbox root: when set, the path must resolve under it.
        self.root_dir = Path(root_dir).resolve() if root_dir else None

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the existing file to present.",
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional caption shown on the card.",
                        },
                    },
                    "required": ["path"],
                },
            },
        }

    def _resolve(self, raw: str) -> Path:
        path = Path(raw).expanduser()
        if not path.is_absolute() and self.root_dir is not None:
            path = self.root_dir / path
        path = path.resolve()
        if self.root_dir is not None and not path.is_relative_to(self.root_dir):
            raise ValueError(f"Path escapes the workspace: {path}")
        return path

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        raw = str(kwargs.get("path", "")).strip()
        if not raw:
            return ToolOutput(text="Error: 'path' is required.", metadata={"ok": False})
        try:
            path = self._resolve(raw)
        except ValueError as err:
            return ToolOutput(text=f"Error: {err}", metadata={"ok": False})
        if not path.is_file():
            return ToolOutput(
                text=f"Error: no file to present at {path}. Create it first, then "
                "present it.",
                metadata={"ok": False},
            )

        suffix = path.suffix.lower()
        kind = _KINDS.get(suffix, "file")
        size = path.stat().st_size
        title = str(kwargs.get("title", "")).strip() or path.name
        metadata: dict[str, Any] = {
            "ok": True,
            # `path` is the key the runtime's artifact tracker reads — this is
            # what turns the file into a tracked, downloadable deliverable.
            "path": str(path),
            "name": path.name,
            "title": title,
            "kind": kind,
            "bytes": size,
            "download": True,
            "media": str(path),
        }
        # An image previews inline via the shared vision bridge (unless huge).
        media_type = _IMAGE_TYPES.get(suffix)
        if media_type and size <= _MAX_INLINE_BYTES:
            metadata["image_base64"] = base64.b64encode(path.read_bytes()).decode("ascii")
            metadata["media_type"] = media_type
            metadata["vision"] = True

        return ToolOutput(
            text=f"Presented {title} ({kind}, {size:,} bytes) for download.\nMEDIA:{path}",
            metadata=metadata,
        )
