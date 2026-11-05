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
    "glob_files", "grep_files", "web_search", "open_url", "todo", "ask_user", "memory",
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
    permission_mode: str = "default"
    can_use_tool: Any = None
    #: ``{"PreToolUse": [HookMatcher(...)], ...}``, or an ``AgentHooks``.
    hooks: Any = None
    agents: dict[str, Any] | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    cwd: str | Path | None = None
    #: ``{"type": "json_schema", "schema": {...}}``: the answer must match it,
    #: and arrives parsed as ``ResultMessage.structured_output``.
    output_format: dict[str, Any] | None = None
    include_partial_messages: bool = False
    #: Record files before the file tools change them, for ``AgentClient.rewind_files``.
    enable_file_checkpointing: bool = False
    session_id: str | None = None
    #: Continue a saved session from ``session_store``; with ``fork_session``,
    #: continue a copy of it under a new id instead.
    resume: str | None = None
    fork_session: bool = False
    session_store: Any = None
    #: Passed to the model adapter when it takes them (Anthropic does).
    effort: str | None = None
    thinking: str | dict[str, Any] | None = None
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
