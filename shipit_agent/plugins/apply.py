"""Fold activated plugins into an agent's tools and hooks.

:func:`activate` (in :mod:`.registry`) runs plugins and yields a
:class:`~shipit_agent.plugins.base.PluginRegistrar` carrying the tools and hook
callbacks they contributed. This module turns that into the two things an
:class:`~shipit_agent.Agent` actually takes: a merged tool list and an
:class:`~shipit_agent.hooks.AgentHooks`. Each plugin hook point maps one-to-one
onto an ``AgentHooks`` list, so a plugin hook is a real wired callback.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..hooks import AgentHooks
from .base import PluginRegistrar
from .registry import activate


def apply_to_hooks(registrar: PluginRegistrar, hooks: AgentHooks | None = None) -> AgentHooks:
    """Merge a registrar's hook callbacks onto an :class:`AgentHooks`.

    Appends to any existing callbacks (a caller's own hooks run alongside the
    plugins'). Returns the same ``hooks`` object, or a fresh one if none given.
    """
    hooks = hooks or AgentHooks()
    for point, callbacks in registrar.hook_callbacks.items():
        target = getattr(hooks, point, None)
        if isinstance(target, list):
            target.extend(callbacks)
    return hooks


def merge_plugins(
    plugins: Iterable[Any] | None,
    *,
    tools: list[Any] | None = None,
    hooks: AgentHooks | None = None,
) -> tuple[list[Any], AgentHooks | None]:
    """Resolve, activate, and fold plugins into ``(tools, hooks)``.

    ``plugins`` may be :class:`Plugin` objects or catalog names. Returns the
    tool list with each plugin's tools appended and an ``AgentHooks`` with each
    plugin's hooks attached (``None`` for hooks only when there were no plugins
    and no incoming hooks, to stay a no-op for callers that pass neither).
    """
    tools = list(tools or [])
    plugins = list(plugins or [])
    if not plugins:
        return tools, hooks
    registrar = activate(plugins)
    tools.extend(registrar.tools)
    hooks = apply_to_hooks(registrar, hooks)
    return tools, hooks
