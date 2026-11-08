"""Sandbox settings, in the Claude Agent SDK's shape, and the policy they become.

``SandboxSettings`` uses the SDK's field names, so a settings dict written for
``ClaudeAgentOptions(sandbox=...)`` works here unchanged. ``SandboxPolicy`` is
the validated form the tools use.

What is enforced: commands run with writes limited to the project, the
folders added with ``add_dirs``, the temp folder and ``filesystem.allowWrite``;
``filesystem.denyWrite`` and ``filesystem.denyRead`` paths are blocked; and the
network is off unless ``network.allowedDomains`` is set. Domains are not
filtered one by one: any allowed domain turns the network on for every host,
and ``deniedDomains`` is not enforced. Proxy ports, Mach lookups, violation
filters and the weaker nested sandbox are accepted for compatibility and
have no effect.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any, TypedDict

from shipit_agent.tools.bash.command_risk import command_segments


class SandboxNetworkConfig(TypedDict, total=False):
    allowedDomains: list[str]
    deniedDomains: list[str]
    allowManagedDomainsOnly: bool
    allowUnixSockets: list[str]
    allowAllUnixSockets: bool
    allowLocalBinding: bool
    allowMachLookup: list[str]
    httpProxyPort: int
    socksProxyPort: int


class SandboxFilesystemConfig(TypedDict, total=False):
    allowWrite: list[str]
    denyWrite: list[str]
    denyRead: list[str]


class SandboxSettings(TypedDict, total=False):
    enabled: bool
    autoAllowBashIfSandboxed: bool
    excludedCommands: list[str]
    allowUnsandboxedCommands: bool
    network: SandboxNetworkConfig
    filesystem: SandboxFilesystemConfig
    ignoreViolations: dict[str, list[str]]
    enableWeakerNestedSandbox: bool
    failIfUnavailable: bool


_KEYS = {
    "": set(SandboxSettings.__annotations__),
    "network": set(SandboxNetworkConfig.__annotations__),
    "filesystem": set(SandboxFilesystemConfig.__annotations__),
}


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """How commands are sandboxed; built from :class:`SandboxSettings`."""

    enabled: bool = False
    auto_allow_bash: bool = True
    excluded_commands: tuple[str, ...] = ()
    allow_unsandboxed: bool = True
    fail_if_unavailable: bool = False
    allowed_domains: tuple[str, ...] = ()
    denied_domains: tuple[str, ...] = ()
    allow_local_binding: bool = False
    allow_unix_sockets: tuple[str, ...] = ()
    allow_all_unix_sockets: bool = False
    allow_write: tuple[str, ...] = ()
    deny_write: tuple[str, ...] = ()
    deny_read: tuple[str, ...] = ()

    @property
    def allow_network(self) -> bool:
        return bool(self.allowed_domains)

    @classmethod
    def from_settings(cls, settings: SandboxSettings | dict[str, Any]) -> SandboxPolicy:
        """The policy for *settings*; an unknown key is an error, not ignored."""
        _check_keys(settings, "")
        network = settings.get("network") or {}
        filesystem = settings.get("filesystem") or {}
        _check_keys(network, "network")
        _check_keys(filesystem, "filesystem")
        return cls(
            enabled=bool(settings.get("enabled", False)),
            auto_allow_bash=bool(settings.get("autoAllowBashIfSandboxed", True)),
            excluded_commands=tuple(settings.get("excludedCommands") or ()),
            allow_unsandboxed=bool(settings.get("allowUnsandboxedCommands", True)),
            fail_if_unavailable=bool(settings.get("failIfUnavailable", False)),
            allowed_domains=tuple(network.get("allowedDomains") or ()),
            denied_domains=tuple(network.get("deniedDomains") or ()),
            allow_local_binding=bool(network.get("allowLocalBinding", False)),
            allow_unix_sockets=tuple(network.get("allowUnixSockets") or ()),
            allow_all_unix_sockets=bool(network.get("allowAllUnixSockets", False)),
            allow_write=tuple(filesystem.get("allowWrite") or ()),
            deny_write=tuple(filesystem.get("denyWrite") or ()),
            deny_read=tuple(filesystem.get("denyRead") or ()),
        )

    def excludes(self, command: str) -> bool:
        """Whether *command* runs outside the sandbox by ``excludedCommands``.

        Every simple command in it must match an entry: one sandboxed part
        keeps the whole command sandboxed, since it runs as one process.
        """
        segments = command_segments(command)
        return bool(self.excluded_commands) and bool(segments) and all(
            any(fnmatch.fnmatchcase(segment.strip(), pattern) for pattern in self.excluded_commands)
            for segment in segments
        )


def _check_keys(value: Any, section: str) -> None:
    if not isinstance(value, dict):
        raise TypeError(f"sandbox{'.' + section if section else ''} must be a dict")
    unknown = sorted(set(value) - _KEYS[section])
    if unknown:
        where = f"sandbox.{section}" if section else "sandbox"
        raise ValueError(f"unknown {where} setting(s): {', '.join(unknown)}")
