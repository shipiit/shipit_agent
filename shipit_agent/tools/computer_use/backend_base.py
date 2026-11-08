"""The computer-use backend interface and the subprocess helper backends share."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class BackendError(RuntimeError):
    """Raised when the platform backend can't satisfy an action."""


@dataclass(slots=True)
class Backend:
    """Common contract; subclasses override the methods they support."""

    platform: str

    def screenshot(self, path: Path) -> Path:
        raise BackendError("screenshot not implemented")

    def click(
        self, x: int, y: int, *, button: str = "left", double: bool = False
    ) -> None:
        raise BackendError("click not implemented")

    def move(self, x: int, y: int) -> None:
        raise BackendError("move not implemented")

    def drag(self, x: int, y: int, to_x: int, to_y: int) -> None:
        raise BackendError("drag not implemented")

    def type_text(self, text: str) -> None:
        raise BackendError("type_text not implemented")

    def key(self, keys: str) -> None:
        raise BackendError("key not implemented")

    def scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        raise BackendError("scroll not implemented")

    def list_apps(self) -> list[str]:
        """Names of the currently running foreground applications."""
        raise BackendError("list_apps not implemented")

    def focus_app(self, name: str) -> None:
        """Bring an application to the front so keystrokes/clicks land in it."""
        raise BackendError("focus_app not implemented")


def _run(cmd: list[str], *, timeout: float = 15.0) -> str:
    """Run a command, raising :class:`BackendError` on any failure.

    Returns decoded stdout (stripped) so callers that need output — e.g.
    ``list_apps`` reading ``osascript`` — can use it; action callers ignore it.
    """
    try:
        proc = subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
    except FileNotFoundError as err:
        raise BackendError(f"{cmd[0]} not found: {err}") from err
    except subprocess.CalledProcessError as err:
        raise BackendError(
            f"{cmd[0]} exit {err.returncode}: {err.stderr.decode('utf-8', 'ignore')[:200]}"
        ) from err
    except subprocess.TimeoutExpired as err:
        raise BackendError(f"{cmd[0]} timed out after {timeout}s") from err
    return proc.stdout.decode("utf-8", "ignore").strip()

