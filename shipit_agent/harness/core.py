"""The harness: settings files and plugins, applied to an agent.

    harness = Harness.load(cwd, plugins=[{"type": "local", "path": "./my-plugin"}],
                           setting_sources=["project", "local"])
    agent = Agent(llm=llm, harness=harness)
    agent.run("/my-plugin:review src/app.py")

Settings files are read only for the sources named: they can declare hook
commands, and a library has no "do you trust this folder?" prompt, so
nothing on disk runs unless the caller asked for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from shipit_agent.skills.registry import split_frontmatter

from .command_hooks import command_hook_matchers
from .plugins import Plugin, load_plugin
from .settings import HarnessSettings, SettingSource, load_settings_sources

__all__ = ["Harness"]


@dataclass
class Harness:
    cwd: Path
    plugins: list[Plugin] = field(default_factory=list)
    settings: HarnessSettings = field(default_factory=HarnessSettings)
    commands: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    #: This harness's hooks, built once. Agent.clone() copies an agent's
    #: hooks and applies the harness again, so they are merged by identity.
    _hooks: Any = field(default=None, repr=False)

    @classmethod
    def load(
        cls,
        cwd: str | Path = ".",
        *,
        plugins: list[Any] | None = None,
        setting_sources: list[SettingSource] | None = None,
    ) -> "Harness":
        root = Path(cwd).resolve()
        harness = cls(cwd=root, settings=load_settings_sources(setting_sources, root))
        harness.errors.extend(harness.settings.errors)
        for spec in plugins or []:
            plugin = load_plugin(spec, cwd=root, errors=harness.errors)
            if plugin is not None:
                harness.plugins.append(plugin)
                harness.commands.update(plugin.commands)
        if "project" in (setting_sources or []):
            harness.commands.update(_project_commands(root))
        return harness

    @property
    def skills(self) -> list[Any]:
        return [skill for plugin in self.plugins for skill in plugin.skills]

    def expand(self, prompt: str) -> str | None:
        """``/name args`` as the command's text (``$ARGUMENTS``, ``$1``...), or ``None``.

        A plugin skill invoked by name (``/plugin:skill``) becomes its instructions.
        """
        if not prompt.startswith("/") or len(prompt) < 2:
            return None
        name, _, args = prompt[1:].partition(" ")
        body = self.commands.get(name)
        if body is None:
            skill = next((s for s in self.skills if s.id == name), None)
            if skill is None:
                return None
            body = f"{skill.prompt_template}\n\n$ARGUMENTS".strip()
        args = args.strip()
        text = body.replace("$ARGUMENTS", args)
        for index, token in enumerate(args.split(), start=1):
            text = text.replace(f"${index}", token)
        return text.strip()

    def apply(self, agent: Any) -> None:
        """Add the plugins' and settings' skills, agents, hooks, MCP servers and rules to *agent*."""
        from shipit_agent.safety.hooks import AgentHooks
        from shipit_agent.sdk.build import mcp_servers
        from shipit_agent.skills import SkillRegistry

        if self.skills:
            if agent.skill_registry is None:
                agent.skill_registry = SkillRegistry()
            for skill in self.skills:
                agent.skill_registry.register(skill)
        plugin_agents = {name: d for plugin in self.plugins for name, d in plugin.agents.items()}
        if plugin_agents:
            agent.agents = {**plugin_agents, **dict(agent.agents or {})}
        present = {getattr(server, "name", None) for server in agent.mcps}
        servers = {name: config for plugin in self.plugins for name, config in plugin.mcp_servers.items()
                   if name not in present}
        if servers:
            agent.mcps = [*agent.mcps, *mcp_servers(servers)]
        self._apply_rules(agent)
        if self._hooks is None:
            self._hooks = self._build_hooks(agent)
        hooks = agent.hooks if agent.hooks is not None else AgentHooks()
        for item in fields(hooks):
            registered = getattr(hooks, item.name)
            if isinstance(registered, list):
                registered.extend(fn for fn in getattr(self._hooks, item.name) if fn not in registered)
        agent.hooks = hooks

    def _build_hooks(self, agent: Any) -> Any:
        """The settings' and plugins' command hooks, as one hooks registry."""
        from shipit_agent.safety.hooks import AgentHooks
        from shipit_agent.sdk.hooks import build_agent_hooks

        hooks = AgentHooks()
        base = {"session_id": agent.session_id or "", "transcript_path": "", "cwd": str(self.cwd),
                "permission_mode": agent.permission_mode}
        for label, events, _ in self.settings.hooks:
            matchers = command_hook_matchers(events, project_dir=self.cwd, env=self.settings.env,
                                             source=label, errors=self.errors)
            build_agent_hooks(matchers, base=base, into=hooks)
        for plugin in self.plugins:
            for events in plugin.hooks:
                matchers = command_hook_matchers(events, project_dir=self.cwd, plugin_root=plugin.path,
                                                 env=self.settings.env, source=f"plugin {plugin.name}",
                                                 errors=self.errors)
                build_agent_hooks(matchers, base=base, into=hooks)
        return hooks

    def _apply_rules(self, agent: Any) -> None:
        agent.allowed_tools = _merged(agent.allowed_tools, self.settings.allow)
        agent.disallowed_tools = _merged(agent.disallowed_tools, self.settings.deny)
        if self.settings.ask:
            agent.permissions = _with_ask(agent.permissions, agent.permission_mode, self.settings.ask)
        if self.settings.default_mode and agent.permission_mode == "default":
            agent.permission_mode = self.settings.default_mode

    def info(self) -> dict[str, Any]:
        """What the SDK's ``init`` message reports about plugins, skills and commands."""
        return {
            "plugins": [{"name": p.name, "path": str(p.path)} for p in self.plugins],
            "plugin_errors": list(self.errors),
            "skills": sorted(skill.id for skill in self.skills),
            "slash_commands": sorted({*self.commands, *(skill.id for skill in self.skills)}),
        }


def _merged(rules: list[str], extra: list[str]) -> list[str]:
    return [*rules, *(rule for rule in extra if rule not in rules)]


def _with_ask(permissions: Any, mode: str, ask: list[str]) -> Any:
    from shipit_agent.safety.permissions import coerce_permissions

    engine = coerce_permissions(permissions) or coerce_permissions(mode)
    engine.ask = [*engine.ask, *(rule for rule in ask if rule not in engine.ask)]
    return engine


def _project_commands(cwd: Path) -> dict[str, str]:
    folder = cwd / ".claude" / "commands"
    if not folder.is_dir():
        return {}
    commands = {}
    for path in sorted(folder.glob("*.md")):
        _, body = split_frontmatter(path.read_text(encoding="utf-8"))
        commands[path.stem] = body.strip()
    return commands
