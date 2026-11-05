"""Tools the user asked for by name: which ones, which have not run yet, and the nudge to run them.

Mixed into :class:`~shipit_agent.core.runtime_core.RuntimeCore`;
the methods run on the runtime instance.
"""

from __future__ import annotations

import re
from typing import Any, Sequence


class RequestedToolsMixin:
    """Tools the user asked for by name: which ones, which have not run yet, and the nudge to run them."""

    @staticmethod
    def requested_tool_names(user_prompt: str, registry: Any) -> set[str]:
        """Return exact tool identifiers mentioned in the prompt.

        This is diagnostic only. Natural-language intent belongs to the model;
        mandatory execution belongs to the explicit ``required_tools`` API.
        The runtime must not turn prose around "tool" or "MCP" into policy.
        """
        source = user_prompt.lower()
        return {
            name
            for tool in registry.values()
            if (name := str(getattr(tool, "name", "") or ""))
            and re.search(
                rf"(?<![a-z0-9_]){re.escape(name.lower())}(?![a-z0-9_])",
                source,
            )
        }

    def missing_requested_tools(
        self, user_prompt: str, registry: Any, tool_results: Sequence[Any]
    ) -> list[str]:
        # Compatibility seam for custom RuntimeCore subclasses. Shipit no
        # longer promotes language guesses into mandatory execution policy.
        return []

    def initial_required_tool_names(self, user_prompt: str, registry: Any) -> set[str]:
        """Resolve first-step required tools against the live registry.

        Hosts may provide ``Agent(required_tools=[...])`` when their own
        routing has made an unambiguous capability choice. Unknown names are
        ignored so a changing connector catalogue cannot break a run.
        """
        available = {str(getattr(tool, "name", "") or "") for tool in registry.values()}
        configured = {
            str(name)
            for name in (getattr(self, "required_tools", None) or ())
            if str(name)
        }
        return configured & available

    def record_requested_tool_nudge(self, names: Sequence[str]) -> None:
        self._requested_tool_nudges.update(names)
