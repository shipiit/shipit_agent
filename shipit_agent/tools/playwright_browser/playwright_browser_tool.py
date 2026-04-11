from __future__ import annotations

import re
from html import unescape

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools._playwright import run_playwright_sync
from .prompt import PLAYWRIGHT_BROWSER_PROMPT


class PlaywrightBrowserTool:
    def __init__(
        self,
        *,
        name: str = "playwright_browse",
        description: str = "Use Playwright to open a page and return the rendered text content.",
        prompt: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or PLAYWRIGHT_BROWSER_PROMPT
        self.prompt_instructions = "Use this when JavaScript rendering matters or basic HTTP fetch is insufficient."

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Page URL"},
                    },
                    "required": ["url"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        url = str(kwargs["url"]).strip()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return ToolOutput(
                text=f"Playwright is not installed for {url}",
                metadata={"url": url, "driver": "playwright", "implemented": False},
            )

        try:

            def _run() -> str:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.goto(url, wait_until="networkidle")
                    content = page.content()
                    browser.close()
                    return content

            content = run_playwright_sync(_run)
        except Exception as exc:
            return ToolOutput(
                text=f"Playwright could not open {url}: {exc}",
                metadata={
                    "url": url,
                    "driver": "playwright",
                    "implemented": False,
                    "error": str(exc),
                },
            )

        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(content))).strip()
        return ToolOutput(
            text=text[:4000],
            metadata={"url": url, "driver": "playwright", "implemented": True},
        )
