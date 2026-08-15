"""Drop-in plugin packs — tools and lifecycle hooks, one directory each.

A plugin is a ``catalog/<name>/`` directory (bundled, in a user plugin dir, or
from a pip entry point) with a declarative ``plugin.yaml`` and a ``plugin.py``
exporting ``register(reg)``. The registry discovers them from all three sources
(user and entry-point plugins override bundled ones), and an agent folds their
tools and hooks in.

    from shipit_agent.plugins import list_plugins, merge_plugins

    for p in list_plugins():
        print(p.name, "-", p.description)

    tools, hooks = merge_plugins(["audit-log"], tools=my_tools)
    agent = Agent(llm=llm, tools=tools, hooks=hooks)
"""

from __future__ import annotations

from .apply import apply_to_hooks, merge_plugins
from .base import HOOK_POINTS, Plugin, PluginRegistrar
from .manifests import PluginManifestError, parse_manifest
from .registry import (
    PLUGIN_DIAGNOSTICS,
    activate,
    get_plugin,
    list_plugins,
    load_catalog,
    plugin_names,
    register,
)

__all__ = [
    "HOOK_POINTS",
    "Plugin",
    "PluginRegistrar",
    "PluginManifestError",
    "parse_manifest",
    "PLUGIN_DIAGNOSTICS",
    "activate",
    "apply_to_hooks",
    "merge_plugins",
    "get_plugin",
    "list_plugins",
    "load_catalog",
    "plugin_names",
    "register",
]
