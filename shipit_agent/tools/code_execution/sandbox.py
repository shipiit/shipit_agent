"""Docker sandbox helpers for `code_execution`.

Split out of the main tool file so both files stay under the 300-line
ceiling. The sandbox path runs the user's snippet inside a disposable
container with ``--network none`` and a read-only rootfs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final


# Per-language Docker images. Small, official, trivially pullable.
# Users can override per call with the `image` kwarg.
SANDBOX_IMAGES: Final[dict[str, str]] = {
    "python": "python:3.11-slim",
    "bash": "alpine:3.20",
    "sh": "alpine:3.20",
    "zsh": "alpine:3.20",
    "javascript": "node:22-alpine",
    "typescript": "node:22-slim",
    "ruby": "ruby:3.3-alpine",
    "php": "php:8.3-cli-alpine",
    "perl": "perl:5.40-slim",
    "lua": "alpine:3.20",
    "r": "r-base:4.4.1",
}

# Per-language argv INSIDE the container. The file path inside is
# appended by :func:`build_sandbox_command` when needed.
SANDBOX_CMDS: Final[dict[str, list[str]]] = {
    "python": ["python3"],
    "bash": ["sh"],
    "sh": ["sh"],
    "zsh": ["sh"],
    "javascript": ["node"],
    "typescript": ["sh", "-c"],  # rebuilt dynamically — needs tsx install
    "ruby": ["ruby"],
    "php": ["php"],
    "perl": ["perl"],
    "lua": ["lua"],
    "r": ["Rscript"],
}


def build_sandbox_command(
    language: str,
    script_path: Path,
    workspace_root: Path,
    *,
    allow_network: bool,
    image: str | None,
) -> tuple[list[str], Path]:
    """Return the ``docker run`` argv + the cwd the caller should spawn in.

    Security contract:
      - whole workspace bind-mounted at ``/work`` read-only
      - rootfs is ``--read-only`` with a writable ``/tmp`` tmpfs (64 MB)
      - network off by default; opt in via ``allow_network=True``
    """
    chosen = image or SANDBOX_IMAGES.get(language)
    if not chosen:
        raise RuntimeError(
            f"No sandbox image registered for language '{language}'. "
            f"Pass an `image` kwarg to override."
        )

    workspace = workspace_root.resolve()
    inside = f"/work/{script_path.name}"

    if language == "typescript":
        # Install tsx on first run — slow path, only used for untrusted ts.
        inside_cmd = [
            "sh",
            "-c",
            f"npm install -g --silent tsx >/dev/null 2>&1 && tsx {inside}",
        ]
    else:
        inside_cmd = [*SANDBOX_CMDS.get(language, ["sh"]), inside]

    argv: list[str] = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "bridge" if allow_network else "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=64m",
        "-v",
        f"{workspace}:/work:ro",
        "-w",
        "/work",
        chosen,
        *inside_cmd,
    ]
    return argv, workspace
