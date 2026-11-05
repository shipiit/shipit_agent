"""Turning one call into runtime options: slash commands, attachments, and the runtime's settings.

Mixed into :class:`~shipit_agent.agent.Agent`; the methods run on the agent.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

# Moved methods log under the agent's own name, so filters and levels
# configured for it keep applying.
logger = logging.getLogger("shipit_agent.agent")


class RunOptionsMixin:
    """Turning one call into runtime options: slash commands, attachments, and the runtime's settings."""

    def _expand_slash_command(self, user_prompt: str) -> str:
        """Expand a ``/command`` from ``.shipit/commands/``; else pass through."""
        if not isinstance(user_prompt, str) or not user_prompt.startswith("/"):
            return user_prompt
        from shipit_agent.workspace import expand_command

        expanded = expand_command(self.project_root, user_prompt)
        return expanded if expanded is not None else user_prompt

    def _user_content_blocks(
        self,
        prompt_text: str,
        images: list[str] | None,
        files: list[str] | None = None,
    ) -> list[dict[str, Any]] | None:
        """Content blocks for a user turn with attachments, or None.

        None keeps every existing caller on the exact string path they had —
        blocks appear only when the turn actually carries attachments.
        """
        if not images and not files and self.media_parser is None:
            return None
        blocks: list[dict[str, Any]] | None = None
        if self.media_parser is not None:
            from shipit_agent.multimodal import build_multimodal_message

            try:
                parsed = self.media_parser.parse(prompt_text)
                blocks = list(build_multimodal_message(parsed).get("content") or [])
            except Exception:
                logger.warning("media_parser failed; sending prompt as text only")
                blocks = None
        if blocks is None:
            blocks = [{"type": "text", "text": prompt_text}]
        base_block_count = len(blocks)
        # Images FIRST, ahead of the prose. Several vision models — Gemma 4 on
        # Bedrock among them — read an image best when it precedes the text that
        # asks about it, so prepend rather than append.
        if images:
            from shipit_agent.multimodal.builder import image_block_from

            image_blocks = [image_block_from(image) for image in images]
            blocks = image_blocks + blocks
        if files:
            from shipit_agent.multimodal.builder import file_blocks_from

            for file in files:
                blocks.extend(file_blocks_from(file))
        nothing_attached = len(blocks) == base_block_count and all(
            isinstance(b, dict) and b.get("type") == "text" for b in blocks
        )
        return None if nothing_attached else blocks

    def _runtime_options(
        self,
        *,
        user_prompt: str,
        selected_skills: list[Any],
        effective_tools: list[Any],
        skill_ids: list[str],
        skill_tool_names: list[str],
        skill_details: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """One runtime configuration path shared by sync and async APIs."""
        return {
            "llm": self.llm,
            "decision_llm": self.decision_llm,
            "progress_summaries": self.progress_summaries,
            "reminder": self.reminder,
            "evict_prior_tool_outputs": self.evict_prior_tool_outputs,
            "prompt": self._effective_prompt(
                user_prompt, selected_skills=selected_skills
            ),
            "tools": effective_tools,
            "mcps": self.mcps,
            "required_tools": self.required_tools,
            "require_tool_call": self.require_tool_call,
            "max_required_tool_text_chars": self.max_required_tool_text_chars,
            "max_completion_text_chars": self.max_completion_text_chars,
            "max_tool_argument_chars": self.max_tool_argument_chars,
            "metadata": {
                "agent_name": self.name,
                "agent_description": self.description,
                **self.metadata,
                "max_task_tokens": self.max_task_tokens,
                "max_session_tokens": self.max_session_tokens,
                "max_budget_usd": self.max_budget_usd,
                "used_skills": skill_ids,
                "used_skill_tools": skill_tool_names,
                "selected_skills": skill_details,
            },
            "history_messages": list(self.history),
            "memory_store": self.memory_store,
            "session_store": self.session_store,
            "session_id": self.session_id,
            "trace_store": self._resolved_trace_store(),
            "trace_id": self.trace_id,
            "max_iterations": self._effective_max_iterations(selected_skills),
            "retry_policy": self.retry_policy,
            "router_policy": self.router_policy,
            "credential_store": self.credential_store,
            "parallel_tool_execution": self.parallel_tool_execution,
            "max_tool_concurrency": self.max_tool_concurrency,
            "hooks": self.hooks,
            "context_window_tokens": self.context_window_tokens,
            "fixed_prefix_tokens": self.fixed_prefix_tokens,
            "max_tool_output_chars": self.max_tool_output_chars,
            "max_tool_output_group_chars": self.max_tool_output_group_chars,
            "tool_output_dir": (
                str(Path(self.project_root) / ".shipit" / "tool-results")
                if self.persist_large_tool_outputs
                else None
            ),
            "replan_interval": self.replan_interval,
            "permissions": self._effective_permissions(),
            "guardrails": self.guardrails,
            "heal_tool_calls": self.heal_tool_calls,
            "approvals": self.approvals,
            "code_mode": self.code_mode,
            "deferred_tools": self.deferred_tools,
            "lockdown": self.lockdown,
            "verify_before_stop": self.verify_before_stop,
            "response_format": response_format,
            "session_runtime_state": self._session_runtime_state,
            "close_mcps_on_finish": False,
            "stream_queue_maxsize": self.stream_queue_maxsize,
            "cancel_on_stream_close": self.cancel_on_stream_close,
            "stream_join_timeout": self.stream_join_timeout,
        }

    def _resolved_trace_store(self) -> Any:
        """The trace store to run with, honouring ``observability``.

        Import failures and misconfiguration are swallowed on purpose:
        observability that can stop a run is worse than none, because the
        run is the thing the user actually asked for.
        """
        if self.trace_store is not None:
            return self.trace_store
        if self.observability is False:
            return None
        try:
            from shipit_agent.tracing_exporters import WatcherExporter

            if self.observability != "auto":
                return WatcherExporter()
            from shipit_watcher import get_config

            return WatcherExporter() if get_config().is_active else None
        except Exception:
            logger.debug("shipit-watcher not available", exc_info=True)
            return None
