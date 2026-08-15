"""Parse a plugin ``plugin.yaml`` into a :class:`Plugin` (manifest only).

The manifest is the declarative half of a plugin — one per directory under
``catalog/``. This module is the single place that knows the on-disk shape, so
the rest of the system only ever sees a validated :class:`Plugin`. The plugin's
``register`` callable is attached separately by the loader from ``plugin.py``.
Invalid manifests raise :class:`PluginManifestError`; the loader turns that into
a skipped-with-diagnostic, never a crash.

Schema (v1)::

    plugin_version: 1
    name: audit-log
    description: Append every tool call to an audit file.
    version: 1.0.0
    author: you@example.com
    kind: standalone
    icon: "📋"
    provides_tools: []                 # declared tool names (optional)
    hooks: [after_tool, on_session_end]
"""

from __future__ import annotations

import re
from typing import Any

from .base import HOOK_POINTS, Plugin

_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class PluginManifestError(ValueError):
    """A plugin manifest is missing a required field or has an invalid value."""


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def parse_manifest(data: dict[str, Any]) -> Plugin:
    """Validate a plugin manifest dict and build a :class:`Plugin` (no register)."""
    if not isinstance(data, dict):
        raise PluginManifestError("manifest must be a mapping")
    version = data.get("plugin_version", 1)
    if version != 1:
        raise PluginManifestError(
            f"unsupported plugin_version {version!r} (expected 1)"
        )

    name = str(data.get("name") or "").strip()
    if not name:
        raise PluginManifestError("missing required field 'name'")
    if not _NAME.match(name):
        raise PluginManifestError(f"invalid name {name!r} (allowed: A-Z a-z 0-9 _ -)")

    kind = str(data.get("kind") or "standalone").lower()
    if kind != "standalone":
        raise PluginManifestError(
            f"unsupported kind {kind!r} (only 'standalone' today)"
        )

    hooks = _str_list(data.get("hooks"))
    bad = [h for h in hooks if h not in HOOK_POINTS]
    if bad:
        raise PluginManifestError(
            f"unknown hook point(s) {', '.join(bad)}; valid: {', '.join(HOOK_POINTS)}"
        )

    return Plugin(
        name=name,
        description=str(data.get("description") or ""),
        kind=kind,
        version=str(data.get("version") or "0.0.0"),
        author=str(data.get("author") or ""),
        provides_tools=_str_list(data.get("provides_tools")),
        hooks=hooks,
        icon=str(data.get("icon") or ""),
    )
