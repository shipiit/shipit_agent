from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import ClassVar

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import CODE_EXECUTION_PROMPT


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

        self.workspace_root.mkdir(parents=True, exist_ok=True)
        suffix = self.LANGUAGE_SUFFIXES.get(language, ".txt")
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=suffix,
            dir=self.workspace_root,
            delete=False,
        ) as handle:
            handle.write(code)
            script_path = Path(handle.name)

        command = self._command_for_language(language, script_path)
        completed = subprocess.run(
            command,
            cwd=self.workspace_root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
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
                "workspace_root": str(self.workspace_root.resolve()),
            },
        )
