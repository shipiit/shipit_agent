import asyncio
import threading
import time

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
    assert isinstance(
        build_search_provider("serper", api_key="x"), SerperSearchProvider
    )
    assert isinstance(
        build_search_provider("tavily", api_key="x"), TavilySearchProvider
    )


def test_web_search_runs_multiple_queries_in_parallel_and_deduplicates() -> None:
    class ParallelProvider:
        name = "parallel-test"

        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def search(self, query: str, max_results: int = 5):
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.02)
            with self.lock:
                self.active -= 1
            return [
                {
                    "title": f"Result for {query}",
                    "url": "https://example.com/shared",
                    "snippet": query,
                }
            ]

    provider = ParallelProvider()
    tool = WebSearchTool(provider=provider)

    output = tool.run(None, queries=["alpha", "beta", "alpha"], max_results=3)

    assert provider.max_active == 2
    assert output.metadata["queries"] == ["alpha", "beta"]
    assert output.metadata["parallel"] is True
    assert len(output.metadata["results"]) == 1
    assert output.metadata["results"][0]["matched_queries"] == ["alpha", "beta"]


def test_web_search_batch_isolates_query_failures() -> None:
    class PartialProvider:
        name = "partial-test"

        def search(self, query: str, max_results: int = 5):
            if query == "broken":
                raise TimeoutError("search timed out")
            return [{"title": "Good", "url": "https://good.test", "snippet": "ok"}]

    output = WebSearchTool(provider=PartialProvider()).run(
        None, queries=["working", "broken"]
    )

    assert len(output.metadata["results"]) == 1
    assert output.metadata["errors"] == {"broken": "search timed out"}
    assert "[search failed] broken" in output.text


def test_web_search_rejects_empty_query_input() -> None:
    output = WebSearchTool(provider="duckduckgo").run(None)
    assert output.metadata["ok"] is False
    assert output.metadata["error"] == "missing_argument"
