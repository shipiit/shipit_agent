"""``ComputerUseAgent`` — the screenshot → reason → act loop."""

from __future__ import annotations

from typing import Any

from .browser_session import BrowserSession
from .models import (
    ActionKind,
    ActionRecord,
    ComputerAction,
    ComputerUseResult,
)
from .parser import parse_action


SYSTEM_PROMPT = """You are a computer-use agent. You see screenshots of a browser viewport and decide the next action to take to achieve a goal. Output ONE action per turn.

Action commands:
- ACTION: click X,Y         — left-click at pixel (x,y)
- ACTION: type "text"       — type text into the focused element
- ACTION: key Enter         — press a key (Enter, Tab, Escape, ArrowDown, etc.)
- ACTION: scroll DX DY      — scroll by (dx, dy) pixels
- ACTION: navigate URL      — open a URL
- ACTION: screenshot        — take a fresh screenshot (re-read state)
- ACTION: done <final text> — end the run with your final answer

Rules:
- Output ONE action per turn, on its own line, prefixed with "ACTION:".
- Optionally add 1-2 sentences of reasoning before the ACTION line.
- Coordinates are pixel (x, y) from the top-left of the viewport.
- When you have enough information to answer the user's goal, emit "ACTION: done <answer>".

Be efficient. Don't take redundant actions."""


class ComputerUseAgent:
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
        history: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Goal: {self.goal}"},
        ]
        action_history: list[ActionRecord] = []

        for i in range(self.max_iterations):
            try:
                screenshot_b64 = self.browser.screenshot()
            except Exception as exc:
                return _error_result(
                    action_history,
                    iterations=i,
                    error=f"screenshot failed: {exc}",
                )

            history.append(self._user_message_with_screenshot(screenshot_b64))

            try:
                response = self.llm.complete(messages=history)
            except Exception as exc:
                return _error_result(
                    action_history,
                    iterations=i,
                    error=f"llm call failed: {exc}",
                )

            action = parse_action(response)
            history.append(self._assistant_message(response))

            record = ActionRecord(
                action=action, screenshot_b64=screenshot_b64, iteration=i
            )

            if action.kind == ActionKind.DONE:
                action_history.append(record)
                return ComputerUseResult(
                    status="done",
                    final_text=action.args.get("final_text", ""),
                    action_history=action_history,
                    iterations=i + 1,
                )

            try:
                self._execute(action)
            except Exception as exc:
                record.error = str(exc)
                action_history.append(record)
                # Surface the error back to the model so it can recover
                history.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your last action failed: {exc}. "
                            "Take a different approach."
                        ),
                    }
                )
                continue

            action_history.append(record)

        return ComputerUseResult(
            status="max_iterations",
            final_text="",
            action_history=action_history,
            iterations=self.max_iterations,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _execute(self, action: ComputerAction) -> None:
        if action.kind == ActionKind.CLICK:
            self.browser.click(int(action.args["x"]), int(action.args["y"]))
        elif action.kind == ActionKind.TYPE:
            self.browser.type_text(str(action.args.get("text", "")))
        elif action.kind == ActionKind.KEY:
            self.browser.key(str(action.args.get("key", "")))
        elif action.kind == ActionKind.SCROLL:
            self.browser.scroll(
                int(action.args.get("dx", 0)),
                int(action.args.get("dy", 0)),
            )
        elif action.kind == ActionKind.NAVIGATE:
            self.browser.navigate(str(action.args.get("url", "")))
        elif action.kind in (ActionKind.SCREENSHOT, ActionKind.NOOP):
            # Both kinds simply request another screenshot — no browser action.
            pass

    def _user_message_with_screenshot(self, screenshot_b64: str) -> dict[str, Any]:
        """Build the user message with screenshot.

        Anthropic content-block shape:
        ``[{"type": "image", "source": {...}}, {"type": "text", "text": "..."}]``

        For text-only LLMs the caller can call .complete() with this same
        message — most stubs ignore the image block.
        """
        viewport = f"{self.viewport_size[0]}×{self.viewport_size[1]}"
        return {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": f"image/{self.screenshot_format}",
                        "data": screenshot_b64,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        f"Current viewport ({viewport}). What's the next action toward: "
                        f"{self.goal!r}?"
                    ),
                },
            ],
        }

    def _assistant_message(self, response: Any) -> dict[str, Any]:
        """Translate the model's response into a stored assistant message.

        Lossy on purpose — we keep the textual rationale and discard the
        image-binary parts, since adding them to history bloats tokens.
        """
        text = ""
        if isinstance(response, str):
            text = response
        elif isinstance(response, dict):
            text = response.get("content") or response.get("text") or str(response)[:300]
        else:
            text = (
                getattr(response, "content", None)
                or getattr(response, "text", None)
                or str(response)[:300]
            )
        return {"role": "assistant", "content": str(text)}


def _error_result(
    history: list[ActionRecord], *, iterations: int, error: str
) -> ComputerUseResult:
    return ComputerUseResult(
        status="error",
        final_text="",
        action_history=history,
        iterations=iterations,
        error=error,
    )
