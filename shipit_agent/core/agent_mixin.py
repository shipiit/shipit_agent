"""Inspection and the ``*_v2`` entry points, all on the one agent loop.

These began as the way into a second, graph-shaped loop. That loop has been
retired: everything it did now lives in the one loop, so the ``*_v2`` names
remain only for compatibility and run the same loop as ``run`` and
``stream``::

    agent.preflight()        # what would go wrong, before spending a token
    agent.describe_tools_v2()  # which tools are loaded, which wait for a search
    agent.run_v2("...")      # == agent.run("...")
    agent.packets_v2("...")  # agent.stream(...) as typed packets for a UI
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from shipit_agent.core.models import AgentEvent, AgentResult
from shipit_agent.llms.capabilities import capabilities_for, describe
from shipit_agent.observability.live import Packet, to_packets

logger = logging.getLogger(__name__)

#: Share of the input budget the fixed prefix may use before preflight warns.
_PREFIX_WARNING_SHARE = 0.25


class UpgradeMixin:
    """Inspection, and the ``*_v2`` names for the one loop's ``run`` and ``stream``."""

    # -- running -----------------------------------------------------------

    def stream_v2(self, user_prompt: str, **kwargs: Any) -> Iterator[AgentEvent]:
        """Same as :meth:`stream`; kept for code written against the retired v2 loop."""
        _ignore_v2_arguments(kwargs)
        yield from self.stream(user_prompt)

    def run_v2(self, user_prompt: str, **kwargs: Any) -> AgentResult:
        """Same as :meth:`run`; kept for code written against the retired v2 loop."""
        _ignore_v2_arguments(kwargs)
        return self.run(user_prompt)

    def packets_v2(self, user_prompt: str, **kwargs: Any) -> Iterator[Packet]:
        """The stream as typed packets, for a UI or an SSE endpoint.

        Every tool packet carries ``tool_call_id``, so parallel tool calls
        render as separate live panes; the last packet is terminal.
        """
        yield from to_packets(self.stream_v2(user_prompt, **kwargs))

    # -- inspection --------------------------------------------------------

    def preflight(self) -> dict[str, Any]:
        """A cheap self-check before any token is spent.

        Most misconfiguration is visible without calling a model: an MCP
        server that will not start, a parameter this model family rejects, a
        fixed prompt already using a large share of the context window.
        """
        from shipit_agent.context.compaction import estimate_tokens, get_model_limits
        from shipit_agent.llms.parameters import resolve_parameters

        model = self._model_v2()
        caps = capabilities_for(model)
        limits = get_model_limits(model)
        tools, deferred = self._tool_split()
        resident = [tool for tool in tools if getattr(tool, "name", "") not in deferred]
        schemas = [tool.schema() for tool in resident if hasattr(tool, "schema")]
        prompt = self._effective_prompt("")
        prefix_tokens = estimate_tokens(prompt) + estimate_tokens(
            json.dumps(schemas, default=str)
        )
        budget = limits.input_budget
        parameters = resolve_parameters(model, self._llm_parameters())

        report: dict[str, Any] = {
            "model": model,
            "schema_dialect": caps.schema_dialect,
            "context_window": limits.context_window,
            "prefix_tokens": prefix_tokens,
            "prefix_share": round(prefix_tokens / budget, 3) if budget else None,
            "tools_bound": len(resident),
            "tools_deferred": len(deferred),
            "skills": len(self._listed_skills()) + len(self.skills),
            "parameters": parameters.explain(),
            "warnings": [],
        }

        failed = self._unreachable_mcps()
        if self.mcps:
            report["mcp"] = {"servers": [m.name for m in self.mcps], "failed": failed}
        for server, error in failed.items():
            report["warnings"].append(f"MCP server {server} unavailable: {error}")
        if parameters.dropped:
            report["warnings"].append(
                "Blocked for this model and not sent: "
                + ", ".join(sorted(parameters.dropped))
            )
        if parameters.rejected:
            report["warnings"].append(
                "Not numeric and ignored: " + ", ".join(sorted(parameters.rejected))
            )
        if budget and prefix_tokens > budget * _PREFIX_WARNING_SHARE:
            report["warnings"].append(
                f"The fixed prefix is {report['prefix_share']:.0%} of the input "
                "budget before any conversation. Defer more tools or trim rules."
            )
        if not caps.context_window and limits.context_window == _default_window():
            report["warnings"].append(
                f"No context window known for {model!r}; compaction will use a "
                "default that may be far from correct."
            )
        return report

    def describe_tools_v2(self) -> list[dict[str, Any]]:
        """Every reachable tool: which are loaded now, which wait for a search."""
        tools, deferred = self._tool_split()
        return sorted(
            (
                {
                    "name": getattr(tool, "name", ""),
                    "bound": getattr(tool, "name", "") not in deferred,
                    "deferred": getattr(tool, "name", "") in deferred,
                    "description": str(getattr(tool, "description", ""))[:120],
                }
                for tool in tools
            ),
            key=lambda row: row["name"],
        )

    def describe_model_v2(self) -> dict[str, Any]:
        """The resolved capability row for this agent's model."""
        return describe([self._model_v2()])[0]

    def upgrade_report(self) -> dict[str, str]:
        """Configured features the loop does not reproduce: none, since there is one loop."""
        return {}

    @property
    def last_ledger_v2(self) -> None:
        """Retired with the v2 loop: a run's accounting is in ``result.metadata["run_summary"]``."""
        return None

    # -- internals ---------------------------------------------------------

    def _model_v2(self) -> str:
        return str(
            getattr(self, "model", "")
            or getattr(getattr(self, "llm", None), "model", "")
        )

    def _tool_split(self) -> tuple[list[Any], set[str]]:
        """The tools a run would have, and the names deferral would hold back."""
        from shipit_agent.core.registry import ToolRegistry
        from shipit_agent.deferral.core import resolve_deferred_names

        tools = list(
            ToolRegistry.build(tools=self._effective_tools(""), mcps=self.mcps).values()
        )
        return tools, resolve_deferred_names(tools, self.deferred_tools)

    def _unreachable_mcps(self) -> dict[str, str]:
        failed: dict[str, str] = {}
        for mcp in self.mcps:
            try:
                mcp.discover_tools()
            except Exception as error:  # a broken server is the finding, not a crash
                failed[str(getattr(mcp, "name", "mcp"))] = (
                    f"{type(error).__name__}: {error}"
                )
        return failed

    def _llm_parameters(self) -> dict[str, Any]:
        """The sampling and limit parameters the model adapter will send."""
        llm = getattr(self, "llm", None)
        params = dict(getattr(llm, "completion_kwargs", None) or {})
        for name in ("max_tokens", "temperature", "reasoning_effort"):
            value = getattr(llm, name, None)
            if value is not None:
                params.setdefault(name, value)
        return params


def _ignore_v2_arguments(kwargs: dict[str, Any]) -> None:
    if kwargs:
        logger.debug("Ignoring v2-only arguments: %s", ", ".join(sorted(kwargs)))


def _default_window() -> int:
    from shipit_agent.context.compaction import DEFAULT_CONTEXT_WINDOW

    return DEFAULT_CONTEXT_WINDOW
