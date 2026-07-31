"""Tests for DeepResearchTool — multi-angle sweep, dedupe, digest shape."""

from __future__ import annotations

from types import SimpleNamespace as ns

from shipit_agent.tools import DeepResearchTool
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.research_brief.research_brief_tool import _NetError

CTX = ToolContext(prompt="", system_prompt="", state={})


def _src(url, title="t", snippet="s"):
    return ns(url=url, title=title, snippet=snippet)


def _tool(search_results, pages=None, fail_fetch=()):
    tool = DeepResearchTool(max_sources=6, fetch_top=3)
    calls = {"queries": []}

    def fake_search(query, limit):
        calls["queries"].append(query)
        return search_results.get(query, search_results.get("*", []))

    def fake_fetch(url):
        if url in fail_fetch:
            raise _NetError("blocked")
        return (pages or {}).get(url, f"content of {url} " * 30)

    tool._brief._search = fake_search
    tool._brief._fetch = fake_fetch
    return tool, calls


class TestSweep:
    def test_default_angles_and_dedupe(self) -> None:
        tool, calls = _tool({"*": [_src("https://a.com"), _src("https://b.com")]})
        out = tool.run(CTX, topic="vector databases")
        assert out.metadata["ok"] is True
        # four default angles swept
        assert len(calls["queries"]) == 4
        assert calls["queries"][0] == "vector databases"
        assert "limitations" in calls["queries"][2]
        # same URLs from every angle → deduped to 2
        assert out.metadata["source_urls"] == ["https://a.com", "https://b.com"]

    def test_explicit_queries_override(self) -> None:
        tool, calls = _tool({"*": [_src("https://x.com")]})
        tool.run(CTX, topic="t", queries=["only this query"])
        assert calls["queries"] == ["only this query"]

    def test_digest_structure(self) -> None:
        tool, _ = _tool(
            {"*": [_src("https://a.com", title="Alpha", snippet="the alpha site")]},
            pages={"https://a.com": "Alpha page body text here."},
        )
        out = tool.run(CTX, topic="alpha")
        text = out.text
        assert "# Deep research digest: alpha" in text
        assert "## Query angles swept" in text
        assert "[1] Alpha" in text
        assert "Alpha page body text here." in text
        assert "Cite sources inline as [n]" in text

    def test_fetch_failure_is_inline_not_fatal(self) -> None:
        tool, _ = _tool(
            {"*": [_src("https://bad.com"), _src("https://good.com")]},
            fail_fetch=("https://bad.com",),
        )
        out = tool.run(CTX, topic="t")
        assert out.metadata["ok"] is True
        assert "(fetch failed: blocked)" in out.text

    def test_no_sources_reports_cleanly(self) -> None:
        tool, _ = _tool({"*": []})
        out = tool.run(CTX, topic="nothing")
        assert out.metadata["ok"] is False

    def test_missing_topic(self) -> None:
        tool, _ = _tool({"*": []})
        assert tool.run(CTX).metadata["ok"] is False

    def test_in_builtin_catalogue(self) -> None:
        from shipit_agent.builtins import get_builtin_tools

        names = [t.name for t in get_builtin_tools(project_root=".")]
        assert "deep_research" in names
