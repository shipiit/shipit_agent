"""The first phase of a turn: screen the prompt, load tools and history, open the transcript.

Prior history lives in :mod:`.turn_history`; which tools are advertised, in
:mod:`.turn_tools`.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

import asyncio
from typing import Any

from shipit_agent.core.loop.turn import Turn
from shipit_agent.core.state import (
    RuntimeState,
)
from shipit_agent.core.tool_runner import ToolRunner
from shipit_agent.llms.base import (
    LLMResponse,
)


class TurnSetupMixin:
    """The first phase of a turn: screen the prompt, load tools and history, open the transcript."""

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
        state.verify_gate = self._open_verify_gate()

        user_prompt, refusal = self._screen_prompt(state, user_prompt)
        if refusal is not None:
            return state, refusal

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
        tool_prompt = self._tools_prompt(registry.values())
        base_prompt = (
            self.prompt if not tool_prompt else f"{self.prompt}\n\n{tool_prompt}"
        )

        prior = self._load_prior_turns(registry)
        if prior.recall_installed:
            # The recall tool joined the registry: re-publish tool state and
            # describe it in the prompt.
            shared_state.update(self.build_shared_state(registry, state))
            tool_prompt = self._tools_prompt(registry.values())
            base_prompt = (
                self.prompt if not tool_prompt else f"{self.prompt}\n\n{tool_prompt}"
            )
        self._open_transcript(
            state,
            base_prompt=base_prompt,
            prior=prior,
            user_prompt=user_prompt,
            user_content=user_content,
        )

        self.emit(state, "run_started", "Agent run started", prompt=user_prompt)
        self._announce_attachments(state)

        tool_runner = ToolRunner(registry)
        tool_schemas, base_prompt = self._advertise_tools(
            state,
            registry=registry,
            tool_runner=tool_runner,
            shared_state=shared_state,
            user_prompt=user_prompt,
            base_prompt=base_prompt,
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
            existing_session=prior.session,
            fact_ledger=prior.fact_ledger,
            original_prior=prior.original,
        )

    def _open_verify_gate(self) -> Any:
        """The verify gate for this turn, or ``None`` when it is off or unavailable.

        Its ledger lives in the project's ``.shipit/verify.db``, or in memory
        when there is no project root.
        """
        if not self.verify_before_stop:
            return None
        from pathlib import Path

        from shipit_agent.verify import VerifyGate

        root = VerifyGate.project_root_from_output_dir(self.tool_output_dir)
        db = (
            str(Path(root) / ".shipit" / "verify.db")
            if root not in ("", ".")
            else ":memory:"
        )
        try:
            return VerifyGate(session_id=self.session_id, root=root, db_path=db)
        except Exception:
            # Verification is an aid, not a requirement: without a usable
            # ledger the turn runs without the gate.
            return None

    def _screen_prompt(
        self, state: RuntimeState, user_prompt: str
    ) -> tuple[str, LLMResponse | None]:
        """Run prompt hooks, then guardrails, on the user's prompt.

        Returns the prompt as rewritten, and a refusal response when either
        one blocks the turn; a blocked prompt never reaches the model.
        """
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
            return user_prompt, LLMResponse(content=hook_refusal)

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
            return user_prompt, LLMResponse(content=refusal)
        return user_prompt, None
