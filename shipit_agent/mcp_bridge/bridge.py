"""MCPBridge: describe every attached server, disclose some, connect on demand."""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, Iterator, Mapping

from shipit_agent.llms.capabilities import capabilities_for
from shipit_agent.core.models import AgentEvent

from .descriptors import AttachedServer, MCPToolDescriptor, _LazyMCPTool

logger = logging.getLogger("shipit_agent.mcp_bridge")


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
