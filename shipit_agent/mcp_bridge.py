"""Attaching MCP servers to a run without paying for the ones nobody calls.

Connecting to an MCP server is not free. A stdio server spawns a subprocess, runs
the ``initialize`` handshake and answers ``tools/list`` — all before the model has
decided to use a single one of its tools. With twenty connectors attached that is
twenty subprocesses and twenty round-trips on every run, most of them wasted. And
the tools that *are* discovered cost tokens forever after: twenty servers at ten
tools each is two hundred schemas in a prompt that is re-sent every turn.

So attachment happens in three separable stages, and a run pays only for the ones
it reaches:

1. **Describe** — read tool descriptors from the on-disk schema cache. No process
   spawned, no network. Enough to build the catalog and the tool definitions.
2. **Disclose** — put the cheap ones in the prompt and hold the rest behind
   ``tool_search`` (see :mod:`shipit_agent.discovery`), so a hundred available
   tools cost a handful of schemas until one is actually wanted.
3. **Connect** — spawn or dial only when a tool is called, and reuse the
   connection for the rest of the run.

Two smaller things this module fixes, both cheap and both currently missing:

**Server instructions reach the model.** The MCP spec's ``instructions`` field is
the server telling the model how to use it — "call ``list_projects`` before
``create_task``", "ids are ULIDs, not integers". It is read off the handshake and
then dropped on the floor, which means the model rediscovers those rules by
failing. Here it goes into the stable prefix, deduped and sorted by server.

**Schemas are prepared for the model that will see them.** MCP servers built on
Pydantic or FastMCP emit ``$defs`` and ``$ref`` for every nested argument model.
A strict OpenAI-*compatible* validator rejects those, so the failure is quiet and
selective: simple tools keep working, nested ones stop, and the model reads as
stupid rather than blocked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Mapping, Protocol, Sequence

from shipit_agent.llms.capabilities import capabilities_for
from shipit_agent.llms.schema_prep import prepare_schema
from shipit_agent.models import AgentEvent

logger = logging.getLogger(__name__)

__all__ = [
    "MCPToolDescriptor",
    "AttachedServer",
    "MCPBridge",
    "namespaced",
    "split_namespaced",
    "MCP_DELIMITER",
]

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


class MCPBridge:
    """Turns a set of MCP servers into tools, instructions and a catalog.

    Discovery failures are contained per server. One connector being down is an
    ordinary condition — a subprocess that will not start, an expired token, a
    service having an outage — and it must degrade that server's tools, not the
    whole run.
    """

    def __init__(
        self,
        servers: Iterable[Any] = (),
        *,
        deferred_servers: Iterable[str] = (),
        max_eager_tools: int = 12,
    ) -> None:
        """*deferred_servers* are held behind ``tool_search`` regardless of size.

        ``max_eager_tools`` is the budget for schemas shown up front. Servers
        past it are deferred automatically, largest last, so a run with a few
        small connectors keeps them all visible and one with twenty does not
        drown the prompt.

        Twelve rather than something generous: a single server exposing thirty
        tools should be searched, not bound. The budget is per-run and the
        deferred tail costs one ``tool_search`` round-trip, paid once.
        """
        self._servers = list(servers)
        self._deferred_names = set(deferred_servers)
        self._max_eager = max_eager_tools
        self.attached: list[AttachedServer] = []

    # -- discovery ---------------------------------------------------------

    def attach(self) -> list[AttachedServer]:
        """Describe every server. Cheap: reads descriptors, opens nothing."""
        self.attached = [self._describe(server) for server in self._servers]
        self._apply_deferral()
        return self.attached

    def _describe(self, server: Any) -> AttachedServer:
        name = str(getattr(server, "name", "") or "server")
        try:
            tools = server.discover_tools() or []
        except Exception as error:  # noqa: BLE001 — one bad server, not a bad run
            logger.warning("MCP server %s failed discovery: %s", name, error)
            return AttachedServer(name=name, error=str(error))

        descriptors = [
            MCPToolDescriptor(
                server=name,
                tool=str(getattr(tool, "name", "")),
                description=str(getattr(tool, "description", "") or ""),
                parameters=self._parameters_of(tool),
            )
            for tool in tools
            if getattr(tool, "name", None)
        ]
        return AttachedServer(
            name=name,
            instructions=str(getattr(server, "instructions", "") or ""),
            descriptors=descriptors,
        )

    @staticmethod
    def _parameters_of(tool: Any) -> dict[str, Any]:
        schema = getattr(tool, "schema", None)
        raw = schema() if callable(schema) else getattr(tool, "inputSchema", None)
        if isinstance(raw, Mapping):
            function = raw.get("function")
            if isinstance(function, Mapping) and isinstance(
                function.get("parameters"), Mapping
            ):
                return dict(function["parameters"])
            return dict(raw)
        return {}

    def _apply_deferral(self) -> None:
        """Decide which tools are shown up front and which wait to be searched."""
        eager_budget = self._max_eager
        # Smallest servers first: showing three one-tool connectors and hiding
        # one forty-tool connector serves the model better than the reverse.
        for server in sorted(self.attached, key=lambda s: len(s.descriptors)):
            forced = server.name in self._deferred_names
            fits = len(server.descriptors) <= eager_budget
            deferred = forced or not fits
            if not deferred:
                eager_budget -= len(server.descriptors)
            server.descriptors = [
                MCPToolDescriptor(
                    server=d.server,
                    tool=d.tool,
                    description=d.description,
                    parameters=d.parameters,
                    deferred=deferred,
                )
                for d in server.descriptors
            ]

    # -- what the run consumes --------------------------------------------

    def instructions(self) -> dict[str, str]:
        """Server instructions for the stable prefix, keyed by server.

        This is the field the MCP spec defines for a server to tell the model
        how to use it. Dropping it means the model learns those rules by failing.
        """
        return {
            server.name: server.instructions
            for server in self.attached
            if server.healthy and server.instructions.strip()
        }

    def descriptors(self, *, include_deferred: bool = True) -> list[MCPToolDescriptor]:
        return [
            descriptor
            for server in self.attached
            if server.healthy
            for descriptor in server.descriptors
            if include_deferred or not descriptor.deferred
        ]

    def tools(self, connect: Callable[[str], Any]) -> list[Any]:
        """Callable tools that connect on first use.

        *connect* maps a server name to something with ``.call(tool, args)``.
        """
        return [
            _LazyMCPTool(descriptor, lambda s=descriptor.server: connect(s))
            for descriptor in self.descriptors()
        ]

    def schemas(self, model: str, *, include_deferred: bool = False) -> list[dict[str, Any]]:
        """Tool definitions prepared for *model*'s schema dialect."""
        dialect = capabilities_for(model).schema_dialect
        return [
            descriptor.schema(dialect=dialect)
            for descriptor in self.descriptors(include_deferred=include_deferred)
        ]

    def events(self) -> Iterator[AgentEvent]:
        """Attachment events for the run's stream, healthy and failed alike."""
        for server in self.attached:
            if server.healthy:
                eager = sum(1 for d in server.descriptors if not d.deferred)
                yield AgentEvent(
                    type="mcp_attached",  # type: ignore[arg-type]
                    message=f"{server.name}: {len(server.descriptors)} tools",
                    payload={
                        "server": server.name,
                        "tools": len(server.descriptors),
                        "eager": eager,
                        "deferred": len(server.descriptors) - eager,
                        "has_instructions": bool(server.instructions.strip()),
                    },
                )
            else:
                yield AgentEvent(
                    type="mcp_attached",  # type: ignore[arg-type]
                    message=f"{server.name} unavailable: {server.error}",
                    payload={"server": server.name, "error": server.error, "tools": 0},
                )

    def summary(self) -> dict[str, Any]:
        """For ``doctor``: what attached, what deferred, what broke."""
        healthy = [s for s in self.attached if s.healthy]
        descriptors = self.descriptors()
        return {
            "servers": len(self.attached),
            "healthy": len(healthy),
            "failed": {s.name: s.error for s in self.attached if not s.healthy},
            "tools_total": len(descriptors),
            "tools_eager": sum(1 for d in descriptors if not d.deferred),
            "tools_deferred": sum(1 for d in descriptors if d.deferred),
            "with_instructions": sorted(self.instructions()),
        }
