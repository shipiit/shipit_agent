"""Running a saved app and collecting what it produced."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import App


@dataclass(slots=True)
class AppRunResult:
    """What one run of an app produced: success, its value and captured output."""
    ok: bool
    value: Any = None
    stdout: str = ""
    error: str = ""
    exit_code: int | None = 0
    timed_out: bool = False
    env_calls: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "value": self.value,
            "stdout": self.stdout,
            "error": self.error,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "env_calls": self.env_calls,
        }


_RUNNER = '''\
import json, runpy, sys, traceback

_payload = json.loads(sys.stdin.read() or "{}")
_module = runpy.run_path(_payload["entrypoint"])
_run = _module.get("run")
if _run is None:
    print(json.dumps({"__shipit_error__": "app.py does not define run(input, env)"}),
          file=sys.stderr)
    raise SystemExit(2)

try:
    _value = _run(_payload.get("input") or {}, env)
except Exception:
    print(json.dumps({"__shipit_error__": traceback.format_exc(limit=6)}),
          file=sys.stderr)
    raise SystemExit(1)

try:
    _encoded = json.dumps(_value, default=str)
except (TypeError, ValueError):
    _encoded = json.dumps(str(_value))
print("__SHIPIT_APP_RESULT__" + _encoded)
'''


def run_app(
    app: App,
    payload: dict[str, Any] | None = None,
    *,
    invoker: Any = None,
    bindings: dict[str, Any] | None = None,
    timeout_seconds: float = 60.0,
    python: str | None = None,
    cwd: str | Path | None = None,
) -> AppRunResult:
    """Run *app* in a subprocess and return what its ``run()`` returned.

    ``env`` inside the app carries only the bindings the manifest names, and
    every call on it crosses the capability bridge back to the parent's
    permission engine. With no ``invoker`` the app still runs — it simply has
    no `env`, which is the right outcome for an app that never asked for one.
    """
    from shipit_agent.codemode.bridge import BridgeServer
    from shipit_agent.codemode.preamble import build_preamble

    wired = _wired_bindings(app, bindings or {})
    missing = sorted(set(app.manifest.bindings) - set(wired))
    source = build_preamble(wired) + "\n" + _RUNNER

    child_env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    bridge: Any = None
    if invoker is not None:
        bridge = BridgeServer(invoker)
        bridge.start()
        child_env.update(bridge.address.as_env())

    try:
        with tempfile.TemporaryDirectory(prefix="shipit-app-") as workdir:
            script = Path(workdir) / "_runner.py"
            script.write_text(source, encoding="utf-8")
            stdin = json.dumps(
                {"entrypoint": str(app.entrypoint), "input": payload or {}}
            )
            try:
                completed = subprocess.run(
                    [python or sys.executable, "-I", str(script)],
                    input=stdin,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    cwd=str(cwd or app.path),
                    env=child_env,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return AppRunResult(
                    ok=False,
                    error=f"app timed out after {timeout_seconds:.0f}s",
                    exit_code=None,
                    timed_out=True,
                )
    finally:
        if bridge is not None:
            bridge.stop()

    result = _parse(completed.stdout, completed.stderr, completed.returncode)
    result.env_calls = bridge.call_count if bridge is not None else 0
    if missing and not result.ok:
        result.error += (
            f"\n(the manifest wires {', '.join(missing)}, which the agent's "
            "environment does not currently offer)"
        )
    return result


def _wired_bindings(app: App, available: dict[str, Any]) -> dict[str, Any]:
    """The app's env: only what its manifest names, under the names it chose."""
    wired: dict[str, Any] = {}
    for inner, outer in app.manifest.bindings.items():
        binding = available.get(outer)
        if binding is not None:
            wired[inner] = binding
    return wired


def _parse(stdout: str, stderr: str, code: int) -> AppRunResult:
    marker = "__SHIPIT_APP_RESULT__"
    value: Any = None
    lines = []
    for line in (stdout or "").splitlines():
        if line.startswith(marker):
            try:
                value = json.loads(line[len(marker):])
            except ValueError:
                value = line[len(marker):]
        else:
            lines.append(line)

    error = ""
    for line in (stderr or "").splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            error += line + "\n"
            continue
        if isinstance(payload, dict) and "__shipit_error__" in payload:
            error += str(payload["__shipit_error__"])
        else:
            error += line + "\n"

    return AppRunResult(
        ok=code == 0 and not error.strip(),
        value=value,
        stdout="\n".join(lines).strip(),
        error=error.strip(),
        exit_code=code,
    )

