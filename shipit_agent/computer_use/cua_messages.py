"""How ComputerUseAgent describes and executes actions and builds its messages."""

from __future__ import annotations

from typing import Any

from .models import (
    ActionKind,
    ComputerAction,
)


class _ComputerUseMessages:
    """How ComputerUseAgent describes and executes actions and builds its messages."""

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
