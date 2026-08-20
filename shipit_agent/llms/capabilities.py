"""What each model family will and won't accept — and adapting to the rest.

The default failure mode of a multi-provider agent is sending one parameter bag
to every model and letting the provider reject it. The rejection is an HTTP 400
on a live turn, the message names a field the caller never deliberately set
(``temperature`` arrives from a default, not from intent), and the same code
works on the next model, so the bug reads as "this model is broken".

So the quirks live here, declaratively, one rule per family, each recording the
error it prevents. Rules are ordered most-specific-first and matched by regex,
because these are open-ended families — "Gemini 3.5 Flash *and later*",
"o-series *and* GPT-5 but not GPT-5-chat" — which a lookup table cannot express
and a substring check gets wrong.

Beyond parameters, a rule now also declares the things that differ per family
but are not parameters at all: how reasoning is requested and whether prior
reasoning may be replayed, which image sources the endpoint accepts, whether
prompt caching is explicit or implicit, the tool-schema dialect, and the model's
context window. Every one of these was previously an ``if provider ==`` branch
somewhere in the runtime; here they are data.

Three properties matter more than coverage:

- **A missing rule is silent and harmless.** An unmatched model gets
  ``ModelCapabilities()``, which blocks nothing, strips nothing and assumes
  nothing. This layer only removes or adapts what a provider is known to
  reject; it never invents behaviour.
- **Dropping is logged, never silent.** A parameter that vanishes without a
  trace is worse than one that 400s, because the 400 at least names itself.
- **Recommendations never override intent.** ``recommended_params`` fills only
  keys the caller left unset.

Both spellings of every parameter are listed. Callers reach these adapters
through LiteLLM, OpenAI and Anthropic SDKs that disagree about ``top_p`` versus
``topP``, and a rule that catches one spelling and misses the other is a rule
that works until someone switches SDKs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Literal

logger = logging.getLogger(__name__)

__all__ = [
    "ModelCapabilities",
    "RULES",
    "DEFAULT_CAPABILITIES",
    "capabilities_for",
    "sanitize_params",
    "apply_recommended_params",
    "register_rule",
    "supports",
    "describe",
    "with_reason",
]

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


def _both_spellings(*names: str) -> frozenset[str]:
    """``top_p`` and ``topP`` are the same parameter to a provider, and
    different keys to a dict. Every rule needs both or it half-works."""
    out: set[str] = set()
    for name in names:
        out.add(name)
        head, *rest = name.split("_")
        out.add(head + "".join(part.title() for part in rest))
    return frozenset(out)


#: Sampling parameters that reasoning/thinking models reject.
_SAMPLING = _both_spellings(
    "temperature",
    "top_p",
    "top_k",
    "presence_penalty",
    "frequency_penalty",
    "logit_bias",
    "logprobs",
)

#: Everything bedrock-mantle rejects for Gemma 4. AWS documents sampling as
#: ``temperature`` and ``top_p`` only, so every other knob is a 400 waiting to
#: happen — including the numeric thinking budget a qualitative effort replaced.
_GEMMA_BLOCKED = _both_spellings(
    "top_k",
    "presence_penalty",
    "frequency_penalty",
    "logit_bias",
    "logprobs",
    "thinking_budget",
    "reasoning_effort",
) | frozenset({"n", "modify_params"})

#: Shared by every Gemma 4 variant; E2B differs only in effort and window.
_GEMMA_4 = ModelCapabilities(
    blocked_params=_GEMMA_BLOCKED,
    recommended_params={"temperature": 1.0, "top_p": 0.95},
    supports_vision=True,
    supports_reasoning=True,
    supports_prompt_cache=True,
    supports_service_tier=True,
    supports_parallel_tool_calls=False,
    reasoning_history="strip",
    reasoning_channel="responses_api",
    prompt_cache_mode="implicit",
    image_sources=frozenset({"base64", "s3"}),
    content_block_order="image_first",
    schema_dialect="openai_strict",
    context_window=256_000,
    output_reserve=16_384,
    reason=(
        "Gemma 4 on bedrock-mantle: temperature/top_p only, reasoning via the "
        "Responses API, prior reasoning must not be replayed"
    ),
)


#: (pattern, capabilities). Ordered — the FIRST match wins, so the most
#: specific pattern must come first. `-e2b` before the Gemma 4 family and
#: `-lite` before `-flash` are not cosmetic: the general rule listed first
#: would swallow every specific variant.
RULES: list[tuple[re.Pattern[str], ModelCapabilities]] = [
    # ── Gemma 4 E2B ───────────────────────────────────────────────────────
    # The smallest variant reasons extensively by default; a high effort keeps
    # that in the dedicated reasoning channel instead of leaking into the
    # answer. Its window is half the larger variants'.
    (
        re.compile(r"gemma[-_]?4[-_]?e2b", re.I),
        replace(
            _GEMMA_4,
            default_reasoning_effort="high",
            context_window=128_000,
            output_reserve=8_192,
            reason=(
                "Gemma 4 E2B: high reasoning effort keeps thinking in the "
                "reasoning channel, out of the final answer"
            ),
        ),
    ),
    # ── Gemma 4 family (31B, 26B-A4B, and later ids) ──────────────────────
    (re.compile(r"gemma[-_]?([4-9]|\d{2,})", re.I), _GEMMA_4),
    # ── Google: Gemini 3.5+ Flash and later "thinking" models ─────────────
    # These 400 on every sampling parameter and on the numeric thinking
    # budget, which a qualitative `thinking_level` replaced.
    (
        re.compile(r"gemini-([3-9]\.[5-9]|[4-9])|gemini-\d{2,}", re.I),
        ModelCapabilities(
            blocked_params=_SAMPLING | _both_spellings("thinking_budget"),
            supports_vision=True,
            supports_reasoning=True,
            reasoning_history="strip",
            reasoning_channel="param",
            image_sources=frozenset({"base64", "url"}),
            schema_dialect="gemini",
            context_window=1_000_000,
            output_reserve=32_768,
            reason="Gemini 3.5+ rejects sampling params and numeric thinking_budget",
        ),
    ),
    (
        re.compile(r"gemini|vertex_ai", re.I),
        ModelCapabilities(
            supports_vision=True,
            schema_dialect="gemini",
            reason="Gemini function calling accepts only a Schema subset",
        ),
    ),
    # ── DeepSeek thinking mode ────────────────────────────────────────────
    # The inverse contract to Gemma: `reasoning_content` MUST be replayed on
    # every prior assistant message that emitted tool calls, or tool calling
    # breaks across turns.
    (
        re.compile(r"deepseek", re.I),
        ModelCapabilities(
            supports_reasoning=True,
            reasoning_history="replay",
            reasoning_channel="param",
            schema_dialect="openai_strict",
            reason="DeepSeek thinking mode requires reasoning_content replay",
        ),
    ),
    # ── OpenAI reasoning models ───────────────────────────────────────────
    # `gpt-5-chat` and `gpt-5.1` DO accept sampling params, so the negative
    # lookahead is load-bearing — without it, every GPT-5 variant is stripped
    # and the non-reasoning ones silently lose their temperature.
    (
        re.compile(r"\b(o[13]|gpt-5)(?!\.|-chat)(?:-|$)", re.I),
        ModelCapabilities(
            blocked_params=_SAMPLING | frozenset({"n"}),
            renamed_params={"max_tokens": "max_completion_tokens"},
            supports_reasoning=True,
            supports_vision=True,
            reasoning_history="strip",
            reasoning_channel="responses_api",
            schema_dialect="openai_strict",
            reason="o-series/GPT-5 reasoning models reject sampling params",
        ),
    ),
    # ── Anthropic ─────────────────────────────────────────────────────────
    (
        re.compile(r"claude|anthropic", re.I),
        ModelCapabilities(
            supports_vision=True,
            supports_prompt_cache=True,
            supports_reasoning=True,
            prompt_cache_mode="explicit",
            schema_dialect="anthropic",
            context_window=200_000,
            output_reserve=16_384,
            reason="",
        ),
    ),
    # ── Amazon Bedrock, non-Anthropic families ────────────────────────────
    # Nova/Titan/Llama/Mistral reject `modify_params`, which exists only for
    # Bedrock-Claude's strict tool_use/tool_result id pairing.
    (
        re.compile(r"(nova|titan|llama|mistral|cohere|ai21)", re.I),
        ModelCapabilities(
            blocked_params=frozenset({"modify_params"}),
            reason="non-Anthropic Bedrock families reject modify_params",
        ),
    ),
]

#: Everything unmatched. Blocks nothing — an unknown model must not be
#: degraded by a layer whose whole job is to prevent avoidable 400s.
DEFAULT_CAPABILITIES = ModelCapabilities()


def capabilities_for(model: str | None) -> ModelCapabilities:
    """Capabilities for *model*, or permissive defaults when unmatched."""
    if not model:
        return DEFAULT_CAPABILITIES
    for pattern, caps in RULES:
        if pattern.search(model):
            return caps
    return DEFAULT_CAPABILITIES


def sanitize_params(
    model: str | None, params: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Strip parameters *model* is known to reject.

    Returns ``(accepted, dropped)``. Callers that want to surface the drop to a
    user have the dropped mapping; callers that don't can ignore it.
    """
    if not params:
        return {}, {}
    return capabilities_for(model).sanitize(params, model=model or "")


