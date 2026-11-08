"""The bash tool's side of the OS sandbox (``AgentOptions(sandbox=...)``).

Commands run inside the sandbox when the policy is on. The model may ask
for one command to run outside it with ``dangerouslyDisableSandbox`` when
``allowUnsandboxedCommands`` is set; that call then needs approval like any
risky command. With ``autoAllowBashIfSandboxed`` (the default), a command
that will run sandboxed needs no approval unless it is blocked outright.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shipit_agent.sandbox import SandboxPolicy, Wrapped, runs_sandboxed, wrap_argv

from .command_risk import CommandVerdict

UNSANDBOXED_FLAG = "dangerouslyDisableSandbox"


class SandboxedShellMixin:
    sandbox_policy: SandboxPolicy | None
    root_dir: Path
    extra_roots: tuple[Path, ...]

    def _shell_argv(self, command: str, *, unsandboxed: bool = False) -> Wrapped:
        """The argv that runs *command* with bash, inside the sandbox when it applies."""
        return wrap_argv(
            ["/bin/bash", "-lc", command],
            command,
            self.sandbox_policy,
            [self.root_dir, *self.extra_roots],
            unsandboxed=unsandboxed,
        )

    def _offers_unsandboxed(self) -> bool:
        policy = self.sandbox_policy
        return policy is not None and policy.enabled and policy.allow_unsandboxed

    def _with_sandbox_flag(self, schema: dict[str, Any]) -> dict[str, Any]:
        if self._offers_unsandboxed():
            schema["function"]["parameters"]["properties"][UNSANDBOXED_FLAG] = {
                "type": "boolean",
                "description": (
                    "Run this command outside the sandbox. Only when it fails "
                    "because of the sandbox (a blocked write or network call); "
                    "the user is asked to approve."
                ),
            }
        return schema

    def _sandbox_verdict(self, arguments: dict[str, Any], verdict: CommandVerdict) -> CommandVerdict:
        """*verdict* adjusted for where the command runs."""
        if verdict.level == "blocked":
            return verdict
        command = str(arguments.get("command", ""))
        asks_out = bool(arguments.get(UNSANDBOXED_FLAG)) and self._offers_unsandboxed()
        if asks_out and runs_sandboxed(self.sandbox_policy, command):
            return CommandVerdict("risky", (*verdict.reasons, "it runs outside the sandbox"))
        policy = self.sandbox_policy
        if policy is not None and policy.auto_allow_bash and runs_sandboxed(policy, command, unsandboxed=asks_out):
            return CommandVerdict("safe")
        return verdict
