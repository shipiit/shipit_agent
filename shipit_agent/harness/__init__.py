"""Claude Code's harness for any shipit agent: settings files, command hooks and plugins.

See :class:`Harness`; ``AgentOptions(plugins=..., setting_sources=...)``
builds one for an SDK-style run.
"""

from __future__ import annotations

from .core import Harness
from .plugins import Plugin, load_plugin
from .settings import HarnessSettings, SettingSource, load_settings_sources

__all__ = ["Harness", "HarnessSettings", "Plugin", "SettingSource", "load_plugin", "load_settings_sources"]
