"""Making a hundred available tools cost the tokens of a dozen.

Every tool bound to a model costs its whole JSON Schema, on every turn, forever.
Twenty MCP connectors at ten tools each is two hundred schemas — tens of
thousands of tokens re-sent each iteration, for a task that will touch three of
them. The naive fixes are both bad: attaching fewer connectors makes the agent
less capable, and summarising schemas makes tool calls fail validation.

Progressive disclosure keeps the capability and drops the cost. A **core set**
stays bound — the tools a run reaches for constantly, where a search round-trip
would be pure latency. Everything else is described in one cheap line and bound
only once ``tool_search`` has found it. A tool discovered this way stays bound
for the rest of the run, so the cost is paid once, not per use.

Two properties matter:

* **Search is over descriptions, not names.** A model looking for "something to
  file a bug" should find ``create_issue__mcp__jira`` without knowing either
  word, so matching scores name, description and server together.
* **A miss is informative.** Returning "nothing found" teaches the model
  nothing; returning the nearest few, plus the servers that exist, lets it
  correct in one turn instead of guessing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    "TOOL_SEARCH_NAME",
    "DiscoveryState",
    "ToolSearchTool",
    "score_match",
]

TOOL_SEARCH_NAME = "tool_search"

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def score_match(query: str, *, name: str, description: str, server: str = "") -> float:
    """How well one tool answers *query*. Zero means no signal at all.

    Weighted so a name hit beats a description hit beats a server hit — a query
    naming the tool should rank it first — but description matches still count,
    which is what lets "file a bug" find ``create_issue``.
    """
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0

    name_tokens = _tokens(name)
    description_tokens = _tokens(description)
    server_tokens = _tokens(server)

    score = 0.0
    score += 3.0 * len(query_tokens & name_tokens)
    score += 1.0 * len(query_tokens & description_tokens)
    score += 0.5 * len(query_tokens & server_tokens)

    # A substring hit on the whole query catches multi-word names that
    # tokenising splits apart ("pull request" vs "pull_request").
    haystack = f"{name} {description}".lower()
    if query.strip().lower() in haystack:
        score += 2.0
    return score


@dataclass
class DiscoveryState:
    """Which deferred tools this run has found so far.

    Held as run state rather than recomputed from history, so a resumed run can
    restore it: with deferred loading, the search results that revealed a tool
    live in the checkpoint, and a resume that replays only messages comes back
    without the schema for the very tool it paused on.
    """

    #: name → one-line description, for everything held back.
    deferred: dict[str, str] = field(default_factory=dict)
    #: Which server each deferred tool belongs to, for search and for reporting.
    servers: dict[str, str] = field(default_factory=dict)
    #: Names discovered this run. These are bound like any core tool.
    discovered: set[str] = field(default_factory=set)

    def is_deferred(self, name: str) -> bool:
        return name in self.deferred and name not in self.discovered

    def is_available(self, name: str) -> bool:
        """True when *name* may be called right now."""
        return name not in self.deferred or name in self.discovered

    def discover(self, name: str) -> bool:
        """Mark *name* usable. Returns False when it was not a deferred tool."""
        if name not in self.deferred:
            return False
        self.discovered.add(name)
        return True

    def search(self, query: str, *, limit: int = 8) -> list[tuple[str, str, float]]:
        scored = [
            (name, description, score_match(
                query, name=name, description=description,
                server=self.servers.get(name, ""),
            ))
            for name, description in self.deferred.items()
        ]
        hits = [row for row in scored if row[2] > 0]
        hits.sort(key=lambda row: (-row[2], row[0]))
        return hits[:limit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "deferred": dict(self.deferred),
            "servers": dict(self.servers),
            "discovered": sorted(self.discovered),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DiscoveryState":
        return cls(
            deferred=dict(data.get("deferred") or {}),
            servers=dict(data.get("servers") or {}),
            discovered=set(data.get("discovered") or ()),
        )

    @classmethod
    def from_descriptors(cls, descriptors: Iterable[Any]) -> "DiscoveryState":
        """Build from :class:`~shipit_agent.mcp_bridge.MCPToolDescriptor` values."""
        state = cls()
        for descriptor in descriptors:
            if not getattr(descriptor, "deferred", False):
                continue
            state.deferred[descriptor.name] = descriptor.description
            state.servers[descriptor.name] = descriptor.server
        return state


class ToolSearchTool:
    """Finds tools that are available but not currently bound.

    Returns full signatures for what it finds, so the model can call a
    discovered tool immediately rather than needing a second round-trip to learn
    its arguments.
    """

    name = TOOL_SEARCH_NAME
    description = (
        "Search for tools that are available but not loaded. Many connected "
        "tools are held back to keep the context small. Describe what you need "
        "to do — 'create a ticket', 'read a spreadsheet' — and matching tools "
        "become callable immediately."
    )
    prompt_instructions = (
        "Not every available tool is listed. If no loaded tool fits the task, "
        "search for one before concluding it cannot be done."
    )

    def __init__(
        self,
        state: DiscoveryState,
        *,
        schemas: Mapping[str, Mapping[str, Any]] | None = None,
        limit: int = 8,
    ) -> None:
        self._state = state
        self._schemas = dict(schemas or {})
        self._limit = limit

    def schema(self) -> dict[str, Any]:
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
                            "description": (
                                "What you need to do, in plain words. Not a tool "
                                "name — describe the task."
                            ),
                        }
                    },
                    "required": ["query"],
                },
            },
        }

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        from shipit_agent.tools_compat import make_output

        query = str(kwargs.get("query", "")).strip()
        if not query:
            return make_output("No query given. Describe what you need to do.")

        hits = self._state.search(query, limit=self._limit)
        if not hits:
            return make_output(self._no_matches(query), metadata={"found": 0})

        lines: list[str] = [f"Found {len(hits)} tool(s), now callable:\n"]
        for name, description, _score in hits:
            self._state.discover(name)
            lines.append(f"### {name}\n{description}")
            signature = self._signature(name)
            if signature:
                lines.append(signature)
            lines.append("")

        return make_output(
            "\n".join(lines).strip(),
            metadata={"found": len(hits), "tools": [h[0] for h in hits]},
        )

    # -- internals ---------------------------------------------------------

    def _signature(self, name: str) -> str:
        """Render a tool's arguments, so it can be called without a second search."""
        schema = self._schemas.get(name)
        if not isinstance(schema, Mapping):
            return ""
        function = schema.get("function")
        parameters = (
            function.get("parameters") if isinstance(function, Mapping) else schema
        )
        if not isinstance(parameters, Mapping):
            return ""
        properties = parameters.get("properties")
        if not isinstance(properties, Mapping) or not properties:
            return "Arguments: none"
        required = set(parameters.get("required") or ())
        rendered = ", ".join(
            f"{key}{'' if key in required else '?'}: "
            f"{(spec or {}).get('type', 'any') if isinstance(spec, Mapping) else 'any'}"
            for key, spec in properties.items()
        )
        return f"Arguments: {rendered}"

    def _no_matches(self, query: str) -> str:
        servers = sorted(set(self._state.servers.values()))
        available = len(self._state.deferred)
        if not available:
            return "No additional tools are available beyond those already loaded."
        nearest = sorted(self._state.deferred)[:5]
        parts = [f"No tool matched {query!r} among {available} unloaded tools."]
        if servers:
            parts.append(f"Connected servers: {', '.join(servers)}.")
        parts.append(f"Examples of what is available: {', '.join(nearest)}.")
        parts.append("Try describing the task differently, or name a server.")
        return " ".join(parts)


def bind_discovered(
    state: DiscoveryState, all_tools: Mapping[str, Any]
) -> list[Any]:
    """The tools that may be bound right now: core plus everything discovered."""
    return [tool for name, tool in all_tools.items() if state.is_available(name)]


def filter_schemas(
    state: DiscoveryState, schemas: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Drop schemas for tools still held behind search."""

    def name_of(schema: Mapping[str, Any]) -> str:
        function = schema.get("function")
        if isinstance(function, Mapping):
            return str(function.get("name", ""))
        return str(schema.get("name", ""))

    return [dict(schema) for schema in schemas if state.is_available(name_of(schema))]
