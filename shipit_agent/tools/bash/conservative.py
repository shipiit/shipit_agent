"""The bash tool's conservative mode: a first-token allowlist and no redirection.

Opt in with ``BashTool(unrestricted=False)`` or an explicit
``allowed_command_prefixes``. The default is a full shell whose commands are
judged by :mod:`.command_risk`; this mode suits a host that wants the old,
narrow surface.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Sequence

#: Commands the conservative mode runs, by their first token.
DEFAULT_ALLOWED_PREFIXES: tuple[str, ...] = (
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
)

#: Substrings the conservative mode refuses outright.
DEFAULT_BLOCKED_SUBSTRINGS: tuple[str, ...] = (
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
)


def check_conservative(command: str, allowed_prefixes: Sequence[str]) -> None:
    """Raise ``ValueError`` unless *command* passes the conservative filter.

    The allowlist inspects only the first token of each ``;``/``&&``/``||``/
    ``|`` segment, so anything that runs a command without it leading (command
    or process substitution, and redirection, which covers heredocs) is
    refused first, on the raw string. The filter is deliberately syntactic: it
    false-positives on ``>`` inside quotes, and does not confine arguments
    (``cat /etc/passwd`` passes).
    """
    if "$(" in command:
        raise ValueError("Command substitution '$(...)' is not allowed")
    if "`" in command:
        raise ValueError("Command substitution with backticks is not allowed")
    if "<(" in command or ">(" in command:
        raise ValueError("Process substitution '<(...)'/'>(...)' is not allowed")
    if ">" in command or "<" in command:
        raise ValueError("File redirection ('>', '>>', '<') is not allowed")

    for segment in re.split(r"\s*(?:&&|\|\||;|\|)\s*", command):
        stripped = segment.strip()
        if not stripped:
            continue
        try:
            tokens = shlex.split(stripped)
        except ValueError:
            raise ValueError(
                "Command could not be parsed for the allowlist check"
            ) from None
        if not tokens:
            continue
        first = tokens[0]
        if not any(
            first == prefix or first.startswith(f"{prefix}/")
            for prefix in allowed_prefixes
        ):
            raise ValueError(
                f"Command '{first}' is not in the allowlist for the bash tool"
            )
