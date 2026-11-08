"""macOS computer-use backend: screencapture, AppleScript and cliclick."""

from __future__ import annotations

import shutil
from pathlib import Path

from .backend_base import Backend, BackendError, _run


class MacBackend(Backend):
    """Screen capture and input control on macOS."""
    def __init__(self) -> None:
        super().__init__(platform="darwin")
        self._cliclick = shutil.which("cliclick")

    def screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        # -x = no capture sound, -C = capture cursor.
        _run(["screencapture", "-x", "-C", str(path)])
        if not path.exists():
            raise BackendError("screencapture produced no file.")
        return path

    def click(
        self, x: int, y: int, *, button: str = "left", double: bool = False
    ) -> None:
        if self._cliclick:
            verb = {"left": "c", "right": "rc", "middle": "c"}.get(button, "c")
            if double:
                verb = "dc"
            _run([self._cliclick, f"{verb}:{x},{y}"])
            return
        # Fallback: AppleScript.
        script = f'tell application "System Events" to {"double click" if double else "click"} at {{{x}, {y}}}'
        _run(["osascript", "-e", script])

    def move(self, x: int, y: int) -> None:
        if not self._cliclick:
            raise BackendError(
                "cliclick required for move (install: brew install cliclick)"
            )
        _run([self._cliclick, f"m:{x},{y}"])

    def drag(self, x: int, y: int, to_x: int, to_y: int) -> None:
        if not self._cliclick:
            raise BackendError(
                "cliclick required for drag (install: brew install cliclick)"
            )
        _run([self._cliclick, f"dd:{x},{y}", f"du:{to_x},{to_y}"])

    def type_text(self, text: str) -> None:
        if self._cliclick:
            _run([self._cliclick, "w:50", f"t:{text}"])
            return
        script = 'tell application "System Events" to keystroke ' + _apple_quote(text)
        _run(["osascript", "-e", script])

    def key(self, keys: str) -> None:
        # Accept "cmd+shift+4" style chords. cliclick uses single keys with kp:,
        # AppleScript expresses modifiers via "key code" syntax — messy.
        # Easiest reliable path: AppleScript keystroke with modifiers.
        token = keys.lower().replace(" ", "")
        parts = token.split("+")
        mods = []
        final_key = parts[-1]
        for m in parts[:-1]:
            if m in ("cmd", "command"):
                mods.append("command down")
            elif m in ("opt", "option", "alt"):
                mods.append("option down")
            elif m in ("shift",):
                mods.append("shift down")
            elif m in ("ctrl", "control"):
                mods.append("control down")
        quoted = _apple_quote(final_key if len(final_key) == 1 else f'"{final_key}"')
        using = " using {" + ", ".join(mods) + "}" if mods else ""
        if len(final_key) == 1:
            script = f'tell application "System Events" to keystroke {quoted}{using}'
        else:
            script = f'tell application "System Events" to key code {_mac_key_code(final_key)}{using}'
        _run(["osascript", "-e", script])

    def scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        # cliclick has no native scroll; fall back to key-press PageDown/Up.
        if dy > 0:
            for _ in range(abs(dy)):
                self.key("pagedown")
        elif dy < 0:
            for _ in range(abs(dy)):
                self.key("pageup")
        # Horizontal scroll is rare; ignore silently.

    def list_apps(self) -> list[str]:
        out = _run([
            "osascript", "-e",
            'tell application "System Events" to get name of every process '
            "whose background only is false",
        ])
        return [n.strip() for n in out.split(",") if n.strip()]

    def focus_app(self, name: str) -> None:
        # `activate` is the reliable way to raise an app; System Events
        # `set frontmost` needs the exact process name and Accessibility perms.
        _run(["osascript", "-e", f'tell application {_apple_quote(name)} to activate'])


def _apple_quote(s: str) -> str:
    """Escape a Python string into an AppleScript string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# Minimal AppleScript key-code table for common named keys. Anything not
# listed falls back to keystroke semantics — for more obscure keys the
# caller should install cliclick.
_MAC_KEYS = {
    "return": 36,
    "enter": 36,
    "tab": 48,
    "space": 49,
    "delete": 51,
    "escape": 53,
    "up": 126,
    "down": 125,
    "left": 123,
    "right": 124,
    "pageup": 116,
    "pagedown": 121,
    "home": 115,
    "end": 119,
}


def _mac_key_code(name: str) -> int:
    code = _MAC_KEYS.get(name.lower())
    if code is None:
        raise BackendError(
            f"unknown key '{name}' (supported: {', '.join(sorted(_MAC_KEYS))})"
        )
    return code

