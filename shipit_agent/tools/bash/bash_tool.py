from __future__ import annotations

import re
import shlex
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.formatting import clip_text

from .prompt import BASH_PROMPT

# Patterns that signal a long-running / never-exits-cleanly process
# (dev servers, watchers, REPLs, etc.). When the LLM tries to run one of
# these in the foreground we'd just sit there until subprocess.run hits its
# timeout and kills the whole agent. Detect them up front and either
# (a) auto-background them with logs piped to a file the LLM can tail, or
# (b) refuse with a clear message so the model picks a non-blocking path.
_LONG_RUNNING_PATTERNS = (
    re.compile(r"\bnpm\s+(run\s+)?(dev|start|serve|watch)\b"),
    re.compile(r"\bnpm\s+run\s+\S+:(dev|watch|serve)\b"),
    re.compile(r"\b(yarn|pnpm|bun)\s+(dev|start|serve|watch)\b"),
    re.compile(r"\bvite(\s+(dev|preview))?\b(?!\s+build)"),
    re.compile(r"\bnext\s+(dev|start)\b"),
    re.compile(r"\b(nodemon|tsc\s+--watch|webpack\s+(serve|--watch))\b"),
    re.compile(r"\b(uvicorn|gunicorn|hypercorn|fastapi\s+dev|flask\s+run)\b"),
    re.compile(r"\bpython\s+-m\s+http\.server\b"),
    re.compile(r"\brails\s+(s|server)\b"),
    re.compile(r"\bdocker\s+compose\s+up\b(?!\s+-d)"),
    re.compile(r"\btail\s+-f\b"),
)


def _is_long_running(command: str) -> bool:
    return any(p.search(command) for p in _LONG_RUNNING_PATTERNS)


