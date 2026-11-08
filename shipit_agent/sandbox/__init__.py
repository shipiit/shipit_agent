"""OS sandboxing for the commands an agent runs, as the SDK's ``sandbox`` option.

    from shipit_agent.sdk import AgentOptions
    options = AgentOptions(sandbox={"enabled": True})

With it on, bash and code execution run under Seatbelt on macOS or
bubblewrap on Linux: writes only in the project, added folders and temp,
and no network unless ``network.allowedDomains`` is set. See
:mod:`.settings` for exactly what is and is not enforced.
"""

from .backends import available_backend
from .settings import SandboxFilesystemConfig, SandboxNetworkConfig, SandboxPolicy, SandboxSettings
from .wrap import SandboxUnavailable, Wrapped, check_available, runs_sandboxed, wrap_argv

__all__ = [
    "SandboxFilesystemConfig",
    "SandboxNetworkConfig",
    "SandboxPolicy",
    "SandboxSettings",
    "SandboxUnavailable",
    "Wrapped",
    "available_backend",
    "check_available",
    "runs_sandboxed",
    "wrap_argv",
]
