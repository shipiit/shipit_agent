"""Signal handling for Autopilot: stop cleanly on SIGTERM and SIGHUP."""

from __future__ import annotations

import signal
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from .core import Autopilot

class _SignalGuard:
    """Install SIGTERM/SIGHUP handlers on entry, restore on exit.

    SIGINT already maps to KeyboardInterrupt by default, so we don't
    need to swap its handler — the try/except in the main loop
    catches the interrupt and drains a final checkpoint.
    """

    def __init__(self, autopilot: Autopilot) -> None:
        self.autopilot = autopilot
        self._old: dict[int, Any] = {}

    def __enter__(self) -> None:
        if not self.autopilot.install_signal_handlers:
            return
        # Only attempt signal install on the main thread — signals
        # can't be bound from worker threads, and fan-out runs
        # children inside a ThreadPoolExecutor.
        import threading

        if threading.current_thread() is not threading.main_thread():
            return
        for sig_name in ("SIGTERM", "SIGHUP"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                self._old[sig] = signal.signal(sig, self._handler)
            except (ValueError, OSError):
                pass

    def __exit__(self, *_: Any) -> None:
        for sig, old in self._old.items():
            try:
                signal.signal(sig, old)
            except (ValueError, OSError):
                pass

    def _handler(self, signum: int, _frame: Any) -> None:
        name = signal.Signals(signum).name
        self.autopilot.request_stop(f"halted by {name}")
