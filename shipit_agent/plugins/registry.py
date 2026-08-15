"""The plugin registry — discover, list, and activate plugins.

Discovery draws from three sources, in increasing precedence so a user can
always override a bundled plugin (last-writer-wins by name):

1. **bundled** — ``plugins/catalog/<name>/`` shipped with the library.
2. **user** — ``$SHIPIT_PLUGINS_DIR`` (or ``$SHIPIT_HOME/plugins``), a directory
   of drop-in ``<name>/`` plugin folders.
3. **entry points** — any installed package advertising the
   ``shipit_agent.plugins`` entry-point group (a factory returning a
   :class:`Plugin`).

Each source is scanned with the same contract as the connector and provider
catalogs: parse the manifest, attach the ``register`` from ``plugin.py``, and
**skip-invalid-with-a-diagnostic** — one broken plugin never breaks the rest.
``activate(plugins)`` runs each plugin's ``register`` and returns a merged
:class:`PluginRegistrar` (its tools + hook callbacks) ready to fold into an
agent.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Iterable

from .base import Plugin, PluginRegistrar
from .manifests import parse_manifest

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Plugin] = {}
#: (source, error) for every plugin that failed to load — surfaced by a UI/CI.
PLUGIN_DIAGNOSTICS: list[tuple[str, str]] = []
_loaded = False
_load_lock = Lock()

_BUNDLED_DIR = Path(__file__).parent / "catalog"
_ENTRY_POINT_GROUP = "shipit_agent.plugins"


def register(plugin: Plugin) -> Plugin:
    """Add (or override) a plugin in the registry — last-writer-wins by name."""
    _REGISTRY[plugin.name] = plugin
    return plugin


def _user_dirs() -> list[Path]:
    """User plugin roots from the environment (may not exist)."""
    roots: list[Path] = []
    explicit = os.getenv("SHIPIT_PLUGINS_DIR")
    if explicit:
        roots.append(Path(explicit))
    home = os.getenv("SHIPIT_HOME")
    if home:
        roots.append(Path(home) / "plugins")
    return roots


def load_catalog() -> None:
    """Discover plugins from all three sources (bundled → user → entry points).

    Idempotent and thread-safe. Precedence is source order: a user plugin
    overrides a bundled one of the same name; an entry-point plugin overrides
    both. Invalid plugins are recorded in :data:`PLUGIN_DIAGNOSTICS`, never fatal.
    """
    global _loaded
    if _loaded:
        return
    with _load_lock:
        if _loaded:
            return
        _scan_dir(_BUNDLED_DIR, source="bundled")
        for root in _user_dirs():
            _scan_dir(root, source="user")
        # Entry-point plugins execute code from any installed package, so they
        # are OPT-IN: a stray `pip install` can't inject a plugin unless the
        # deployer explicitly turns this on (set SHIPIT_PLUGIN_ENTRY_POINTS=1).
        if _entry_points_enabled():
            _load_entry_points()
        _loaded = True


def _entry_points_enabled() -> bool:
    return os.getenv("SHIPIT_PLUGIN_ENTRY_POINTS", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _scan_dir(root: Path, *, source: str) -> None:
    """Register every ``<root>/<name>/plugin.yaml`` directory."""
    if not root or not root.is_dir():
        return
    try:
        import yaml
    except ImportError:
        logger.warning(
            "plugin catalog needs PyYAML — install with "
            "'pip install shipit-agent[connectors]'."
        )
        return
    for manifest_path in sorted(root.glob("*/plugin.yaml")):
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            plugin = parse_manifest(data)
            plugin.register = _load_register(manifest_path.parent, plugin.name)
            register(plugin)
        except Exception as exc:  # noqa: BLE001 — a bad plugin is skipped, never fatal
            PLUGIN_DIAGNOSTICS.append((f"{source}:{manifest_path}", str(exc)))
            logger.warning("plugin %s skipped: %s", manifest_path.parent.name, exc)


def _load_register(directory: Path, name: str):
    """Import ``plugin.py``'s ``register`` from a plugin dir, if present."""
    plugin_py = directory / "plugin.py"
    if not plugin_py.exists():
        return None
    spec = importlib.util.spec_from_file_location(
        f"shipit_agent.plugins._catalog_{name}", plugin_py
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, "register", None)
    return fn if callable(fn) else None


def _load_entry_points() -> None:
    """Register plugins advertised by installed packages (highest precedence)."""
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover — Python < 3.8
        return
    try:
        eps = entry_points(group=_ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover — older API returns a dict
        eps = entry_points().get(_ENTRY_POINT_GROUP, [])
    for ep in eps:
        try:
            factory = ep.load()
            plugin = factory() if callable(factory) else factory
            if isinstance(plugin, Plugin):
                register(plugin)
            else:
                raise TypeError(f"entry point {ep.name!r} did not return a Plugin")
        except Exception as exc:  # noqa: BLE001
            PLUGIN_DIAGNOSTICS.append((f"entry_point:{ep.name}", str(exc)))
            logger.warning("plugin entry point %s skipped: %s", ep.name, exc)


# ── lookup ───────────────────────────────────────────────────────────────


def get_plugin(name: str) -> Plugin | None:
    load_catalog()
    return _REGISTRY.get(name)


def list_plugins() -> list[Plugin]:
    """Every discovered plugin, alphabetically by name."""
    load_catalog()
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def plugin_names() -> list[str]:
    load_catalog()
    return sorted(_REGISTRY)


# ── activation ───────────────────────────────────────────────────────────


def activate(plugins: Iterable[Plugin | str] | None = None) -> PluginRegistrar:
    """Run each plugin's ``register`` and return the merged registrar.

    Accepts :class:`Plugin` objects or names (resolved from the catalog). The
    returned :class:`PluginRegistrar` carries the combined tools and hook
    callbacks, ready for an agent to fold in. Unknown names raise ``KeyError``.
    """
    reg = PluginRegistrar()
    for item in plugins or []:
        plugin = get_plugin(item) if isinstance(item, str) else item
        if plugin is None:
            raise KeyError(f"unknown plugin {item!r}; known: {', '.join(plugin_names())}")
        plugin(reg)
    return reg
