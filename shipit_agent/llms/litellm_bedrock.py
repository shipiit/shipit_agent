"""Amazon Bedrock through LiteLLM, including Bedrock's OpenAI-compatible Mantle endpoint."""

from __future__ import annotations

import re
from typing import Any, Callable

from shipit_agent.llms.base import LLMResponse
from shipit_agent.llms.bedrock_token import (
    BedrockTokenError,
    existing_bearer_token,
    generate_bearer_token,
)
from shipit_agent.llms.litellm_base import LiteLLMChatLLM

#: Bedrock Mantle model ids in every spelling seen in the wild — ``gemma-4``,
#: ``gemma4``, ``gemma_4`` — and any major version from 4 up. Matching the
#: literal ``"gemma-4"`` alone silently routed ``gemma4-31b`` to the Converse
#: API, which cannot serve it, so the same model worked or failed depending on
#: how its id was punctuated.
_MANTLE_MODEL_RE = re.compile(r"gemma[-_]?([4-9]|\d{2,})")


def _litellm_supports_bedrock_mantle() -> bool:
    """Does the installed LiteLLM ship the native ``bedrock_mantle`` provider?

    Added in LiteLLM ~1.84 (mirrors AWS's Bedrock Mantle OpenAI-compatible
    surface — https://docs.litellm.ai/docs/providers/bedrock_mantle). Feature-
    detected rather than version-compared so forks and backports behave.
    """
    try:
        import litellm  # type: ignore

        return any("bedrock_mantle" == p.value for p in litellm.LlmProviders)
    except Exception:
        return False


