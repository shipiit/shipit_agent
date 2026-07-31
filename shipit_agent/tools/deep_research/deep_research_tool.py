"""`deep_research` — multi-angle research sweep in a single tool call.

Where `research_brief` runs ONE query, this fans out several query angles
(overview, comparison, limitations, recency), searches each, dedupes the
combined sources, fetches the top pages (scheme-guarded), and returns a
structured, citation-ready digest the model synthesizes from. One call
replaces the search→open→search→open crawl that burns iterations.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.formatting import clip_text
from shipit_agent.tools.research_brief.research_brief_tool import (
    ResearchBriefTool,
    _NetError,
)

_ANGLES = [
    "{topic}",
    "{topic} comparison alternatives",
    "{topic} limitations problems criticism",
    "{topic} latest 2026",
]


class DeepResearchTool:
    name = "deep_research"
    description = (
        "Deep multi-angle research: several search queries, deduped sources, "
        "top pages fetched — returns a structured digest with citations."
    )

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        max_sources: int = 8,
        fetch_top: int = 4,
        per_page_chars: int = 3000,
    ) -> None:
        # Compose the battle-tested single-query machinery (search backend,
        # SSRF-guarded fetch, HTML→text) instead of re-implementing it.
        self._brief = ResearchBriefTool(user_agent=user_agent)
        self.max_sources = max_sources
        self.fetch_top = fetch_top
        self.per_page_chars = per_page_chars
        self.prompt = self.prompt_instructions = (
            "Use for substantial research questions where one search isn't "
            "enough — it sweeps multiple query angles and returns sources + "
            "page excerpts to synthesize WITH CITATIONS. For a quick lookup "
            "use web_search or research_brief instead."
        )

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "The research question or topic",
                        },
                        "queries": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Optional explicit query list — overrides the "
                                "default multi-angle sweep."
                            ),
                        },
                    },
                    "required": ["topic"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        topic = str(kwargs.get("topic", "")).strip()
        if not topic:
            return ToolOutput(text="deep_research: `topic` is required.",
                              metadata={"ok": False})
        queries = [str(q) for q in (kwargs.get("queries") or [])] or [
            angle.format(topic=topic) for angle in _ANGLES
        ]

        # 1. Fan out the searches; dedupe by URL, keep first-seen order.
        sources: dict[str, Any] = {}
        per_query: dict[str, list[str]] = {}
        for query in queries:
            try:
                found = self._brief._search(query, limit=self.max_sources)
            except Exception as exc:
                per_query[query] = [f"(search failed: {exc})"]
                continue
            per_query[query] = []
            for src in found:
                per_query[query].append(src.url)
                if src.url not in sources and len(sources) < self.max_sources:
                    sources[src.url] = src

        if not sources:
            return ToolOutput(
                text="deep_research: no sources found for any query angle.",
                metadata={"ok": False, "queries": queries},
            )

        # 2. Fetch the top pages (scheme-guarded by the brief's fetcher).
        excerpts: dict[str, str] = {}
        for url in list(sources)[: self.fetch_top]:
            try:
                page_text = self._brief._fetch(url)
                excerpts[url] = clip_text(
                    page_text, max_chars=self.per_page_chars, max_lines=80
                )
            except _NetError as exc:
                excerpts[url] = f"(fetch failed: {exc})"
            except Exception as exc:
                excerpts[url] = f"(fetch failed: {exc})"

        # 3. Assemble the digest.
        lines = [f"# Deep research digest: {topic}", ""]
        lines.append("## Query angles swept")
        for query in queries:
            lines.append(f"- {query} ({len(per_query.get(query, []))} hits)")
        lines.append("")
        lines.append(f"## Sources ({len(sources)} deduped)")
        for i, (url, src) in enumerate(sources.items(), 1):
            title = getattr(src, "title", "") or url
            snippet = getattr(src, "snippet", "")
            lines.append(f"[{i}] {title}\n    {url}")
            if snippet:
                lines.append(f"    {snippet[:200]}")
        lines.append("")
        lines.append("## Page excerpts (top sources)")
        for i, (url, excerpt) in enumerate(excerpts.items(), 1):
            lines.append(f"### [{i}] {url}")
            lines.append(excerpt)
            lines.append("")
        lines.append(
            "## Instructions\nSynthesize an answer from the excerpts above. "
            "Cite sources inline as [n] using the numbering here. Note "
            "disagreements between sources explicitly."
        )
        return ToolOutput(
            text="\n".join(lines),
            metadata={
                "ok": True,
                "topic": topic,
                "queries": queries,
                "source_urls": list(sources),
                "fetched": list(excerpts),
            },
        )
