"""Building the :class:`~shipit_agent.Agent` an :class:`AgentOptions` describes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shipit_agent.safety.hooks import AgentHooks
from shipit_agent.safety.permission_rules import rule_names_tool, sdk_tool_name

from .hooks import build_agent_hooks
from .options import DEFAULT_TOOLS, AgentOptions
from .permissions import permission_callback

__all__ = ["build_agent", "llm_for_model"]

_OPENAI_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt-")


def build_agent(options: AgentOptions) -> Any:
    """The agent for *options*; every option lands on the matching Agent setting."""
    from shipit_agent import Agent

    llm = options.llm if options.llm is not None else llm_for_model(options.model)
    for name in ("effort", "thinking"):
        value = getattr(options, name)
        if value is not None and hasattr(llm, name):
            setattr(llm, name, value)
    root = Path(options.cwd).resolve() if options.cwd else Path.cwd()
    settings: dict[str, Any] = {
        "llm": llm,
        "prompt": system_prompt(options.system_prompt),
        "tools": tools_for(options.tools, llm=llm, root=root),
        "mcps": mcp_servers(options.mcp_servers),
        "project_root": root,
        "permission_mode": options.permission_mode,
        "allowed_tools": list(options.allowed_tools),
        "disallowed_tools": list(options.disallowed_tools),
        "max_turns": options.max_turns,
        "max_budget_usd": options.max_budget_usd,
        "fallback_model": options.fallback_model,
    }
    if options.can_use_tool is not None:
        settings["permission_callback"] = permission_callback(options.can_use_tool)
    if options.agents:
        settings["agents"] = dict(options.agents)
    if options.session_id:
        settings["session_id"] = options.session_id
    if options.hooks is not None:
        settings["hooks"] = _hooks(options, root)
    settings.update(options.agent_options)
    return Agent(**settings)


def llm_for_model(model: str | None) -> Any:
    """An adapter for *model*, with the provider read from its name."""
    from shipit_agent.llms.factory import build_llm_from_env, build_llm_from_settings

    if not model:
        return build_llm_from_env()
    name = model.lower()
    if name.startswith(("claude", "anthropic/")):
        provider = "anthropic"
    elif name.startswith(_OPENAI_PREFIXES):
        provider = "openai"
    elif name.startswith("bedrock/"):
        provider = "bedrock"
    else:
        provider = "litellm"
    return build_llm_from_settings({"model": model.removeprefix("anthropic/")}, provider=provider)


def system_prompt(spec: str | dict[str, Any] | None) -> str:
    from shipit_agent.prompts.default_agent_prompt import DEFAULT_AGENT_PROMPT

    if spec is None:
        return DEFAULT_AGENT_PROMPT
    if isinstance(spec, str):
        return spec
    kind = spec.get("type")
    if kind == "preset":
        append = str(spec.get("append") or "").strip()
        return f"{DEFAULT_AGENT_PROMPT.rstrip()}\n\n{append}" if append else DEFAULT_AGENT_PROMPT
    if kind == "custom":
        return str(spec.get("prompt") or "")
    if kind == "file":
        return Path(str(spec["path"])).read_text(encoding="utf-8")
    raise ValueError(f"unknown system_prompt type {kind!r}; expected preset, custom or file")


def tools_for(spec: list[Any] | str | None, *, llm: Any, root: Path) -> list[Any]:
    from shipit_agent.agent_setup.builtins import get_builtin_tool_map

    if isinstance(spec, list) and all(not isinstance(item, str) for item in spec):
        return list(spec)
    builtins = get_builtin_tool_map(llm=llm, project_root=str(root))
    if spec == "all":
        return list(builtins.values())
    if spec is None:
        return [builtins[name] for name in DEFAULT_TOOLS if name in builtins]
    if isinstance(spec, str):
        raise ValueError('tools must be None, "all", or a list')
    chosen: list[Any] = []
    for item in spec:
        if not isinstance(item, str):
            chosen.append(item)
            continue
        primary = sdk_tool_name(item)
        if primary is not None:
            matches = [builtins[primary]] if primary in builtins else []
        else:
            matches = [tool for name, tool in builtins.items() if rule_names_tool(item, name)]
        if not matches:
            raise ValueError(f"no built-in tool is named {item!r}")
        chosen.extend(tool for tool in matches if tool not in chosen)
    return chosen


def mcp_servers(spec: dict[str, Any] | list[Any]) -> list[Any]:
    from shipit_agent.mcp import (
        MCPServer,
        MCPStreamableHTTPTransport,
        PersistentMCPSubprocessTransport,
        RemoteMCPServer,
    )

    if isinstance(spec, list):
        return list(spec)
    servers: list[Any] = []
    for name, config in spec.items():
        if isinstance(config, MCPServer):
            servers.append(config)
            continue
        kind = config.get("type") or ("stdio" if "command" in config else None)
        if kind == "sdk":
            servers.append(config["instance"])
        elif kind == "stdio":
            command = [str(config["command"]), *map(str, config.get("args") or [])]
            transport = PersistentMCPSubprocessTransport(command=command, env=config.get("env"))
            servers.append(RemoteMCPServer(name=name, transport=transport, include_server_in_tool_names=True))
        elif kind == "http":
            transport = MCPStreamableHTTPTransport(str(config["url"]), headers=config.get("headers"))
            servers.append(RemoteMCPServer(name=name, transport=transport, include_server_in_tool_names=True))
        else:
            raise ValueError(f"MCP server {name!r}: type {kind!r} is not supported (use stdio, http or sdk)")
    return servers


def _hooks(options: AgentOptions, root: Path) -> AgentHooks:
    if isinstance(options.hooks, AgentHooks):
        return options.hooks
    base = {
        "session_id": options.session_id or "",
        "transcript_path": "",
        "cwd": str(root),
        "permission_mode": options.permission_mode,
    }
    return build_agent_hooks(dict(options.hooks), base=base)
