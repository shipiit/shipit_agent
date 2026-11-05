"""Artifacts on disk: one folder per id, one file per version, and a ``latest`` copy.

    <root>/<id>/v1.md
    <root>/<id>/v2.md
    <root>/<id>/latest.md

Ids are plain names (letters, digits, ``-``, ``_``, ``.``), so an artifact can
never be written outside its root. Earlier versions are never overwritten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Artifact types, and the file extension each is saved with.
TYPE_EXTENSIONS: dict[str, str] = {
    "markdown": ".md",
    "html": ".html",
    "svg": ".svg",
    "mermaid": ".mmd",
    "json": ".json",
    "csv": ".csv",
    "text": ".txt",
}

#: Extensions for ``type="code"``, by language.
CODE_EXTENSIONS: dict[str, str] = {
    "python": ".py",
    "javascript": ".js",
    "typescript": ".ts",
    "tsx": ".tsx",
    "jsx": ".jsx",
    "go": ".go",
    "rust": ".rs",
    "java": ".java",
    "sql": ".sql",
    "bash": ".sh",
    "shell": ".sh",
    "ruby": ".rb",
    "css": ".css",
    "yaml": ".yaml",
}

#: Media types accepted by the old ``media_type`` parameter.
MEDIA_TYPES: dict[str, str] = {
    "text/markdown": "markdown",
    "text/html": "html",
    "image/svg+xml": "svg",
    "application/json": "json",
    "text/csv": "csv",
    "text/plain": "text",
}

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ArtifactError(ValueError):
    """A request the store refuses, with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SavedVersion:
    """One version as written: where it lives and how it was made."""

    id: str
    version: int
    path: Path
    extension: str


def check_id(artifact_id: str) -> str:
    """*artifact_id* if it is a plain name, else an ``invalid_id`` error."""
    if not _SAFE_ID.match(artifact_id) or ".." in artifact_id:
        raise ArtifactError(
            "invalid_id",
            f"Artifact id {artifact_id!r} is not allowed. Use a short name of "
            "letters, digits, '-', '_' or '.', like 'q3-report'.",
        )
    return artifact_id


def extension_for(artifact_type: str, language: str = "") -> str:
    """The file extension an artifact of *artifact_type* is saved with."""
    if artifact_type == "code":
        return CODE_EXTENSIONS.get(language.lower(), ".txt")
    return TYPE_EXTENSIONS.get(artifact_type, ".txt")


def latest(root: Path, artifact_id: str) -> SavedVersion | None:
    """The newest saved version of *artifact_id*, or ``None`` if there is none."""
    folder = root / artifact_id
    if not folder.is_dir():
        return None
    versions = []
    for path in folder.glob("v*"):
        match = re.fullmatch(r"v(\d+)(\..*)?", path.name)
        if match:
            versions.append((int(match.group(1)), path))
    if not versions:
        return None
    number, path = max(versions)
    return SavedVersion(artifact_id, number, path, path.suffix)


def save(root: Path, artifact_id: str, content: str, extension: str) -> SavedVersion:
    """Write *content* as the next version of *artifact_id* and refresh ``latest``."""
    previous = latest(root, artifact_id)
    number = previous.version + 1 if previous else 1
    folder = root / artifact_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"v{number}{extension}"
    path.write_text(content, encoding="utf-8")
    (folder / f"latest{extension}").write_text(content, encoding="utf-8")
    return SavedVersion(artifact_id, number, path, extension)


def confined(root: Path, relative: str) -> Path:
    """*relative* under *root*, or an ``outside_artifacts`` error if it escapes."""
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ArtifactError(
            "outside_artifacts",
            f"Export path {relative!r} leaves the artifacts folder. Use a path "
            "inside it, like 'exports/report.md'.",
        )
    return target
