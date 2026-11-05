"""Claude Code settings files: user, project and local.

    user     ~/.claude/settings.json
    project  <cwd>/.claude/settings.json
    local    <cwd>/.claude/settings.local.json

Only the sources a caller names are read. Merging follows Claude Code:
permission ``allow`` / ``deny`` / ``ask`` lists add up across files,
``defaultMode`` and ``model`` come from the most specific file, ``env``
merges with the more specific value winning, and every file's hooks run.
``env`` is given to hook commands only; it never touches this process's
environment, which other agents may share.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

__all__ = ["SettingSource", "HarnessSettings", "load_settings_sources", "settings_file"]

SettingSource = Literal["user", "project", "local"]
_ORDER: tuple[SettingSource, ...] = ("user", "project", "local")


@dataclass(slots=True)
class HarnessSettings:
    """What the settings files say, merged."""

    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    ask: list[str] = field(default_factory=list)
    default_mode: str | None = None
    model: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    #: ``(source label, event map, that file's env)`` for each file with hooks.
    hooks: list[tuple[str, dict[str, Any], dict[str, str]]] = field(default_factory=list)
    loaded: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def settings_file(source: SettingSource, cwd: Path) -> Path:
    if source == "user":
        return Path.home() / ".claude" / "settings.json"
    name = "settings.json" if source == "project" else "settings.local.json"
    return cwd / ".claude" / name


def load_settings_sources(sources: list[SettingSource] | None, cwd: Path) -> HarnessSettings:
    """Read and merge the named sources, least specific first."""
    merged = HarnessSettings()
    for source in _ORDER:
        if source not in (sources or []):
            continue
        path = settings_file(source, cwd)
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            merged.errors.append(f"{path}: not valid JSON ({error})")
            continue
        if not isinstance(data, dict):
            merged.errors.append(f"{path}: expected a JSON object")
            continue
        _merge(merged, data, str(path))
    return merged


def _merge(merged: HarnessSettings, data: dict[str, Any], label: str) -> None:
    merged.loaded.append(label)
    permissions = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}
    for key in ("allow", "deny", "ask"):
        target = getattr(merged, key)
        target.extend(rule for rule in _strings(permissions.get(key)) if rule not in target)
    if isinstance(permissions.get("defaultMode"), str):
        merged.default_mode = permissions["defaultMode"]
    if isinstance(data.get("model"), str):
        merged.model = data["model"]
    env = {str(k): str(v) for k, v in (data.get("env") or {}).items()} if isinstance(data.get("env"), dict) else {}
    merged.env.update(env)
    if isinstance(data.get("hooks"), dict) and data["hooks"]:
        merged.hooks.append((label, data["hooks"], env))


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []
