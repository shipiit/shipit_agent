from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.web_search.providers import (
    SearchProvider,
    build_search_provider,
)
from .prompt import WEB_SEARCH_PROMPT


class WebSearchTool:
    def __init__(
        self,
        *,
        provider: str | SearchProvider | None = None,
        api_key: str | None = None,
        provider_config: dict | None = None,
        name: str = "web_search",
        description: str = "Search the web and return structured search results.",
        prompt: str | None = None,
        max_queries: int = 4,
        max_workers: int = 4,
    ) -> None:
        self.provider = build_search_provider(
            provider, api_key=api_key, config=provider_config
        )
        self.provider_name = getattr(
            self.provider,
            "name",
            provider if isinstance(provider, str) else "custom",
        )
        self.name = name
        self.description = description
        self.prompt = prompt or WEB_SEARCH_PROMPT
        self.max_queries = max(1, int(max_queries))
        self.max_workers = max(1, int(max_workers))
        self.prompt_instructions = (
            "Use this for current information, discovery, and source gathering. "
            "After finding promising sources, use open_url for deeper reading."
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
                        "query": {"type": "string", "description": "Search query"},
                        "queries": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": self.max_queries,
                            "description": (
                                "Independent targeted queries to run concurrently. "
                                "Use query or queries, not both."
                            ),
                        },
                        "max_results": {
                            "type": "number",
                            "description": "Maximum results",
                            "default": 5,
                        },
                    },
                    "required": [],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        raw_queries = kwargs.get("queries")
        if raw_queries is None:
            raw_queries = [kwargs.get("query", "")]
        if not isinstance(raw_queries, list):
            raw_queries = [raw_queries]
        queries = list(
            dict.fromkeys(
                str(query).strip() for query in raw_queries if str(query).strip()
            )
        )[: self.max_queries]
        if not queries:
            return ToolOutput(
                text="Provide a non-empty `query` or `queries` list.",
                metadata={
                    "ok": False,
                    "error": "missing_argument",
                    "argument": "query",
                    "results": [],
                },
            )

        max_results = max(1, min(int(kwargs.get("max_results", 5)), 10))
        by_query: dict[str, list[dict]] = {}
        errors: dict[str, str] = {}
        if len(queries) == 1:
            by_query[queries[0]] = self.provider.search(
                queries[0], max_results=max_results
            )
        else:
            with ThreadPoolExecutor(
                max_workers=min(self.max_workers, len(queries))
            ) as pool:
                futures = {
                    pool.submit(
                        self.provider.search, query, max_results=max_results
                    ): query
                    for query in queries
                }
                for future in as_completed(futures):
                    query = futures[future]
                    try:
                        by_query[query] = future.result()
                    except Exception as exc:
                        errors[query] = str(exc)

        results: list[dict] = []
        by_url: dict[str, dict] = {}
        for query in queries:
            for raw_result in by_query.get(query, []):
                result = dict(raw_result)
                result["matched_queries"] = [query]
                url = str(result.get("url", ""))
                if url and url in by_url:
                    by_url[url]["matched_queries"].append(query)
                    continue
                results.append(result)
                if url:
                    by_url[url] = result
        lines = []
        for index, result in enumerate(results, start=1):
            matched = ", ".join(result.get("matched_queries", []))
            lines.append(
                f"[{index}] {result.get('title', 'Untitled')}\n"
                f"{result.get('snippet', '')}\n"
                f"URL: {result.get('url', '')}\n"
                f"Matched query: {matched}"
            )
        for query, error in errors.items():
            lines.append(f"[search failed] {query}: {error}")
        return ToolOutput(
            text="\n\n".join(lines) if lines else "No results found.",
            metadata={
                "query": queries[0] if len(queries) == 1 else None,
                "queries": queries,
                "results": results,
                "results_by_query": by_query,
                "errors": errors,
                "parallel": len(queries) > 1,
                "provider": self.provider_name,
                "ok": bool(results) or not errors,
            },
        )
