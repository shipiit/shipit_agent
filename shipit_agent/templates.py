from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PromptTemplate:
    """Renders prompt templates with {variable.path} references.

    Supports nested dot-path access: {payload.pull_request.title}
    resolves to payload["pull_request"]["title"].
    """

    template: str

    def render(self, **context: Any) -> str:
        def _replacer(match: re.Match[str]) -> str:
            path = match.group(1)
            parts = path.split(".")
            value: Any = context
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part, match.group(0))
                    if value is match.group(0):
                        return value
                else:
                    return match.group(0)
            return str(value)

        return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}", _replacer, self.template)

    def variables(self) -> list[str]:
        return re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}", self.template)
