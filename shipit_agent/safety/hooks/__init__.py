"""Lifecycle hooks that can observe a run, and block or rewrite prompts and tool calls."""

from __future__ import annotations

from .agent_hooks import AgentHooks
from .decisions import _coerce_hook_decision

__all__ = ["AgentHooks", "_coerce_hook_decision"]
