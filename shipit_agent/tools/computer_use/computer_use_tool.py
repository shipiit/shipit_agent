"""`computer_use` tool — the public :class:`Tool` implementation.

Backed by the per-platform primitives in :mod:`.backends`. The tool itself
is thin: validate the action, delegate to the backend, return a structured
``ToolOutput`` the agent can reason about.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput

from .backends import BackendError, resolve_backend
from .prompt import COMPUTER_USE_PROMPT


TAKE_SCREENSHOT_ACTIONS = frozenset({"screenshot", "capture"})
_ACTIONS = frozenset({
    "screenshot", "capture",
    "mouse_move", "move",
    "click", "drag",
    "scroll", "type", "key",
    "wait",
})


class ComputerUseTool:
    """Control the local desktop — screenshots, clicks, typing, key chords.

    Mirrors the surface of Anthropic's computer-use reference tool while
    staying minimal: one enum of actions, one consistent return shape,
    one platform-agnostic call site.
    """

    name = "computer_use"
    description = (
        "Drive the local desktop — screenshots, mouse, keyboard. "
        "Use only when web / API / CLI paths don't reach the target UI."
    )
    prompt_instructions = (
        "Use computer_use to control the local desktop (macOS, Linux, or Windows). "
        "ALWAYS take a screenshot first unless you're certain where to click."
    )

    def __init__(
        self,
        *,
        output_dir: str | Path | None = None,
        auto_screenshot_after_action: bool = False,
    ) -> None:
        self.output_dir = (
            Path(output_dir).expanduser()
            if output_dir
            else Path.home() / ".shipit_agent" / "computer_use"
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.auto_screenshot_after_action = auto_screenshot_after_action
        self.prompt = COMPUTER_USE_PROMPT

    # ── tool protocol ────────────────────────────────────────────

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": sorted(_ACTIONS)},
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "to_x": {"type": "integer"},
                        "to_y": {"type": "integer"},
                        "dx": {"type": "integer", "default": 0},
                        "dy": {"type": "integer", "default": 0},
                        "text": {"type": "string"},
                        "keys": {"type": "string", "description": 'Chord like "cmd+shift+4".'},
                        "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                        "double": {"type": "boolean", "default": False},
                        "seconds": {"type": "number"},
                        "filename": {"type": "string"},
                        "vision": {
                            "type": "boolean",
                            "description": "When action=screenshot, include the PNG as image content so a vision-capable LLM can actually see what's on screen. Default true; pass false to save bytes.",
                            "default": True,
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        action = str(kwargs.get("action", "")).strip().lower()
        if action not in _ACTIONS:
            return ToolOutput(
                text=f"Error: unsupported action {action!r}. Use one of: {', '.join(sorted(_ACTIONS))}.",
                metadata={"ok": False},
            )

        try:
            backend = resolve_backend()
        except BackendError as err:
            return ToolOutput(text=f"Error: {err}", metadata={"ok": False})

        try:
            return self._dispatch(backend, action, kwargs)
        except BackendError as err:
            return ToolOutput(text=f"Error: {err}", metadata={"ok": False, "action": action})
        except Exception as err:  # noqa: BLE001
            return ToolOutput(
                text=f"Error: unhandled {type(err).__name__}: {err}",
                metadata={"ok": False, "action": action},
            )

    # ── action dispatch ──────────────────────────────────────────

    def _dispatch(self, backend: Any, action: str, kwargs: dict[str, Any]) -> ToolOutput:
        if action in TAKE_SCREENSHOT_ACTIONS:
            return self._screenshot(backend, kwargs)

        if action in ("mouse_move", "move"):
            x, y = self._require_xy(kwargs)
            backend.move(x, y)
            return self._ok(backend, action, {"x": x, "y": y})

        if action == "click":
            x, y = self._require_xy(kwargs)
            backend.click(
                x, y,
                button=str(kwargs.get("button", "left")),
                double=bool(kwargs.get("double", False)),
            )
            return self._ok(backend, action, {"x": x, "y": y, "button": kwargs.get("button", "left")})

        if action == "drag":
            x, y = self._require_xy(kwargs)
            to_x = int(kwargs.get("to_x", 0))
            to_y = int(kwargs.get("to_y", 0))
            backend.drag(x, y, to_x, to_y)
            return self._ok(backend, action, {"from": [x, y], "to": [to_x, to_y]})

        if action == "scroll":
            x, y = self._require_xy(kwargs)
            backend.scroll(x, y, int(kwargs.get("dx", 0)), int(kwargs.get("dy", 0)))
            return self._ok(backend, action, {"dx": kwargs.get("dx", 0), "dy": kwargs.get("dy", 0)})

        if action == "type":
            text = str(kwargs.get("text", ""))
            if not text:
                return ToolOutput(text="Error: 'text' is required for action=type.", metadata={"ok": False})
            backend.type_text(text)
            return self._ok(backend, action, {"len": len(text)})

        if action == "key":
            keys = str(kwargs.get("keys", "")).strip()
            if not keys:
                return ToolOutput(text="Error: 'keys' is required for action=key.", metadata={"ok": False})
            backend.key(keys)
            return self._ok(backend, action, {"keys": keys})

        if action == "wait":
            seconds = float(kwargs.get("seconds", 1.0))
            time.sleep(max(0.0, min(60.0, seconds)))
            return self._ok(backend, action, {"seconds": seconds})

        return ToolOutput(text=f"Error: unroutable action {action!r}.", metadata={"ok": False})

    # ── helpers ─────────────────────────────────────────────────

    def _screenshot(self, backend: Any, kwargs: dict[str, Any]) -> ToolOutput:
        name = kwargs.get("filename") or f"shot-{int(time.time())}.png"
        target = self.output_dir / str(name)
        path = backend.screenshot(target)

        # Vision feedback — attach the PNG to tool output so the runtime
        # can wrap it as image content on the NEXT user message.
        # Adapters that don't support images fall back to just seeing
        # the filepath in text (identical to the previous behavior).
        vision_meta: dict[str, Any] = {
            "ok": True,
            "path": str(path),
            "platform": backend.platform,
        }
        if kwargs.get("vision", True):     # on by default; opt-out with vision=False
            try:
                import base64
                raw = path.read_bytes()
                if raw:
                    # Cap at ~4 MB to avoid blowing up the model context
                    # when an agent takes many screenshots in one run.
                    if len(raw) <= 4_000_000:
                        vision_meta["vision"] = True
                        vision_meta["image_base64"] = base64.b64encode(raw).decode("ascii")
                        vision_meta["media_type"] = "image/png"
                    else:
                        vision_meta["vision"] = False
                        vision_meta["vision_skip_reason"] = (
                            f"png too large ({len(raw)} bytes) — pass vision=False "
                            "or use a smaller capture area"
                        )
            except OSError as err:
                vision_meta["vision"] = False
                vision_meta["vision_skip_reason"] = f"could not read PNG: {err}"

        return ToolOutput(
            text=f"Screenshot saved: {path}",
            metadata=vision_meta,
        )

    @staticmethod
    def _require_xy(kwargs: dict[str, Any]) -> tuple[int, int]:
        if "x" not in kwargs or "y" not in kwargs:
            raise BackendError("this action requires 'x' and 'y'")
        return int(kwargs["x"]), int(kwargs["y"])

    def _ok(self, backend: Any, action: str, extra: dict[str, Any]) -> ToolOutput:
        if self.auto_screenshot_after_action and action != "wait":
            shot = self._screenshot(backend, {})
            extra["screenshot"] = shot.metadata.get("path")
        return ToolOutput(
            text=f"ok: {action} {extra}",
            metadata={"ok": True, "action": action, **extra},
        )
