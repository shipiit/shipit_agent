"""Background jobs for the bash tool: commands that keep running, and the tool to check on them.

A command becomes a job in two ways: the model asks for ``background`` (a
dev server, a watcher), or a foreground command outlives its timeout. Either
way it keeps running with its output in log files, and ``bash_job`` reads or
stops it by id.
"""

from __future__ import annotations

import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shipit_agent.core.tasks import TaskInfo
from shipit_agent.tools.base import ToolContext, ToolOutput

from .runner import StillRunning, read_log

if TYPE_CHECKING:
    from .bash_tool import BashTool

#: Lines of output shown when a command moves to the background.
_EARLY_LINES = 40

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


def is_long_running(command: str) -> bool:
    return any(p.search(command) for p in _LONG_RUNNING_PATTERNS)


class BackgroundJobsMixin:
    """Starting, adopting, polling and stopping the bash tool's background jobs.

    Mixed into :class:`~shipit_agent.tools.bash.bash_tool.BashTool`, which
    provides ``root_dir``, ``background_jobs`` and ``_child_env``.
    """

    def _adopt_timed_out(
        self, command: str, cwd: Path, outcome: StillRunning
    ) -> ToolOutput:
        """Keep a command that outlived its timeout running, as a background job."""
        job_id = f"job_{len(self.background_jobs) + 1}_{outcome.process.pid}"
        self.background_jobs[job_id] = {
            "process": outcome.process,
            "log_path": outcome.stdout_path,
            "err_path": outcome.stderr_path,
            "command": command,
        }
        so_far = "\n".join(read_log(outcome.stdout_path).splitlines()[-_EARLY_LINES:])
        return ToolOutput(
            text="\n".join(
                [
                    f"Still running after {outcome.waited:.0f}s, so it continues in "
                    f"the background as {job_id} (pid {outcome.process.pid}).",
                    f"Check on it with the bash_job tool using job_id {job_id!r}; "
                    "the kill action stops it.",
                    "",
                    "Output so far:",
                    so_far or "(no output yet)",
                ]
            ),
            metadata={
                "command": command,
                "cwd": str(cwd),
                "background": True,
                "timed_out": True,
                "job_id": job_id,
                "pid": outcome.process.pid,
                "log_path": str(outcome.stdout_path),
            },
        )

    def _run_background(
        self, command: str, cwd: Path, *, argv: list[str] | None = None
    ) -> ToolOutput:
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
                argv or ["/bin/bash", "-lc", command],
                cwd=str(cwd),
                env=self._child_env(),
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
        text = read_log(job["log_path"])
        if job.get("err_path") is not None:
            errors = read_log(job["err_path"])
            if errors:
                text = f"{text}\n[stderr]\n{errors}" if text else f"[stderr]\n{errors}"
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
            job["stopped"] = True
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                process.terminate()
        return {"ok": True, "job_id": job_id, "killed": True}

    def list_background_tasks(self) -> list[TaskInfo]:
        """The jobs as background tasks (see :mod:`shipit_agent.core.tasks`)."""
        return [self._task_info(job_id, job) for job_id, job in self.background_jobs.items()]

    def stop_background_task(self, task_id: str) -> TaskInfo | None:
        if task_id not in self.background_jobs:
            return None
        self.kill_job(task_id)
        self.background_jobs[task_id]["process"].wait(timeout=5)
        return self._task_info(task_id, self.background_jobs[task_id])

    @staticmethod
    def _task_info(job_id: str, job: dict[str, Any]) -> TaskInfo:
        code = job["process"].poll()
        status = ("running" if code is None else "stopped" if job.get("stopped")
                  else "completed" if code == 0 else "failed")
        return TaskInfo(job_id, "local_bash", str(job["command"]), status,
                        output_file=str(job["log_path"]), exit_code=code)


class BashJobTool:
    """Poll or kill a background job started by the bash tool.

    The bash tool can spawn a
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
        text = f"Job {job_id} is {status}.\n\nRecent output:\n" + (
            result["output"] or "(no output yet)"
        )
        return ToolOutput(text=text, metadata=result)
