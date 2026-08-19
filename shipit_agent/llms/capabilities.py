"""What each model family will and won't accept — and stripping the rest.

The default failure mode of a multi-provider agent is sending one parameter bag
to every model and letting the provider reject it. The rejection is an HTTP 400
on a live turn, the message names a field the caller never deliberately set
(``temperature`` arrives from a default, not from intent), and the same code
works on the next model, so the bug reads as "this model is broken".

So the quirks live here, declaratively, one rule per family, each recording the
error it prevents. The rules are ordered most-specific-first and matched by
regex, because these are open-ended families — "Gemini 3.5 Flash *and later*",
"o-series *and* GPT-5 but not GPT-5-chat" — which a lookup table cannot express
and a substring check gets wrong.

Two properties matter more than coverage:

- **A missing rule is silent and harmless.** An unmatched model gets
  ``ModelCapabilities()``, which blocks nothing. This layer can only ever
  remove parameters a provider is known to reject; it never invents behaviour.
- **Dropping is logged, never silent.** A parameter that vanishes without a
  trace is worse than one that 400s, because the 400 at least names itself.

Both spellings of every parameter are listed. Callers reach these adapters
through LiteLLM, OpenAI and Anthropic SDKs that disagree about ``top_p`` versus
``topP``, and a rule that catches one spelling and misses the other is a rule
that works until someone switches SDKs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """What a model family accepts. Defaults are permissive by design."""

    #: Parameters the provider rejects outright. Both spellings, always.
    blocked_params: frozenset[str] = frozenset()
    #: Parameters the provider accepts only under another name.
    renamed_params: dict[str, str] = field(default_factory=dict)
    supports_tools: bool = True
    supports_vision: bool = False
    supports_prompt_cache: bool = False
    supports_reasoning: bool = False
    #: Free-text note naming the failure this rule prevents, for the log line.
    reason: str = ""

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

#: (pattern, capabilities). Ordered — the FIRST match wins, so the most
#: specific pattern must come first. `-lite` before `-flash` is not cosmetic:
#: a `-flash` rule listed first would swallow every `-flash-lite` model.
RULES: list[tuple[re.Pattern[str], ModelCapabilities]] = [
    # ── Google: Gemini 3.5+ Flash and Gemma 4+ "thinking" models ─────────
    # These 400 on every sampling parameter and on the numeric thinking
    # budget, which a qualitative `thinking_level` replaced.
    (
        re.compile(r"gemini-([3-9]\.[5-9]|[4-9])|gemini-\d{2,}", re.I),
        ModelCapabilities(
            blocked_params=_SAMPLING | _both_spellings("thinking_budget"),
            supports_vision=True,
            supports_reasoning=True,
            reason="Gemini 3.5+ rejects sampling params and numeric thinking_budget",
        ),
    ),
    (
        re.compile(r"gemma[-_]?([4-9]|\d{2,})", re.I),
        ModelCapabilities(
            blocked_params=_both_spellings("thinking_budget"),
            supports_vision=True,
            reason="Gemma 4+ uses a qualitative thinking_level, not a budget",
        ),
    ),
    # ── OpenAI reasoning models ──────────────────────────────────────────
    # `gpt-5-chat` and `gpt-5.1` DO accept sampling params, so the negative
    # lookahead is load-bearing — without it, every GPT-5 variant is
    # stripped and the non-reasoning ones silently lose their temperature.
    (
        re.compile(r"\b(o[13]|gpt-5)(?!\.|-chat)(?:-|$)", re.I),
        ModelCapabilities(
            blocked_params=_SAMPLING | frozenset({"n"}),
            renamed_params={"max_tokens": "max_completion_tokens"},
            supports_reasoning=True,
            supports_vision=True,
            reason="o-series/GPT-5 reasoning models reject sampling params",
        ),
    ),
    # ── Anthropic ────────────────────────────────────────────────────────
    (
        re.compile(r"claude|anthropic", re.I),
        ModelCapabilities(
            supports_vision=True,
            supports_prompt_cache=True,
            supports_reasoning=True,
            reason="",
        ),
    ),
    # ── Amazon Bedrock, non-Anthropic families ───────────────────────────
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
    RULES.insert(0, (compiled, capabilities)) if first else RULES.append(
        (compiled, capabilities)
    )


def supports(model: str | None, capability: str) -> bool:
    """Does *model* support *capability*? Unknown capability names are False."""
    return bool(getattr(capabilities_for(model), capability, False))


def describe(models: Iterable[str]) -> list[dict[str, Any]]:
    """A capability matrix for *models* — for `doctor`, docs, or a UI."""
    rows: list[dict[str, Any]] = []
    for model in models:
        caps = capabilities_for(model)
        rows.append(
            {
                "model": model,
                "tools": caps.supports_tools,
                "vision": caps.supports_vision,
                "prompt_cache": caps.supports_prompt_cache,
                "reasoning": caps.supports_reasoning,
                "blocked": sorted(caps.blocked_params),
                "renamed": dict(caps.renamed_params),
            }
        )
    return rows


def with_reason(caps: ModelCapabilities, reason: str) -> ModelCapabilities:
    """Copy *caps* with a different explanation — for registering variants."""
    return replace(caps, reason=reason)