def apply_recommended_params(
    model: str | None, params: dict[str, Any]
) -> dict[str, Any]:
    """Fill this family's recommended values for keys the caller left unset."""
    return capabilities_for(model).with_recommendations(params or {})


def register_rule(
    pattern: str | re.Pattern[str],
    capabilities: ModelCapabilities,
    *,
    first: bool = True,
) -> None:
    """Add a rule at runtime, for a model this package doesn't know yet.

    Defaults to the front of the list so a caller's specific rule wins over a
    shipped general one — the common case being a private or preview model
    whose id matches an existing family pattern but behaves differently.
    """
    compiled = re.compile(pattern, re.I) if isinstance(pattern, str) else pattern
    if first:
        RULES.insert(0, (compiled, capabilities))
    else:
        RULES.append((compiled, capabilities))


def supports(model: str | None, capability: str) -> bool:
    """Does *model* support *capability*? Unknown capability names are False."""
    return bool(getattr(capabilities_for(model), capability, False))


def describe(models: Iterable[str]) -> list[dict[str, Any]]:
    """A capability matrix for *models* — for ``doctor``, docs, or a UI."""
    rows: list[dict[str, Any]] = []
    for model in models:
        caps = capabilities_for(model)
        rows.append(
            {
                "model": model,
                "tools": caps.supports_tools,
                "vision": caps.supports_vision,
                "prompt_cache": caps.prompt_cache_mode,
                "reasoning": caps.supports_reasoning,
                "reasoning_history": caps.reasoning_history,
                "schema_dialect": caps.schema_dialect,
                "context_window": caps.context_window,
                "service_tier": caps.supports_service_tier,
                "blocked": sorted(caps.blocked_params),
                "renamed": dict(caps.renamed_params),
                "recommended": dict(caps.recommended_params),
            }
        )
    return rows


def with_reason(caps: ModelCapabilities, reason: str) -> ModelCapabilities:
    """Copy *caps* with a different explanation — for registering variants."""
    return replace(caps, reason=reason)
