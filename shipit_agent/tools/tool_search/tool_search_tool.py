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
    where ``haystack`` includes the name, description, instructions, family,
    connector state, and MCP server, and ``token_hits`` counts how many query
    words appear literally in it. Tie-break by insertion order.

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
        mcp_discovery_threshold: float = 0.30,
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
        self.mcp_discovery_threshold = mcp_discovery_threshold

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
                        "detail": {
                            "type": "string",
                            "enum": ["name", "description", "schema"],
                            "description": (
                                "Result detail level. Use 'schema' immediately "
                                "before calling a hidden tool."
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
                metadata={"error": "empty_query", "matches": [], "discovery_only": True},
            )

        # Clamp limit to [1, max_limit].
        try:
            limit = int(kwargs.get("limit") or self.default_limit)
        except (TypeError, ValueError):
            limit = self.default_limit
        limit = max(1, min(limit, self.max_limit))
        detail = str(kwargs.get("detail") or "description").strip().lower()
        if detail not in {"name", "description", "schema"}:
            detail = "description"

        query_lower = query_text.lower()
        query_tokens = [t for t in query_lower.split() if t]
        initial_tools = context.state.get("available_tools", []) or []
        core_names = {"tool_search", "call_tool", "execute_code", "describe_binding"}
        local_scores = [
            self._score(
                query_lower,
                query_tokens,
                " ".join(
                    str(tool.get(key, "") or "")
                    for key in ("name", "description", "prompt_instructions", "category")
                ).lower(),
            )
            for tool in initial_tools
            if str(tool.get("name", "")) not in core_names
        ]
        deferred_servers = [
            str(name).lower()
            for name in context.state.get("deferred_mcp_servers", [])
            if str(name).strip()
        ]
        explicit_servers = [
            str(name).lower()
            for name in context.state.get("explicit_mcp_servers", [])
            if str(name).strip()
        ]
        request_context = (
            f"{query_lower}\n"
            f"{str(getattr(context, 'prompt', '') or '').lower()}"
        )
        requested_servers = {
            name
            for name in (*deferred_servers, *explicit_servers)
            if name in request_context
        }
        explicitly_requested_mcp = bool(requested_servers)
        best_local_score = max(local_scores, default=0.0)

        discovery = context.state.get("discover_deferred_tools")
        discovery_result: dict[str, Any] = {}
        if callable(discovery) and (
            explicitly_requested_mcp
            or best_local_score < self.mcp_discovery_threshold
        ):
            discovery_result = dict(discovery(request_context) or {})

        tools = context.state.get("available_tools", []) or []
        # Discovery gateways are control-plane tools, never search results.
        # Returning `call_tool` from `tool_search` led weak models to invoke
        # `call_tool(name="call_tool")` instead of the hidden capability.
        tools = [
            tool
            for tool in tools
            if str(tool.get("name", "")) not in core_names
        ]
        if requested_servers:
            server_tools = [
                tool
                for tool in tools
                if str(tool.get("server", "")).lower() in requested_servers
            ]
            if server_tools:
                tools = server_tools
        if not tools:
            return ToolOutput(
                text="No tools are currently registered on this agent.",
                metadata={"query": query_text, "matches": [], "discovery_only": True},
            )

        scored: list[dict[str, Any]] = []
        for tool in tools:
            name = str(tool.get("name", "") or "")
            description = str(tool.get("description", "") or "")
            instructions = str(tool.get("prompt_instructions", "") or "")
            category = str(tool.get("category", "") or "")
            connection_id = str(tool.get("connection_id", "") or "")
            connection_state = str(tool.get("connection_state", "") or "")
            server = str(tool.get("server", "") or "")
            schema = tool.get("schema") if isinstance(tool.get("schema"), dict) else {}
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
                )
            ).lower()
            score = self._score(query_lower, query_tokens, haystack)
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
                    "schema": schema,
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        # Newly discovered capabilities are hidden behind `call_tool`; names
        # and descriptions are insufficient to invoke them safely. Upgrade
        # the default description response to a bounded schema response. An
        # explicit `detail="name"` remains a catalog-only request.
        detail_upgraded = False
        if detail == "description" and (
            int(discovery_result.get("discovered", 0))
            or explicitly_requested_mcp
        ):
            detail = "schema"
            detail_upgraded = True
        if detail == "schema":
            limit = min(limit, 3)
        matches = scored[:limit]

        # Drop matches with zero-ish scores — they're noise.
        meaningful = [m for m in matches if m["score"] > 0.05]
        if not meaningful:
            return ToolOutput(
                text=f"No tools matched '{query_text}'. Try rephrasing or broadening the query.",
                metadata={"query": query_text, "matches": matches, "discovery_only": True},
            )

        lines = [f"Best tools for '{query_text}' (ranked by relevance):"]
        for idx, match in enumerate(meaningful, start=1):
            desc = match["description"] or "No description provided."
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
            if detail == "name":
                lines.append(f"{idx}. {match['name']}")
                continue
            lines.append(
                f"{idx}. {match['name']} (score={match['score']}{detail_text}) — {desc}"
            )
            if detail == "schema" and match["schema"]:
                import json

                lines.append(
                    "   schema: " + json.dumps(match["schema"], sort_keys=True)
                )
            elif match["prompt_instructions"]:
                lines.append(f"   ↳ when to use: {match['prompt_instructions']}")

        return ToolOutput(
            text="\n".join(lines),
            metadata={
                "query": query_text,
                "limit": limit,
                "detail": detail,
                "detail_upgraded": detail_upgraded,
                "total_candidates": len(tools),
                "discovered": int(discovery_result.get("discovered", 0)),
                "discovery_failures": list(discovery_result.get("failures", [])),
                "matches": [
                    (
                        match
                        if detail == "schema"
                        else {key: value for key, value in match.items() if key != "schema"}
                    )
                    for match in meaningful
                ],
                "discovery_only": True,
            },
        )
