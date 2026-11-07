"""Classifying a shell command: safe to run, needs approval, or never.

The bash tool runs any command. What may run without asking is decided here,
from the command text, before it runs:

* **blocked**: commands that can wreck the machine (wiping ``/`` or a home
  folder, formatting a disk, a fork bomb). Never run, whatever the settings.
* **risky**: deleting, discarding git work, publishing, escalating
  privileges, writing outside the project, sending data out, running a
  downloaded script, stopping processes, or opening up permissions. These need
  an explicit allow rule, bypass mode, or a yes from ``permission_callback``.
* **safe**: everything else, which is nearly all of development: reading,
  searching, testing, building, installing into the project, fetching a page.

The checks read the whole command, including subshells and ``$(...)``, so a
risky command inside one is still found. They lean towards *risky*: a false
alarm costs one approval, a miss costs the user's files.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

__all__ = ["CommandVerdict", "assess_command", "command_segments"]

RiskLevel = Literal["safe", "risky", "blocked"]


@dataclass(frozen=True, slots=True)
class CommandVerdict:
    """How risky a command is, and why."""

    level: RiskLevel
    reasons: tuple[str, ...] = field(default_factory=tuple)


_HOME = r"(?:~|\$HOME|\$\{HOME\})"

#: Commands that are never run.
_BLOCKED: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            rf"\brm\s+(?:-[a-zA-Z-]+\s+)*(?:--no-preserve-root\s+)?(?:/|/\*|{_HOME}/?)(?:\s|$|;|&|\|)"
        ),
        "deletes the whole filesystem or a home folder",
    ),
    (re.compile(r":\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:"), "is a fork bomb"),
    (re.compile(r"\bmkfs(?:\.\w+)?\b"), "formats a disk"),
    (re.compile(r"\bdd\b[^|;&]*\bof=/dev/"), "writes raw data over a device"),
    (re.compile(r">\s*/dev/(?:sd|nvme|disk|hd)\w*"), "writes raw data over a device"),
    (re.compile(r"\b(?:shutdown|reboot|halt|poweroff)\b"), "shuts the machine down"),
)

#: Commands that need approval, by what they do.
_RISKY: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:^|[\s;&|(`$])(?:rm|rmdir|shred|unlink)\s"), "deletes files"),
    (re.compile(r"\bfind\b[^|;&]*\s-delete\b"), "deletes files"),
    (re.compile(r"\bgit\s+clean\b"), "deletes untracked files"),
    (
        re.compile(r"\bgit\s+(?:reset\s+--hard|checkout\s+--\s|restore\s)"),
        "discards uncommitted work",
    ),
    (re.compile(r"\bgit\s+branch\s+-D\b"), "discards uncommitted work"),
    (re.compile(r"\bgit\s+push\b"), "publishes to a remote"),
    (
        re.compile(
            r"\b(?:npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b|\bcargo\s+publish\b|\bgem\s+push\b"
        ),
        "publishes a package",
    ),
    (re.compile(r"(?:^|[\s;&|(])(?:sudo|su|doas)\s"), "raises privileges"),
    (
        re.compile(
            r"\bcurl\b[^|;&]*\s(?:-T|--upload-file|-d|--data\S*|-F|--form|-X\s*(?:POST|PUT|PATCH|DELETE))\b"
        ),
        "sends data to a server",
    ),
    (re.compile(r"\bwget\b[^|;&]*--post"), "sends data to a server"),
    (re.compile(r"\b(?:scp|sftp|rsync)\b[^|;&]*\S+:\S*"), "sends data to a server"),
    (re.compile(r"\b(?:nc|ncat|netcat|ssh)\s"), "sends data to a server"),
    (
        re.compile(r"\b(?:curl|wget)\b[^;&]*\|\s*(?:sudo\s+)?(?:ba|z)?sh\b"),
        "downloads and runs a script",
    ),
    (re.compile(r"\b(?:kill|pkill|killall)\s"), "stops processes"),
    (
        re.compile(r"\bchmod\s+(?:-R\s+)?(?:0?777|a\+rwx)\b|\bchown\s+-R\b"),
        "opens up file permissions",
    ),
)

#: Commands whose path arguments are written to.
_WRITERS = frozenset(
    {"cp", "mv", "ln", "tee", "install", "touch", "mkdir", "chmod", "chown", "truncate"}
)
_SEGMENT_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
_REDIRECT_TARGET = re.compile(r"(?<![<>&\d])>>?\s*([^\s;&|]+)")


def command_segments(command: str) -> list[str]:
    """The simple commands in *command*, split at ``&&``, ``||``, ``;``, ``|`` and newlines."""
    return [segment for segment in _SEGMENT_SPLIT.split(command.strip()) if segment]


def assess_command(command: str, *, root: Path) -> CommandVerdict:
    """Classify *command* for a shell rooted at *root*."""
    text = command.strip()
    if not text:
        return CommandVerdict("safe")
    for pattern, reason in _BLOCKED:
        if pattern.search(text):
            return CommandVerdict("blocked", (f"blocked: it {reason}",))
    reasons: list[str] = []
    for pattern, reason in _RISKY:
        if pattern.search(text) and f"it {reason}" not in reasons:
            reasons.append(f"it {reason}")
    if _writes_outside(text, root.resolve()):
        reasons.append("it writes outside the project")
    return (
        CommandVerdict("risky", tuple(reasons)) if reasons else CommandVerdict("safe")
    )


def _writes_outside(text: str, root: Path) -> bool:
    """Whether a redirection or a file-writing command targets a path outside *root*."""
    targets = [match.group(1) for match in _REDIRECT_TARGET.finditer(text)]
    for segment in _SEGMENT_SPLIT.split(text):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        if tokens and Path(tokens[0]).name in _WRITERS:
            # The destination is the last argument for cp/mv/ln/install; every
            # argument for touch/mkdir/tee/chmod.
            args = [token for token in tokens[1:] if not token.startswith("-")]
            targets.extend(
                args[-1:] if tokens[0] in {"cp", "mv", "ln", "install"} else args
            )
    return any(_outside(target, root) for target in targets)


def _outside(target: str, root: Path) -> bool:
    if target.startswith(("~", "$HOME", "${HOME}")):
        return True
    if not target.startswith("/") or target.startswith("/dev/null"):
        return False
    path = Path(target)
    allowed = (root, Path("/tmp"), Path("/private/tmp"), Path("/var/folders"))
    return not any(path == base or base in path.parents for base in allowed)
