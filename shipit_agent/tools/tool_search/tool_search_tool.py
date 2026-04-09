from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import TOOL_SEARCH_PROMPT


class ToolSearchTool:
    """Semantic-ish tool discovery for agents with many available tools.

    Given a plain-language query, ranks every tool currently registered on
    the agent by how well it matches, and returns the top-N with descriptions.
    This solves two real problems that hit any agent with more than a handful
    of tools:

    1. **Token bloat** — every turn sends the full tool catalog to the LLM.
       With `tool_search` the model can ask for a shortlist first, then call
       the right tool with only a few relevant schemas in mind.
    2. **Tool hallucination** — when many similar tools exist, models often
       invent tool names or pick the wrong one. A ranked shortlist grounds
       the decision in actual registered tools.

    Scoring (from drk_cache's implementation):
        score = SequenceMatcher(query, haystack).ratio() + 0.12 * token_hits
    where ``haystack`` concatenates the tool name, description, and
    prompt_instructions, and ``token_hits`` counts how many query words
    appear literally in the haystack. Tie-break by insertion order.

    Pure stdlib — no embeddings, no external services, no API keys.
    """

    def __init__(
        self,
        *,
        name: str = "tool_search",
        description: str = (
            "Search the current agent's available tools and return a ranked "
            "shortlist of the best matches for a task. Use this when many "
            "tools are available and you want to confirm the right one before "
            "calling it."
        ),
        prompt: str | None = None,
        max_limit: int = 10,
        default_limit: int = 5,
        token_bonus: float = 0.12,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or TOOL_SEARCH_PROMPT
        self.prompt_instructions = (
            "Use this when many tools are available and you need to identify "
            "the right one before acting. Pass a plain-language query "
            "describing what you want to do."
        )
        self.max_limit = max_limit
        self.default_limit = default_limit
        self.token_bonus = token_bonus

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What you are trying to do, in plain language.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": (
                                f"Maximum number of matching tools to return "
                                f"(1-{self.max_limit}, default {self.default_limit})."
                            ),
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    # ------------------------------------------------------------------ #

    def _score(self, query_lower: str, query_tokens: list[str], haystack: str) -> float:
        ratio = SequenceMatcher(None, query_lower, haystack).ratio()
        token_hits = sum(1 for token in query_tokens if token and token in haystack)
        return round(ratio + (self.token_bonus * token_hits), 4)

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        query_text = str(kwargs.get("query", "") or "").strip()
        if not query_text:
            return ToolOutput(
                text="Error: `query` is required. Describe what you are trying to do.",
                metadata={"error": "empty_query", "matches": []},
            )

        # Clamp limit to [1, max_limit].
        try:
            limit = int(kwargs.get("limit") or self.default_limit)
        except (TypeError, ValueError):
            limit = self.default_limit
        limit = max(1, min(limit, self.max_limit))

        tools = context.state.get("available_tools", []) or []
        if not tools:
            return ToolOutput(
                text="No tools are currently registered on this agent.",
                metadata={"query": query_text, "matches": []},
            )

        query_lower = query_text.lower()
        query_tokens = [t for t in query_lower.split() if t]

        scored: list[dict[str, Any]] = []
        for tool in tools:
            name = str(tool.get("name", "") or "")
            description = str(tool.get("description", "") or "")
            instructions = str(tool.get("prompt_instructions", "") or "")
            haystack = f"{name} {description} {instructions}".lower()
            score = self._score(query_lower, query_tokens, haystack)
            scored.append({
                "name": name,
                "description": description,
                "prompt_instructions": instructions,
                "score": score,
            })

        scored.sort(key=lambda item: item["score"], reverse=True)
        matches = scored[:limit]

        # Drop matches with zero-ish scores — they're noise.
        meaningful = [m for m in matches if m["score"] > 0.05]
        if not meaningful:
            return ToolOutput(
                text=f"No tools matched '{query_text}'. Try rephrasing or broadening the query.",
                metadata={"query": query_text, "matches": matches},
            )

        lines = [f"Best tools for '{query_text}' (ranked by relevance):"]
        for idx, match in enumerate(meaningful, start=1):
            desc = match["description"] or "No description provided."
            lines.append(
                f"{idx}. {match['name']} (score={match['score']}) — {desc}"
            )
            if match["prompt_instructions"]:
                lines.append(f"   ↳ when to use: {match['prompt_instructions']}")

        return ToolOutput(
            text="\n".join(lines),
            metadata={
                "query": query_text,
                "limit": limit,
                "total_candidates": len(tools),
                "matches": meaningful,
            },
        )
