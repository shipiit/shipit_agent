from __future__ import annotations

import re
import shlex
import subprocess
import time
from pathlib import Path

from shipit_agent.tools.base import ToolContext, ToolOutput

from .prompt import BASH_PROMPT


class BashTool:
    def __init__(
        self,
        *,
        root_dir: str | Path = "/tmp",
        name: str = "bash",
        description: str = "Run a shell command inside the local project root with basic safety checks.",
        prompt: str | None = None,
        default_timeout: float = 30.0,
        max_timeout: float = 120.0,
        allowed_command_prefixes: list[str] | None = None,
        blocked_substrings: list[str] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.name = name
        self.description = description
        self.prompt = prompt or BASH_PROMPT
        self.prompt_instructions = "Use this for bounded shell inspection, test runs, and local developer workflows."
        self.default_timeout = default_timeout
        self.max_timeout = max_timeout
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
        for segment in re.split(r"\s*(?:&&|\|\||;|\|)\s*", normalized):
            stripped = segment.strip()
            if not stripped:
                continue
            first = shlex.split(stripped)[0]
            if not any(
                first == prefix or first.startswith(f"{prefix}/")
                for prefix in self.allowed_command_prefixes
            ):
                raise ValueError(
                    f"Command '{first}' is not in the allowlist for the bash tool"
                )

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        command = str(kwargs.get("command", ""))
        self._validate_command(command)
        timeout = min(
            max(float(kwargs.get("timeout", self.default_timeout)), 1.0),
            self.max_timeout,
        )
        cwd = self._resolve_dir(kwargs.get("working_directory"))
        started_at = time.monotonic()
        completed = subprocess.run(
            ["/bin/bash", "-lc", command],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = time.monotonic() - started_at
        output = completed.stdout.strip()
        error = completed.stderr.strip()
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
