"""Sorting out what a "model parameter" actually is.

Callers pass one bag of settings, but the entries are not one kind of thing.
Some belong on the wire; some are instructions to this process and would be
rejected as unknown fields if forwarded. ``max_context_tokens`` is the clearest
case: it tells the compactor when to act, and sending it to an
OpenAI-compatible endpoint is a 400 naming a field the caller never meant for
the provider at all.

So every parameter passes through four steps, in order:

1. **Canonicalise** — ``topP``, ``top_p`` and ``topK`` are one setting each to a
   provider and three keys to a dict. A rule that catches one spelling and
   misses the other works until someone switches SDKs.
2. **Coerce** — a UI hands back ``"0.7"``. A string where a float belongs is
   either a 400 or, worse, silently ignored. Explicit ``0`` and negative values
   survive: ``temperature=0`` is a deliberate choice, not a missing value.
3. **Route** — wire params go to the provider, host params stay here.
4. **Adapt** — the family's rules block what it rejects and fill what it
   recommends (:mod:`shipit_agent.llms.capabilities`).

Nothing is silently dropped. A parameter that vanishes without a trace is worse
than one that errors, because the error at least names itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

logger = logging.getLogger(__name__)

__all__ = [
    "WIRE_PARAMS",
    "HOST_PARAMS",
    "NUMERIC_PARAMS",
    "ResolvedParameters",
    "canonical_name",
    "coerce_numeric",
    "normalize_parameters",
    "resolve_parameters",
]


#: camelCase → snake_case for every parameter seen in the wild. Both spellings
#: reach us because LiteLLM, the OpenAI SDK and the Anthropic SDK disagree.
_ALIASES: dict[str, str] = {
    "topp": "top_p",
    "topk": "top_k",
    "maxtokens": "max_tokens",
    "maxoutputtokens": "max_output_tokens",
    "maxcompletiontokens": "max_completion_tokens",
    "maxcontexttokens": "max_context_tokens",
    "frequencypenalty": "frequency_penalty",
    "presencepenalty": "presence_penalty",
    "repetitionpenalty": "repetition_penalty",
    "logitbias": "logit_bias",
    "thinkingbudget": "thinking_budget",
    "reasoningeffort": "reasoning_effort",
    "filetokenlimit": "file_token_limit",
    "stopsequences": "stop_sequences",
    "servicetier": "service_tier",
    "streamusage": "stream_usage",
}

#: Sent to the provider.
WIRE_PARAMS: frozenset[str] = frozenset(
    {
        "temperature",
        "top_p",
        "top_k",
        "frequency_penalty",
        "presence_penalty",
        "repetition_penalty",
        "logit_bias",
        "logprobs",
        "n",
        "seed",
        "stop",
        "stop_sequences",
        "max_tokens",
        "max_output_tokens",
        "max_completion_tokens",
        "thinking_budget",
        "reasoning_effort",
        "service_tier",
        "stream_usage",
        "response_format",
    }
)

#: Consumed by this process. Forwarding one is a 400 on a field the caller never
#: aimed at the provider.
HOST_PARAMS: frozenset[str] = frozenset(
    {
        "max_context_tokens",   # when the compactor acts
        "file_token_limit",     # per-attachment budget
        "max_iterations",       # loop ceiling
        "max_tool_output_chars",
        "reserve_ratio",
        "compact_at",
    }
)

#: Keys that must end up as finite numbers.
NUMERIC_PARAMS: frozenset[str] = frozenset(
    {
        "temperature",
        "top_p",
        "top_k",
        "frequency_penalty",
        "presence_penalty",
        "repetition_penalty",
        "n",
        "seed",
        "max_tokens",
        "max_output_tokens",
        "max_completion_tokens",
        "max_context_tokens",
        "file_token_limit",
        "max_iterations",
        "max_tool_output_chars",
        "thinking_budget",
        "reserve_ratio",
        "compact_at",
    }
)


def canonical_name(key: str) -> str:
    """One spelling per setting. ``topP`` and ``top_p`` both become ``top_p``."""
    flattened = key.replace("_", "").replace("-", "").lower()
    return _ALIASES.get(flattened, key.strip())


def coerce_numeric(value: Any) -> float | int | None:
    """A finite number, or ``None`` when the value cannot be one.

    ``True``/``False`` are rejected rather than becoming 1/0: a boolean where a
    float belongs is a caller mistake, and quietly turning ``temperature=True``
    into ``1.0`` hides it.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(number) if text.lstrip("+-").isdigit() else number


