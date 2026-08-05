"""The capability bridge — `env` in a sandbox, credentials outside it.

Code mode needs the agent's code to reach real resources. The obvious
implementation — `exec()` the model's code in-process with `env` in its globals
— hands arbitrary model-written Python the same address space as your API
tokens, your credential store, and the permission engine that is supposed to be
policing it. One `import os` and the gate is decoration.

Cloudflare OS does not do that: the gadget runs in a sandbox and the Gatekeeper
holding the credentials runs outside it, with an RPC boundary between them.
This is that boundary.

    ┌─ parent ──────────────────┐        ┌─ child (sandboxed) ─────┐
    │ credentials               │        │ the model's code        │
    │ permission engine  ◄──────┼── RPC ─┤ env.GITHUB.create_issue │
    │ approval queue            │        │ (no secrets, no tools)  │
    │ the actual tools          │────────► plain JSON result       │
    └───────────────────────────┘        └─────────────────────────┘

What crosses the boundary is JSON: a binding name, a method name, and keyword
arguments in; text and metadata out. The child never holds a credential, never
holds a tool object, and cannot bypass the gate — because the gate runs on the
other side of a socket it can only send requests to.

Three limits bound a runaway loop: a per-call timeout, a total-call ceiling,
and a wall-clock budget for the whole execution.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

__all__ = ["BridgeCall", "BridgeServer", "BridgeLimits", "BridgeAddress"]


@dataclass(frozen=True, slots=True)
class BridgeLimits:
    """Bounds on what one execution may ask the parent to do."""

    max_calls: int = 100
    call_timeout_seconds: float = 60.0
    total_seconds: float = 300.0


@dataclass(frozen=True, slots=True)
class BridgeAddress:
    """How the child reaches the parent. Passed via environment variables."""

    kind: str  # "unix" | "tcp"
    path: str = ""
    host: str = "127.0.0.1"
    port: int = 0
    token: str = ""

    def as_env(self) -> dict[str, str]:
        return {
            "SHIPIT_BRIDGE_KIND": self.kind,
            "SHIPIT_BRIDGE_PATH": self.path,
            "SHIPIT_BRIDGE_HOST": self.host,
            "SHIPIT_BRIDGE_PORT": str(self.port),
            "SHIPIT_BRIDGE_TOKEN": self.token,
        }


@dataclass(slots=True)
class BridgeCall:
    """One `env` call the sandboxed code made, for the transcript and audit."""

    binding: str
    method: str
    arguments: dict[str, Any]
    ok: bool = True
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0


# The handler receives (binding, method, kwargs) and returns (text, metadata).
# It is where the runtime applies the permission gate and the approval queue.
Handler = Callable[[str, str, dict[str, Any]], tuple[str, dict[str, Any]]]


class BridgeServer:
    """Parent-side listener. Serves one execution, then closes.

    Use as a context manager::

        with BridgeServer(handler) as bridge:
            run_child(env=bridge.address.as_env())
        bridge.calls  # what the code actually did
    """

    def __init__(
        self,
        handler: Handler,
        *,
        limits: BridgeLimits | None = None,
    ) -> None:
        self._handler = handler
        self.limits = limits or BridgeLimits()
        self.calls: list[BridgeCall] = []
        self._token = secrets.token_urlsafe(32)
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._tempdir: str | None = None
        self.address: BridgeAddress | None = None
        self._started_at = 0.0
        self._lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────

    def __enter__(self) -> "BridgeServer":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    def start(self) -> BridgeAddress:
        """Listen, and return the address the child should connect to."""
        if hasattr(socket, "AF_UNIX"):
            # A unix socket inside a 0700 directory: the filesystem enforces
            # that only this user can connect, which a localhost TCP port
            # cannot do — any local process can reach 127.0.0.1.
            self._tempdir = tempfile.mkdtemp(prefix="shipit-bridge-")
            os.chmod(self._tempdir, 0o700)
            path = os.path.join(self._tempdir, "sock")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(path)
            os.chmod(path, 0o600)
            self.address = BridgeAddress(kind="unix", path=path, token=self._token)
        else:
            # Windows and anywhere without AF_UNIX. The token is doing the
            # access control here, so it is a 32-byte secret and single-use.
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.bind(("127.0.0.1", 0))
            self.address = BridgeAddress(
                kind="tcp", port=server.getsockname()[1], token=self._token
            )

        server.listen(4)
        server.settimeout(0.5)
        self._socket = server
        self._started_at = time.monotonic()
        self._thread = threading.Thread(
            target=self._serve, name="shipit-codemode-bridge", daemon=True
        )
        self._thread.start()
        return self.address

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        if self._tempdir:
            for name in os.listdir(self._tempdir):
                try:
                    os.unlink(os.path.join(self._tempdir, name))
                except OSError:
                    pass
            try:
                os.rmdir(self._tempdir)
            except OSError:
                pass
            self._tempdir = None

    # ── serving ──────────────────────────────────────────────────────────

    def _serve(self) -> None:
        while not self._stop.is_set():
            if time.monotonic() - self._started_at > self.limits.total_seconds:
                return
            try:
                conn, _ = self._socket.accept()  # type: ignore[union-attr]
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                return
            threading.Thread(
                target=self._handle_connection, args=(conn,), daemon=True
            ).start()

    def _handle_connection(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(self.limits.call_timeout_seconds)
            reader = conn.makefile("r", encoding="utf-8")
            writer = conn.makefile("w", encoding="utf-8")
            for line in reader:
                if self._stop.is_set():
                    return
                try:
                    response = self._dispatch(line)
                except Exception as exc:  # noqa: BLE001 - never kill the bridge
                    response = {"ok": False, "error": f"bridge error: {exc}"}
                try:
                    writer.write(json.dumps(response) + "\n")
                    writer.flush()
                except (BrokenPipeError, ValueError, OSError):
                    return

    def _dispatch(self, line: str) -> dict[str, Any]:
        try:
            request = json.loads(line)
        except ValueError:
            return {"ok": False, "error": "malformed request"}
        if not isinstance(request, dict):
            return {"ok": False, "error": "malformed request"}

        # Constant-time compare: the token is the only thing standing between
        # a local process and the agent's capabilities on the TCP path.
        if not secrets.compare_digest(str(request.get("token", "")), self._token):
            return {"ok": False, "error": "unauthorized"}

        request_id = request.get("id")
        binding = str(request.get("binding") or "")
        method = str(request.get("method") or "")
        kwargs = request.get("kwargs")
        kwargs = dict(kwargs) if isinstance(kwargs, dict) else {}

        with self._lock:
            if len(self.calls) >= self.limits.max_calls:
                return {
                    "id": request_id,
                    "ok": False,
                    "error": (
                        f"env call limit reached ({self.limits.max_calls}). "
                        f"Batch your work into fewer calls."
                    ),
                }
            if time.monotonic() - self._started_at > self.limits.total_seconds:
                return {
                    "id": request_id,
                    "ok": False,
                    "error": "execution time budget exhausted",
                }
            record = BridgeCall(binding=binding, method=method, arguments=kwargs)
            self.calls.append(record)

        started = time.perf_counter()
        try:
            text, metadata = self._handler(binding, method, kwargs)
            record.ok = True
            record.output = text
            return {
                "id": request_id,
                "ok": True,
                "result": text,
                "metadata": metadata,
            }
        except Exception as exc:  # noqa: BLE001 - surfaced to the child as data
            record.ok = False
            record.error = str(exc)
            return {"id": request_id, "ok": False, "error": str(exc)}
        finally:
            record.duration_ms = round((time.perf_counter() - started) * 1000, 1)

    # ── reporting ────────────────────────────────────────────────────────

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def summary(self) -> dict[str, Any]:
        return {
            "calls": len(self.calls),
            "failed": sum(1 for c in self.calls if not c.ok),
            "bindings": sorted({c.binding for c in self.calls}),
            "total_ms": round(sum(c.duration_ms for c in self.calls), 1),
        }
