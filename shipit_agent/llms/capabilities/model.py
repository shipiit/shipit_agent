"""What a model family accepts and how it behaves, as one value."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)


ReasoningHistory = Literal["replay", "strip", "ignore"]


ReasoningChannel = Literal["none", "responses_api", "param"]


PromptCacheMode = Literal["none", "explicit", "implicit"]


BlockOrder = Literal["any", "image_first", "text_first"]


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """What a model family accepts. Every default is the permissive one."""

    # ── parameters ────────────────────────────────────────────────────────
    #: Parameters the provider rejects outright. Both spellings, always.
    blocked_params: frozenset[str] = frozenset()
    #: Parameters the provider accepts only under another name.
    renamed_params: dict[str, str] = field(default_factory=dict)
    #: Applied only where the caller set nothing. Never overrides intent.
    recommended_params: dict[str, Any] = field(default_factory=dict)

    # ── coarse capability flags ───────────────────────────────────────────
    supports_tools: bool = True
    supports_vision: bool = False
    supports_prompt_cache: bool = False
    supports_reasoning: bool = False
    supports_service_tier: bool = False
    #: Whether a single assistant turn may request multiple client-side tools.
    #: This is independent of whether the runtime executes a returned batch
    #: concurrently. Unknown providers remain permissive.
    supports_parallel_tool_calls: bool = True

    # ── reasoning ─────────────────────────────────────────────────────────
    #: ``replay``  — prior reasoning MUST be resent (DeepSeek thinking mode).
    #: ``strip``   — prior reasoning MUST be removed (Gemma 4; replaying it
    #:               degrades responses).
    #: ``ignore``  — reasoning never enters history.
    reasoning_history: ReasoningHistory = "ignore"
    #: Where the reasoning control lives: a request parameter, the Responses
    #: API ``reasoning`` object, or nowhere.
    reasoning_channel: ReasoningChannel = "none"
    #: Effort to request when the caller names none.
    default_reasoning_effort: str | None = None

    # ── prompt caching ────────────────────────────────────────────────────
    #: ``explicit`` needs cache_control markers; ``implicit`` needs only a
    #: byte-stable prefix, which is a constraint on how prompts are assembled.
    prompt_cache_mode: PromptCacheMode = "none"

    # ── multimodal wire format ────────────────────────────────────────────
    #: Image source kinds the endpoint accepts: ``base64``, ``url``, ``s3``.
    image_sources: frozenset[str] = frozenset({"base64", "url"})
    #: Recommended ordering of content blocks within one message.
    content_block_order: BlockOrder = "any"

    # ── tool schemas ──────────────────────────────────────────────────────
    #: Dialect name resolved by :mod:`schema_rules`.
    schema_dialect: str = "json_schema_2020"

    # ── context budget ────────────────────────────────────────────────────
    #: Total window in tokens. ``None`` means "consult the caller's table".
    context_window: int | None = None
    #: Tokens held back for the response when deriving an input budget.
    output_reserve: int = 8_192

    #: Free-text note naming the failure this rule prevents, for the log line.
    reason: str = ""

    # ── behaviour ─────────────────────────────────────────────────────────

    def sanitize(
        self, params: dict[str, Any], *, model: str = ""
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return ``(accepted, dropped)`` for *params* under these rules."""
        accepted: dict[str, Any] = {}
        dropped: dict[str, Any] = {}
        for key, value in params.items():
            if key in self.blocked_params:
                dropped[key] = value
                continue
            accepted[self.renamed_params.get(key, key)] = value
        if dropped:
            logger.debug(
                "Dropped %s for %s (%s)",
                ", ".join(sorted(dropped)),
                model or "model",
                self.reason or "not accepted by this model family",
            )
        return accepted, dropped

    def with_recommendations(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fill recommended values for keys the caller left unset.

        A recommendation is never applied to a blocked parameter, and never
        overwrites a value the caller chose — including an explicit ``0``.
        """
        if not self.recommended_params:
            return dict(params)
        merged = dict(params)
        for key, value in self.recommended_params.items():
            if key in self.blocked_params or key in merged:
                continue
            merged[key] = value
        return merged

    def input_budget(self) -> int | None:
        """Tokens available for the prompt, or ``None`` when unknown."""
        if self.context_window is None:
            return None
        return max(1_024, self.context_window - self.output_reserve)
