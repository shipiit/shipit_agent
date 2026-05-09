"""Dataclasses + enums for ComputerUseAgent."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionKind(str, Enum):
    """The kinds of actions a ComputerUseAgent can emit."""

    CLICK = "click"
    """Mouse click at (x, y)."""
    TYPE = "type"
    """Type a string at the current focus."""
    KEY = "key"
    """Press a special key (Enter, Tab, Escape, etc.)."""
    SCROLL = "scroll"
    """Scroll by (dx, dy) pixels."""
    NAVIGATE = "navigate"
    """Open a URL."""
    SCREENSHOT = "screenshot"
    """Just take a fresh screenshot (re-read state)."""
    DONE = "done"
    """End of the run with optional final text."""
    NOOP = "noop"
    """Parser couldn't read an action; the agent will request a new screenshot."""


@dataclass(slots=True)
class ComputerAction:
    """A structured action the agent decided to take."""

    kind: ActionKind
    """Which action."""

    args: dict[str, Any] = field(default_factory=dict)
    """Per-kind arguments. Examples:
    - click:    {"x": 100, "y": 200}
    - type:     {"text": "hello world"}
    - key:      {"key": "Enter"}
    - scroll:   {"dx": 0, "dy": 600}
    - navigate: {"url": "https://example.com"}
    - done:     {"final_text": "I found the answer: X"}
    """

    rationale: str = ""
    """Optional model-emitted reasoning. Stored on the action for tracing."""


@dataclass(slots=True)
class ActionRecord:
    """One action + the screenshot the agent saw before deciding it."""

    action: ComputerAction
    screenshot_b64: str
    """Pre-action screenshot, base64-encoded PNG/JPEG."""
    iteration: int = 0
    timestamp: float = field(default_factory=time.time)
    error: str | None = None
    """Set if the action raised when executed."""


@dataclass(slots=True)
class ComputerUseResult:
    """Outcome of a full ComputerUseAgent.run()."""

    status: str
    """``done`` | ``max_iterations`` | ``error``."""

    final_text: str = ""
    """Text the model emitted in its DONE action (or empty if it ran out of iterations)."""

    action_history: list[ActionRecord] = field(default_factory=list)
    """Every action attempted during the run, in order."""

    iterations: int = 0
    """Number of think→act cycles completed."""

    error: str | None = None
    """Top-level error message if ``status`` is ``error``."""

    metadata: dict[str, Any] = field(default_factory=dict)
