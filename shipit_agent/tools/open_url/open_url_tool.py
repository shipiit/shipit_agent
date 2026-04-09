from __future__ import annotations

import logging
import re
from html import unescape

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import OPEN_URL_PROMPT

logger = logging.getLogger(__name__)


# A realistic desktop Chrome UA — many sites 503/403 minimal clients.
_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def _strip_html(value: str) -> str:
    cleaned = re.sub(r"<script[\s\S]*?</script>", " ", value or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"<style[\s\S]*?</style>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


class OpenURLTool:
    """Fetch a URL and return clean text.

    Primary path: **Playwright (Chromium) in-process** — handles JS-rendered
    pages, modern TLS/ALPN, and anti-bot protections that reject minimal HTTP
    clients with HTTP 503.

    Fallback path: stdlib ``urllib`` — used only if Playwright is not installed
    or the browser binary is missing. No third-party HTTP libraries involved.
    """

    def __init__(
        self,
        *,
        name: str = "open_url",
        description: str = "Fetch a URL and return a clean text excerpt.",
        prompt: str | None = None,
        timeout: float = 30.0,
        max_chars: int = 4000,
        user_agent: str = _DEFAULT_UA,
        headless: bool = True,
        wait_until: str = "domcontentloaded",
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
        self.headless = headless
        self.wait_until = wait_until

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

    # ------------------------------------------------------------------ #
    #  Fetch paths
    # ------------------------------------------------------------------ #

    def _fetch_via_playwright(self, url: str) -> tuple[str, str, dict]:
        """Returns (text, page_title, metadata). Raises on failure."""
        from playwright.sync_api import sync_playwright  # local import — optional dep

        timeout_ms = int(self.timeout * 1000)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            try:
                context = browser.new_context(
                    user_agent=self.user_agent,
                    viewport={"width": 1280, "height": 800},
                    locale="en-US",
                )
                page = context.new_page()
                response = page.goto(url, wait_until=self.wait_until, timeout=timeout_ms)
                status = response.status if response is not None else None
                if status is not None and status >= 400:
                    raise RuntimeError(f"HTTP {status} from {url}")

                # Prefer visible body text; fall back to full rendered HTML.
                try:
                    text = page.evaluate("() => document.body && document.body.innerText || ''")
                except Exception:
                    text = ""
                if not text:
                    text = _strip_html(page.content())

                title = ""
                try:
                    title = page.title() or ""
                except Exception:
                    pass

                metadata = {
                    "fetch_method": "playwright",
                    "status_code": status,
                    "final_url": page.url,
                    "title": title,
                }
                return text, title, metadata
            finally:
                browser.close()

    def _fetch_via_urllib(self, url: str) -> tuple[str, str, dict]:
        """Stdlib fallback. Raises on failure."""
        from urllib.request import Request, urlopen

        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urlopen(request, timeout=self.timeout) as response:  # nosec B310
            raw = response.read().decode("utf-8", errors="replace")
            final_url = response.geturl()
            status = response.status
        text = _strip_html(raw)
        title_match = re.search(r"<title[^>]*>([\s\S]*?)</title>", raw, re.IGNORECASE)
        title = _strip_html(title_match.group(1)) if title_match else ""
        return text, title, {
            "fetch_method": "urllib",
            "status_code": status,
            "final_url": final_url,
            "title": title,
        }

    # ------------------------------------------------------------------ #
    #  Entry point
    # ------------------------------------------------------------------ #

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        url = str(kwargs["url"]).strip()
        max_chars = int(kwargs.get("max_chars", self.max_chars))

        errors: list[str] = []
        text: str = ""
        title: str = ""
        metadata: dict = {"url": url, "max_chars": max_chars}

        # Try Playwright first
        try:
            text, title, meta = self._fetch_via_playwright(url)
            metadata.update(meta)
        except ImportError:
            errors.append("playwright not installed — using urllib fallback")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"playwright failed: {exc}")
            logger.warning("open_url: Playwright fetch failed for %s: %s", url, exc)

        # Fallback to urllib if Playwright produced nothing
        if not text:
            try:
                text, title, meta = self._fetch_via_urllib(url)
                metadata.update(meta)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"urllib failed: {exc}")
                logger.error("open_url: urllib fetch failed for %s: %s", url, exc)

        if not text:
            joined = " | ".join(errors) or "unknown error"
            return ToolOutput(
                text=f"Error: could not fetch {url} — {joined}",
                metadata={**metadata, "error": joined},
            )

        text = text[:max_chars]
        if errors:
            metadata["warnings"] = errors
        return ToolOutput(text=text, metadata=metadata)
