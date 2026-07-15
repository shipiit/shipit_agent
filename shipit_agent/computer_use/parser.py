"""Parse LLM output into a ``ComputerAction``.

Supports two emit shapes:

1. **Anthropic native computer-use** — the model returns a ``tool_use`` block
   with ``name=='computer'`` and structured ``input``. We detect this from a
   dict-shaped response and pull fields directly.

2. **Plain-text fallback** — line-oriented commands like:

   ```
   ACTION: click 320,180
   ACTION: type "hello world"
   ACTION: key Enter
   ACTION: scroll 0 600
   ACTION: navigate https://example.com
   ACTION: done The price is $99.
   ```

   Tolerant of casing and whitespace; falls through to NOOP if nothing
   matches.

The parser is pure (no IO) so it tests fast.
"""

from __future__ import annotations

import re
from typing import Any

from .models import ActionKind, ComputerAction


def _strip_quotes(value: str) -> str:
    """Remove surrounding single/double quotes (repeatedly, for ""url"")."""
    value = value.strip()
    while len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_action(raw: Any) -> ComputerAction:
    """Best-effort parse of an LLM response into a ``ComputerAction``.

    Accepts:
    - ``dict`` shaped like an Anthropic ``tool_use`` content block
    - any object with a ``content`` / ``text`` attribute (Anthropic Message,
      OpenAI Choice, etc.)
    - plain ``str``
    """
    # 1. Anthropic native — dict with ``type``: ``tool_use``
    if isinstance(raw, dict) and raw.get("type") == "tool_use":
        return _from_anthropic_tool_use(raw)

    # 2. Anthropic-style content list — find a tool_use block
    if isinstance(raw, dict) and isinstance(raw.get("content"), list):
        for block in raw["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                return _from_anthropic_tool_use(block)

    # 3. Object with a content/text attribute
    text = _extract_text(raw)
    if text:
        return _from_plain_text(text)

    return ComputerAction(kind=ActionKind.NOOP, rationale="empty response")


# ---------------------------------------------------------------------------
# Anthropic native shape
# ---------------------------------------------------------------------------


def _from_anthropic_tool_use(block: dict[str, Any]) -> ComputerAction:
    name = block.get("name", "")
    if name not in ("computer", "computer_use"):
        return ComputerAction(
            kind=ActionKind.NOOP, rationale=f"unrecognized tool name: {name!r}"
        )
    input_ = block.get("input") or {}
    if not isinstance(input_, dict):
        return ComputerAction(kind=ActionKind.NOOP, rationale="non-dict input")

    # Anthropic's computer-use tool uses ``action`` as the discriminator
    action = str(input_.get("action", "")).lower().strip()
    rationale = str(input_.get("rationale", input_.get("reason", "")))[:300]

    if action in ("left_click", "click"):
        coord = input_.get("coordinate") or [
            input_.get("x", 0),
            input_.get("y", 0),
        ]
        return ComputerAction(
            kind=ActionKind.CLICK,
            args={"x": int(coord[0]), "y": int(coord[1])},
            rationale=rationale,
        )

    if action in ("type", "input"):
        return ComputerAction(
            kind=ActionKind.TYPE,
            args={"text": str(input_.get("text", ""))},
            rationale=rationale,
        )

    if action == "key":
        return ComputerAction(
            kind=ActionKind.KEY,
            args={"key": str(input_.get("key", ""))},
            rationale=rationale,
        )

    if action == "scroll":
        return ComputerAction(
            kind=ActionKind.SCROLL,
            args={
                "dx": int(input_.get("dx", 0)),
                "dy": int(input_.get("dy", 0)),
            },
            rationale=rationale,
        )

    if action == "navigate":
        return ComputerAction(
            kind=ActionKind.NAVIGATE,
            args={"url": _strip_quotes(str(input_.get("url", "")))},
            rationale=rationale,
        )

    if action == "screenshot":
        return ComputerAction(kind=ActionKind.SCREENSHOT, rationale=rationale)

    if action in ("done", "finish", "complete"):
        return ComputerAction(
            kind=ActionKind.DONE,
            args={"final_text": str(input_.get("final_text", ""))},
            rationale=rationale,
        )

    return ComputerAction(
        kind=ActionKind.NOOP, rationale=f"unrecognized action: {action!r}"
    )


# ---------------------------------------------------------------------------
# Plain-text fallback
# ---------------------------------------------------------------------------


_ACTION_RE = re.compile(r"\bACTION\s*:\s*(\w+)\s*(.*)$", re.IGNORECASE | re.MULTILINE)


def _from_plain_text(text: str) -> ComputerAction:
    text = text.strip()
    # Search for the LAST action line (model may emit multiple, but the last
    # is what it wants us to do *now*).
    matches = list(_ACTION_RE.finditer(text))
    if not matches:
        return ComputerAction(
            kind=ActionKind.NOOP,
            rationale="no ACTION: line in response",
        )
    m = matches[-1]
    cmd = m.group(1).lower()
    rest = m.group(2).strip()

    # Rationale = everything before the last ACTION line, trimmed
    rationale = text[: m.start()].strip()[:300]

    if cmd == "click":
        # Either "x,y" or "x y"
        parts = re.split(r"[,\s]+", rest, maxsplit=2)
        if len(parts) >= 2 and parts[0].lstrip("-").isdigit() and parts[1].lstrip("-").isdigit():
            return ComputerAction(
                kind=ActionKind.CLICK,
                args={"x": int(parts[0]), "y": int(parts[1])},
                rationale=rationale,
            )
        return ComputerAction(
            kind=ActionKind.NOOP, rationale="click missing coords"
        )

    if cmd == "type":
        return ComputerAction(
            kind=ActionKind.TYPE,
            args={"text": _strip_quotes(rest)},
            rationale=rationale,
        )

    if cmd == "key":
        return ComputerAction(
            kind=ActionKind.KEY,
            args={"key": _strip_quotes(rest) or "Enter"},
            rationale=rationale,
        )

    if cmd == "scroll":
        parts = re.split(r"[,\s]+", rest, maxsplit=2)
        if len(parts) >= 2 and parts[0].lstrip("-").isdigit() and parts[1].lstrip("-").isdigit():
            return ComputerAction(
                kind=ActionKind.SCROLL,
                args={"dx": int(parts[0]), "dy": int(parts[1])},
                rationale=rationale,
            )
        # Single number → vertical scroll
        if rest.lstrip("-").isdigit():
            return ComputerAction(
                kind=ActionKind.SCROLL,
                args={"dx": 0, "dy": int(rest)},
                rationale=rationale,
            )
        return ComputerAction(kind=ActionKind.NOOP, rationale="scroll missing args")

    if cmd == "navigate":
        # Models frequently emit `navigate "https://…"` or `navigate
        # url=https://…` — normalize both so Playwright never sees literal
        # quote characters (→ "Cannot navigate to invalid URL").
        url = rest
        if url.lower().startswith("url="):
            url = url[4:]
        url = _strip_quotes(url)
        return ComputerAction(
            kind=ActionKind.NAVIGATE,
            args={"url": url},
            rationale=rationale,
        )

    if cmd == "screenshot":
        return ComputerAction(kind=ActionKind.SCREENSHOT, rationale=rationale)

    if cmd in ("done", "finish", "complete"):
        return ComputerAction(
            kind=ActionKind.DONE, args={"final_text": rest}, rationale=rationale
        )

    return ComputerAction(
        kind=ActionKind.NOOP, rationale=f"unknown command: {cmd!r}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_text(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        for key in ("content", "text", "output"):
            v = raw.get(key)
            if isinstance(v, str):
                return v
        # Anthropic Message shape — content may be a list of blocks
        if isinstance(raw.get("content"), list):
            for block in raw["content"]:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    return block["text"]
        return ""
    text = getattr(raw, "content", None) or getattr(raw, "text", None)
    return text if isinstance(text, str) else ""
