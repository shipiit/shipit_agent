"""Bringing earlier turns into a new one: the stored session and the opening transcript.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shipit_agent.context.session_facts import FactLedger
from shipit_agent.core.decisions.prior_outputs import evict_prior_tool_outputs
from shipit_agent.core.models import Message
from shipit_agent.core.registry import ToolRegistry
from shipit_agent.core.state import RuntimeState


@dataclass
class PriorTurns:
    """What a turn inherits from the turns before it."""

    #: The stored session this turn continues, or ``None`` for a new one.
    session: Any
    #: Earlier messages as this turn's requests will see them.
    messages: list[Message]
    #: Earlier messages as stored, written back unchanged when the turn saves.
    original: list[Message]
    fact_ledger: FactLedger
    #: True when a recall tool was added, so the tools prompt must be rebuilt.
    recall_installed: bool


class TurnHistoryMixin:
    """Bringing earlier turns into a new one: the stored session and the opening transcript."""

    def _load_prior_turns(self, registry: ToolRegistry) -> PriorTurns:
        """Load the session's history, discovery state, calibration and checkpoint.

        Earlier turns' tool payloads were already read into the answers that
        follow them, so with ``evict_prior_tool_outputs`` they are replaced by
        short notices for this turn's requests (with a recall tool to fetch
        one back). Eviction is a per-request view only: the originals are kept
        and written back at save time.
        """
        session = self.session_store.load(self.session_id)
        self.restore_discovery(
            session.metadata.get("tool_discovery")
            if session
            else self.metadata.get("tool_discovery")
        )
        if session:
            self.token_calibrator.restore(session.metadata.get("token_calibration"))
            self._restore_compaction_checkpoint(session)
            prior_messages = session.messages
        elif self.history_messages:
            prior_messages = self.history_messages
        else:
            prior_messages = []
        fact_ledger = FactLedger.from_serialized(
            session.metadata.get("verified_facts") if session else None
        )
        recall_tool_name = (
            self.install_result_recall(registry, prior_messages)
            if self.evict_prior_tool_outputs
            else ""
        )
        original = [m for m in prior_messages if m.role != "system"]
        if self.evict_prior_tool_outputs:
            prior_messages = evict_prior_tool_outputs(
                list(prior_messages), recall_tool_name=recall_tool_name
            )
        return PriorTurns(
            session=session,
            messages=list(prior_messages),
            original=original,
            fact_ledger=fact_ledger,
            recall_installed=bool(recall_tool_name),
        )

    def _restore_compaction_checkpoint(self, session: Any) -> None:
        """Resume from the session's last compaction summary, if it still applies."""
        stored = session.metadata.get("compaction_checkpoint")
        if (
            self.context_window_tokens < 0
            or not isinstance(stored, dict)
            or self.compactor().latest()
        ):
            return
        from shipit_agent.context.compaction import CompactionCheckpoint

        checkpoint = CompactionCheckpoint.from_dict(stored)
        if checkpoint.summary and checkpoint.compacted_to <= len(session.messages):
            self.compactor().checkpoints.append(checkpoint)

    def _open_transcript(
        self,
        state: RuntimeState,
        *,
        base_prompt: str,
        prior: PriorTurns,
        user_prompt: str,
        user_content: list[dict[str, Any]] | None,
    ) -> str:
        """Seed the transcript: system prompt, earlier turns, known facts, the request.

        Exactly one fresh system message leads. System messages stored by
        earlier turns are dropped, so a long session doesn't stack them. A
        caller's own ``history=`` may carry system context, such as a
        conversation summary: that is folded into the one system message.
        Returns that system text, the prompt the model calls of this turn send.
        """
        carried = [
            str(m.content)
            for m in prior.messages
            if prior.session is None and m.role == "system" and m.content and m.content != base_prompt
        ]
        system_text = "\n\n".join([base_prompt, *carried]) if carried else base_prompt
        state.messages.append(
            Message(role="system", content=system_text, metadata=dict(self.metadata))
        )
        state.messages.extend(m for m in prior.messages if m.role != "system")
        rendered_facts = prior.fact_ledger.render()
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
        return system_text