def normalize_parameters(
    params: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Canonicalise and coerce. Returns ``(clean, rejected)``.

    Rejected entries are returned rather than discarded so a caller can surface
    them — a typo in a parameter name should be visible, not absorbed.
    """
    clean: dict[str, Any] = {}
    rejected: dict[str, Any] = {}

    for raw_key, value in (params or {}).items():
        key = canonical_name(str(raw_key))
        if value is None:
            continue
        if key in NUMERIC_PARAMS:
            number = coerce_numeric(value)
            if number is None:
                rejected[key] = value
                continue
            clean[key] = number
            continue
        clean[key] = value

    if rejected:
        logger.debug(
            "Ignoring non-numeric values for %s", ", ".join(sorted(rejected))
        )
    return clean, rejected


@dataclass(frozen=True, slots=True)
class ResolvedParameters:
    """The outcome of resolving one parameter bag, with nothing hidden."""

    #: Ready to send to the provider.
    wire: dict[str, Any] = field(default_factory=dict)
    #: Consumed by this process — budgets, limits, loop control.
    host: dict[str, Any] = field(default_factory=dict)
    #: Blocked by the model family's rules, with the values that were dropped.
    dropped: dict[str, Any] = field(default_factory=dict)
    #: Filled in from the family's recommendations because the caller set none.
    recommended: dict[str, Any] = field(default_factory=dict)
    #: Names that could not be coerced to a number.
    rejected: dict[str, Any] = field(default_factory=dict)
    #: Names that are neither wire nor host parameters — likely typos, but
    #: forwarded anyway, since a provider may accept a field we do not know.
    unknown: dict[str, Any] = field(default_factory=dict)

    def explain(self) -> str:
        """One line per decision, for ``preflight`` and for debugging a 400."""
        lines: list[str] = []
        if self.wire:
            lines.append(f"sent: {', '.join(sorted(self.wire))}")
        if self.host:
            lines.append(f"used locally: {', '.join(sorted(self.host))}")
        if self.recommended:
            pairs = ", ".join(f"{k}={v}" for k, v in sorted(self.recommended.items()))
            lines.append(f"defaulted: {pairs}")
        if self.dropped:
            lines.append(f"blocked for this model: {', '.join(sorted(self.dropped))}")
        if self.rejected:
            lines.append(f"not numeric, ignored: {', '.join(sorted(self.rejected))}")
        if self.unknown:
            lines.append(f"unrecognised, forwarded: {', '.join(sorted(self.unknown))}")
        return "; ".join(lines) or "no parameters"

    def host_value(self, name: str, default: Any = None) -> Any:
        return self.host.get(canonical_name(name), default)


def resolve_parameters(
    model: str | None,
    params: Mapping[str, Any] | None,
    *,
    apply_recommendations: bool = True,
) -> ResolvedParameters:
    """Turn one caller-supplied bag into wire params, host params, and a record.

    The record matters as much as the split: when a provider returns a 400 about
    a parameter, ``explain()`` says exactly what was sent, what was withheld and
    what was filled in — which is usually the whole debugging session.
    """
    from shipit_agent.llms.capabilities import capabilities_for

    clean, rejected = normalize_parameters(params)
    caps = capabilities_for(model)

    wire: dict[str, Any] = {}
    host: dict[str, Any] = {}
    unknown: dict[str, Any] = {}
    for key, value in clean.items():
        if key in HOST_PARAMS:
            host[key] = value
        elif key in WIRE_PARAMS:
            wire[key] = value
        else:
            # Not in either table. Forwarded rather than dropped: a provider may
            # accept a field this package has never heard of, and silently
            # removing it would be the harder failure to diagnose.
            unknown[key] = value

    recommended: dict[str, Any] = {}
    if apply_recommendations:
        for key, value in caps.recommended_params.items():
            canonical = canonical_name(key)
            if canonical in caps.blocked_params or canonical in wire:
                continue
            wire[canonical] = value
            recommended[canonical] = value

    accepted, dropped = caps.sanitize({**wire, **unknown}, model=model or "")
    forwarded_unknown = {k: v for k, v in unknown.items() if k in accepted}

    return ResolvedParameters(
        wire={k: v for k, v in accepted.items()},
        host=host,
        dropped=dropped,
        recommended={k: v for k, v in recommended.items() if k in accepted},
        rejected=rejected,
        unknown=forwarded_unknown,
    )
