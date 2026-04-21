"""Platform-specific helpers for computer_use.

Each backend exposes the same surface: ``screenshot(path)``, ``click(x, y, button, double)``,
``move(x, y)``, ``drag(x, y, to_x, to_y)``, ``type_text(text)``, ``key(keys)``,
``scroll(x, y, dx, dy)``. Each raises :class:`BackendError` on missing
dependencies with a one-line install hint.

Selection order:
  - ``sys.platform == "darwin"`` → MacBackend (screencapture + cliclick / osascript)
  - ``sys.platform.startswith("linux")`` → LinuxBackend (scrot + xdotool)
  - ``sys.platform == "win32"`` → WindowsBackend (PowerShell)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


class BackendError(RuntimeError):
    """Raised when the platform backend can't satisfy an action."""


@dataclass(slots=True)
class Backend:
    """Common contract; subclasses override the methods they support."""
    platform: str

    def screenshot(self, path: Path) -> Path: raise BackendError("screenshot not implemented")
    def click(self, x: int, y: int, *, button: str = "left", double: bool = False) -> None: raise BackendError("click not implemented")
    def move(self, x: int, y: int) -> None: raise BackendError("move not implemented")
    def drag(self, x: int, y: int, to_x: int, to_y: int) -> None: raise BackendError("drag not implemented")
    def type_text(self, text: str) -> None: raise BackendError("type_text not implemented")
    def key(self, keys: str) -> None: raise BackendError("key not implemented")
    def scroll(self, x: int, y: int, dx: int, dy: int) -> None: raise BackendError("scroll not implemented")


# ─────────────────────── macOS ───────────────────────


class MacBackend(Backend):
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

    def click(self, x: int, y: int, *, button: str = "left", double: bool = False) -> None:
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
            raise BackendError("cliclick required for move (install: brew install cliclick)")
        _run([self._cliclick, f"m:{x},{y}"])

    def drag(self, x: int, y: int, to_x: int, to_y: int) -> None:
        if not self._cliclick:
            raise BackendError("cliclick required for drag (install: brew install cliclick)")
        _run([self._cliclick, f"dd:{x},{y}", f"du:{to_x},{to_y}"])

    def type_text(self, text: str) -> None:
        if self._cliclick:
            _run([self._cliclick, "w:50", f"t:{text}"])
            return
        script = (
            'tell application "System Events" to keystroke '
            + _apple_quote(text)
        )
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
            if m in ("cmd", "command"): mods.append("command down")
            elif m in ("opt", "option", "alt"): mods.append("option down")
            elif m in ("shift",): mods.append("shift down")
            elif m in ("ctrl", "control"): mods.append("control down")
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


# ─────────────────────── Linux ───────────────────────


class LinuxBackend(Backend):
    def __init__(self) -> None:
        super().__init__(platform="linux")
        self._shot = shutil.which("scrot") or shutil.which("import")
        self._xdotool = shutil.which("xdotool")

    def screenshot(self, path: Path) -> Path:
        if not self._shot:
            raise BackendError("scrot or imagemagick 'import' required (apt install scrot).")
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._shot.endswith("scrot"):
            _run([self._shot, "-z", str(path)])
        else:  # ImageMagick's `import`
            _run([self._shot, "-window", "root", str(path)])
        if not path.exists():
            raise BackendError("screenshot produced no file.")
        return path

    def click(self, x: int, y: int, *, button: str = "left", double: bool = False) -> None:
        self._require_xdotool()
        b = {"left": "1", "right": "3", "middle": "2"}.get(button, "1")
        args = [self._xdotool, "mousemove", str(x), str(y), "click"]
        args += ["--repeat", "2"] if double else []
        args += [b]
        _run(args)

    def move(self, x: int, y: int) -> None:
        self._require_xdotool()
        _run([self._xdotool, "mousemove", str(x), str(y)])

    def drag(self, x: int, y: int, to_x: int, to_y: int) -> None:
        self._require_xdotool()
        _run([self._xdotool, "mousemove", str(x), str(y), "mousedown", "1"])
        _run([self._xdotool, "mousemove", str(to_x), str(to_y), "mouseup", "1"])

    def type_text(self, text: str) -> None:
        self._require_xdotool()
        _run([self._xdotool, "type", "--delay", "20", text])

    def key(self, keys: str) -> None:
        self._require_xdotool()
        _run([self._xdotool, "key", keys])

    def scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self._require_xdotool()
        _run([self._xdotool, "mousemove", str(x), str(y)])
        for _ in range(abs(dy)):
            _run([self._xdotool, "click", "5" if dy > 0 else "4"])

    def _require_xdotool(self) -> None:
        if not self._xdotool:
            raise BackendError("xdotool required (apt install xdotool).")


# ─────────────────────── Windows ───────────────────────


class WindowsBackend(Backend):
    def __init__(self) -> None:
        super().__init__(platform="win32")

    def screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
            "$g = [System.Drawing.Graphics]::FromImage($bmp); "
            f"$g.CopyFromScreen(0,0,0,0,$bmp.Size); $bmp.Save('{str(path).replace(chr(92), chr(92)*2)}');"
        )
        _run(["powershell", "-NoProfile", "-Command", script])
        if not path.exists():
            raise BackendError("powershell screenshot produced no file.")
        return path


# ─────────────────────── dispatch + helpers ───────────────────────


def resolve_backend() -> Backend:
    if sys.platform == "darwin":
        return MacBackend()
    if sys.platform.startswith("linux"):
        return LinuxBackend()
    if sys.platform == "win32":
        return WindowsBackend()
    raise BackendError(f"unsupported platform: {sys.platform}")


def _run(cmd: list[str], *, timeout: float = 15.0) -> None:
    try:
        subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
    except FileNotFoundError as err:
        raise BackendError(f"{cmd[0]} not found: {err}") from err
    except subprocess.CalledProcessError as err:
        raise BackendError(f"{cmd[0]} exit {err.returncode}: {err.stderr.decode('utf-8', 'ignore')[:200]}") from err
    except subprocess.TimeoutExpired as err:
        raise BackendError(f"{cmd[0]} timed out after {timeout}s") from err


def _apple_quote(s: str) -> str:
    """Escape a Python string into an AppleScript string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# Minimal AppleScript key-code table for common named keys. Anything not
# listed falls back to keystroke semantics — for more obscure keys the
# caller should install cliclick.
_MAC_KEYS = {
    "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51, "escape": 53,
    "up": 126, "down": 125, "left": 123, "right": 124,
    "pageup": 116, "pagedown": 121, "home": 115, "end": 119,
}
def _mac_key_code(name: str) -> int:
    code = _MAC_KEYS.get(name.lower())
    if code is None:
        raise BackendError(f"unknown key '{name}' (supported: {', '.join(sorted(_MAC_KEYS))})")
    return code
