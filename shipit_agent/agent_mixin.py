"""Adding the new machinery to the existing ``Agent`` without replacing it.

``Agent`` keeps every field and every method it has. This mixin adds new ones
beside them, so adoption is two lines and a rollback is deleting those two
lines::

    from shipit_agent.agent_mixin import UpgradeMixin

    @dataclass
    class Agent(UpgradeMixin):        # ← the only change
        ...

Then, incrementally:

    agent.preflight()          # what would go wrong, before spending a token
    agent.upgrade_report()     # which features the new loop does not yet cover
    agent.run_v2("...")        # the new loop, same Agent, same fields
    agent.stream_v2("...")     # live events, tool output included

``run`` and ``stream`` are untouched. Both loops read the same configuration —
``bridge.spec_from_agent`` maps the fields — so the two can be compared on real
work rather than argued about, and the old one stays until it is not needed.

Nothing here is silent. ``upgrade_report()`` names every configured feature the
new loop does not reproduce, because a migration that quietly loses a feature is
worse than one that refuses to start.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

from shipit_agent.bridge import spec_from_agent, unmapped
from shipit_agent.graph import AgentGraph
from shipit_agent.live import Packet, to_packets
from shipit_agent.llms.capabilities import capabilities_for, describe
from shipit_agent.models import AgentEvent, AgentResult
from shipit_agent.usage import UsageLedger

logger = logging.getLogger(__name__)

__all__ = ["UpgradeMixin"]


class UpgradeMixin:
    """New capabilities for an existing ``Agent``. Adds; never overrides."""

    # -- running -----------------------------------------------------------

    def stream_v2(self, user_prompt: str, **kwargs: Any) -> Iterator[AgentEvent]:
        """The new loop, yielding every moment as it happens.

        Text deltas, streamed tool arguments, live tool output, skill loads,
        tool discovery, sub-agent activity and compaction all arrive here on one
        channel. The result is assembled from the same events, so ``run_v2`` and
        this cannot disagree.
        """
        graph = self._build_graph_v2(user_prompt, **kwargs)
        self._last_graph_v2 = graph

        answer = ""
        for event in graph.run(user_prompt):
            if event.type in ("final_answer", "run_completed"):
                answer = str(event.payload.get("text") or answer)
            yield event

        self._last_result_v2 = graph.result(answer)

    def run_v2(self, user_prompt: str, **kwargs: Any) -> AgentResult:
        """The new loop, returning a result. The stream, drained."""
        for _ in self.stream_v2(user_prompt, **kwargs):
            pass
        return self._last_result_v2

    def packets_v2(self, user_prompt: str, **kwargs: Any) -> Iterator[Packet]:
        """The stream as typed packets, for a UI or an SSE endpoint.

        Every packet carries ``tool_call_id``, so parallel tool calls render as
        separate live panes instead of interleaved text.
        """
        yield from to_packets(self.stream_v2(user_prompt, **kwargs))

    # -- inspection --------------------------------------------------------

    def preflight(self) -> dict[str, Any]:
        """A cheap self-check before any token is spent.

        Most agent misconfiguration is visible without calling a model: a server
        that will not start, a parameter this family rejects, a prompt already
        occupying a quarter of the context window. Finding those at startup
        costs nothing; finding them mid-run costs the run.
        """
        graph = self._build_graph_v2("")
        caps = capabilities_for(graph.spec.model)
        prefix_tokens = graph.prefix.approx_tokens()
        budget = caps.input_budget()

        report: dict[str, Any] = {
            "model": graph.spec.model,
            "schema_dialect": caps.schema_dialect,
            "context_window": caps.context_window,
            "prefix_tokens": prefix_tokens,
            "prefix_share": round(prefix_tokens / budget, 3) if budget else None,
            "tools_bound": len(graph.prefix.tool_definitions),
            "tools_deferred": len(graph.discovery.deferred),
            "skills": len(graph.spec.skills),
            "parameters": graph.parameters.explain(),
            "warnings": [],
        }

        if graph.spec.mcp is not None:
            summary = graph.spec.mcp.summary()
            report["mcp"] = summary
            for server, error in summary["failed"].items():
                report["warnings"].append(f"MCP server {server} unavailable: {error}")

        if graph.parameters.dropped:
            report["warnings"].append(
                "Blocked for this model and not sent: "
                + ", ".join(sorted(graph.parameters.dropped))
            )
        if graph.parameters.rejected:
            report["warnings"].append(
                "Not numeric and ignored: " + ", ".join(sorted(graph.parameters.rejected))
            )
        if budget and prefix_tokens > budget * 0.25:
            report["warnings"].append(
                f"The fixed prefix is {report['prefix_share']:.0%} of the input "
                "budget before any conversation. Defer more tools or trim rules."
            )
        if not caps.context_window:
            report["warnings"].append(
                f"No context window known for {graph.spec.model!r}; compaction "
                "will use a default that may be far from correct."
            )

        gaps = self.upgrade_report()
        if gaps:
            report["not_yet_in_v2"] = sorted(gaps)

        return report

    def describe_tools_v2(self) -> list[dict[str, Any]]:
        """Every reachable tool: which are bound now, which wait for a search."""
        graph = self._build_graph_v2("")
        bound = {d["function"]["name"] for d in graph.prefix.tool_definitions}
        return sorted(
            (
                {
                    "name": name,
                    "bound": name in bound,
                    "deferred": graph.discovery.is_deferred(name),
                    "description": str(getattr(tool, "description", ""))[:120],
                }
                for name, tool in graph._tools.items()
            ),
            key=lambda row: row["name"],
        )

    def describe_model_v2(self) -> dict[str, Any]:
        """The resolved capability row for this agent's model."""
        return describe([self._model_v2()])[0]

    def upgrade_report(self) -> dict[str, str]:
        """Configured features the new loop does not yet reproduce.

        Only features actually enabled are listed — an agent that never turned
        on ``code_mode`` should not be told it is missing.
        """
        return unmapped(self)

    # -- internals ---------------------------------------------------------

    _last_graph_v2: Any = None
    _last_result_v2: Any = None

    def _model_v2(self) -> str:
        return str(
            getattr(self, "model", "")
            or getattr(getattr(self, "llm", None), "model", "")
        )

    def _build_graph_v2(self, prompt: str, **kwargs: Any) -> AgentGraph:
        """One graph per run: private skill session, discovery state and ledger.

        Built fresh each time rather than cached on the agent, so two runs of one
        agent cannot leak into each other — an agent is reusable, a run is not.
        """
        spec = spec_from_agent(
            self,
            prompt,
            ledger=UsageLedger(),
            model=kwargs.pop("model", "") or self._model_v2(),
            compact=kwargs.pop("compact", None),
        )
        if kwargs:
            logger.debug("Ignoring unsupported v2 arguments: %s", ", ".join(kwargs))

        graph = AgentGraph(spec)
        history = list(getattr(self, "history", None) or [])
        if history:
            graph.messages.extend(history)
        return graph

    @property
    def last_ledger_v2(self) -> UsageLedger | None:
        """The token and cost accounting from the most recent ``run_v2``."""
        return getattr(self._last_graph_v2, "ledger", None)
