"""One plugin, one directory.

A :class:`Plugin` is a drop-in extension pack: a small declarative manifest
(`plugin.yaml`) plus a ``register()`` callable that contributes **tools** and
**lifecycle hooks** to an agent. It is the unifying extension mechanism —
a plugin can add a tool, wrap every tool call, redact a prompt, or clean up at
the end of a session, all without editing the library.

Each plugin lives in its own clean directory under ``plugins/catalog/`` (or a
user plugin directory, or a pip entry point):

    plugins/catalog/<name>/
      plugin.yaml     # name, description, kind, provides_tools, hooks
      plugin.py       # def register(reg: PluginRegistrar) -> None

The manifest is metadata the loader validates and a UI can render; the real
wiring happens when ``register()`` is called with a :class:`PluginRegistrar`
that the plugin uses to add tools and hook callbacks. Nothing here runs a
plugin's code at import — discovery reads manifests; ``register`` runs only when
a plugin is actually applied to an agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

#: A plugin's registration entry point: called with a PluginRegistrar so the
#: plugin can add tools and hook callbacks. Defined in ``plugin.py``.
RegisterFn = Callable[["PluginRegistrar"], None]

#: The lifecycle points a plugin hook may attach to. Each maps one-to-one onto
#: the agent's existing hook surface (see :mod:`shipit_agent.hooks.AgentHooks`),
#: so a plugin hook is a real, wired callback — never a dead declaration.
HOOK_POINTS = (
    "before_llm",
    "after_llm",
    "before_tool",
    "after_tool",
    "user_prompt",
)


@dataclass(slots=True)
class Plugin:
    """A declarative extension pack + its registration callable."""

    #: Catalog key, e.g. ``"audit-log"``. Lowercase, ``-``/``_`` allowed.
    name: str
    #: One line for a catalog card / listing.
    description: str = ""
    #: ``"standalone"`` (adds tools/hooks) — reserved for future kinds.
    kind: str = "standalone"
    #: Semver-ish version string from the manifest.
    version: str = "0.0.0"
    #: Author / provenance.
    author: str = ""
    #: Names of tools this plugin provides (declared for a UI; the truth is
    #: whatever ``register`` adds).
    provides_tools: list[str] = field(default_factory=list)
    #: Hook points this plugin attaches to (declared; see :data:`HOOK_POINTS`).
    hooks: list[str] = field(default_factory=list)
    #: Emoji / short glyph for a catalog card.
    icon: str = ""
    #: The plugin's ``register(reg)`` — set by the loader from ``plugin.py``.
    register: RegisterFn | None = None

    def __call__(self, reg: "PluginRegistrar") -> None:
        """Apply the plugin: run its ``register`` against a registrar."""
        if self.register is not None:
            self.register(reg)


@dataclass(slots=True)
class PluginRegistrar:
    """What a plugin's ``register()`` is handed to wire itself in.

    Collects the tools and hook callbacks a plugin contributes. The agent then
    merges ``tools`` into its tool belt and ``hooks`` into its
    :class:`~shipit_agent.hooks.AgentHooks`. Kept deliberately tiny so a plugin
    is trivial to write and to test in isolation.
    """

    #: Tools the plugin adds (any object the agent accepts in ``tools=``).
    tools: list[Any] = field(default_factory=list)
    #: hook point -> list of callbacks, e.g. ``{"after_tool": [fn]}``.
    hook_callbacks: dict[str, list[Callable[..., Any]]] = field(default_factory=dict)

    def add_tool(self, tool: Any) -> None:
        """Contribute a tool to the agent's belt."""
        self.tools.append(tool)

    def add_hook(self, point: str, fn: Callable[..., Any]) -> None:
        """Attach ``fn`` at a lifecycle point (see :data:`HOOK_POINTS`)."""
        if point not in HOOK_POINTS:
            raise ValueError(
                f"unknown hook point {point!r}; valid: {', '.join(HOOK_POINTS)}"
            )
        self.hook_callbacks.setdefault(point, []).append(fn)
