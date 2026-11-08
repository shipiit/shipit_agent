"""Running one shell command: wait for it, or hand it over to the background.

Output goes to log files rather than pipes, for two reasons. A command that
outlives its timeout can keep running with nowhere to block: the files keep
filling, and the bash tool turns it into a background job the model can poll.
And a long result can be clipped for the model while the complete text stays
on disk, at a path the model is given.

Logs live in a fresh temporary folder per command, outside the project, so
running commands never litters the user's repository.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Finished:
    """A command that exited within its timeout."""

    exit_code: int
    stdout: str
    stderr: str
    duration: float
    stdout_path: Path
    stderr_path: Path


@dataclass(frozen=True, slots=True)
class StillRunning:
    """A command still running when its timeout passed; it has not been stopped."""

    process: subprocess.Popen[bytes]
    stdout_path: Path
    stderr_path: Path
    waited: float


def run_command(
    command: str,
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    argv: list[str] | None = None,
) -> Finished | StillRunning:
    """Run *command* with bash, waiting up to *timeout* seconds for it to exit.

    *argv*, when given, is how to run it instead, such as wrapped in a sandbox.
    """
    log_dir = Path(tempfile.mkdtemp(prefix="shipit-bash-"))
    stdout_path = log_dir / "stdout.log"
    stderr_path = log_dir / "stderr.log"
    started = time.monotonic()
    with open(stdout_path, "wb") as stdout, open(stderr_path, "wb") as stderr:
        process = subprocess.Popen(
            argv or ["/bin/bash", "-lc", command],
            cwd=str(cwd),
            env=env,
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            # Its own process group, so stopping it later stops its children.
            start_new_session=True,
        )
    try:
        exit_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return StillRunning(process, stdout_path, stderr_path, time.monotonic() - started)
    return Finished(
        exit_code=exit_code,
        stdout=read_log(stdout_path),
        stderr=read_log(stderr_path),
        duration=time.monotonic() - started,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )


def read_log(path: Path) -> str:
    """The text of one log file, or ``""`` when it cannot be read."""
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""
