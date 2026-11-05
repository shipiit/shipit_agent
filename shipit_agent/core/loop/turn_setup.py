"""The first phase of a turn: hooks and guardrails, tools, the system prompt and prior history.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

import asyncio
from typing import Any

from shipit_agent.context.session_facts import FactLedger
from shipit_agent.core.loop.turn import Turn
from shipit_agent.core.models import Message
from shipit_agent.core.runtime_core import (
    evict_prior_tool_outputs,
)
from shipit_agent.core.state import (
    RuntimeState,
)
from shipit_agent.core.tool_runner import ToolRunner
from shipit_agent.llms.base import (
    LLMResponse,
)
from shipit_agent.tools.helpers import build_tools_prompt


class TurnSetupMixin:
    """The first phase of a turn: hooks and guardrails, tools, the system prompt and prior history."""

    async def _begin_turn(
        self,
        user_prompt: str,
        *,
        user_content: list[dict[str, Any]] | None = None,
    ) -> Turn | tuple[RuntimeState, LLMResponse]:
        """Prepare a turn: hooks and guardrails, tools, system prompt, prior history.

        Returns the :class:`Turn` the steps run on, or a finished ``(state,
        response)`` when a prompt hook or guardrail refuses the turn outright.
        """
        state = RuntimeState()

        if self.verify_before_stop:
            from pathlib import Path

            from shipit_agent.verify import VerifyGate

            root = VerifyGate.project_root_from_output_dir(self.tool_output_dir)
            db = (
                str(Path(root) / ".shipit" / "verify.db")
                if root not in ("", ".")
                else ":memory:"
            )
            try:
                state.verify_gate = VerifyGate(
                    session_id=self.session_id, root=root, db_path=db
                )
            except Exception:
                state.verify_gate = None

        # on_user_prompt hooks: rewrite or block before anything else sees it.
        user_prompt, hook_refusal = self.apply_user_prompt_hooks(state, user_prompt)
        if hook_refusal is not None:
            self.emit(
                state,
                "run_completed",
                "Run blocked by a prompt hook",
                output=hook_refusal,
                content=hook_refusal,
                format="markdown",
                usage={},
                cancelled=False,
            )
            return state, LLMResponse(content=hook_refusal)

        # Guardrails: blocked prompts never reach the LLM.
        user_prompt, refusal = self.check_input(state, user_prompt)
        if refusal is not None:
            self.emit(
                state,
                "run_completed",
                "Run blocked by guardrails",
                output=refusal,
                content=refusal,
                format="markdown",
                usage={},
                cancelled=False,
                guardrail_blocked=True,
            )
            return state, LLMResponse(content=refusal)

        # MCP discovery may spawn processes and perform several network
        # handshakes. Keep it off the application event loop.
        registry = await asyncio.to_thread(self.registry)
        # Build the capability control plane before the system prompt so the
        # model sees the same connection/MCP metadata that tools can search.
        shared_state: dict[str, Any] = self.build_shared_state(registry, state)
        initially_required = self.initial_required_tool_names(user_prompt, registry)
        if initially_required:
            shared_state["forced_tool_names"] = initially_required
        elif self.require_tool_call and list(registry.values()):
            shared_state["force_any_tool"] = True
        tool_prompt = build_tools_prompt(
            registry.values(),
            connections=self.connections.all(),
            mcps=self.mcps,
            supports_parallel_tool_calls=self.model_supports_parallel_tool_calls(),
        )
        base_prompt = (
            self.prompt if not tool_prompt else f"{self.prompt}\n\n{tool_prompt}"
        )
        existing_session = self.session_store.load(self.session_id)
        self.restore_discovery(
            existing_session.metadata.get("tool_discovery")
            if existing_session
            else self.metadata.get("tool_discovery")
        )
        if existing_session:
            self.token_calibrator.restore(
                existing_session.metadata.get("token_calibration")
            )
            stored_checkpoint = existing_session.metadata.get("compaction_checkpoint")
            if (
                self.context_window_tokens >= 0
                and isinstance(stored_checkpoint, dict)
                and not self.compactor().latest()
            ):
                from shipit_agent.context.compaction import CompactionCheckpoint

                checkpoint = CompactionCheckpoint.from_dict(stored_checkpoint)
                if checkpoint.summary and checkpoint.compacted_to <= len(
                    existing_session.messages
                ):
                    self.compactor().checkpoints.append(checkpoint)
            prior_messages = existing_session.messages
        elif self.history_messages:
            prior_messages = self.history_messages
        else:
            prior_messages = []
        fact_ledger = FactLedger.from_serialized(
            existing_session.metadata.get("verified_facts")
            if existing_session
            else None
        )
        recall_tool_name = (
            self.install_result_recall(registry, prior_messages)
            if self.evict_prior_tool_outputs
            else ""
        )
        if recall_tool_name:
            shared_state.update(self.build_shared_state(registry, state))
            tool_prompt = build_tools_prompt(
                registry.values(),
                connections=self.connections.all(),
                mcps=self.mcps,
                supports_parallel_tool_calls=(
                    self.model_supports_parallel_tool_calls()
                ),
            )
            base_prompt = (
                self.prompt if not tool_prompt else f"{self.prompt}\n\n{tool_prompt}"
            )
        # Earlier turns' tool payloads have already been read into the
        # answers below them; re-sending them costs their whole length on
        # every step of this turn. The calls and arguments stay.
        #
        # Eviction is a per-REQUEST view only — the originals are kept aside
        # and written back at save time. (See sync AgentRuntime for details.)
        original_prior = [m for m in prior_messages if m.role != "system"]
        if self.evict_prior_tool_outputs:
            prior_messages = evict_prior_tool_outputs(
                list(prior_messages), recall_tool_name=recall_tool_name
            )
        # Exactly one fresh system message at the front; strip any persisted
        # system messages from prior turns so multi-turn sessions don't stack
        # duplicates and grow unbounded. (See sync AgentRuntime for details.)
        state.messages.append(
            Message(role="system", content=base_prompt, metadata=dict(self.metadata))
        )
        state.messages.extend(m for m in prior_messages if m.role != "system")
        rendered_facts = fact_ledger.render()
        if rendered_facts:
            state.messages.append(
                Message(
                    role="assistant",
                    content=rendered_facts,
                    metadata={"internal": True, "kind": "verified_session_facts"},
                )
            )
        state.messages.append(
            Message(
                role="user",
                content=user_content or user_prompt,
                metadata={"turn_start": True},
            )
        )

        self.emit(state, "run_started", "Agent run started", prompt=user_prompt)

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

        tool_schemas = registry.schemas()
        # Built by RuntimeCore, so both loops publish identical tool state.
        tool_runner = ToolRunner(registry)

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
                core_prompt = build_tools_prompt(
                    core_tools,
                    connections=self.connections.all(),
                    supports_parallel_tool_calls=(
                        self.model_supports_parallel_tool_calls()
                    ),
                )
                base_prompt = "\n\n".join(
                    part for part in (self.prompt, core_prompt, index) if part
                )
                state.messages[0] = Message(
                    role="system", content=base_prompt, metadata=dict(self.metadata)
                )
                tool_schemas = [
                    schema
                    for schema in tool_schemas
                    if (schema.get("function") or {}).get("name") in CORE_TOOLS
                ]

        # Deferred tool loading — same decision as the sync loop, made by
        # RuntimeCore: core schemas stay resident, the rest are names in an
        # index until tool_search (or a direct call) loads them.
        deferral_index = self.setup_deferral(registry, shared_state)
        if deferral_index or (
            shared_state.get("discovery_hidden") and not self.code_mode
        ):
            tool_schemas = registry.schemas()
            from shipit_agent.deferral import DEFERRED_NAMES_KEY

            deferred_names = shared_state.get(DEFERRED_NAMES_KEY) or set()
            resident_tools = [
                tool
                for tool in registry.values()
                if getattr(tool, "name", "") not in deferred_names
                and getattr(tool, "name", "")
                not in shared_state.get("discovery_hidden", set())
            ]
            resident_prompt = build_tools_prompt(
                resident_tools,
                connections=self.connections.all(),
                mcps=self.mcps,
                supports_parallel_tool_calls=self.model_supports_parallel_tool_calls(),
            )
            base_prompt = "\n\n".join(
                part for part in (self.prompt, resident_prompt, deferral_index) if part
            )
            state.messages[0] = Message(
                role="system", content=base_prompt, metadata=dict(self.metadata)
            )

        await self._run_planner_if_needed(
            state=state,
            registry=registry,
            user_prompt=user_prompt,
            base_prompt=base_prompt,
            shared_state=shared_state,
            tool_runner=tool_runner,
        )

        return Turn(
            user_prompt=user_prompt,
            state=state,
            registry=registry,
            tool_runner=tool_runner,
            tool_schemas=tool_schemas,
            base_prompt=base_prompt,
            shared_state=shared_state,
            existing_session=existing_session,
            fact_ledger=fact_ledger,
            original_prior=original_prior,
        )
