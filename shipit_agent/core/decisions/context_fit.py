"""Keeping the conversation inside the context window: compaction, request fitting and re-grounding.

Mixed into :class:`~shipit_agent.core.runtime_core.RuntimeCore`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from typing import Any, Sequence

from shipit_agent.core.models import Message
from shipit_agent.llms.base import LLMResponse


class ContextFitMixin:
    """Keeping the conversation inside the context window: compaction, request fitting and re-grounding."""

    def compactor(self) -> Any:
        if self._compactor_instance is None:
            from shipit_agent.context.compaction import Compactor

            self._compactor_instance = Compactor(
                llm=self.llm,
                model=getattr(self.llm, "model", None),
                context_window_tokens=self.context_window_tokens,
                fixed_prefix_tokens=self._fixed_prefix_tokens,
                calibrator=self.token_calibrator,
            )
            self._session_runtime_state["compactor"] = self._compactor_instance
        return self._compactor_instance

    def account_request_overhead(self, tool_schemas: Sequence[Any]) -> None:
        """Include the current tool-schema payload in compaction decisions.

        Schemas are transmitted outside ``messages`` and can consume thousands
        of tokens. Calculate them on every cycle because deferred loading and
        the final tool-free synthesis step change the advertised set. A caller's
        explicit ``fixed_prefix_tokens`` remains an additive reserve.
        """
        import json

        from shipit_agent.context.compaction import content_tokens

        model = getattr(self.llm, "model", None)
        try:
            rendered = json.dumps(list(tool_schemas), sort_keys=True, default=str)
        except (TypeError, ValueError):
            rendered = repr(list(tool_schemas))
        schema_tokens = content_tokens(rendered, model) if tool_schemas else 0
        self._schema_prefix = rendered
        self._fixed_prefix_tokens = self._configured_fixed_prefix_tokens + schema_tokens
        if self._compactor_instance is not None:
            self._compactor_instance.fixed_prefix_tokens = self._fixed_prefix_tokens

    def clear_old_tool_results(self, state: Any, messages: Sequence[Message]) -> list[Message]:
        """The request without old tool results, when clearing is on; the history is untouched."""
        if self._clearing is None:
            return list(messages)
        from shipit_agent.context.compaction import content_tokens
        from shipit_agent.context.tool_result_clearing import clear_old_tool_results

        model = getattr(self.llm, "model", None)
        before = self._session_runtime_state.get("tool_results_cleared")
        view, after = clear_old_tool_results(messages, self._clearing, lambda text: content_tokens(text, model),
                                             state=before)
        if after != before:
            self._session_runtime_state["tool_results_cleared"] = after
            cleared = sum(1 for m in view if m.metadata.get("cleared"))
            self.emit(state, "tool_results_cleared", f"Cleared {cleared} old tool results from the request",
                      cleared=cleared)
        return view

    def fit_provider_request(
        self,
        state: Any,
        messages: Sequence[Message],
        *,
        iteration: int,
    ) -> list[Message]:
        """Final hard fit of the exact message view before provider dispatch."""
        from shipit_agent.context.fit import fit_messages

        compactor = self.compactor()
        budget = compactor.limits.input_budget
        messages = self.clear_old_tool_results(state, messages)

        def fits(candidate: Sequence[Message]) -> bool:
            return compactor.estimated_prompt_tokens(candidate) <= budget

        fitted, stats = fit_messages(messages, fits=fits)
        import hashlib

        from shipit_agent.context.compaction import content_tokens

        model = getattr(self.llm, "model", None)
        for message in fitted:
            category = (
                "system"
                if message.role == "system"
                else "tool_results"
                if message.role == "tool"
                else "conversation"
            )
            self._request_estimates[category] += content_tokens(
                message.content or "", model
            )
        self._request_estimates["schemas"] += max(
            0, self._fixed_prefix_tokens - self._configured_fixed_prefix_tokens
        )
        prefix = self._schema_prefix + repr(
            [m.content for m in fitted if m.role == "system"]
        )
        digest = hashlib.sha256(prefix.encode()).hexdigest()
        fingerprints = self._session_runtime_state.setdefault("request_prefixes", {})
        previous = fingerprints.pop(self.session_id, None)
        self._prefix_changes += int(previous is not None and previous != digest)
        fingerprints[self.session_id] = digest
        while len(fingerprints) > 32:
            fingerprints.pop(next(iter(fingerprints)))
        if stats["dropped_messages"] or stats["reduced_messages"]:
            self.emit(
                state,
                "context_compacted",
                "Final request fitted to the provider context window",
                mode="hard_fit",
                before=len(messages),
                after=len(fitted),
                budget_tokens=budget,
                estimated_tokens=compactor.estimated_prompt_tokens(fitted),
                iteration=iteration,
                **stats,
            )
        return fitted

    def compact(
        self,
        state: Any,
        messages: list[Message],
        iteration: int,
        shared_state: dict[str, Any] | None = None,
    ) -> list[Message]:
        """Compact if needed, emitting a notice. Returns what to send.

        The full history in ``state.messages`` never shrinks — compaction is
        a per-request view. The latest checkpoint is REUSED as long as its
        view still fits: without that reuse, every step past the threshold
        would write a brand-new summary (one extra completion per step,
        uncounted and identical). A fresh summary is only written when the
        replayed view itself outgrows the budget again.

        When a fresh summary IS written, the read-before-edit gate is reset:
        a file whose contents were just summarized out of context is no
        longer something the model can see, so editing it against a
        reconstructed ``old_text`` would be a silent staleness bug. Clearing
        the gate forces a cheap re-read (the file is often still in the hot
        tail) before the next edit is allowed.
        """
        if self.context_window_tokens < 0:
            return messages
        compactor = self.compactor()
        latest = compactor.latest()
        if latest is not None:
            view = latest.replay(messages)
            if not compactor.needs_compaction(view):
                return view
        elif not compactor.needs_compaction(messages):
            return messages
        self.emit(
            state,
            "context_compaction_started",
            "Context automatically compacting",
            before=len(messages),
            estimated_tokens=compactor.estimated_prompt_tokens(messages),
            budget_tokens=compactor.limits.input_budget,
            iteration=iteration,
        )
        instructions = (
            self.hooks.run_pre_compact(
                messages,
                {
                    "trigger": "auto",
                    "estimated_tokens": compactor.estimated_prompt_tokens(messages),
                    "budget_tokens": compactor.limits.input_budget,
                },
            )
            if self.hooks is not None
            else ""
        )
        checkpoint = compactor.compact(messages, instructions=instructions)
        if checkpoint is None:
            return latest.replay(messages) if latest is not None else messages
        self._reset_read_gate(shared_state)
        # The summary was a real completion — count its tokens.
        summary_usage = dict(getattr(compactor, "last_summary_usage", None) or {})
        if summary_usage:
            self.track_usage(
                state,
                LLMResponse(
                    usage=summary_usage,
                    metadata={
                        **getattr(compactor, "last_summary_metadata", {}),
                        "purpose": "context_compaction",
                    },
                ),
                iteration,
            )
        replayed = checkpoint.replay(messages)
        self.emit(
            state,
            "context_compacted",
            "Older turns condensed to stay within the context window",
            before=len(messages),
            after=len(replayed),
            saved_tokens=checkpoint.saved_tokens,
            checkpoints=len(compactor.checkpoints),
            iteration=iteration,
        )
        return replayed

    @staticmethod
    def _reset_read_gate(shared_state: dict[str, Any] | None) -> None:
        """Drop the read-before-edit record after a compaction.

        ``read_file`` records which paths were read (and their mtimes) so
        ``edit_file`` can refuse a write against contents the model never
        saw. After compaction those reads may be summarized away, so the
        record is stale — clearing it makes the next edit re-read first.

        The paths that WERE read are remembered so the loop can re-inject the
        most recent one as a fresh read (see ``regrounding_message``): after
        compaction the model should work from the code, not a prose summary
        of it.
        """
        if not isinstance(shared_state, dict):
            return
        shared_state["compaction_reread_hint"] = list(
            shared_state.get("read_files", [])
        )[-3:]
        shared_state["read_files"] = []
        shared_state["read_file_mtimes"] = {}

    @staticmethod
    def regrounding_messages(shared_state: dict[str, Any] | None) -> list[Message]:
        """Fresh reads of the files a just-fired compaction summarized away.

        Re-establish file state after compaction rather than leaving the
        model with a description of code. The most recently read
        files (up to 3) are re-read from disk and returned as tool messages,
        so the post-compaction context holds current contents, not prose.
        Consumes the hint so it fires once per compaction. Best-effort: an
        unreadable or vanished file is simply skipped.
        """
        if not isinstance(shared_state, dict):
            return []
        hints = shared_state.pop("compaction_reread_hint", None) or []
        messages: list[Message] = []
        read_files = list(shared_state.get("read_files", []))
        mtimes = dict(shared_state.get("read_file_mtimes", {}))
        for path_str in hints:
            try:
                from pathlib import Path

                path = Path(path_str)
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                if len(text) > 40_000:
                    text = text[:40_000] + "\n…[truncated]"
                messages.append(
                    Message(
                        role="user",
                        content=(
                            f"[re-grounding after compaction] Current contents "
                            f"of {path.name}:\n{text}"
                        ),
                        metadata={
                            "regrounding": True,
                            "internal": True,
                            "path": path_str,
                        },
                    )
                )
                # Restore the read-gate for the re-read file so an edit can
                # follow without another explicit read.
                if path_str not in read_files:
                    read_files.append(path_str)
                try:
                    mtimes[path_str] = path.stat().st_mtime_ns
                except OSError:
                    pass
            except Exception:
                continue
        if messages:
            shared_state["read_files"] = read_files
            shared_state["read_file_mtimes"] = mtimes
        return messages
