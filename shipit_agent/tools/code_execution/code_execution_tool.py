from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import ClassVar

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import CODE_EXECUTION_PROMPT
from .sandbox import (
    SANDBOX_CMDS as _SANDBOX_CMDS,
    SANDBOX_IMAGES as _SANDBOX_IMAGES,
    build_sandbox_command,
)


class CodeExecutionTool:
    LANGUAGE_ALIASES: ClassVar[dict[str, str]] = {
        "python3": "python",
        "py": "python",
        "shell": "bash",
        "zsh": "zsh",
        "node": "javascript",
        "js": "javascript",
        "ts": "typescript",
    }
    LANGUAGE_COMMANDS: ClassVar[dict[str, list[list[str]]]] = {
        "python": [["python3"], ["python"]],
        "bash": [["bash"]],
        "sh": [["sh"]],
        "zsh": [["zsh"]],
        "javascript": [["node"]],
        "typescript": [["tsx"], ["ts-node"], ["bun", "run"]],
        "ruby": [["ruby"]],
        "php": [["php"]],
        "perl": [["perl"]],
        "lua": [["lua"]],
        "r": [["Rscript"]],
    }
    LANGUAGE_SUFFIXES: ClassVar[dict[str, str]] = {
        "python": ".py",
        "bash": ".sh",
        "sh": ".sh",
        "zsh": ".zsh",
        "javascript": ".js",
        "typescript": ".ts",
        "ruby": ".rb",
        "php": ".php",
        "perl": ".pl",
        "lua": ".lua",
        "r": ".R",
    }

    # Sandbox defaults (images + inside-container argv) live in
    # sandbox.py so this file stays under the 300-line ceiling. Expose
    # them via class attributes so callers can still read/override them.
    SANDBOX_IMAGES: ClassVar[dict[str, str]] = _SANDBOX_IMAGES  # filled below
    SANDBOX_CMDS: ClassVar[dict[str, list[str]]] = _SANDBOX_CMDS

    def __init__(
        self,
        *,
        workspace_root: str | Path = ".shipit_workspace/code_execution",
        name: str = "run_code",
        description: str = "Execute Python or shell code in a local subprocess workspace.",
        prompt: str | None = None,
        timeout_seconds: int = 15,
    ) -> None:
        self.workspace_root = Path(workspace_root)
        self.name = name
        self.description = description
        self.prompt = prompt or CODE_EXECUTION_PROMPT
        self.prompt_instructions = "Use this for deterministic local execution, transformations, parsing, and script-based validation."
        self.timeout_seconds = timeout_seconds

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "language": {
                            "type": "string",
                            "enum": sorted(self.supported_languages()),
                            "description": "Interpreter to use",
                        },
                        "code": {
                            "type": "string",
                            "description": "Source code to execute",
                        },
                        "timeout_seconds": {
                            "type": "number",
                            "description": "Optional execution timeout",
                        },
                        "sandbox": {
                            "type": "boolean",
                            "description": (
                                "Run inside a disposable Docker container with "
                                "--network none and a read-only rootfs. Safer for "
                                "untrusted snippets. Requires `docker` on PATH."
                            ),
                            "default": False,
                        },
                        "network": {
                            "type": "boolean",
                            "description": (
                                "When sandbox=true, allow outbound network. "
                                "Default false."
                            ),
                            "default": False,
                        },
                        "image": {
                            "type": "string",
                            "description": (
                                "When sandbox=true, override the default Docker "
                                "image for the chosen language."
                            ),
                        },
                        "workspace_root": {
                            "type": "string",
                            "description": (
                                "Override the workspace directory for this call. "
                                "Lets specialists (developer, debugger, designer, "
                                "researcher) work inside the user's project instead "
                                "of the shared default. Absolute or cwd-relative path."
                            ),
                        },
                    },
                    "required": ["language", "code"],
                },
            },
        }

    @classmethod
    def supported_languages(cls) -> list[str]:
        return sorted(cls.LANGUAGE_COMMANDS)

    def _normalize_language(self, language: str) -> str:
        lowered = language.strip().lower()
        return self.LANGUAGE_ALIASES.get(lowered, lowered)

    def _command_for_language(self, language: str, script_path: Path) -> list[str]:
        normalized = self._normalize_language(language)
        candidates = self.LANGUAGE_COMMANDS.get(normalized)
        if candidates is None:
            raise ValueError(f"Unsupported language: {language}")
        for candidate in candidates:
            executable = shutil.which(candidate[0])
            if executable is None:
                continue
            return [executable, *candidate[1:], str(script_path)]
        tried = ", ".join(" ".join(parts) for parts in candidates)
        raise RuntimeError(
            f"No interpreter found for language '{normalized}'. Tried: {tried}"
        )

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        language = self._normalize_language(str(kwargs["language"]))
        code = str(kwargs["code"])
        timeout_seconds = int(kwargs.get("timeout_seconds", self.timeout_seconds))
        sandbox = bool(kwargs.get("sandbox", False))
        allow_network = bool(kwargs.get("network", False))
        override_image = kwargs.get("image")

        # Allow callers — specialists, CLI users, notebooks — to redirect
        # the scratch directory on a per-call basis. Falls back to the
        # constructor default when omitted.
        override_workspace = kwargs.get("workspace_root")
        workspace_root = (
            Path(str(override_workspace)).expanduser().resolve()
            if override_workspace
            else self.workspace_root
        )
        workspace_root.mkdir(parents=True, exist_ok=True)
        suffix = self.LANGUAGE_SUFFIXES.get(language, ".txt")
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=suffix,
            dir=workspace_root,
            delete=False,
        ) as handle:
            handle.write(code)
            script_path = Path(handle.name)

        if sandbox:
            command, cwd = build_sandbox_command(
                language,
                script_path,
                workspace_root,
                allow_network=allow_network,
                image=str(override_image) if override_image else None,
            )
        else:
            command = self._command_for_language(language, script_path)
            cwd = workspace_root

        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError as err:
            if sandbox:
                return ToolOutput(
                    text=(
                        "Error: docker is not installed or not on PATH. "
                        "Install Docker Desktop or call the tool without sandbox=true."
                    ),
                    metadata={"ok": False, "sandbox": True, "error": str(err)},
                )
            raise
        text = "\n".join(
            [
                f"exit_code: {completed.returncode}",
                "stdout:",
                completed.stdout.rstrip(),
                "stderr:",
                completed.stderr.rstrip(),
            ]
        ).strip()
        return ToolOutput(
            text=text,
            metadata={
                "language": language,
                "supported_languages": self.supported_languages(),
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "script_path": str(script_path),
                "workspace_root": str(workspace_root.resolve()),
                "sandbox": sandbox,
                "sandbox_image": override_image
                if sandbox and override_image
                else (self.SANDBOX_IMAGES.get(language) if sandbox else None),
                "sandbox_network": allow_network if sandbox else False,
            },
        )
