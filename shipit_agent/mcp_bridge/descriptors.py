"""How a server's tools are named, described from cache, and connected on first call."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from shipit_agent.llms.schema_prep import prepare_schema


#: Separates a tool's own name from the server it came from. Two servers may
#: legitimately both expose ``search``; without a namespace one silently wins.
MCP_DELIMITER = "__mcp__"


def namespaced(server: str, tool: str) -> str:
    """``search`` on server ``jira`` becomes ``search__mcp__jira``."""
    return f"{tool}{MCP_DELIMITER}{server}"


def split_namespaced(name: str) -> tuple[str, str | None]:
    """Inverse of :func:`namespaced`. Returns ``(tool, server or None)``."""
    if MCP_DELIMITER not in name:
        return name, None
    tool, _, server = name.partition(MCP_DELIMITER)
    return tool, server or None


class _Server(Protocol):
    """The subset of an MCP server this module needs."""

    name: str
    instructions: str

    def discover_tools(self) -> Sequence[Any]: ...


@dataclass(frozen=True, slots=True)
class MCPToolDescriptor:
    """One tool, described without connecting to anything."""

    server: str
    tool: str
    description: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    #: Held behind ``tool_search`` rather than shown up front.
    deferred: bool = False

    @property
    def name(self) -> str:
        return namespaced(self.server, self.tool)

    def schema(self, *, dialect: str) -> dict[str, Any]:
        """An OpenAI-shaped entry with parameters prepared for *dialect*."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": prepare_schema(
                    dict(self.parameters) or {"type": "object", "properties": {}},
                    dialect=dialect,
                    tool_name=self.name,
                ),
            },
        }

    def catalog_line(self) -> str:
        summary = " ".join(self.description.split())[:100]
        return f"- {self.name}: {summary}" if summary else f"- {self.name}"


class _LazyMCPTool:
    """A callable tool that connects on first use and not before.

    Holds the descriptor (cheap, from cache) and a factory that produces a live
    connection. The factory is called at most once per run: a connection opened
    for the first call is reused for the rest, and a run that never calls this
    tool never opens one at all.
    """

    __slots__ = ("descriptor", "_connect", "_connection", "prompt_instructions")

    def __init__(
        self,
        descriptor: MCPToolDescriptor,
        connect: Callable[[], Any],
    ) -> None:
        self.descriptor = descriptor
        self._connect = connect
        self._connection: Any = None
        self.prompt_instructions = ""

    @property
    def name(self) -> str:
        return self.descriptor.name

    @property
    def description(self) -> str:
        return self.descriptor.description

    def schema(self) -> dict[str, Any]:
        # Dialect-agnostic here; the graph re-prepares per model before binding.
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.descriptor.parameters)
                or {"type": "object", "properties": {}},
            },
        }

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        if self._connection is None:
            self._connection = self._connect()
        return self._connection.call(self.descriptor.tool, kwargs)


@dataclass
class AttachedServer:
    """One server's contribution to a run."""

    name: str
    instructions: str = ""
    descriptors: list[MCPToolDescriptor] = field(default_factory=list)
    #: Set when discovery failed. A broken server must not fail the run — it
    #: contributes nothing and says so, and the other servers still work.
    error: str = ""

    @property
    def healthy(self) -> bool:
        return not self.error
