import asyncio
import threading

from shipit_agent import (
    DuckDuckGoSearchProvider,
    PlaywrightBrowserTool,
    SerperSearchProvider,
    TavilySearchProvider,
    WebSearchTool,
    build_search_provider,
)
from shipit_agent.tools._playwright import run_playwright_sync


def test_run_playwright_sync_runs_inline_without_event_loop() -> None:
    thread_id = threading.get_ident()

    def task() -> int:
        return threading.get_ident()

    assert run_playwright_sync(task) == thread_id


def test_run_playwright_sync_uses_worker_thread_with_running_loop() -> None:
    outer_thread_id = threading.get_ident()

    async def runner() -> int:
        return run_playwright_sync(threading.get_ident)

    worker_thread_id = asyncio.run(runner())
    assert worker_thread_id != outer_thread_id


def test_playwright_browser_tool_returns_fallback_or_real_metadata() -> None:
    tool = PlaywrightBrowserTool()
    result = tool.run(context=None, url="https://example.com")  # type: ignore[arg-type]
    assert result.metadata["driver"] == "playwright"
    assert "implemented" in result.metadata


def test_web_search_defaults_to_duckduckgo_provider() -> None:
    tool = WebSearchTool()
    assert tool.provider_name == "duckduckgo"
    assert isinstance(tool.provider, DuckDuckGoSearchProvider)


def test_build_search_provider_supports_duckduckgo() -> None:
    provider = build_search_provider("duckduckgo")
    assert isinstance(provider, DuckDuckGoSearchProvider)


def test_build_search_provider_requires_keys_for_remote_apis() -> None:
    try:
        build_search_provider("serper")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError for missing Serper key")


def test_build_search_provider_accepts_remote_api_keys() -> None:
    assert isinstance(build_search_provider("serper", api_key="x"), SerperSearchProvider)
    assert isinstance(build_search_provider("tavily", api_key="x"), TavilySearchProvider)
