"""The OS sandboxes: Seatbelt (``sandbox-exec``) on macOS, bubblewrap on Linux.

Each turns a :class:`SandboxPolicy` and the folders a command may write to
into the argv prefix that runs the command inside the sandbox.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from .settings import SandboxPolicy

Backend = Literal["seatbelt", "bubblewrap"]
SANDBOX_EXEC = "/usr/bin/sandbox-exec"

#: Device files a shell writes to in ordinary use.
_DEVICE_WRITES = ("/dev/null", "/dev/zero", "/dev/stdout", "/dev/stderr", "/dev/dtracehelper")


def available_backend() -> Backend | None:
    """The sandbox this machine can run, or ``None``."""
    if sys.platform == "darwin" and os.path.exists(SANDBOX_EXEC):
        return "seatbelt"
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        return "bubblewrap"
    return None


def writable_paths(roots: Iterable[Path], policy: SandboxPolicy) -> list[str]:
    """Every folder a sandboxed command may write to, resolved, without repeats."""
    paths = [*roots, Path(tempfile.gettempdir()), Path("/tmp"), *map(Path, policy.allow_write)]
    seen: list[str] = []
    for path in paths:
        for form in (str(path.expanduser()), os.path.realpath(path.expanduser())):
            if form not in seen:
                seen.append(form)
    return seen


def _quote(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _resolved(paths: Iterable[str]) -> list[str]:
    out: list[str] = []
    for path in paths:
        for form in (os.path.expanduser(path), os.path.realpath(os.path.expanduser(path))):
            if form not in out:
                out.append(form)
    return out


def seatbelt_profile(policy: SandboxPolicy, writable: list[str]) -> str:
    """A Seatbelt profile: reads allowed, writes and network as the policy says.

    In Seatbelt the last matching rule wins, so the denies for
    ``denyWrite`` come after the allowed folders they carve out of.
    """
    rules = ["(version 1)", "(allow default)", "(deny file-write*)"]
    allowed = [f"(subpath {_quote(p)})" for p in writable]
    allowed += [f"(literal {_quote(p)})" for p in _DEVICE_WRITES]
    allowed += ['(regex #"^/dev/tty")', '(regex #"^/dev/fd/")']
    rules.append("(allow file-write*\n  " + "\n  ".join(allowed) + ")")
    for path in _resolved(policy.deny_write):
        rules.append(f"(deny file-write* (subpath {_quote(path)}))")
    for path in _resolved(policy.deny_read):
        rules.append(f"(deny file-read* (subpath {_quote(path)}))")
    if not policy.allow_network:
        rules.append("(deny network*)")
        if policy.allow_local_binding:
            rules.append('(allow network-bind network-inbound (local ip "localhost:*"))')
            rules.append('(allow network-outbound (remote ip "localhost:*"))')
        if policy.allow_all_unix_sockets:
            rules.append("(allow network* (remote unix-socket))")
        for path in _resolved(policy.allow_unix_sockets):
            rules.append(f"(allow network* (remote unix-socket (path-literal {_quote(path)})))")
    return "\n".join(rules) + "\n"


def bubblewrap_args(policy: SandboxPolicy, writable: list[str]) -> list[str]:
    """bubblewrap options: the filesystem read-only except the writable folders.

    Later mounts cover earlier ones, so ``denyWrite`` and ``denyRead`` come
    last. Paths that do not exist are skipped; bubblewrap cannot mount them.
    """
    args = ["--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--die-with-parent"]
    for path in writable:
        if os.path.isdir(path):
            args += ["--bind", path, path]
    for path in _resolved(policy.deny_write):
        if os.path.exists(path):
            args += ["--ro-bind", path, path]
    for path in _resolved(policy.deny_read):
        if os.path.isdir(path):
            args += ["--tmpfs", path]
        elif os.path.exists(path):
            args += ["--ro-bind", "/dev/null", path]
    if not policy.allow_network:
        args.append("--unshare-net")
    return args


def sandbox_prefix(backend: Backend, policy: SandboxPolicy, roots: Iterable[Path]) -> list[str]:
    """The argv to put before a command to run it in *backend*'s sandbox."""
    writable = writable_paths(roots, policy)
    if backend == "seatbelt":
        return [SANDBOX_EXEC, "-p", seatbelt_profile(policy, writable)]
    return ["bwrap", *bubblewrap_args(policy, writable), "--"]
