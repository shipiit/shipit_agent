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
import sys
from pathlib import Path

from .backend_base import Backend as Backend
from .backend_base import BackendError as BackendError
from .backend_base import _run
from .mac_backend import MacBackend as MacBackend

# ─────────────────────── macOS ───────────────────────


# ─────────────────────── Linux ───────────────────────


class LinuxBackend(Backend):
    """Screen capture and input control on Linux."""
    def __init__(self) -> None:
        super().__init__(platform="linux")
        self._shot = shutil.which("scrot") or shutil.which("import")
        self._xdotool = shutil.which("xdotool")

    def screenshot(self, path: Path) -> Path:
        if not self._shot:
            raise BackendError(
                "scrot or imagemagick 'import' required (apt install scrot)."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._shot.endswith("scrot"):
            _run([self._shot, "-z", str(path)])
        else:  # ImageMagick's `import`
            _run([self._shot, "-window", "root", str(path)])
        if not path.exists():
            raise BackendError("screenshot produced no file.")
        return path

    def click(
        self, x: int, y: int, *, button: str = "left", double: bool = False
    ) -> None:
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
    """Screen capture and input control on Windows."""
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
    """The computer-use backend for the current operating system."""
    if sys.platform == "darwin":
        return MacBackend()
    if sys.platform.startswith("linux"):
        return LinuxBackend()
    if sys.platform == "win32":
        return WindowsBackend()
    raise BackendError(f"unsupported platform: {sys.platform}")
