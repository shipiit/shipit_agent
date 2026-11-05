"""Which tools a turn advertises, and how the system prompt describes them.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

import asyncio
from typing import Any, Iterable

from shipit_agent.core.models import Message
from shipit_agent.core.registry import ToolRegistry
from shipit_agent.core.state import RuntimeState
from shipit_agent.core.tool_runner import ToolRunner
from shipit_agent.tools.helpers import build_tools_prompt


class TurnToolsMixin:
    """Which tools a turn advertises, and how the system prompt describes them."""

    def _tools_prompt(self, tools: Iterable[Any], *, with_mcps: bool = True) -> str:
        """The tools section of the system prompt for *tools*."""
        return build_tools_prompt(
            tools,
            connections=self.connections.all(),
            mcps=self.mcps if with_mcps else (),
            supports_parallel_tool_calls=self.model_supports_parallel_tool_calls(),
        )

    def _system_prompt(self, *sections: str) -> str:
        """The agent's prompt followed by each non-empty section."""
        return "\n\n".join(part for part in (self.prompt, *sections) if part)

    def _announce_attachments(self, state: RuntimeState) -> None:
        """Report the skills selected for this turn and the attached MCP servers."""
        selected_skills = self.metadata.get("selected_skills", [])
        if isinstance(selected_skills, list) and selected_skills:
            skill_ids = [
                str(skill.get("id", ""))
                for skill in selected_skills
                if isinstance(skill, dict) and skill.get("id")
            ]
            self.emit(
                state,
                "skills_selected",
                "Skills selected: " + ", ".join(skill_ids),
                skills=[
                    dict(skill) for skill in selected_skills if isinstance(skill, dict)
                ],
                skill_ids=skill_ids,
                injected_tools=list(self.metadata.get("used_skill_tools", [])),
                count=len(skill_ids),
            )
        for mcp in self.mcps:
            self.emit(
                state,
                "mcp_attached",
                f"MCP server attached: {mcp.name}",
                server=mcp.name,
            )

    def _advertise_tools(
        self,
        state: RuntimeState,
        *,
        registry: ToolRegistry,
        tool_runner: ToolRunner,
        shared_state: dict[str, Any],
        user_prompt: str,
        base_prompt: str,
    ) -> tuple[list[dict[str, Any]], str]:
        """Choose the schemas sent to the model, and the system prompt that matches.

        Starts from every tool. Code mode narrows the schemas to its core tools
        plus an index the script can call; deferred loading keeps only resident
        tools and lists the rest by name until ``tool_search`` loads them.
        Returns ``(tool_schemas, base_prompt)``; when the prompt changes, the
        transcript's system message is replaced to match.
        """
        tool_schemas = registry.schemas()

        if self.code_mode:
            index = self._install_code_mode(
                state=state,
                registry=registry,
                tool_runner=tool_runner,
                shared_state=shared_state,
                user_prompt=user_prompt,
                base_prompt=base_prompt,
                loop=asyncio.get_running_loop(),
            )
            if index:
                from shipit_agent.codemode import CORE_TOOLS

                core_tools = [
                    tool
                    for tool in registry.values()
                    if getattr(tool, "name", "") in CORE_TOOLS
                ]
                base_prompt = self._system_prompt(
                    self._tools_prompt(core_tools, with_mcps=False), index
                )
                self._replace_system_message(state, base_prompt)
                tool_schemas = [
                    schema
                    for schema in tool_schemas
                    if (schema.get("function") or {}).get("name") in CORE_TOOLS
                ]

        deferral_index = self.setup_deferral(registry, shared_state)
        if deferral_index or (
            shared_state.get("discovery_hidden") and not self.code_mode
        ):
            from shipit_agent.deferral import DEFERRED_NAMES_KEY

            tool_schemas = registry.schemas()
            deferred_names = shared_state.get(DEFERRED_NAMES_KEY) or set()
            hidden = shared_state.get("discovery_hidden", set())
            resident_tools = [
                tool
                for tool in registry.values()
                if getattr(tool, "name", "") not in deferred_names
                and getattr(tool, "name", "") not in hidden
            ]
            base_prompt = self._system_prompt(
                self._tools_prompt(resident_tools), deferral_index
            )
            self._replace_system_message(state, base_prompt)

        return tool_schemas, base_prompt

    def _replace_system_message(self, state: RuntimeState, base_prompt: str) -> None:
        """Swap the transcript's leading system message for *base_prompt*."""
        state.messages[0] = Message(
            role="system", content=base_prompt, metadata=dict(self.metadata)
        )
