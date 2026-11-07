"""MCP over a subprocess's stdin and stdout: one process per call, or one kept alive."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from itertools import count
from typing import Any

from .transport import _MCP_DEFAULT_TIMEOUT, MCPError


class MCPSubprocessTransport:
    """Talk to an MCP server over stdio, starting a fresh process for each request.

    Simple and isolated, but slow for chatty servers; prefer
    :class:`PersistentMCPSubprocessTransport` for repeated calls.
    """

    def __init__(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout: float = _MCP_DEFAULT_TIMEOUT,
    ) -> None:
        self.command = command
        self.env = env
        self.timeout = timeout
        self._id_counter = count(1)

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._id_counter),
            "method": method,
            "params": params or {},
        }
        try:
            completed = subprocess.run(
                self.command,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                env=self.env,
                check=False,
                timeout=self.timeout or None,
            )
        except subprocess.TimeoutExpired as exc:
            raise MCPError(
                f"MCP subprocess timed out after {self.timeout:.0f}s on {method!r}"
            ) from exc
        if completed.returncode != 0:
            raise MCPError(
                completed.stderr.strip()
                or f"MCP subprocess failed with exit code {completed.returncode}"
            )
        output = completed.stdout.strip()
        if not output:
            return {}
        response = json.loads(output)
        if "error" in response:
            raise MCPError(str(response["error"]))
        return dict(response.get("result", {}))

    def close(self) -> None:
        return None


# Friendly aliases matching MCP ecosystem naming (and our docs).
MCPStdioTransport = MCPSubprocessTransport


class PersistentMCPSubprocessTransport:
    """Talk to an MCP server over stdio, keeping one process alive across requests."""

    def __init__(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout: float = _MCP_DEFAULT_TIMEOUT,
    ) -> None:
        self.command = command
        self.env = {**os.environ, **(env or {})}
        self.timeout = timeout
        self._id_counter = count(1)
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        #: Bumped on every (re)spawn. RemoteMCPServer compares it against the
        #: generation it handshook with — a crashed-and-respawned server must
        #: be re-`initialize`d before it can serve `tools/call`.
        self.generation = 0

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        self._process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env,
        )
        self.generation += 1
        return self._process

    def _readline_with_deadline(self, process: subprocess.Popen[str]) -> str:
        """A readline that cannot wedge the run.

        ``process.stdout.readline()`` under ``self._lock`` with no deadline
        turns one hung MCP server into a hung agent — observed shape, and
        ``cancel()`` cannot interrupt it. The read runs on a worker thread;
        on expiry the process is killed (its pipe state is undefined mid-
        message, so respawn-next-request is the only safe recovery) and a
        readable MCPError surfaces to the model.
        """
        if not self.timeout:
            return process.stdout.readline()  # type: ignore[union-attr]
        result: list[str] = []

        def _read() -> None:
            result.append(process.stdout.readline())  # type: ignore[union-attr]

        reader = threading.Thread(target=_read, daemon=True)
        reader.start()
        reader.join(self.timeout)
        if reader.is_alive():
            process.kill()
            raise MCPError(
                f"Persistent MCP subprocess timed out after "
                f"{self.timeout:.0f}s; the process was killed and will be "
                "respawned on the next request."
            )
        return result[0] if result else ""

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self._lock:
            process = self._ensure_process()
            if process.stdin is None or process.stdout is None:
                raise MCPError("Persistent MCP subprocess did not expose stdio pipes.")
            request_id = next(self._id_counter)
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()
            while True:
                line = self._readline_with_deadline(process)
                if not line:
                    stderr = process.stderr.read() if process.stderr is not None else ""
                    raise MCPError(
                        stderr.strip()
                        or "Persistent MCP subprocess exited without a response."
                    )
                response = json.loads(line)
                if response.get("id") == request_id:
                    break
            if "error" in response:
                raise MCPError(str(response["error"]))
            return dict(response.get("result", {}))

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        with self._lock:
            process = self._ensure_process()
            if process.stdin is None:
                raise MCPError("Persistent MCP subprocess did not expose stdin.")
            process.stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": method,
                        "params": params or {},
                    }
                )
                + "\n"
            )
            process.stdin.flush()

    def close(self) -> None:
        with self._lock:
            if self._process is None:
                return
            if self._process.stdin is not None:
                try:
                    self._process.stdin.close()
                except Exception:
                    pass
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            self._process = None


PersistentMCPSession = PersistentMCPSubprocessTransport
