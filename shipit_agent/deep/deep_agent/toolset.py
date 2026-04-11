"""The deep-agent toolset.

A single function that returns the seven tools every Deep Agent gets,
plus a small helper to merge them with user-supplied and built-in tools
without producing duplicates.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.decision_matrix import DecisionMatrixTool
from shipit_agent.tools.evidence_synthesis import EvidenceSynthesisTool
from shipit_agent.tools.planner import PlannerTool
from shipit_agent.tools.sub_agent import SubAgentTool
from shipit_agent.tools.thought_decomposition import ThoughtDecompositionTool
from shipit_agent.tools.verifier import VerifierTool
from shipit_agent.tools.workspace_files import WorkspaceFilesTool


def deep_tool_set(*, llm: Any, workspace_root: str) -> list[Any]:
    """Return the seven tools that every DeepAgent ships with."""
    return [
        PlannerTool(),
        ThoughtDecompositionTool(),
        WorkspaceFilesTool(root_dir=workspace_root),
        SubAgentTool(llm=llm),
        EvidenceSynthesisTool(),
        DecisionMatrixTool(),
        VerifierTool(),
    ]


def merge_tools(*tool_lists: list[Any]) -> list[Any]:
    """Merge multiple tool lists, deduping by tool ``name``.

    Later occurrences win, so deep-agent tools always take precedence
    over a builtin or user-supplied tool with the same name.
    """
    seen: dict[str, Any] = {}
    for tools in tool_lists:
        for tool in tools:
            name = getattr(tool, "name", None)
            if name:
                seen[name] = tool
    return list(seen.values())


__all__ = ["deep_tool_set", "merge_tools"]
