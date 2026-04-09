from __future__ import annotations

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.web_search.providers import SearchProvider, build_search_provider
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
    ) -> None:
        self.provider = build_search_provider(provider, api_key=api_key, config=provider_config)
        self.provider_name = getattr(
            self.provider,
            "name",
            provider if isinstance(provider, str) else "custom",
        )
        self.name = name
        self.description = description
        self.prompt = prompt or WEB_SEARCH_PROMPT
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
                        "max_results": {"type": "number", "description": "Maximum results", "default": 5},
                    },
                    "required": ["query"],
                },
            },
        }

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        query = str(kwargs["query"]).strip()
        max_results = int(kwargs.get("max_results", 5))
        results = self.provider.search(query, max_results=max_results)
        lines = []
        for index, result in enumerate(results, start=1):
            lines.append(
                f"[{index}] {result.get('title', 'Untitled')}\n"
                f"{result.get('snippet', '')}\n"
                f"URL: {result.get('url', '')}"
            )
        return ToolOutput(
            text="\n\n".join(lines) if lines else "No results found.",
            metadata={"query": query, "results": results, "provider": self.provider_name},
        )
