from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import OPEN_URL_PROMPT

logger = logging.getLogger(__name__)


class URLNotAllowedError(ValueError):
    """Raised when a requested URL fails the SSRF / scheme guard."""


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if ``ip`` is a private/loopback/link-local/reserved address.

    169.254.0.0/16 (and the IPv6 link-local equivalent) is the cloud-metadata
    range; ``is_link_local`` already covers it but we keep the explicit check
    for clarity and defence in depth.
    """
    link_local_v4 = ipaddress.ip_network("169.254.0.0/16")
    if isinstance(ip, ipaddress.IPv4Address) and ip in link_local_v4:
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


# A realistic desktop Chrome UA — many sites 503/403 minimal clients.
_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


class _TextExtractor(HTMLParser):
    """Extract the main content of a page as readable markdown.

    Uses a real parser (not a regex tag filter) so malformed or nested
    ``<script>`` tags can't slip executable text into the output (clears
    CodeQL ``py/bad-tag-filter``). Unlike a flat tag-strip, this preserves
    structure — headings become ``#``, list items ``-``, paragraphs are
    separated by blank lines — and drops chrome (nav, header, footer, aside,
    forms) so the model reads the article, not the site furniture.
    """

    _SKIP = {
        "script", "style", "head", "noscript", "template", "svg",
        # site chrome — rarely the answer, always context cost
        "nav", "header", "footer", "aside", "form", "button", "iframe",
    }
    _BLOCK = {"p", "div", "section", "article", "br", "tr", "blockquote", "pre"}
    _HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._pending_prefix = ""

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self._HEADINGS:
            self._parts.append("\n\n")
            self._pending_prefix = "#" * int(tag[1]) + " "
        elif tag == "li":
            self._parts.append("\n")
            self._pending_prefix = "- "
        elif tag in self._BLOCK:
            self._parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data.strip():
            return
        if self._pending_prefix:
            self._parts.append(self._pending_prefix)
            self._pending_prefix = ""
        self._parts.append(data)

    def markdown(self) -> str:
        raw = "".join(self._parts)
        # Collapse runs of blank lines and trailing spaces into tidy markdown.
        lines = [re.sub(r"[ \t]+", " ", ln).rstrip() for ln in raw.splitlines()]
        out: list[str] = []
        blank = 0
        for ln in lines:
            if not ln.strip():
                blank += 1
                if blank <= 1 and out:
                    out.append("")
                continue
            blank = 0
            out.append(ln.strip())
        return "\n".join(out).strip()


def _strip_html(value: str) -> str:
    """Readable markdown of a page's main content (structure preserved)."""
    # Many SPAs render a loading shell but embed the real article as hydration
    # JSON. Recover article-shaped objects generically before the HTML parser
    # intentionally drops script elements. This is based on fields, not on a
    # publisher, framework, URL, or JavaScript variable name.
    decoder = json.JSONDecoder()
    roots = []
    for match in re.finditer(r"(?:=|>)\s*(\{)", value or ""):
        try:
            candidate, _ = decoder.raw_decode(value, match.start(1))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict):
            roots.append(candidate)
    articles: list[tuple[str, str]] = []
    stack = list(roots)
    while stack:
        candidate = stack.pop()
        if isinstance(candidate, dict):
            body = candidate.get("articleBody") or candidate.get("body")
            title = candidate.get("headline") or candidate.get("title") or ""
            if isinstance(body, str) and len(body.strip()) >= 160:
                articles.append((str(title), body))
            stack.extend(candidate.values())
        elif isinstance(candidate, list):
            stack.extend(candidate)
    if articles:
        title, body = max(articles, key=lambda item: len(item[1]))
        value = (f"<h1>{title}</h1>" if title else "") + body

    parser = _TextExtractor()
    try:
        parser.feed(value or "")
        parser.close()
        cleaned = parser.markdown()
        if cleaned:
            return cleaned
    except Exception:
        pass
    # Conservative fallback: blanket-strip every tag and unescape entities.
    cleaned = unescape(re.sub(r"<[^>]+>", " ", value or ""))
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
        allow_private_hosts: bool = False,
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
        self.allow_private_hosts = bool(allow_private_hosts)

    # ------------------------------------------------------------------ #
    #  SSRF guard
    # ------------------------------------------------------------------ #

    def _validate_url(self, url: str) -> None:
        """Reject non-http(s) schemes and URLs that resolve to internal hosts.

        This blocks ``file://`` (local file read) and SSRF against private,
        loopback, link-local (cloud metadata, 169.254.0.0/16), reserved, and
        multicast addresses. Set ``allow_private_hosts=True`` on the tool to
        bypass this guard for trusted internal usage.

        NOTE: validation happens on the *original* URL only. A server that
        returns an HTTP redirect to an internal address can still be reached
        after this check passes (TOCTOU on redirect-following); fully closing
        that gap would require intercepting each redirect hop.
        """
        if self.allow_private_hosts:
            return

        parts = urlsplit(url)
        scheme = (parts.scheme or "").lower()
        # Scheme check first — this rejects file://, ftp://, gopher://, etc.
        # before any DNS resolution happens.
        if scheme not in ("http", "https"):
            raise URLNotAllowedError(
                f"Only http/https URLs are allowed (got scheme '{scheme or 'none'}')"
            )
        host = parts.hostname
        if not host:
            raise URLNotAllowedError("URL has no host")

        # Resolve the hostname to every address it maps to and block if ANY
        # of them is internal (a host can resolve to several addresses).
        try:
            infos = socket.getaddrinfo(host, parts.port or None, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise URLNotAllowedError(f"Could not resolve host '{host}': {exc}") from exc

        for info in infos:
            sockaddr = info[4]
            try:
                ip = ipaddress.ip_address(sockaddr[0])
            except ValueError:
                continue
            if _ip_is_blocked(ip):
                raise URLNotAllowedError(
                    f"Host '{host}' resolves to a blocked address ({ip}); "
                    "private/loopback/link-local/reserved hosts are not allowed"
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
                        "url": {"type": "string", "description": "URL to open"},
                        "max_chars": {
                            "type": "number",
                            "description": "Optional max output length",
                        },
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
        from shipit_agent.tools._playwright import run_playwright_sync

        def _do_fetch() -> tuple[str, str, dict]:
            from playwright.sync_api import (
                sync_playwright,
            )  # local import — optional dep

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
                    response = page.goto(
                        url, wait_until=self.wait_until, timeout=timeout_ms
                    )
                    status = response.status if response is not None else None
                    if status is not None and status >= 400:
                        raise RuntimeError(f"HTTP {status} from {url}")

                    # A SPA often has only a loading shell at DOMContentLoaded.
                    # Give its network/render pass a bounded chance to settle
                    # before reading the body; never make network-idle a hard
                    # requirement because analytics can keep connections open.
                    try:
                        page.wait_for_load_state(
                            "networkidle", timeout=min(timeout_ms, 10_000)
                        )
                    except Exception:
                        pass

                    # Prefer visible body text; fall back to full rendered HTML.
                    try:
                        text = page.evaluate(
                            "() => document.body && document.body.innerText || ''"
                        )
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

        return run_playwright_sync(_do_fetch)

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
        return (
            text,
            title,
            {
                "fetch_method": "urllib",
                "status_code": status,
                "final_url": final_url,
                "title": title,
            },
        )

    # ------------------------------------------------------------------ #
    #  Entry point
    # ------------------------------------------------------------------ #

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        url = str(kwargs["url"]).strip()
        max_chars = int(kwargs.get("max_chars", self.max_chars))

        # SSRF / scheme guard — applied once, before either fetch path, so it
        # covers both the Playwright and the urllib backends.
        try:
            self._validate_url(url)
        except URLNotAllowedError as exc:
            return ToolOutput(
                text=f"Error: refusing to fetch {url} — {exc}",
                metadata={"url": url, "error": str(exc), "blocked": True},
            )

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
