"""``ComputerUseAgent`` — the screenshot → reason → act loop."""

from __future__ import annotations

from typing import Any

from .browser_session import BrowserSession
from .cua_messages import _ComputerUseMessages
from .cua_stream import _ComputerUseStream
from .cua_support import SYSTEM_PROMPT as SYSTEM_PROMPT
from .models import (
    ComputerUseResult,
)


class ComputerUseAgent(_ComputerUseStream, _ComputerUseMessages):
    """Drive a browser by showing screenshots to a vision-capable LLM.

    Args:
        llm: any object exposing ``complete(messages=...)`` that accepts
            multimodal content (image + text). For Anthropic Claude models,
            this happens automatically. For text-only LLMs the screenshot
            is omitted from history and the model has to drive blind —
            still useful for replay/testing.
        browser: a ``BrowserSession`` (Playwright in production, mock in tests).
        goal: the user's objective in plain English.
        max_iterations: safety cap on think-act cycles. Default 10.
        viewport_size: ``(width, height)`` for screenshot annotation. Defaults
            to ``browser.viewport_size`` if available, else ``(1280, 720)``.
        action_emit_mode: ``"auto"`` (try Anthropic native, fall back to text),
            ``"anthropic"`` (force tool-use parsing), or ``"text"`` (force
            plain-text parsing).
        screenshot_format: ``"png"`` or ``"jpeg"``. Hints to the screenshot
            method; some browsers respect, others don't.
    """

    def __init__(
        self,
        *,
        llm: Any,
        browser: BrowserSession,
        goal: str,
        max_iterations: int = 10,
        viewport_size: tuple[int, int] | None = None,
        action_emit_mode: str = "auto",
        screenshot_format: str = "png",
    ) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if action_emit_mode not in {"auto", "anthropic", "text"}:
            raise ValueError(f"unknown action_emit_mode: {action_emit_mode!r}")

        self.llm = llm
        self.browser = browser
        self.goal = goal
        self.max_iterations = max_iterations
        self.viewport_size = viewport_size or getattr(
            browser, "viewport_size", (1280, 720)
        )
        self.action_emit_mode = action_emit_mode
        self.screenshot_format = screenshot_format

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self) -> ComputerUseResult:
        """Execute the screenshot → reason → act loop until DONE or max_iterations."""
        generator = self.stream()
        while True:
            try:
                next(generator)
            except StopIteration as stop:
                return stop.value

    # ------------------------------------------------------------------
    # Internals
