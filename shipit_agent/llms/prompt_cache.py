from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


PromptCacheStrategy = Literal["auto", "automatic", "explicit", "disabled"]


@dataclass(frozen=True, slots=True)
class PromptCachePolicy:
    """Provider-aware prompt-cache behavior for an LLM adapter."""

    provider: str
    model: str
    supported: bool | None
    enabled: bool | None
    mode: str
    reason: str
    explicit_breakpoints: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "supported": self.supported,
            "enabled": self.enabled,
            "mode": self.mode,
            "reason": self.reason,
        }


def _provider_prefix(model: str) -> str:
    value = (model or "").lower()
    return value.split("/", 1)[0] if "/" in value else ""


def litellm_prompt_cache_policy(
    model: str,
    *,
    enabled: bool = True,
    strategy: PromptCacheStrategy = "auto",
) -> PromptCachePolicy:
    """Resolve a safe LiteLLM cache policy without probing the provider.

    ``auto`` uses explicit breakpoints only for families whose translation is
    documented by LiteLLM. Unknown routes remain provider-managed. Callers can
    opt a newly supported provider into ``explicit`` without waiting for a
    SHIPIT release.
    """
    if strategy not in {"auto", "automatic", "explicit", "disabled"}:
        raise ValueError(
            "prompt_cache_strategy must be auto, automatic, explicit, or disabled"
        )

    value = (model or "").lower()
    prefix = _provider_prefix(value)
    provider = prefix or "litellm"
    is_anthropic = "anthropic" in value or "claude" in value
    is_google_cache = prefix in {"gemini", "vertex_ai", "vertex_ai_beta"} and (
        "gemini" in value or prefix == "gemini"
    )
    automatic_prefixes = {"openai", "azure", "deepseek", "xai"}
    is_bare_openai = not prefix and value.startswith(("gpt-", "o1", "o3", "o4"))
    known_supported = (
        is_anthropic
        or is_google_cache
        or prefix in automatic_prefixes
        or is_bare_openai
    )
    if not enabled or strategy == "disabled":
        return PromptCachePolicy(
            provider,
            model,
            True if known_supported else None,
            False,
            "disabled",
            "disabled_by_caller",
        )
    if strategy == "explicit":
        return PromptCachePolicy(
            provider,
            model,
            True,
            True,
            "explicit",
            "caller_selected_explicit_breakpoints",
            True,
        )
    if strategy == "automatic":
        return PromptCachePolicy(
            provider, model, True, True, "automatic", "caller_selected_automatic"
        )

    if is_anthropic or is_google_cache:
        return PromptCachePolicy(
            provider,
            model,
            True,
            True,
            "explicit",
            "litellm_cache_control_translation",
            True,
        )

    if prefix in automatic_prefixes or is_bare_openai:
        return PromptCachePolicy(
            provider, model, True, True, "automatic", "provider_automatic"
        )

    return PromptCachePolicy(
        provider,
        model,
        None,
        None,
        "provider_managed",
        "capability_not_declared",
    )


def prompt_cache_status(
    capability: dict[str, Any],
    *,
    read_tokens: int,
    write_tokens: int,
    usage_reported: bool,
) -> dict[str, Any]:
    """Combine static capability and observed usage without inventing a miss."""
    hit: bool | None
    if read_tokens > 0:
        hit = True
    elif usage_reported or capability.get("supported") is False:
        hit = False
    else:
        hit = None
    return {
        **capability,
        "hit": hit,
        "usage_reported": usage_reported,
        "read_tokens": read_tokens,
        "write_tokens": write_tokens,
    }
