from __future__ import annotations

import re
from html import unescape
from urllib.request import Request, urlopen

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import OPEN_URL_PROMPT


def _strip_html(value: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", value or "")
    cleaned = unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


class OpenURLTool:
    def __init__(
        self,
        *,
        name: str = "open_url",
        description: str = "Fetch a URL and return a clean text excerpt.",
        prompt: str | None = None,
        timeout: float = 15.0,
        max_chars: int = 4000,
        user_agent: str = "shipit-agent/0.1",
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or OPEN_URL_PROMPT
        self.prompt_instructions = (
            "Use this when you need exact content from a specific URL. "
            "Prefer this after search results identify a likely source."
        )
        self.timeout = timeout
        self.max_chars = max_chars
        self.user_agent = user_agent

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to open"},
                        "max_chars": {"type": "number", "description": "Optional max output length"},
                    },
                    "required": ["url"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        url = str(kwargs["url"]).strip()
        max_chars = int(kwargs.get("max_chars", self.max_chars))
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=self.timeout) as response:  # nosec B310
            raw = response.read().decode("utf-8", errors="replace")
        text = _strip_html(raw)[:max_chars]
        return ToolOutput(text=text, metadata={"url": url, "max_chars": max_chars})
