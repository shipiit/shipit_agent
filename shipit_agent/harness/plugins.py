"""Claude Code plugins from local directories.

    my-plugin/
    ├── .claude-plugin/plugin.json   # optional manifest
    ├── skills/<name>/SKILL.md       # skills, as  my-plugin:<name>
    ├── commands/<name>.md           # commands, as /my-plugin:<name>
    ├── agents/<name>.md             # sub-agents, as my-plugin:<name>
    ├── hooks/hooks.json             # {"hooks": {event: [...]}}
    └── .mcp.json                    # {"mcpServers": {...}}

Manifest keys follow Claude Code: ``skills`` adds to ``skills/``;
``commands`` and ``agents`` replace their folders; ``hooks`` and
``mcpServers`` merge with the default files. ``${CLAUDE_PLUGIN_ROOT}``
is filled in in command, agent and MCP config text; hook commands get it
in their environment. A path that leaves the plugin directory is refused.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from shipit_agent.agents.subagent_definitions import SubagentDefinition, load_subagent_file
from shipit_agent.skills.registry import load_markdown_skill, split_frontmatter

__all__ = ["Plugin", "load_plugin"]

_ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"


@dataclass(slots=True)
class Plugin:
    name: str
    path: Path
    skills: list[Any] = field(default_factory=list)
    commands: dict[str, str] = field(default_factory=dict)
    agents: dict[str, SubagentDefinition] = field(default_factory=dict)
    hooks: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: dict[str, dict[str, Any]] = field(default_factory=dict)


def load_plugin(spec: Any, *, cwd: Path, errors: list[str]) -> Plugin | None:
    """Load ``{"type": "local", "path": ...}`` (or a path); ``None``, with a note in *errors*, on failure."""
    raw = spec.get("path") if isinstance(spec, dict) else spec
    if isinstance(spec, dict) and spec.get("type", "local") != "local":
        errors.append(f"plugin {spec!r}: only type 'local' is supported")
        return None
    root = (cwd / str(raw)).resolve() if raw and not Path(str(raw)).is_absolute() else Path(str(raw or "")).resolve()
    if not raw or not root.is_dir():
        errors.append(f"plugin {raw!r}: no such directory")
        return None
    manifest: dict[str, Any] = {}
    manifest_path = root / ".claude-plugin" / "plugin.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError as error:
            errors.append(f"plugin {root}: plugin.json is not valid JSON ({error})")
            return None
    plugin = Plugin(name=str(manifest.get("name") or root.name), path=root)

    def note(message: str) -> None:
        errors.append(f"plugin {plugin.name}: {message}")

    _load_skills(plugin, manifest, note)
    _load_commands(plugin, manifest, note)
    _load_agents(plugin, manifest, note)
    _load_hooks(plugin, manifest, note)
    _load_mcp(plugin, manifest, note)
    return plugin


def _inside(plugin: Plugin, relative: str, note: Any) -> Path | None:
    target = (plugin.path / relative).resolve()
    if target != plugin.path and plugin.path not in target.parents:
        note(f"path escapes the plugin directory: {relative}")
        return None
    if not target.exists():
        note(f"path not found: {relative}")
        return None
    return target


def _paths(value: Any) -> list[str]:
    return [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _load_skills(plugin: Plugin, manifest: dict[str, Any], note: Any) -> None:
    folders = [plugin.path / "skills"] if (plugin.path / "skills").is_dir() else []
    folders += [p for p in (_inside(plugin, rel, note) for rel in _paths(manifest.get("skills"))) if p]
    files = [f for folder in folders for f in ([folder / "SKILL.md"] if (folder / "SKILL.md").is_file()
                                                   else sorted(folder.glob("*/SKILL.md")))]
    if not folders and (plugin.path / "SKILL.md").is_file():
        files = [plugin.path / "SKILL.md"]
    for path in files:
        skill = load_markdown_skill(path)
        skill.id = skill.name = f"{plugin.name}:{skill.id}"
        plugin.skills.append(skill)


def _load_commands(plugin: Plugin, manifest: dict[str, Any], note: Any) -> None:
    declared = manifest.get("commands")
    if isinstance(declared, dict):
        for name, entry in declared.items():
            if isinstance(entry, dict) and isinstance(entry.get("content"), str):
                plugin.commands[f"{plugin.name}:{name}"] = _fill(plugin, entry["content"])
            elif isinstance(entry, dict) and isinstance(entry.get("source"), str):
                path = _inside(plugin, entry["source"], note)
                if path is not None:
                    plugin.commands[f"{plugin.name}:{name}"] = _command_text(plugin, path)
        return
    targets = [p for p in (_inside(plugin, rel, note) for rel in _paths(declared)) if p] if declared is not None else (
        [plugin.path / "commands"] if (plugin.path / "commands").is_dir() else [])
    for target in targets:
        for path in sorted(target.glob("*.md")) if target.is_dir() else [target]:
            plugin.commands[f"{plugin.name}:{path.stem}"] = _command_text(plugin, path)


def _command_text(plugin: Plugin, path: Path) -> str:
    _, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return _fill(plugin, body.strip())


def _load_agents(plugin: Plugin, manifest: dict[str, Any], note: Any) -> None:
    declared = manifest.get("agents")
    files = [p for p in (_inside(plugin, rel, note) for rel in _paths(declared)) if p] if declared is not None else (
        sorted((plugin.path / "agents").rglob("*.md")) if (plugin.path / "agents").is_dir() else [])
    for path in files:
        loaded = load_subagent_file(path, prefix=f"{plugin.name}:")
        if loaded is None:
            note(f"agent file is malformed: {path.name}")
            continue
        name, definition = loaded
        plugin.agents[name] = replace(definition, prompt=_fill(plugin, definition.prompt))


def _load_hooks(plugin: Plugin, manifest: dict[str, Any], note: Any) -> None:
    declared = manifest.get("hooks")
    entries = declared if isinstance(declared, list) else [declared] if declared else []
    if (plugin.path / "hooks" / "hooks.json").is_file():
        entries = ["./hooks/hooks.json", *entries]
    for entry in entries:
        if isinstance(entry, dict):
            plugin.hooks.append(entry)
            continue
        path = _inside(plugin, str(entry), note)
        if path is None:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            note(f"{entry} is not valid JSON ({error})")
            continue
        if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict):
            note(f'{entry} must wrap its events in a top-level "hooks" key')
            continue
        plugin.hooks.append(data["hooks"])


def _load_mcp(plugin: Plugin, manifest: dict[str, Any], note: Any) -> None:
    declared = manifest.get("mcpServers")
    entries = declared if isinstance(declared, list) else [declared] if declared else []
    if (plugin.path / ".mcp.json").is_file():
        entries = ["./.mcp.json", *entries]
    for entry in entries:
        servers = entry if isinstance(entry, dict) else None
        if servers is None:
            path = _inside(plugin, str(entry), note)
            if path is None:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError as error:
                note(f"{entry} is not valid JSON ({error})")
                continue
            servers = data.get("mcpServers", data) if isinstance(data, dict) else {}
        for name, config in servers.items():
            if isinstance(config, dict):
                safe = re.sub(r"[^A-Za-z0-9_-]+", "_", f"plugin_{plugin.name}_{name}")
                plugin.mcp_servers[safe] = _fill_all(plugin, config)


def _fill(plugin: Plugin, text: str) -> str:
    return text.replace(_ROOT_VAR, str(plugin.path))


def _fill_all(plugin: Plugin, value: Any) -> Any:
    """*value* with the plugin root filled into every string inside it."""
    if isinstance(value, str):
        return _fill(plugin, value)
    if isinstance(value, list):
        return [_fill_all(plugin, item) for item in value]
    if isinstance(value, dict):
        return {key: _fill_all(plugin, item) for key, item in value.items()}
    return value
