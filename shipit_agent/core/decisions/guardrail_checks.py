"""Guardrails on what goes in and out: the user's input, the final answer, and every tool result the model sees.

Mixed into :class:`~shipit_agent.core.runtime_core.RuntimeCore`;
the methods run on the runtime instance.
"""

from __future__ import annotations

import hashlib
from typing import Any

from shipit_agent.core.decisions.call_keys import _REPEAT_MIN_CHARS, _arguments_key


class GuardrailChecksMixin:
    """Guardrails on what goes in and out: the user's input, the final answer, and every tool result the model sees."""

    def check_input(self, state: Any, user_prompt: str) -> tuple[str, str | None]:
        """Apply the input gate. Returns ``(prompt, refusal_or_None)``."""
        if self.guardrails is None:
            return user_prompt, None
        decision = self.guardrails.check_input(user_prompt)
        if decision.blocked:
            self.emit(
                state,
                "guardrail_triggered",
                f"Input blocked: {decision.reason}",
                stage="input",
                reason=decision.reason,
            )
            return user_prompt, f"Request blocked by guardrails: {decision.reason}"
        if decision.action == "redact" and decision.text:
            return decision.text, None
        return user_prompt, None

    def sanitize_output(self, state: Any, content: str) -> str:
        """Apply the output gate — redact secrets and PII before anyone sees them."""
        if self.guardrails is None or not content:
            return content
        decision = self.guardrails.check_output(content)
        if decision.action == "allow":
            return content
        self.emit(
            state,
            "guardrail_triggered",
            f"Output {decision.action}: {decision.reason}",
            stage="output",
            reason=decision.reason,
        )
        return (
            decision.text
            if decision.action == "redact"
            else f"Response withheld by guardrails: {decision.reason}"
        )

    def sanitize_tool_output(
        self, state: Any, tool_name: str, output: str
    ) -> tuple[str, bool]:
        """Sanitize a tool result. Returns ``(text, a_secret_was_redacted)``."""
        if self.guardrails is None or not output:
            return output, False
        sanitized = self.guardrails.check_tool_output(tool_name, output)
        if sanitized.action == "allow":
            return output, False
        self.emit(
            state,
            "guardrail_triggered",
            f"Tool output sanitized: {sanitized.reason}",
            stage="tool_output",
            tool=tool_name,
            reason=sanitized.reason,
        )
        return sanitized.text, "secret" in str(sanitized.reason or "").lower()

    def model_visible_tool_output(
        self,
        tool_result: Any,
        *,
        arguments: Any = None,
        seen: dict | None = None,
        limit_override: int | None = None,
    ) -> str:
        """Bound only the tool output copy sent back to the model.

        The canonical result remains complete for callers and traces. Head and
        tail retention keeps introductory context plus errors printed last.

        A tool called twice with the same arguments, returning byte-identical
        output, is sent back only once. The model already has that text in
        its context from the first call, and a message list is cumulative —
        every copy is re-sent on every subsequent turn, so the cost of a
        repeat is not the repeat, it is the repeat multiplied by the
        iterations that follow it. Observed on a real run: one MCP tool
        called four times with empty arguments returned the same 138,000
        characters each time, and a five-iteration turn spent 507,000 input
        tokens.

        Identity is required, not assumed: the tool still runs, and its
        output is compared. A tool whose answer changed says so in full.
        """
        raw_output = getattr(tool_result, "output", "") or ""
        if not isinstance(raw_output, str):
            # Block-shaped output (images) has no meaningful char budget and
            # stringifying it would feed the model "[{'type': 'image'…}]".
            return raw_output
        semantic_output = getattr(tool_result, "model_text", None)
        has_semantic_output = bool(
            isinstance(semantic_output, str) and semantic_output.strip()
        )
        output = semantic_output if has_semantic_output else raw_output
        name = str(getattr(tool_result, "name", "") or "")
        limit = (
            min(self.max_tool_output_chars, limit_override)
            if self.max_tool_output_chars > 0
            and limit_override is not None
            and limit_override > 0
            else limit_override
            if limit_override is not None
            else self.max_tool_output_chars
        )
        canonical_digest = hashlib.sha256(
            raw_output.encode("utf-8", "replace")
        ).hexdigest()
        persisted_path = ""
        if limit > 0 and len(raw_output) > limit:
            persisted_path = self._persist_tool_output(
                tool_result, output=raw_output, name=name, digest=canonical_digest
            )

        if seen is not None and len(output) >= _REPEAT_MIN_CHARS:
            key = (name, _arguments_key(arguments))
            if seen.get(key) == canonical_digest:
                metadata = getattr(tool_result, "metadata", None)
                if isinstance(metadata, dict):
                    metadata.update(
                        {
                            "repeat_of_earlier_call": True,
                            "omitted_output_chars": len(output),
                        }
                    )
                return (
                    f"[No new data. {name} was already called with exactly "
                    f"these arguments in this run and returned the same "
                    f"{len(output):,} characters, which are already in this "
                    f"conversation above.\n\n"
                    f"Calling it again unchanged will return this same "
                    f"message. Either answer from the result you already "
                    f"have, or call {name} with DIFFERENT arguments — a "
                    f"narrower query, a filter, or a specific id."
                    + (
                        f" The complete result is stored at {persisted_path}.]"
                        if persisted_path
                        else "]"
                    )
                )
            seen[key] = canonical_digest

        if has_semantic_output:
            metadata = getattr(tool_result, "metadata", None)
            if isinstance(metadata, dict):
                metadata.update(
                    {
                        "model_output_semantic": True,
                        "canonical_output_chars": len(raw_output),
                        "model_output_chars": len(output),
                    }
                )

        if limit <= 0 or len(output) <= limit:
            return output

        # Say what was removed and how to get it, not merely that something
        # was. "Shortened" leaves a model guessing whether it saw the
        # important part; a number and an instruction let it decide.
        omitted = len(output) - limit
        marker = (
            f"\n\n[... {omitted:,} of {len(output):,} characters omitted from "
            f"the middle. You are seeing the start and the end.\n"
            f"This tool returned more than fits in context. Do NOT call it "
            f"again unchanged — you will get this same extract. To see the "
            f"omitted part, use a narrower query, a filter, a page or a "
            f"specific id."
            + (
                f" The complete result is stored at {persisted_path}.]\n\n"
                if persisted_path
                else "]\n\n"
            )
        )
        # A tight budget still gets head and tail. The guidance is what is
        # dropped, not the data — an extract missing its end is the shape
        # that makes a model believe it saw the whole answer.
        if limit <= len(marker) + 32:
            marker = f"\n[... {omitted:,} of {len(output):,} chars omitted ...]\n"
        if limit <= len(marker) + 32:
            visible = output[:limit]
        else:
            content_budget = limit - len(marker)
            head_size = int(content_budget * 0.7)
            tail_size = content_budget - head_size
            visible = output[:head_size] + marker + output[-tail_size:]

        metadata = getattr(tool_result, "metadata", None)
        if isinstance(metadata, dict):
            metadata.update(
                {
                    "model_output_truncated": True,
                    "original_output_chars": len(output),
                    "model_output_chars": len(visible),
                    "omitted_output_chars": len(output) - len(visible),
                }
            )
        return visible

    def _persist_tool_output(
        self, tool_result: Any, *, output: str, name: str, digest: str
    ) -> str:
        """Persist a large sanitized result so truncation never loses access."""
        if not self.tool_output_dir:
            return ""
        from pathlib import Path

        safe_name = (
            "".join(
                char if char.isalnum() or char in "-_" else "_" for char in name
            ).strip("_")
            or "tool"
        )
        path = Path(self.tool_output_dir) / f"{safe_name}-{digest[:16]}.txt"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("x", encoding="utf-8", errors="replace") as file:
                    file.write(output)
            except FileExistsError:
                pass
        except OSError:
            return ""
        metadata = getattr(tool_result, "metadata", None)
        if isinstance(metadata, dict):
            metadata["persisted_output_path"] = str(path)
        return str(path)
