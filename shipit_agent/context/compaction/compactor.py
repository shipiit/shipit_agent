"""Compacting a run: summarise everything before a boundary into a handoff, as a checkpoint."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from shipit_agent.core.models import Message

from .boundary import find_boundary, starts_a_turn
from .checkpoint import CompactionCheckpoint
from .limits import TARGET_RATIO, ModelLimits, get_model_limits
from .prompt import COMPACTION_SYSTEM_PROMPT
from .tokens import (
    content_tokens,
    count_messages,
    estimate_tokens,
    messages_tokens,
    should_compact,
)


class Compactor:
    """Decides when to compact, and writes the handoff.

    ``llm`` is used for the summary; any failure falls back to a mechanical
    condensation, because compaction must never be able to take a run down.
    """

    def __init__(
        self,
        *,
        llm: Any = None,
        model: str | None = None,
        context_window_tokens: int = 0,
        fixed_prefix_tokens: int = 0,
        calibrator: Any = None,
        on_summary_failure: Callable[[Exception], None] | None = None,
    ) -> None:
        self.llm = llm
        self.model = model
        # The system prompt + tool schemas are sent on EVERY call but live
        # outside ``messages``, so a trigger that counts messages alone
        # under-counts the real prompt by this whole prefix (~16k tokens on a
        # tool-heavy agent) and compacts that far too late. Counted here so the
        # decision is made against what the provider actually receives.
        self.fixed_prefix_tokens = max(0, int(fixed_prefix_tokens or 0))
        # Optional :class:`~shipit_agent.token_calibration.TokenCalibrator`.
        # When present, the estimate is scaled by its learned per-model factor
        # so ``chars/4`` drift (dense JSON tokenizes far below 4 chars/token) no
        # longer makes the trigger fire late. Read-only here; the runtime feeds
        # it real usage.
        self.calibrator = calibrator
        # An explicit window overrides the model table — useful when a caller
        # knows better (a proxy with a smaller effective limit, say).
        #
        # It is taken as the **input budget itself**, with no response
        # reservation subtracted: shipit's long-standing `context_window_tokens`
        # means "compact when the prompt approaches this", and a caller passing
        # 100 does not mean "100 minus 8k of output room", which would be
        # negative. The model table path still reserves properly.
        self.limits = (
            ModelLimits(context_window_tokens, 0)
            if context_window_tokens
            else get_model_limits(model)
        )
        self._on_summary_failure = on_summary_failure
        self.checkpoints: list[CompactionCheckpoint] = []
        # Host instructions for the summary in progress (see compact()).
        self._instructions = ""
        # Usage of the most recent summarizer call, for the caller's cost
        # accounting — a summary is a real completion and its tokens count.
        self.last_summary_usage: dict[str, int] = {}
        self.last_summary_metadata: dict[str, Any] = {}

    # ── decision ─────────────────────────────────────────────────────────

    def estimated_prompt_tokens(self, messages: Sequence[Message]) -> int:
        """What the next call's prompt will really cost: prefix + messages,
        scaled by the learned per-model correction. The single number the
        trigger and the retention target both derive from, so they never
        disagree."""
        raw = count_messages(messages, self.model) + self.fixed_prefix_tokens
        if self.calibrator is not None:
            return self.calibrator.calibrated(self.model, raw)
        return raw

    def needs_compaction(self, messages: Sequence[Message]) -> bool:
        return should_compact(
            self.estimated_prompt_tokens(messages), self.limits.input_budget
        )

    def latest(self) -> CompactionCheckpoint | None:
        return self.checkpoints[-1] if self.checkpoints else None

    def checkpoint_below(self, sequence: int) -> CompactionCheckpoint | None:
        """The newest checkpoint at or below *sequence* — for reads and reverts."""
        eligible = [c for c in self.checkpoints if c.compacted_to <= sequence]
        return max(eligible, key=lambda c: c.compacted_to) if eligible else None

    # ── compaction ───────────────────────────────────────────────────────

    def compact(
        self,
        messages: Sequence[Message],
        *,
        force: bool = False,
        instructions: str = "",
    ) -> CompactionCheckpoint | None:
        """Compact if needed; return the checkpoint, or ``None`` if nothing to do.

        *instructions* come from the host (a pre-compact hook) and are added to
        the summarizer's own, unlike the transcript, which is only data.
        """
        self._instructions = instructions
        if not force and not self.needs_compaction(messages):
            return None

        # Retain messages such that the calibrated prefix+messages count lands
        # near TARGET_RATIO of the budget. ``find_boundary`` sums UNCALIBRATED
        # counts, so back the prefix and the calibration factor out of the
        # target it is given — and hand it the same per-message counter used
        # above, so both sides of this subtraction are in one unit.
        factor = (
            self.calibrator.factor(self.model) if self.calibrator is not None else 1.0
        )
        gross = self.limits.input_budget * TARGET_RATIO
        target = int(max(1, gross / max(factor, 1.0) - self.fixed_prefix_tokens))
        # A tool-heavy fixed prefix can consume the entire retention target.
        # One token then fits no turn, disabling summarization altogether.
        # Keep at least the newest real turn; older turns can still be safely
        # summarized. Oversized individual turns remain subject to hard fit.
        newest_turn = next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if starts_a_turn(messages[index])
            ),
            None,
        )
        if newest_turn is not None:
            target = max(
                target,
                sum(
                    content_tokens(message.content or "", self.model)
                    for message in messages[newest_turn:]
                ),
            )
        boundary = find_boundary(
            messages, target, lambda content: content_tokens(content, self.model)
        )
        if boundary <= 0:
            # No valid cut point that helps — better to send an oversized
            # prompt and let the provider complain than to cut mid-turn.
            return None

        # Progressive checkpointing: an existing summary already represents
        # everything before its cut. Feed that summary plus only the NEW delta
        # to the summarizer instead of paying to summarize the conversation
        # from the beginning again. Apart from saving tokens, this prevents
        # facts in early turns being repeatedly paraphrased until they drift.
        latest = self.latest()
        delta_start = latest.compacted_to if latest is not None else 0
        if latest is not None and boundary <= delta_start:
            return None
        older: list[Message] = []
        if latest is not None:
            older.append(
                Message(
                    role="assistant",
                    content=latest.summary,
                    metadata={"compacted": True, "progressive_summary": True},
                )
            )
        older.extend(m for m in messages[delta_start:boundary] if m.role != "system")
        if not older:
            return None

        summary = self._summarize(older)
        if not summary:
            return None

        checkpoint = CompactionCheckpoint(
            compacted_to=boundary,
            summary=summary,
            tokens_before=messages_tokens(messages),
            tokens_after=estimate_tokens(summary)
            + messages_tokens(messages[boundary:]),
        )
        self.checkpoints.append(checkpoint)
        return checkpoint

    # ── the summary ──────────────────────────────────────────────────────

    @staticmethod
    def _transcript(messages: Sequence[Message]) -> list[str]:
        lines: list[str] = []
        for message in messages:
            # ``text`` extracts the prose from block-shaped (multimodal)
            # content; a summary has no use for base64 pixels.
            text = (
                (getattr(message, "text", None) or "").strip()
                if not isinstance(message.content, str)
                else (message.content or "").strip()
            )
            if message.role == "tool":
                # Raw search pages and MCP payloads are usually the largest
                # part of a run. The assistant answer after them is the durable
                # synthesis; replaying kilobytes of raw evidence into another
                # model call costs heavily and exposes the summarizer to prompt
                # injection. Preserve a compact status/error marker instead.
                metadata = dict(message.metadata or {})
                detail = ""
                if metadata.get("is_error"):
                    detail = f": {text[:500]}" if text else ""
                elif isinstance(metadata.get("summary"), str):
                    detail = f": {metadata['summary'][:500]}"
                lines.append(f"[tool {message.name or 'unknown'} completed{detail}]")
                continue
            if message.tool_calls:
                names = ", ".join(call.name for call in message.tool_calls)
                if text:
                    lines.append(f"[assistant]: {text[:2000]}")
                lines.append(f"[used tools: {names}]")
                continue
            if text:
                lines.append(f"[{message.role}]: {text[:2000]}")
        return lines

    def _summarize(self, older: Sequence[Message]) -> str:
        lines = self._transcript(older)
        self.last_summary_usage = {}
        self.last_summary_metadata = {}
        if not lines:
            return ""

        if self.llm is not None:
            try:
                response = self.llm.complete(
                    messages=[
                        Message(
                            role="user",
                            content="<transcript>\n"
                            + "\n".join(lines)
                            + "\n</transcript>",
                        )
                    ],
                    tools=[],
                    system_prompt=(
                        f"{COMPACTION_SYSTEM_PROMPT}\n\nThe host also asks the handoff "
                        f"to keep:\n{self._instructions}"
                        if self._instructions
                        else COMPACTION_SYSTEM_PROMPT
                    ),
                    metadata={"purpose": "context_compaction"},
                )
                self.last_summary_usage = dict(getattr(response, "usage", None) or {})
                self.last_summary_metadata = dict(
                    getattr(response, "metadata", None) or {}
                )
                summary = (getattr(response, "content", "") or "").strip()
                if summary:
                    return (
                        "Earlier conversation, compacted into a handoff:\n\n" + summary
                    )
            except Exception as exc:  # noqa: BLE001 - must never break the run
                if self._on_summary_failure is not None:
                    self._on_summary_failure(exc)

        # Mechanical fallback. Worse than a written handoff, but it keeps the
        # run alive and preserves the shape of what happened.
        condensed = [line[:200] for line in lines]
        return (
            "Earlier conversation (condensed mechanically — the summarizer was "
            "unavailable):\n" + "\n".join(condensed)
        )