class BedrockChatLLM(LiteLLMChatLLM):
    """Models hosted on Amazon Bedrock, called through LiteLLM."""

    def __init__(
        self, model: str = "bedrock/openai.gpt-oss-120b-1:0", **completion_kwargs: Any
    ) -> None:
        self._mantle_delegate: Any = None

        # Bedrock Mantle models (Gemma 4 et al.) are served through the
        # OpenAI-compatible `bedrock-mantle` endpoint, NOT the Converse API
        # the rest of Bedrock uses. Accept the id in any spelling callers
        # use: `bedrock_mantle/google.gemma-4-…`, `bedrock/google.gemma-4-…`,
        # or a bare `google.gemma-4-…`.
        #
        # Preferred route: LiteLLM's native `bedrock_mantle/` provider
        # (https://docs.litellm.ai/docs/providers/bedrock_mantle) — but it
        # authenticates with a Bedrock API key as a BEARER token, not SigV4,
        # so it is only taken when such a key is actually present. A SigV4-
        # only environment falls through to the shim below (verified live:
        # the native route 401s without BEDROCK_MANTLE_API_KEY).
        lowered = model.lower()
        is_mantle = bool(_MANTLE_MODEL_RE.search(lowered)) or lowered.startswith(
            "bedrock_mantle/"
        )
        # Accept every spelling of the Bedrock API key. AWS documents
        # ``AWS_BEARER_TOKEN_BEDROCK``; that is also the one the OpenAI shim
        # below actually reads and the one this package's own docstring tells
        # users to export. Checking only ``BEDROCK_MANTLE_API_KEY`` here meant a
        # correctly-configured user was pushed off the preferred native route
        # onto the shim.
        mantle_key = completion_kwargs.get("api_key") or existing_bearer_token()
        # A SigV4-only environment (access keys, a profile, an SSO login, an
        # instance or task role — the common AWS setup) has no bearer token, and
        # both mantle routes need one. Rather than build an adapter that 401s on
        # its first call, derive the token: a short-term Bedrock API key *is* a
        # SigV4-presigned request, so the credentials already present are
        # sufficient. See shipit_agent/llms/bedrock_token.py.
        if is_mantle and not mantle_key:
            region_hint = completion_kwargs.get(
                "aws_region_name"
            ) or completion_kwargs.get("region")
            try:
                mantle_key = generate_bearer_token(region=region_hint)
            except BedrockTokenError as exc:
                raise RuntimeError(
                    f"{model!r} is a Bedrock Mantle model, served over the "
                    "OpenAI-compatible bedrock-mantle endpoint. It authenticates "
                    "with a Bedrock API key sent as a BEARER token, not with "
                    "SigV4 request signing, and no key was found or derivable.\n"
                    f"  Underlying cause: {exc}\n"
                    "  Either export AWS_BEARER_TOKEN_BEDROCK=... (AWS console → "
                    "Amazon Bedrock → API keys), or configure ordinary AWS "
                    "credentials plus a region and one will be derived for you.\n"
                    "SigV4-authenticated Bedrock models (Anthropic, Nova, Llama, "
                    "Mistral, Titan) are unaffected."
                ) from exc

        has_mantle_key = bool(mantle_key)
        if has_mantle_key:
            # Both routes read the key from `api_key`; pass the derived token
            # explicitly rather than exporting it, so a token minted for this
            # adapter never leaks into the process environment or into any other
            # library that happens to read that variable.
            completion_kwargs["api_key"] = mantle_key

        # Always use the OpenAI-compatible shim (`.../openai/v1`) for mantle
        # models — the route AWS documents for Gemma 4, which returns NATIVE
        # structured `tool_calls`. LiteLLM's native `bedrock_mantle/` provider is
        # deliberately NOT used: on this endpoint it 400s
        # `model '…' isn't supported on this route` for the Gemma ids.
        # ``complete()`` forwards to the delegate.
        if is_mantle:
            from shipit_agent.llms.openai_adapter import BedrockGemmaChatLLM

            mantle_model = model.split("/", 1)[-1] if "/" in model else model
            region = completion_kwargs.pop("aws_region_name", None) or (
                completion_kwargs.pop("region", None)
            )
            api_key = completion_kwargs.pop("api_key", None)
            base_url = completion_kwargs.pop("base_url", None)
            # Caching is hard-coded off below; drop any caller-supplied
            # `prompt_caching` so it can't collide with that keyword.
            completion_kwargs.pop("prompt_caching", None)
            self._mantle_delegate = BedrockGemmaChatLLM(
                model=mantle_model,
                region=region,
                api_key=api_key,
                base_url=base_url,
                **completion_kwargs,
            )
            # Initialise the base class even though `complete()` delegates.
            # Returning early left the instance without `prompt_caching` and
            # `completion_kwargs`, so a `BedrockChatLLM` that reports itself as
            # one did not carry the attributes every other instance has —
            # `doctor` only avoids an AttributeError because it happens to
            # guard with hasattr, and it then reports the wrong cache mode.
            # Caching stays off: the mantle endpoint is not Anthropic-family.
            super().__init__(model=model, prompt_caching=False, **completion_kwargs)
            return

        # Bedrock's Anthropic path requires strict tool_use/tool_result id
        # pairing. The shipit_agent Message model doesn't carry tool-call IDs,
        # so we let litellm patch the request on our behalf (inserts dummy
        # assistant turns + filler tool_results where needed). Without this,
        # Bedrock-Claude rejects multi-step tool runs with "Expected
        # toolResult blocks ... for Ids: <uuid>".
        #
        # Other Bedrock model families (Nova, Titan, Llama, Mistral) reject
        # `modify_params` as a malformed input — so only apply it for
        # Anthropic-on-Bedrock. Same story for the global flag.
        is_anthropic = "anthropic" in model.lower() or "claude" in model.lower()
        if is_anthropic:
            completion_kwargs.setdefault("modify_params", True)
        super().__init__(model=model, **completion_kwargs)
        if is_anthropic:
            try:
                import litellm  # type: ignore

                litellm.modify_params = True
            except Exception:
                pass

    def complete(
        self,
        *,
        text_delta_callback: Callable[[str], bool | None] | None = None,
        tool_input_callback: Callable[[str, str, str], bool | None] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        # Gemma 4 → OpenAI-compatible mantle endpoint; everything else →
        # Converse. `text_delta_callback` and `tool_input_callback` are named
        # explicitly rather than left to **kwargs so capability sniffing
        # (`accepts_text_delta_callback`, which requires the parameter by name
        # and does NOT count a bare **kwargs) can see them. Both delegates
        # support both callbacks; an unnamed kwarg would make the runtime treat
        # this adapter as non-streaming and never pass the callback — silently
        # disabling token-by-token output on the mantle route.
        if text_delta_callback is not None:
            kwargs["text_delta_callback"] = text_delta_callback
        if tool_input_callback is not None:
            kwargs["tool_input_callback"] = tool_input_callback
        if self._mantle_delegate is not None:
            return self._mantle_delegate.complete(**kwargs)
        return super().complete(**kwargs)
