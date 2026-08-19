"""A one-function bridge to the host's tool output type.

Modules here return tool results, but must not hard-depend on the host package
so they can be unit-tested standalone. This resolves the real ``ToolOutput``
when shipit_agent is importable and falls back to an equivalent local type when
it is not — same attributes, so callers cannot tell the difference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["make_output", "ToolOutput"]

try:  # pragma: no cover - exercised implicitly by the host package
    from shipit_agent.tools.base import ToolOutput  # type: ignore
except Exception:  # noqa: BLE001

    @dataclass(slots=True)
    class ToolOutput:  # type: ignore[no-redef]
        text: str
        metadata: dict[str, Any] = field(default_factory=dict)


def make_output(text: str, metadata: dict[str, Any] | None = None) -> ToolOutput:
    """Build a tool result of whichever ``ToolOutput`` type is in play."""
    return ToolOutput(text=text, metadata=dict(metadata or {}))