class BashTool:
    def __init__(
        self,
        *,
        root_dir: str | Path = "/tmp",
        name: str = "bash",
        description: str = "Run a shell command inside the local project root with basic safety checks.",
        prompt: str | None = None,
        default_timeout: float = 30.0,
        # Claude Code's Bash allows up to 600s so real test suites and builds
        # aren't killed mid-run. Raised from 120s.
        max_timeout: float = 600.0,
        allowed_command_prefixes: list[str] | None = None,
        blocked_substrings: list[str] | None = None,
        #: Opt in to a full shell — redirections (``>``/``>>``/``<``),
        #: heredocs, pipes into files, and command/process substitution. The
        #: safe default keeps the conservative syntactic filter; set this for
        #: a Claude-Code-style bash when the environment is already trusted /
        #: sandboxed. The allowlist and blocked-substring checks still apply.
        unrestricted: bool = False,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.name = name
        self.description = description
        self.prompt = prompt or BASH_PROMPT
        self.prompt_instructions = "Use this for bounded shell inspection, test runs, and local developer workflows."
        self.default_timeout = default_timeout
        self.max_timeout = max_timeout
        self.unrestricted = unrestricted
        #: Live background jobs, id → {process, log_path, command}, for the
        #: companion poll/kill tool.
        self.background_jobs: dict[str, dict[str, Any]] = {}
        self.allowed_command_prefixes = list(
            allowed_command_prefixes
            or [
                # ── filesystem inspection ─────────────────────────
                "ls",
                "pwd",
                "find",
                "tree",
                "du",
                "df",
                "file",
                "stat",
                "which",
                "whereis",
                # ── filesystem mutation (safe) ────────────────────
                "mkdir",
                "touch",
                "cp",
                "mv",
                "ln",
                "chmod",
                "cd",
                # ── text processing ───────────────────────────────
                "cat",
                "head",
                "tail",
                "wc",
                "sort",
                "uniq",
                "sed",
                "awk",
                "cut",
                "tr",
                "diff",
                "grep",
                "rg",
                "xargs",
                "tee",
                "echo",
                "printf",
                # ── git ───────────────────────────────────────────
                "git",
                # ── python ────────────────────────────────────────
                "python",
                "python3",
                "pip",
                "pip3",
                "uv",
                "pytest",
                "ruff",
                "black",
                "isort",
                "mypy",
                "flake8",
                "pylint",
                "coverage",
                # ── node / js ─────────────────────────────────────
                "node",
                "npm",
                "npx",
                "yarn",
                "pnpm",
                "bun",
                "bunx",
                "vite",
                "vitest",
                "tsx",
                "ts-node",
                "next",
                "nuxt",
                "astro",
                "turbo",
                "nx",
                "poetry",
                "tsc",
                "eslint",
                "prettier",
                # ── build / run ───────────────────────────────────
                "make",
                "bash",
                "sh",
                "env",
                "printenv",
                "export",
                "source",
                "true",
                "false",
                "test",
                "[",
                # ── containers & infra ────────────────────────────
                "docker",
                "docker-compose",
                "kubectl",
                "terraform",
                "aws",
                "gcloud",
                # ── network (safe read-only) ──────────────────────
                "curl",
                "wget",
                "ping",
                "dig",
                "nslookup",
                "host",
                # ── other languages ───────────────────────────────
                "go",
                "cargo",
                "rustc",
                "java",
                "javac",
                "mvn",
                "gradle",
                "ruby",
                "gem",
                "bundle",
            ]
        )
        self.blocked_substrings = list(
            blocked_substrings
            or [
                "rm -rf /",
                "sudo ",
                "shutdown",
                "reboot",
                "mkfs",
                "dd if=",
                "git reset --hard",
                "git clean -fd",
                "git clean -xdf",
                "chmod -R 777 /",
            ]
        )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to run",
                        },
                        "timeout": {
                            "type": "number",
                            "description": "Timeout in seconds",
                        },
                        "working_directory": {
                            "type": "string",
                            "description": "Optional relative working directory under the project root",
                        },
                        "background": {
                            "type": "boolean",
                            "description": (
                                "Run the command detached, write logs to a file, "
                                "and return immediately. Use for dev servers, "
                                "watchers, and other commands that don't exit. "
                                "Common long-running commands (npm run dev, "
                                "next dev, vite, uvicorn, etc.) are auto-detected "
                                "and backgrounded even if this flag isn't set."
                            ),
                        },
                    },
                    "required": ["command"],
                },
            },
        }

    def _resolve_dir(self, relative_path: str | None) -> Path:
        target = self.root_dir if not relative_path else (self.root_dir / relative_path)
        candidate = target.resolve()
        if self.root_dir not in candidate.parents and candidate != self.root_dir:
            raise ValueError("Working directory escapes project root")
        return candidate

    def _validate_command(self, command: str) -> None:
        normalized = command.strip()
        if not normalized:
            raise ValueError("Command must not be empty")
        lowered = normalized.lower()
        for blocked in self.blocked_substrings:
            if blocked in lowered:
                raise ValueError(f"Blocked shell command pattern: {blocked}")

        # The allowlist below only inspects the first token of each
        # `;`/`&&`/`||`/`|` segment, so any construct that runs an arbitrary
        # command *without* appearing as a leading token defeats it entirely.
        # Reject those clear-cut bypasses up front, before any tokenisation:
        #   - command substitution:  $(...)  and backticks `...`
        #   - process substitution:  <(...)  >(...)
        #   - redirection to/from files: >  >>  <  (covers heredocs too)
        # These checks run on the raw string so quoted/malformed input is
        # rejected cleanly rather than slipping past shlex.split.
        #
        # NOTE: this is a deliberately conservative, syntactic filter. It will
        # false-positive on redirection-like characters inside quotes (e.g.
        # `echo "a > b"`), which we accept as the safe trade-off. It does NOT
        # defend against an allowlisted command being handed an absolute path
        # to a sensitive file (e.g. `cat /etc/passwd`) — argument-level path
        # confinement is out of scope for this syntactic guard.
        # In unrestricted mode the shell is trusted: redirections, heredocs,
        # and substitution are exactly what a real developer workflow needs
        # (`pytest > out.txt`, `cat <<EOF`, `diff <(a) <(b)`). The blocked-
        # substring guard above still runs. The syntactic bans below apply
        # only in the conservative default mode.
        if not self.unrestricted:
            if "$(" in normalized:
                raise ValueError("Command substitution '$(...)' is not allowed")
            if "`" in normalized:
                raise ValueError(
                    "Command substitution with backticks is not allowed"
                )
            if "<(" in normalized or ">(" in normalized:
                raise ValueError("Process substitution '<(...)'/'>(...)' is not allowed")
            if ">" in normalized or "<" in normalized:
                raise ValueError("File redirection ('>', '>>', '<') is not allowed")

        # The first-token allowlist is a feature of the conservative mode.
        # Unrestricted mode trusts the environment and runs any command; the
        # blocked-substring guard above is the remaining backstop.
        if self.unrestricted:
            return
        for segment in re.split(r"\s*(?:&&|\|\||;|\|)\s*", normalized):
            stripped = segment.strip()
            if not stripped:
                continue
            try:
                tokens = shlex.split(stripped)
            except ValueError:
                raise ValueError("Command could not be parsed for the allowlist check")
            if not tokens:
                continue
            first = tokens[0]
            if not any(
                first == prefix or first.startswith(f"{prefix}/")
                for prefix in self.allowed_command_prefixes
            ):
                raise ValueError(
                    f"Command '{first}' is not in the allowlist for the bash tool"
                )

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        command = str(kwargs.get("command", ""))
        # A validation failure is a result the model can fix, not a crash: a
        # raised exception escapes the tool and can take the whole run down.
        try:
            self._validate_command(command)
        except ValueError as exc:
            return ToolOutput(
                text=f"Command rejected: {exc}",
                metadata={"ok": False, "error": "invalid_command", "command": command},
            )
        timeout = min(
            max(float(kwargs.get("timeout", self.default_timeout)), 1.0),
            self.max_timeout,
        )
        cwd = self._resolve_dir(kwargs.get("working_directory"))
        background = bool(kwargs.get("background"))
        if background or _is_long_running(command):
            return self._run_background(command, cwd)
        started_at = time.monotonic()
        completed = subprocess.run(
            ["/bin/bash", "-lc", command],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = time.monotonic() - started_at
        # Clip long logs to head + tail so a noisy command can't flood the
        # model's context while still keeping the error/exit at the very end.
        output = clip_text(completed.stdout.strip())
        error = clip_text(completed.stderr.strip())
        lines: list[str] = [f"exit_code: {completed.returncode}"]
        if output:
            lines.append("stdout:")
            lines.append(output)
        if error:
            lines.append("stderr:")
            lines.append(error)
        if not output and not error:
            lines.append("(no output)")
        return ToolOutput(
            text="\n".join(lines),
            metadata={
                "command": command,
                "cwd": str(cwd),
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "duration_seconds": round(duration, 4),
            },
        )

    def _run_background(self, command: str, cwd: Path) -> ToolOutput:
        """Spawn a long-running command detached, log to a file the LLM can tail.

        We never block on the process — `subprocess.Popen` returns immediately
        and the agent continues. The LLM gets the log path back so it can
        `tail -n 50 <log>` to verify the server came up. This is the only sane
        way to handle dev servers / watchers from a tool that has a hard
        timeout above it.
        """
        log_dir = self.root_dir / ".shipit" / "bash_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"bg_{int(time.time())}_{uuid.uuid4().hex[:6]}.log"
        with open(log_path, "wb") as log_file:
            process = subprocess.Popen(
                ["/bin/bash", "-lc", command],
                cwd=str(cwd),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        # Brief settle so the very first line of output (binding port, syntax
        # error, etc.) makes it into the log before we read it back.
        time.sleep(2.0)
        early_output = ""
        try:
            early_output = log_path.read_text(errors="replace")[-2000:]
        except OSError:
            pass
        rel_log = log_path.relative_to(self.root_dir)
        job_id = f"job_{len(self.background_jobs) + 1}_{process.pid}"
        self.background_jobs[job_id] = {
            "process": process,
            "log_path": log_path,
            "command": command,
        }
        lines = [
            f"Started in background as {job_id} (pid {process.pid}).",
            f"Log file: {rel_log}",
            f"Check on it with the bash_job tool using job_id {job_id!r} "
            "to read output, or the kill action to stop it.",
            "",
            "Early output:",
            early_output or "(no output yet)",
        ]
        return ToolOutput(
            text="\n".join(lines),
            metadata={
                "command": command,
                "cwd": str(cwd),
                "background": True,
                "job_id": job_id,
                "pid": process.pid,
                "log_path": str(rel_log),
                "early_output": early_output,
            },
        )

    def poll_job(self, job_id: str, *, tail_lines: int = 50) -> dict[str, Any]:
        """Status + recent output for a background job (for the companion tool)."""
        job = self.background_jobs.get(job_id)
        if job is None:
            known = ", ".join(sorted(self.background_jobs)) or "none"
            return {"ok": False, "error": f"no such job {job_id!r}; known: {known}"}
        process = job["process"]
        code = process.poll()
        try:
            text = job["log_path"].read_text(errors="replace")
        except OSError:
            text = ""
        recent = "\n".join(text.splitlines()[-tail_lines:])
        return {
            "ok": True,
            "job_id": job_id,
            "pid": process.pid,
            "running": code is None,
            "exit_code": code,
            "output": recent,
        }

    def kill_job(self, job_id: str) -> dict[str, Any]:
        """Terminate a background job's process group."""
        import os
        import signal

        job = self.background_jobs.get(job_id)
        if job is None:
            return {"ok": False, "error": f"no such job {job_id!r}"}
        process = job["process"]
        if process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                process.terminate()
        return {"ok": True, "job_id": job_id, "killed": True}


class BashJobTool:
    """Poll or kill a background job started by the bash tool.

    Claude Code's BashOutput / KillShell parity: the bash tool can spawn a
    long-running command detached (a dev server, a watcher, a slow build);
    this tool reads its recent output or stops it, by job id. Bound to the
    same BashTool instance so it shares the live job table.
    """

    read_only = False

    def __init__(self, bash_tool: "BashTool", *, name: str = "bash_job") -> None:
        self._bash = bash_tool
        self.name = name
        self.description = (
            "Read output from, or kill, a background command started by the "
            "bash tool. Pass the job_id the bash tool returned."
        )
        self.prompt_instructions = (
            "After starting a background command with the bash tool in "
            "background mode, use this to check on it: the output action "
            "reads recent log lines, the kill action stops it."
        )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "The job id returned by the bash tool.",
                        },
                        "action": {
                            "type": "string",
                            "enum": ["output", "kill"],
                            "description": "output = read recent log; kill = stop it.",
                        },
                        "tail_lines": {
                            "type": "number",
                            "description": "How many trailing log lines to return (default 50).",
                        },
                    },
                    "required": ["job_id"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        job_id = str(kwargs.get("job_id", ""))
        action = str(kwargs.get("action", "output"))
        if action == "kill":
            result = self._bash.kill_job(job_id)
            text = (
                f"Killed {job_id}."
                if result.get("ok")
                else f"Could not kill: {result.get('error')}"
            )
            return ToolOutput(text=text, metadata=result)
        tail = int(kwargs.get("tail_lines", 50) or 50)
        result = self._bash.poll_job(job_id, tail_lines=tail)
        if not result.get("ok"):
            return ToolOutput(text=result.get("error", "unknown job"), metadata=result)
        status = "running" if result["running"] else f"exited ({result['exit_code']})"
        text = (
            f"Job {job_id} is {status}.\n\nRecent output:\n"
            + (result["output"] or "(no output yet)")
        )
        return ToolOutput(text=text, metadata=result)
