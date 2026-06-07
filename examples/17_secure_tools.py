"""
17 — Hardened local tools (bash allowlist + SSRF-safe URL fetch).

The local-execution tools enforce their guarantees defensively:

- ``BashTool`` runs only allowlisted commands and now rejects shell
  command-substitution (``$(...)``, backticks) and file redirection that
  would otherwise smuggle past the allowlist.
- ``OpenURLTool`` only fetches http/https and blocks private, loopback and
  cloud-metadata addresses (SSRF) as well as ``file://`` URLs.

In normal use you never call these guards yourself — they fire automatically
inside ``tool.run(...)``. This script pokes the internal ``_validate_*``
helpers directly only so it can demonstrate the policy with zero side effects
(no shell commands run, no network requests made), so it runs anywhere.

Run:
    python examples/17_secure_tools.py
"""

from __future__ import annotations

from shipit_agent.tools.bash.bash_tool import BashTool
from shipit_agent.tools.open_url.open_url_tool import OpenURLTool


def _try(label: str, fn) -> None:
    try:
        fn()
        print(f"  ALLOWED  {label}")
    except Exception as exc:  # noqa: BLE001 — demo
        print(f"  BLOCKED  {label}  → {type(exc).__name__}: {str(exc)[:60]}")


def main() -> None:
    print("─" * 60)
    print("  Bash command validation (allowlist: echo, ls)")
    print("─" * 60)
    bash = BashTool(allowed_command_prefixes=["echo", "ls"])
    _try("echo hello", lambda: bash._validate_command("echo hello"))
    _try("echo $(id)", lambda: bash._validate_command("echo $(id)"))
    _try("echo `whoami`", lambda: bash._validate_command("echo `whoami`"))
    _try("echo hi > /etc/x", lambda: bash._validate_command("echo hi > /etc/x"))
    _try("curl evil.com", lambda: bash._validate_command("curl evil.com"))

    print("\n" + "─" * 60)
    print("  URL fetch validation (SSRF-safe)")
    print("─" * 60)
    url_tool = OpenURLTool()
    _try("https://example.com", lambda: url_tool._validate_url("https://example.com"))
    _try("file:///etc/passwd", lambda: url_tool._validate_url("file:///etc/passwd"))
    _try(
        "http://169.254.169.254/  (cloud metadata)",
        lambda: url_tool._validate_url("http://169.254.169.254/latest/meta-data/"),
    )
    _try("http://localhost:8080", lambda: url_tool._validate_url("http://localhost:8080"))


if __name__ == "__main__":
    main()
