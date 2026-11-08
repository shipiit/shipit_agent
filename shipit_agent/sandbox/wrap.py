"""Deciding whether a command runs sandboxed, and wrapping its argv."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .backends import available_backend, sandbox_prefix
from .settings import SandboxPolicy

logger = logging.getLogger(__name__)


class SandboxUnavailable(RuntimeError):
    """The sandbox is required (``failIfUnavailable``) but cannot run here."""


@dataclass(frozen=True, slots=True)
class Wrapped:
    argv: list[str]
    sandboxed: bool
    #: Why the command runs outside the sandbox, when it does.
    reason: str = ""


_warned_unavailable = False


def check_available(policy: SandboxPolicy | None) -> None:
    """Raise when *policy* requires a sandbox this machine cannot run."""
    if policy is not None and policy.enabled and policy.fail_if_unavailable and available_backend() is None:
        raise SandboxUnavailable(
            "sandbox.failIfUnavailable is set, but no sandbox can run here: "
            "macOS needs /usr/bin/sandbox-exec and Linux needs bubblewrap (bwrap)."
        )


def wrap_argv(
    argv: list[str],
    command: str,
    policy: SandboxPolicy | None,
    roots: Iterable[Path],
    *,
    unsandboxed: bool = False,
) -> Wrapped:
    """*argv* run inside the sandbox, or unchanged with the reason it is not."""
    global _warned_unavailable
    if policy is None or not policy.enabled:
        return Wrapped(argv, False, "sandbox off")
    if unsandboxed and policy.allow_unsandboxed:
        return Wrapped(argv, False, "approved to run outside the sandbox")
    if policy.excludes(command):
        return Wrapped(argv, False, "listed in sandbox.excludedCommands")
    backend = available_backend()
    if backend is None:
        check_available(policy)
        if not _warned_unavailable:
            logger.warning("sandbox enabled but unavailable on this machine; commands run unsandboxed")
            _warned_unavailable = True
        return Wrapped(argv, False, "no sandbox available on this machine")
    return Wrapped([*sandbox_prefix(backend, policy, roots), *argv], True)


def runs_sandboxed(policy: SandboxPolicy | None, command: str, *, unsandboxed: bool = False) -> bool:
    """Whether *command* would run inside the sandbox."""
    return wrap_argv([], command, policy, (), unsandboxed=unsandboxed).sandboxed
