"""``AgentOptions``: one object with the Claude Agent SDK's option names.

Every option maps onto an :class:`~shipit_agent.Agent` setting; ``build_agent``
does the mapping, so a run through :func:`~shipit_agent.sdk.query` is a run
of the same agent loop. Options that exist only because the SDK drives a CLI
process (``cli_path``, ``extra_args``, ``stderr``, ``setting_sources``) have
no counterpart here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["AgentOptions"]

#: The tools a run gets when ``tools`` is not given: the same core as the
#: Claude Code preset (sub_agent and load_skill join when they apply).
DEFAULT_TOOLS = (
    "read_file", "edit_file", "write_file", "multi_edit", "notebook_edit", "bash",
    "glob_files", "grep_files", "web_search", "open_url", "todo", "ask_user", "memory", "task_stop",
)


@dataclass
class AgentOptions:
    """How to run an agent: model, tools, permissions, hooks, limits and output."""

    #: A model id (``"claude-opus-5-5"``, ``"gpt-5.5"``, ``"bedrock/..."``) or,
    #: through ``llm``, a ready adapter. Neither: the environment's default.
    model: str | None = None
    llm: Any = None
    fallback_model: Any = None
    #: A string, ``{"type": "preset", "preset": "claude_code", "append": ...}``,
    #: ``{"type": "custom", "prompt": ...}`` or ``{"type": "file", "path": ...}``.
    system_prompt: str | dict[str, Any] | None = None
    #: ``None`` for the core tools, ``"all"`` for every built-in, or a list of
    #: tool objects and built-in names (SDK names such as ``"Bash"`` work).
    tools: list[Any] | str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    #: ``{name: config}``: ``{"type": "stdio", "command", "args", "env"}``,
    #: ``{"type": "http", "url", "headers"}``, or :func:`create_sdk_mcp_server`.
    mcp_servers: dict[str, Any] | list[Any] = field(default_factory=dict)
    #: Use only ``mcp_servers``: servers that plugins declare are left out.
    strict_mcp_config: bool = False
    permission_mode: str = "default"
    can_use_tool: Any = None
    #: ``{"PreToolUse": [HookMatcher(...)], ...}``, or an ``AgentHooks``.
    hooks: Any = None
    agents: dict[str, Any] | None = None
    #: ``[{"type": "local", "path": ...}]``: Claude Code plugins (skills,
    #: commands, agents, hooks, MCP servers). Relative paths start at ``cwd``.
    plugins: list[Any] = field(default_factory=list)
    #: The skills the main agent may use: ``None`` or ``"all"`` for every one
    #: discovered, or a list of exact skill names (or ids); ``[]`` for none.
    skills: list[str] | str | None = None
    #: Which settings files to read: ``"user"``, ``"project"``, ``"local"``.
    #: ``None`` reads none: they can run hook commands, so a caller opts in.
    setting_sources: list[str] | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    #: ``{"total": n}``: stop the run, between steps, once it has used n tokens.
    task_budget: dict[str, Any] | None = None
    cwd: str | Path | None = None
    #: Folders beside ``cwd`` the file tools may also read, write and search.
    add_dirs: list[str | Path] = field(default_factory=list)
    #: ``{"type": "json_schema", "schema": {...}}``: the answer must match it,
    #: and arrives parsed as ``ResultMessage.structured_output``.
    output_format: dict[str, Any] | None = None
    include_partial_messages: bool = False
    #: Report each hook callback as ``SystemMessage("hook_started")`` and
    #: ``SystemMessage("hook_response")`` (with ``outcome`` and ``output``).
    include_hook_events: bool = False
    #: Include a sub-agent's text and thinking in its ``AssistantMessage``s;
    #: by default only its tool calls and results are shown.
    forward_subagent_text: bool = False
    #: Record files before the file tools change them, for ``AgentClient.rewind_files``.
    enable_file_checkpointing: bool = False
    session_id: str | None = None
    #: Continue a saved session from ``session_store``; with ``fork_session``,
    #: continue a copy of it under a new id instead.
    resume: str | None = None
    #: Continue the most recently saved session in ``session_store``.
    continue_conversation: bool = False
    fork_session: bool = False
    #: With ``resume``: continue from this message of the session (a
    #: ``SessionMessage.uuid``), in a copy, so the session itself is unchanged.
    resume_session_at: str | None = None
    session_store: Any = None
    #: Passed to the model adapter when it takes them (Anthropic does).
    effort: str | None = None
    thinking: str | dict[str, Any] | None = None
    #: A thinking budget, for models that take one (adaptive thinking otherwise).
    max_thinking_tokens: int | None = None
    #: How long a cached prompt prefix lives on Claude models: ``"5m"`` (the
    #: adapter's default) or ``"1h"`` for runs that pause longer between steps.
    cache_ttl: str | None = None
    #: Anthropic beta headers to send with every request.
    betas: list[str] = field(default_factory=list)
    #: Environment variables for the commands the tools run (bash, code).
    #: They never enter this process's own environment.
    env: dict[str, str] = field(default_factory=dict)
    #: Run bash and code execution in the OS sandbox: the SDK's
    #: ``SandboxSettings`` (``{"enabled": True, ...}``). See
    #: :mod:`shipit_agent.sandbox` for what is enforced on each platform.
    sandbox: dict[str, Any] | None = None
    #: Any other :class:`~shipit_agent.Agent` setting, by its shipit name.
    agent_options: dict[str, Any] = field(default_factory=dict)

    def output_schema(self) -> dict[str, Any] | None:
        """The JSON Schema from ``output_format``, or ``None``."""
        if not self.output_format:
            return None
        if self.output_format.get("type") != "json_schema" or not isinstance(
            self.output_format.get("schema"), dict
        ):
            raise ValueError('output_format must be {"type": "json_schema", "schema": {...}}')
        return dict(self.output_format["schema"])
