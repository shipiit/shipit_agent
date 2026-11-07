"""A verb spec, the icons, and the small text helpers labels are made with."""

from __future__ import annotations

from dataclasses import dataclass

_TARGET_LIMIT = 60


def _clip(text: str, limit: int = _TARGET_LIMIT) -> str:
    """Collapse whitespace and elide to *limit* characters with an ellipsis."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _usable_target(text: str | None) -> str | None:
    """Drop a target that carries no information.

    Models pass junk: a bare ``0`` for a path, a lone ``"`` for a pattern.
    Rendering it gives ``Read 0`` and ``searched for "``, which reads as
    corruption rather than as what the agent did. Saying less is better —
    ``Read`` is honest, ``Read 0`` is confusing.
    """
    if text is None:
        return None
    stripped = text.strip()
    if len(stripped) < 2 or not any(ch.isalnum() for ch in stripped):
        return None
    return stripped


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    """``2, "file"`` → ``"2 files"``."""
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


@dataclass(frozen=True, slots=True)
class VerbSpec:
    """How one tool narrates itself.

    ``past``/``present`` are the bare verbs (``"Read"`` / ``"Reading"``).
    ``noun`` drives count-aware labels — with ``noun="file"`` five calls read
    ``"Read 5 files"``; without one they read ``"Read 5 times"``.
    ``args`` lists argument names to try, in order, when picking the target.

    ``count_verb`` exists because a verb that reads well with a *target* often
    collides with its own noun in a count: ``edit_file`` wants ``Edited
    app.py`` but ``Made 3 edits``, and ``sql`` wants ``Queried users`` but
    ``Ran 3 queries``. Set it to the ``(past, present)`` pair that composes.
    """

    past: str
    present: str
    icon: str
    noun: str | None = None
    plural: str | None = None
    args: tuple[str, ...] = ()
    read_only: bool = False
    # Set when the verb already contains its object ("Listed blueprints",
    # "Used GitHub"), so the count-aware label falls back to "N times".
    intransitive: bool = False
    # ``(past, present)`` to use in place of ``past``/``present`` when the
    # label is count-aware. ``None`` reuses the plain verbs.
    count_verb: tuple[str, str] | None = None


# ── Icons ────────────────────────────────────────────────────────────────
# A deliberately small vocabulary: a reader should learn all of it at a glance.
FILE = "▤"
EDIT = "✎"
CODE = "❯"
WEB = "◍"
SEARCH = "⌕"
LINK = "⚯"
CREATE = "✚"
APP = "▣"   # something the agent built and can run again
DATA = "⛁"
MAIL = "✉"
CHAT = "✱"
THINK = "◈"
MEMORY = "❋"
IMAGE = "◫"
DOC = "▦"
TOOL = "◆"
STOP = "■"

# ASCII stand-ins for terminals that can't render the above.
ASCII_ICONS = {
    FILE: "[]", EDIT: "*", CODE: ">_", WEB: "()", SEARCH: "?",
    LINK: "--", CREATE: "+", DATA: "=", MAIL: "@", CHAT: "~",
    THINK: "<>", MEMORY: "*", IMAGE: "[]", DOC: "#", TOOL: "+",
    STOP: "x",
}
