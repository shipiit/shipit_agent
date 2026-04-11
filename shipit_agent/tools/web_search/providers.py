from __future__ import annotations

import json
import re
from html import unescape
from typing import Any, Protocol
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from shipit_agent.tools._playwright import run_playwright_sync


def _strip_html(value: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", value or "")
    cleaned = unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]: ...


class DuckDuckGoSearchProvider:
    name = "duckduckgo"

    def __init__(
        self, *, timeout: float = 15.0, user_agent: str = "shipit-agent/0.1"
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=self.timeout) as response:  # nosec B310
            raw = response.read().decode("utf-8", errors="replace")

        pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
            re.DOTALL,
        )

        results: list[dict[str, Any]] = []
        for match in pattern.finditer(raw):
            results.append(
                {
                    "title": _strip_html(match.group("title")),
                    "url": unescape(match.group("url")),
                    "snippet": _strip_html(match.group("snippet")),
                }
            )
            if len(results) >= max_results:
                break
        return results


class PlaywrightSearchProvider:
    name = "playwright"

    def __init__(self, *, timeout_ms: int = 15000) -> None:
        self.timeout_ms = timeout_ms

    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Install `playwright` to use PlaywrightSearchProvider."
            ) from exc

        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"

        def _run() -> str:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                html = page.content()
                browser.close()
                return html

        html = run_playwright_sync(_run)
        return _extract_duckduckgo_results(html, max_results=max_results)


class BraveSearchProvider:
    name = "brave"

    def __init__(self, *, api_key: str, timeout: float = 15.0) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        request = Request(
            f"https://api.search.brave.com/res/v1/web/search?q={quote_plus(query)}&count={max_results}",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
                "User-Agent": "shipit-agent/0.1",
            },
        )
        with urlopen(request, timeout=self.timeout) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        results = []
        for item in payload.get("web", {}).get("results", [])[:max_results]:
            results.append(
                {
                    "title": item.get("title", "Untitled"),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                }
            )
        return results


class SerperSearchProvider:
    name = "serper"

    def __init__(self, *, api_key: str, timeout: float = 15.0) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        request = Request(
            "https://google.serper.dev/search",
            data=json.dumps({"q": query, "num": max_results}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-API-KEY": self.api_key,
                "User-Agent": "shipit-agent/0.1",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        results = []
        for item in payload.get("organic", [])[:max_results]:
            results.append(
                {
                    "title": item.get("title", "Untitled"),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                }
            )
        return results


class TavilySearchProvider:
    name = "tavily"

    def __init__(self, *, api_key: str, timeout: float = 20.0) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        request = Request(
            "https://api.tavily.com/search",
            data=json.dumps(
                {
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": False,
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "shipit-agent/0.1",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        results = []
        for item in payload.get("results", [])[:max_results]:
            results.append(
                {
                    "title": item.get("title", "Untitled"),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", ""),
                }
            )
        return results


def _extract_duckduckgo_results(raw: str, *, max_results: int) -> list[dict[str, Any]]:
    pattern = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
        re.DOTALL,
    )

    results: list[dict[str, Any]] = []
    for match in pattern.finditer(raw):
        results.append(
            {
                "title": _strip_html(match.group("title")),
                "url": unescape(match.group("url")),
                "snippet": _strip_html(match.group("snippet")),
            }
        )
        if len(results) >= max_results:
            break
    return results


def build_search_provider(
    provider: str | SearchProvider | None = None,
    *,
    api_key: str | None = None,
    config: dict[str, Any] | None = None,
) -> SearchProvider:
    if provider and not isinstance(provider, str):
        return provider

    provider_name = (provider or "duckduckgo").strip().lower()
    config = config or {}

    if provider_name == "playwright":
        return PlaywrightSearchProvider(timeout_ms=int(config.get("timeout_ms", 15000)))
    if provider_name in {"duckduckgo", "ddg"}:
        return DuckDuckGoSearchProvider(
            timeout=float(config.get("timeout", 15.0)),
            user_agent=str(config.get("user_agent", "shipit-agent/0.1")),
        )
    if provider_name == "brave":
        if not api_key:
            raise ValueError("Brave search requires `api_key`.")
        return BraveSearchProvider(
            api_key=api_key, timeout=float(config.get("timeout", 15.0))
        )
    if provider_name == "serper":
        if not api_key:
            raise ValueError("Serper search requires `api_key`.")
        return SerperSearchProvider(
            api_key=api_key, timeout=float(config.get("timeout", 15.0))
        )
    if provider_name == "tavily":
        if not api_key:
            raise ValueError("Tavily search requires `api_key`.")
        return TavilySearchProvider(
            api_key=api_key, timeout=float(config.get("timeout", 20.0))
        )

    raise ValueError(f"Unsupported search provider: {provider_name}")
