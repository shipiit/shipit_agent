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

Precision — every screenshot shows the RESULT of your last action:
- Before typing, click the CENTER of the input field, then confirm in the
  next screenshot that it is focused (cursor/highlight) — if your text did
  not appear, click the field again before retyping.
- If the screenshot looks unchanged after a click, the click missed: pick
  visibly different coordinates instead of repeating the same ones.
- Prefer interacting with what is visible; scroll only when the target is
  off-screen.

Obstacles — handle them YOURSELF, never wait for a human:
- Cookie/consent walls ("Before you continue", "We value your privacy"):
  click the "Accept all" / "I agree" / "Reject all" button, then continue.
- Popups, newsletter modals, app-install banners: close them (click the X
  or a "No thanks"/"Maybe later" button, or press Escape).
- Sign-in prompts you can skip: look for "Continue without signing in",
  "Skip", "Not now", or just close the dialog.
- If a page is unusable (hard login wall, CAPTCHA), navigate to an
  alternative site that can also achieve the goal.
- After dismissing any obstacle, take a screenshot to confirm the page is
  clear before proceeding.

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
        generator = self.stream()
        while True:
            try:
                next(generator)
            except StopIteration as stop:
                return stop.value

    def stream(self):
        """Yield live :class:`AgentEvent`s while driving the browser.

        Same loop as :meth:`run`, but observable — each iteration emits
        ``step_started``, ``tool_called`` (the action the model chose),
        ``tool_completed`` / ``tool_failed`` (with ``duration_ms``), and a
        final ``run_completed``. The events use the standard shapes, so
        ``StreamRenderer`` / ``format_event_line`` render browser actions
        as live tool cards::

            renderer = StreamRenderer(style="rich")
            for event in agent.stream():
                renderer.feed(event)

        The generator's return value is the :class:`ComputerUseResult`
        (``run()`` drains the stream and returns it).
        """
        import time as _time

        from shipit_agent.models import AgentEvent

        history: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Goal: {self.goal}"},
        ]
        action_history: list[ActionRecord] = []

        def _done_event(result: ComputerUseResult) -> AgentEvent:
            return AgentEvent(
                type="run_completed",
                message=f"Computer use finished: {result.status}",
                payload={
                    "output": result.final_text or f"[{result.status}]",
                    "content": result.final_text,
                    "status": result.status,
                    "iterations": result.iterations,
                },
            )

        yield AgentEvent(
            type="run_started",
            message=f"Computer use started: {self.goal[:80]}",
            payload={"goal": self.goal},
        )

        for i in range(self.max_iterations):
            yield AgentEvent(
                type="step_started",
                message=f"Iteration {i + 1}",
                payload={"iteration": i},
            )
            try:
                screenshot_b64 = self.browser.screenshot()
            except Exception as exc:
                result = _error_result(
                    action_history, iterations=i, error=f"screenshot failed: {exc}"
                )
                yield _done_event(result)
                return result

            history.append(self._user_message_with_screenshot(screenshot_b64))

            try:
                response = self.llm.complete(messages=history)
            except Exception as exc:
                result = _error_result(
                    action_history, iterations=i, error=f"llm call failed: {exc}"
                )
                yield _done_event(result)
                return result

            action = parse_action(response)
            history.append(self._assistant_message(response))

            record = ActionRecord(
                action=action, screenshot_b64=screenshot_b64, iteration=i
            )
            call_id = f"cu-{i}"

            if action.kind == ActionKind.DONE:
                action_history.append(record)
                result = ComputerUseResult(
                    status="done",
                    final_text=action.args.get("final_text", ""),
                    action_history=action_history,
                    iterations=i + 1,
                )
                yield _done_event(result)
                return result

            yield AgentEvent(
                type="tool_called",
                message=f"Browser action: {action.kind.value}",
                payload={
                    "tool": f"browser.{action.kind.value}",
                    "call_id": call_id,
                    "arguments": dict(action.args),
                    "iteration": i,
                },
            )
            started = _time.perf_counter()
            try:
                self._execute(action)
            except Exception as exc:
                record.error = str(exc)
                action_history.append(record)
                yield AgentEvent(
                    type="tool_failed",
                    message=f"Browser action failed: {action.kind.value}",
                    payload={
                        "tool": f"browser.{action.kind.value}",
                        "call_id": call_id,
                        "error": str(exc),
                        "iteration": i,
                        "duration_ms": round((_time.perf_counter() - started) * 1000, 1),
                    },
                )
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
            yield AgentEvent(
                type="tool_completed",
                message=f"Browser action done: {action.kind.value}",
                payload={
                    "tool": f"browser.{action.kind.value}",
                    "call_id": call_id,
                    "output": self._describe_action(action),
                    "iteration": i,
                    "duration_ms": round((_time.perf_counter() - started) * 1000, 1),
                },
            )

        result = ComputerUseResult(
            status="max_iterations",
            final_text="",
            action_history=action_history,
            iterations=self.max_iterations,
        )
        yield _done_event(result)
        return result

    @staticmethod
    def _describe_action(action: ComputerAction) -> str:
        """One-line human summary of an executed browser action."""
        a = action.args
        kind = action.kind
        if kind == ActionKind.CLICK:
            return f"clicked ({a.get('x')}, {a.get('y')})"
        if kind == ActionKind.TYPE:
            return f"typed {str(a.get('text', ''))[:60]!r}"
        if kind == ActionKind.KEY:
            return f"pressed {a.get('key', '')}"
        if kind == ActionKind.SCROLL:
            return f"scrolled ({a.get('dx', 0)}, {a.get('dy', 0)})"
        if kind == ActionKind.NAVIGATE:
            return f"navigated to {a.get('url', '')}"
        return "screenshot refreshed"

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
