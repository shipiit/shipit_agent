from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from .prompt import TOOL_SEARCH_PROMPT


class ToolSearchTool:
    """Lexical tool discovery for agents with many available tools.

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

    Ranking uses corpus-weighted word overlap, boosts tool-name matches,
    and prioritizes exact names. It searches descriptions, instructions,
    capability families and MCP server metadata. Ties retain catalog order.

    Pure stdlib — no embeddings, no external services, no API keys.
    """

    read_only = True

    @staticmethod
    def _tokens(text: str) -> set[str]:
        # Split camelCase and underscores while retaining Unicode words.
        text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
        return set(re.findall(r"[^\W_]+", text.casefold()))

    def __init__(
        self,
        *,
        name: str = "tool_search",
        description: str = (
            "Search the current agent's available tools and return a ranked "
            "shortlist of the best matches for a task. Use this when many "
            "tools are available and no loaded tool fits. Call an already "
            "loaded matching tool directly instead of searching again."
        ),
        prompt: str | None = None,
        max_limit: int = 10,
        default_limit: int = 5,
        token_bonus: float = 0.12,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt or TOOL_SEARCH_PROMPT.replace("tool_search", name)
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

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        query_text = str(kwargs.get("query", "") or "").strip()
        if not query_text:
            return ToolOutput(
                text="Error: `query` is required. Describe what you are trying to do.",
                metadata={"error": "empty_query", "ok": False, "matches": []},
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
        query_tokens = self._tokens(query_text)
        # Corpus-weighted word matches favour distinctive capabilities over
        # boilerplate shared by every tool. No model call or embedding cost.
        documents = [self._tokens(" ".join(
            str(tool.get(key, "") or "") for key in
            ("name", "description", "prompt_instructions", "category", "server", "discovery_terms")
        )) for tool in tools]
        frequencies = Counter(word for doc in documents for word in doc)

        scored: list[dict[str, Any]] = []
        for tool in tools:
            name = str(tool.get("name", "") or "")
            if name == self.name:
                continue
            description = str(tool.get("description", "") or "")
            instructions = str(tool.get("prompt_instructions", "") or "")
            category = str(tool.get("category", "") or "")
            connection_id = str(tool.get("connection_id", "") or "")
            connection_state = str(tool.get("connection_state", "") or "")
            server = str(tool.get("server", "") or "")
            read_only = tool.get("read_only")
            access_terms = (
                "read only"
                if read_only is True
                else "action write mutate"
                if read_only is False
                else ""
            )
            haystack = " ".join(
                (
                    name,
                    description,
                    instructions,
                    category,
                    connection_id,
                    connection_state,
                    server,
                    access_terms,
                    str(tool.get("discovery_terms", "")),
                )
            )
            words = self._tokens(haystack)
            name_words = self._tokens(name)
            score = sum(
                math.log(1 + len(tools) / (1 + frequencies[token]))
                * (3 if token in name_words else 1)
                for token in query_tokens & words
            )
            if query_lower == name.lower():
                score += 100
            scored.append(
                {
                    "name": name,
                    "description": description,
                    "prompt_instructions": instructions,
                    "category": category,
                    "read_only": read_only if isinstance(read_only, bool) else None,
                    "connection_id": connection_id,
                    "connection_state": connection_state,
                    "server": server,
                    "score": score,
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        exact = [item for item in scored if item["name"].casefold() == query_text.casefold()]
        matches = exact or scored[:limit]

        # Drop matches with zero-ish scores — they're noise.
        meaningful = [m for m in matches if m["score"] > 0.05]
        if not meaningful:
            return ToolOutput(
                text=f"No tools matched '{query_text}'. Try rephrasing or broadening the query.",
                metadata={"query": query_text, "matches": matches},
            )

        lines = [f"Best tools for '{query_text}' (ranked by relevance):"]
        for idx, match in enumerate(meaningful, start=1):
            desc = (match["description"] or "No description provided.")[:400]
            details = [match["category"]] if match["category"] else []
            if match["read_only"] is True:
                details.append("read-only")
            elif match["read_only"] is False:
                details.append("action")
            if match["server"]:
                details.append(f"MCP: {match['server']}")
            if match["connection_id"]:
                state = match["connection_state"] or "unknown"
                details.append(f"{match['connection_id']}: {state}")
            detail_text = f"; {', '.join(details)}" if details else ""
            lines.append(
                f"{idx}. {match['name']} (score={match['score']:.3f}{detail_text}) — {desc}"
            )
            if match["prompt_instructions"]:
                lines.append(f"   ↳ when to use: {match['prompt_instructions'][:300]}")

        # Deferred tool loading: matching a deferred tool loads it — its
        # full schema is advertised from the next step onward. A signature
        # line per loaded tool lets the model plan the call immediately.
        loaded_names = self._load_deferred(context, meaningful, lines)
        from shipit_agent.deferral import LOADED_NAMES_KEY
        already_loaded = [m["name"] for m in meaningful
                          if m["name"] in (context.state.get(LOADED_NAMES_KEY) or ())
                          and m["name"] not in loaded_names]
        if already_loaded:
            lines.append("Already loaded; call directly without another search: " + ", ".join(already_loaded))

        return ToolOutput(
            text="\n".join(lines),
            metadata={
                "query": query_text,
                "limit": limit,
                "total_candidates": len(tools),
                "matches": meaningful,
                "loaded": loaded_names,
                "already_loaded": already_loaded,
            },
        )

    def _load_deferred(
        self,
        context: ToolContext,
        matches: list[dict[str, Any]],
        lines: list[str],
    ) -> list[str]:
        """Mark matched deferred tools as loaded; append signature lines."""
        from shipit_agent.deferral import (
            DEFERRED_NAMES_KEY,
            LOADED_NAMES_KEY,
            SCHEMAS_BY_NAME_KEY,
            signature_line,
        )

        deferred = context.state.get(DEFERRED_NAMES_KEY)
        loaded = context.state.get(LOADED_NAMES_KEY)
        if not deferred or not isinstance(loaded, set):
            return []
        schemas = context.state.get(SCHEMAS_BY_NAME_KEY) or {}
        newly_loaded = [
            m["name"] for m in matches if m["name"] in deferred and m["name"] not in loaded
        ]
        if not newly_loaded:
            return []
        loaded.update(newly_loaded)
        lines.append("")
        lines.append(
            "Loaded and now directly callable (full definitions available "
            "from your next step):"
        )
        for name in newly_loaded:
            signature = signature_line(schemas.get(name))
            lines.append(f"- {signature or name}")
        return newly_loaded
