from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import GREP_SEARCH_PROMPT


class GrepSearchTool:
    def __init__(
        self,
        *,
        root_dir: str | Path = "/tmp",
        name: str = "grep_files",
        description: str = "Search file contents in the local project using ripgrep when available.",
        prompt: str | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.name = name
        self.description = description
        self.prompt = prompt or GREP_SEARCH_PROMPT
        self.prompt_instructions = "Use this to find symbols, error strings, config keys, query fragments, and code references across the project."

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Regex or plain-text pattern to search for",
                        },
                        "path": {
                            "type": "string",
                            "description": "Optional relative directory to search from",
                        },
                        "glob": {
                            "type": "string",
                            "description": "Optional glob filter such as *.py",
                        },
                        "limit": {
                            "type": "number",
                            "description": "Maximum number of matching lines to return",
                        },
                        "case_sensitive": {
                            "type": "boolean",
                            "description": "Whether the search should be case-sensitive",
                        },
                    },
                    "required": ["pattern"],
                },
            },
        }

    def _resolve(self, relative_path: str | None) -> Path:
        candidate = (self.root_dir / (relative_path or ".")).resolve()
        if self.root_dir not in candidate.parents and candidate != self.root_dir:
            raise ValueError("Path escapes project root")
        return candidate

    def _run_rg(
        self,
        *,
        pattern: str,
        path: Path,
        glob_pattern: str | None,
        limit: int,
        case_sensitive: bool,
    ) -> str | None:
        executable = shutil.which("rg")
        if executable is None:
            return None
        command = [executable, "-n", "--no-heading"]
        if not case_sensitive:
            command.append("-i")
        if glob_pattern:
            command.extend(["--glob", glob_pattern])
        command.extend(["-m", str(limit), pattern, str(path)])
        completed = subprocess.run(
            command,
            cwd=self.root_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode not in (0, 1):
            raise RuntimeError(completed.stderr.strip() or "ripgrep failed")
        return completed.stdout.strip()

    def _run_python(
        self,
        *,
        pattern: str,
        path: Path,
        glob_pattern: str | None,
        limit: int,
        case_sensitive: bool,
    ) -> str:
        regex = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        matches: list[str] = []
        file_iter = (
            [path]
            if path.is_file()
            else [candidate for candidate in path.rglob("*") if candidate.is_file()]
        )
        for candidate in file_iter:
            if glob_pattern and not candidate.match(glob_pattern):
                continue
            try:
                lines = candidate.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            except Exception:
                continue
            for line_number, line in enumerate(lines, start=1):
                if regex.search(line):
                    matches.append(
                        f"{candidate.relative_to(self.root_dir)}:{line_number}:{line}"
                    )
                    if len(matches) >= limit:
                        return "\n".join(matches)
        return "\n".join(matches)

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        pattern = str(kwargs["pattern"])
        path = self._resolve(kwargs.get("path"))
        glob_pattern = kwargs.get("glob")
        limit = max(1, int(kwargs.get("limit", 200)))
        case_sensitive = bool(kwargs.get("case_sensitive", True))
        output = self._run_rg(
            pattern=pattern,
            path=path,
            glob_pattern=glob_pattern,
            limit=limit,
            case_sensitive=case_sensitive,
        )
        if output is None:
            output = self._run_python(
                pattern=pattern,
                path=path,
                glob_pattern=glob_pattern,
                limit=limit,
                case_sensitive=case_sensitive,
            )
        return ToolOutput(
            text=output or "No matches found.",
            metadata={
                "pattern": pattern,
                "path": str(path),
                "glob": glob_pattern,
                "limit": limit,
                "case_sensitive": case_sensitive,
            },
        )
