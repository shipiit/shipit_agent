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

from .lookup import (
    apply_recommended_params,
    capabilities_for,
    describe,
    register_rule,
    sanitize_params,
    supports,
    with_reason,
)
from .model import (
    BlockOrder,
    ModelCapabilities,
    PromptCacheMode,
    ReasoningChannel,
    ReasoningHistory,
    logger,
)
from .rules import DEFAULT_CAPABILITIES, RULES

__all__ = [
    "BlockOrder",
    "DEFAULT_CAPABILITIES",
    "ModelCapabilities",
    "PromptCacheMode",
    "RULES",
    "ReasoningChannel",
    "ReasoningHistory",
    "apply_recommended_params",
    "capabilities_for",
    "describe",
    "logger",
    "register_rule",
    "sanitize_params",
    "supports",
    "with_reason",
]
