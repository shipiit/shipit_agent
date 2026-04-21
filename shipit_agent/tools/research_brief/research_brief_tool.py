"""`research_brief` — produce a structured research brief from a topic.

Composes three primitives every agent needs for fast research:

  1. ``web_search`` for a query (caller-supplied backend, or DuckDuckGo HTML).
  2. ``open_url`` on the top N results (or ``urllib`` fallback).
  3. Summary section listing sources with a 1-line takeaway each.

Rather than being "yet another chain", this is a *single tool call* the
model can make — which matters because chains burn tokens re-learning
the shape of the composition every turn.

Intended for the **Researcher**, **Product Manager**, **Marketing
Writer**, and **Sales Outreach** personas — any role where "find what's
true about X in 5 minutes" is the core skill.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput


@dataclass(slots=True)
class _Source:
    url: str
    title: str
    snippet: str


class ResearchBriefTool:
    name = "research_brief"
    description = "Search the web for a topic, skim top pages, return a structured brief with sources."
    prompt_instructions = (
        "Use research_brief when you need fresh facts: industry news, competitor moves, "
        "public company stats. It searches the web, opens the top pages, and returns a "
        "brief with citations. For private-data lookups use the target-specific tool "
        "(hubspot_ops, notion, etc.)."
    )

    def __init__(self, *, user_agent: str | None = None) -> None:
        self.user_agent = user_agent or (
            "Mozilla/5.0 (compatible; shipit-agent/1.0; +https://docs.shipiit.com/)"
        )
        self.prompt = self.prompt_instructions

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query":       {"type": "string", "description": "Research topic / question."},
                        "max_sources": {"type": "integer", "default": 5},
                        "deep":        {"type": "boolean", "default": False, "description": "Fetch each source for a deeper summary."},
                    },
                    "required": ["query"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return ToolOutput(text="Error: `query` is required.", metadata={"ok": False})
        max_sources = max(1, min(10, int(kwargs.get("max_sources", 5))))
        deep = bool(kwargs.get("deep", False))

        try:
            sources = self._search(query, max_sources)
        except _NetError as err:
            return ToolOutput(
                text=f"Error: could not search ({err}). "
                     "If you have an API-backed web_search tool, prefer it.",
                metadata={"ok": False},
            )

        if deep:
            for s in sources:
                try:
                    page = self._fetch(s.url)
                    s.snippet = (s.snippet + "\n" + self._summarize(page)).strip()
                except _NetError:
                    continue

        brief = _format_brief(query, sources)
        return ToolOutput(text=brief, metadata={"ok": True, "sources": [s.url for s in sources]})

    # ── search + fetch ──────────────────────────────────────────

    def _search(self, query: str, limit: int) -> list[_Source]:
        """Tiny DuckDuckGo HTML scraper — works without an API key.

        For production use, swap this for a real SERP API (Brave, SerpAPI,
        Google CSE). The class is intentionally structured so the caller
        can subclass and override ``_search``.
        """
        url = "https://duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        html_text = self._fetch(url)
        sources: list[_Source] = []
        for m in _RESULT_RE.finditer(html_text):
            raw_url = html.unescape(m.group("url"))
            title = html.unescape(_strip_tags(m.group("title"))).strip()
            snippet = html.unescape(_strip_tags(m.group("snippet") or "")).strip()
            if raw_url.startswith("//"):
                raw_url = "https:" + raw_url
            if not raw_url.startswith("http"):
                continue
            sources.append(_Source(url=raw_url, title=title, snippet=snippet))
            if len(sources) >= limit:
                break
        return sources

    def _fetch(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read(2_000_000)  # cap at 2MB to avoid runaway pages
        except Exception as err:  # noqa: BLE001
            raise _NetError(str(err)) from err
        # Tolerate non-UTF-8 gracefully.
        try:
            return raw.decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            return raw.decode("latin-1", "ignore")

    @staticmethod
    def _summarize(page_html: str) -> str:
        """Extract the first ~600 chars of readable text from a page."""
        text = _strip_tags(page_html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:600]


# ── helpers ─────────────────────────────────────────────────────


_RESULT_RE = re.compile(
    r'<a rel="nofollow" class="result__a" href="(?P<url>[^"]+)">(?P<title>.*?)</a>'
    r'.*?<a class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL,
)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(s: str) -> str:
    return _TAG_RE.sub("", s)


def _format_brief(query: str, sources: list[_Source]) -> str:
    if not sources:
        return f"Research brief — {query}\n\n(no sources found)"
    lines = [f"Research brief — {query}", ""]
    for i, s in enumerate(sources, 1):
        title = s.title or s.url
        lines.append(f"[{i}] {title}")
        lines.append(f"    {s.url}")
        if s.snippet:
            snippet = s.snippet.replace("\n", " ")
            lines.append(f"    {snippet[:400]}")
        lines.append("")
    lines.append("Citation format: [1], [2], … as used above.")
    return "\n".join(lines)


class _NetError(RuntimeError):
    pass
