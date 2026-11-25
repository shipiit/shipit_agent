"""`download_file` — fetch a binary file from a URL to local disk.

Streams in chunks with a hard size cap, reuses the battle-tested SSRF /
scheme guard from ``open_url`` (blocks ``file://``, loopback, link-local
cloud-metadata addresses, …), and derives a safe filename from the
Content-Disposition header or the URL path.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib import request as _request
from urllib.parse import unquote, urlsplit

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.open_url.open_url_tool import OpenURLTool, URLNotAllowedError
from shipit_agent.tools.paths import resolve_in_roots
from .prompt import DOWNLOAD_FILE_PROMPT

_CHUNK = 64 * 1024
_FILENAME_RE = re.compile(r'filename\*?=(?:"([^"]+)"|([^;\s]+))', re.IGNORECASE)


class DownloadFileTool:
    """The ``download_file`` tool: download a file (binary-safe: zip, csv, image, pdf, …) from an http(s) URL to local disk.
    """
    def __init__(
        self,
        *,
        name: str = "download_file",
        description: str = (
            "Download a file (binary-safe: zip, csv, image, pdf, …) from an "
            "http(s) URL to local disk."
        ),
        prompt: str | None = None,
        workspace_root: str | Path = ".shipit_workspace/downloads",
        max_bytes: int = 100 * 1024 * 1024,  # 100 MB
        timeout_seconds: int = 60,
        allow_private_hosts: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or DOWNLOAD_FILE_PROMPT
        self.prompt_instructions = (
            "Use this to save a file from a URL to disk. For reading a web "
            "page's text, use open_url instead."
        )
        self.workspace_root = Path(workspace_root)
        #: Folders beside the downloads folder a destination may also be in.
        self.extra_roots: tuple[Path, ...] = ()
        self.max_bytes = int(max_bytes)
        self.timeout_seconds = int(timeout_seconds)
        # Reuse open_url's SSRF/scheme guard rather than re-implementing it.
        self._guard = OpenURLTool(allow_private_hosts=allow_private_hosts)

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "http(s) URL of the file",
                        },
                        "path": {
                            "type": "string",
                            "description": (
                                "Optional destination filename or relative "
                                "path (defaults to a name derived from the "
                                "URL, saved in the downloads workspace)."
                            ),
                        },
                        "overwrite": {
                            "type": "boolean",
                            "description": "Replace an existing file",
                            "default": False,
                        },
                    },
                    "required": ["url"],
                },
            },
        }

    @staticmethod
    def _filename_from(url: str, content_disposition: str | None) -> str:
        if content_disposition:
            match = _FILENAME_RE.search(content_disposition)
            if match:
                candidate = (match.group(1) or match.group(2) or "").strip()
                candidate = unquote(candidate.split("''")[-1])
                if candidate:
                    return Path(candidate).name  # strip any directory parts
        tail = Path(unquote(urlsplit(url).path)).name
        return tail or "download.bin"

    def _resolve_target(self, url: str, override: str | None,
                        content_disposition: str | None) -> Path:
        # The destination is the model's choice, so it is held to the downloads
        # folder (and any added folders): no absolute path, "..", "~" or
        # symlink may take it elsewhere. Raises ValueError when it would.
        root = self.workspace_root.resolve()
        name = override if override else self._filename_from(url, content_disposition)
        if str(name).startswith("~"):
            raise ValueError(f"Path escapes project root: {name} is outside {root}")
        path = resolve_in_roots(name, root, self.extra_roots)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        url = str(kwargs.get("url", "")).strip()
        if not url:
            return ToolOutput(text="download_file: `url` is required.",
                              metadata={"ok": False})
        try:
            self._guard._validate_url(url)
        except URLNotAllowedError as exc:
            return ToolOutput(
                text=f"Download blocked: {exc}",
                metadata={"ok": False, "error": "url_not_allowed", "url": url},
            )

        req = _request.Request(url, headers={"User-Agent": "shipit-agent/1.0"})
        try:
            response = _request.urlopen(req, timeout=self.timeout_seconds)  # nosec B310 — guarded above
        except Exception as exc:
            return ToolOutput(
                text=f"Download failed: {exc}",
                metadata={"ok": False, "error": str(exc), "url": url},
            )

        with response:
            content_type = response.headers.get("Content-Type", "")
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > self.max_bytes:
                return ToolOutput(
                    text=(
                        f"Download refused: file is {int(declared):,} bytes, "
                        f"over the {self.max_bytes:,}-byte limit."
                    ),
                    metadata={"ok": False, "error": "too_large", "url": url},
                )
            try:
                target = self._resolve_target(
                    url, kwargs.get("path"), response.headers.get("Content-Disposition")
                )
            except ValueError:
                return ToolOutput(
                    text=(
                        f"Download refused: {kwargs.get('path')} is outside the downloads "
                        f"folder ({self.workspace_root}). Pass a path inside it."
                    ),
                    metadata={"ok": False, "error": "path_outside_workspace", "url": url},
                )
            if target.exists() and not kwargs.get("overwrite"):
                return ToolOutput(
                    text=(
                        f"Refusing to overwrite existing file: {target}. "
                        "Pass overwrite=true or a different path."
                    ),
                    metadata={"ok": False, "error": "exists", "path": str(target)},
                )

            written = 0
            try:
                with open(target, "wb") as handle:
                    while True:
                        chunk = response.read(_CHUNK)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > self.max_bytes:
                            raise ValueError(
                                f"exceeded the {self.max_bytes:,}-byte limit"
                            )
                        handle.write(chunk)
            except Exception as exc:
                target.unlink(missing_ok=True)  # never leave partial files
                return ToolOutput(
                    text=f"Download aborted: {exc}",
                    metadata={"ok": False, "error": str(exc), "url": url},
                )

        return ToolOutput(
            text=(
                f"Downloaded {written:,} bytes → {target}"
                + (f" ({content_type.split(';')[0]})" if content_type else "")
            ),
            metadata={
                "ok": True,
                "path": str(target.resolve()),
                "bytes": written,
                "content_type": content_type,
                "url": url,
            },
        )
