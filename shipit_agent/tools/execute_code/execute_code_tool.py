"""``execute_code`` — one call that can do what five tool calls used to.

The other half of code mode. `describe_binding` tells the agent what a resource
can do; this lets it *use* several of them together, in one turn, with real
control flow::

    rows = env.WAREHOUSE.call(query="SELECT account, mrr FROM bookings")
    at_risk = [r for r in parse(rows) if r["mrr"] < 1000]
    for account in at_risk:
        env.LINEAR.create_issue(title=f"Check in on {account['account']}")

Without it the model orchestrates that as five separate tool calls, holding
every intermediate result in its context.

The code runs in a **subprocess**, and `env` reaches the parent over the
capability bridge (see :mod:`shipit_agent.codemode.bridge`).

What that boundary does and does not buy, stated plainly, because the
difference matters:

- It **does** keep the parent's live secrets out of the child. Credentials sit
  in a CredentialStore instance in the parent's memory; the child gets a fresh
  interpreter with a scrubbed environment, so importing shipit there yields an
  empty store, not yours.
- It **does** make the permission engine unbypassable *for env*. The child has
  no tool objects — only a socket. Every binding call is gated on the parent
  side exactly as the equivalent tool call would be, and there is no code path
  from the child to a tool that skips it.
- It does **not** sandbox the filesystem or the network. The child is an
  ordinary Python process and can read files and open sockets, the same as the
  existing `run_code` tool. If you need that contained, run the agent itself in
  a container; `run_code` also supports a Docker sandbox.

The distinction is the point: in-process `exec()` would give model-written code
your live credential objects and the ability to monkeypatch the gate. This does
not, and that is what the boundary is for.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from shipit_agent.codemode.bridge import BridgeLimits, BridgeServer
from shipit_agent.codemode.preamble import build_preamble
from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.describe_binding.describe_binding_tool import (
    BINDINGS_STATE_KEY,
)
from shipit_agent.tools.formatting import clip_text

# The runtime publishes a callable here that applies the permission gate,
# contracts and approval queue to one binding call. Without it, `env` is not
# offered at all — an ungated bridge would be worse than no code mode.
INVOKER_STATE_KEY = "codemode_invoker"

EXECUTE_CODE_PROMPT = """
Use `execute_code` when a task needs several resources together, or needs
control flow (loops, conditionals, filtering) over their results. One call that
queries the warehouse, filters in Python and files the tickets beats five tool
calls passing data through your context.

Write plain Python. `env` is already defined — do not import or construct it.
Call `describe_binding` first for any binding you have not used yet.
Pass every binding argument by keyword exactly as described; env methods do
not accept positional arguments.

Print what you want to see; stdout is returned to you. Keep it to a few hundred
lines and avoid unbounded loops: there is a call ceiling and a time budget.
""".strip()

_MAX_OUTPUT = 12_000


class ExecuteCodeTool:
    """Run Python with the agent's `env` bindings available."""

    # Arbitrary code: never auto-approvable, and the agent reads its output,
    # so the decision cannot be deferred. Declared here; contracts.py agrees.
    read_only = False

    def __init__(
        self,
        *,
        name: str = "execute_code",
        timeout_seconds: float = 120.0,
        limits: BridgeLimits | None = None,
        python: str | None = None,
    ) -> None:
        self.name = name
        self.description = (
            "Run Python with the agent's `env` resource bindings available. "
            "Use for work spanning several resources or needing control flow."
        )
        self.prompt_instructions = EXECUTE_CODE_PROMPT
        self.timeout_seconds = timeout_seconds
        self.limits = limits or BridgeLimits()
        self.python = python or sys.executable

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": (
                                "Python to run. `env` is predefined; print what "
                                "you want returned."
                            ),
                        }
                    },
                    "required": ["code"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        code = str(kwargs.get("code") or "")
        if not code.strip():
            return ToolOutput(
                text="execute_code needs `code` to run.",
                metadata={"error": "missing_code"},
            )

        bindings = context.state.get(BINDINGS_STATE_KEY) or {}
        invoker = context.state.get(INVOKER_STATE_KEY)
        if invoker is None:
            # No gate available. Offering an ungated bridge would hand the
            # sandbox capabilities the permission engine never saw.
            return ToolOutput(
                text=(
                    "Code mode is not enabled for this run, so `env` is not "
                    "available. Use the individual tools instead."
                ),
                metadata={"error": "codemode_disabled"},
            )

        with BridgeServer(invoker, limits=self.limits) as bridge:
            result = self._run_child(
                code=code,
                bindings=bindings,
                bridge_env=bridge.address.as_env(),
            )
            calls = list(bridge.calls)
            summary = bridge.summary()

        text = result["output"] or "(the code produced no output)"
        return ToolOutput(
            text=clip_text(text, max_chars=_MAX_OUTPUT),
            metadata={
                "exit_code": result["exit_code"],
                "timed_out": result["timed_out"],
                "env_calls": summary["calls"],
                "env_bindings_used": summary["bindings"],
                "env_call_failures": summary["failed"],
                # Each env call is a real tool invocation and belongs in the
                # transcript, not hidden inside one opaque "ran code" row.
                "calls": [
                    {
                        "binding": c.binding,
                        "method": c.method,
                        "ok": c.ok,
                        "duration_ms": c.duration_ms,
                    }
                    for c in calls
                ],
            },
        )

    # ── the child process ────────────────────────────────────────────────

    def _run_child(
        self, *, code: str, bindings: dict[str, Any], bridge_env: dict[str, str]
    ) -> dict[str, Any]:
        preamble = build_preamble(bindings)
        source = preamble + "\n" + code

        child_env = {
            # A deliberately minimal environment: the child gets what it needs
            # to run Python and reach the bridge, and none of the parent's
            # secrets (API keys routinely live in os.environ).
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            **bridge_env,
        }

        with tempfile.TemporaryDirectory(prefix="shipit-codemode-") as workdir:
            script = Path(workdir) / "agent_code.py"
            script.write_text(source, encoding="utf-8")
            try:
                completed = subprocess.run(
                    [self.python, "-I", str(script)],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    cwd=workdir,
                    env=child_env,
                    check=False,
                )
            except subprocess.TimeoutExpired as expired:
                return {
                    "output": _join(
                        _decode(expired.stdout),
                        _decode(expired.stderr),
                        note=f"[timed out after {self.timeout_seconds:.0f}s]",
                    ),
                    "exit_code": None,
                    "timed_out": True,
                }
            except OSError as exc:
                return {
                    "output": f"Could not start the sandbox: {exc}",
                    "exit_code": None,
                    "timed_out": False,
                }

        return {
            "output": _join(
                completed.stdout,
                _rebase_traceback(completed.stderr, preamble.count("\n") + 1),
            ),
            "exit_code": completed.returncode,
            "timed_out": False,
        }


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def _join(stdout: str, stderr: str, *, note: str = "") -> str:
    parts = [p for p in (stdout.rstrip(), stderr.rstrip(), note) if p]
    return "\n".join(parts)


def _rebase_traceback(stderr: str, preamble_lines: int) -> str:
    """Point line numbers at the model's code, not the injected preamble.

    A traceback reading `line 187` when the model wrote 12 lines is actively
    misleading, and the model will try to "fix" code it never wrote.
    """
    if not stderr or preamble_lines <= 0:
        return stderr or ""
    import re

    def _shift(match: "re.Match[str]") -> str:
        line = int(match.group(1))
        rebased = line - preamble_lines
        return f"line {rebased}" if rebased > 0 else "line ? (injected preamble)"

    return re.sub(r"line (\d+)", _shift, stderr)
