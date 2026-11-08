"""Budget, LLM and event helpers the autopilot CLI commands share."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from shipit_agent.autopilot import BudgetPolicy
from shipit_agent.llms.model_defaults import DEFAULT_MODELS


def _build_budget(args: argparse.Namespace) -> BudgetPolicy:
    budget = BudgetPolicy()
    if args.max_hours is not None:
        budget.max_seconds = max(60.0, args.max_hours * 3600)
    if args.max_tools is not None:
        budget.max_tool_calls = max(1, args.max_tools)
    if args.max_tokens is not None:
        budget.max_tokens = max(1000, args.max_tokens)
    if args.max_dollars is not None:
        budget.max_dollars = max(0.1, args.max_dollars)
    return budget


def _resolve_llm() -> Any | None:
    """Load an LLM instance from the ``SHIPIT_LLM`` env, or None if unset.

    Deliberately tolerant — if the user hasn't installed the provider
    SDK, we fall back to ``SimpleEchoLLM`` so they can smoke-test the
    pipeline before wiring real credentials.
    """
    name = os.environ.get("SHIPIT_LLM", "").lower()
    try:
        if name in ("openai", "oai"):
            from shipit_agent.llms import OpenAIChat

            return OpenAIChat(
                model=os.environ.get("SHIPIT_MODEL", DEFAULT_MODELS["openai"])
            )
        if name in ("anthropic", "claude"):
            from shipit_agent.llms import AnthropicChat

            return AnthropicChat(
                model=os.environ.get("SHIPIT_MODEL", DEFAULT_MODELS["anthropic"])
            )
        if name == "bedrock":
            from shipit_agent.llms import BedrockChat

            return BedrockChat(
                model=os.environ.get(
                    "SHIPIT_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
                )
            )
        if name == "ollama":
            from shipit_agent.llms import OllamaChat

            return OllamaChat(model=os.environ.get("SHIPIT_MODEL", "llama3.3"))
        # Default / fallback — the in-process echo LLM is safe to use
        # without any credentials and is useful for dry-running the loop.
        from shipit_agent.llms import SimpleEchoLLM

        return SimpleEchoLLM()
    except Exception as err:  # noqa: BLE001
        print(f"[warn] could not resolve LLM={name!r}: {err}", file=sys.stderr)
        return None


def _resolve_llm_factory():
    llm = _resolve_llm()
    if llm is None:
        return None
    return lambda: llm


def _stderr_event(payload: dict[str, Any]) -> None:
    # Daemon heartbeat sink — one line to stderr.
    kind = payload.get("kind") or "heartbeat"
    sys.stderr.write(f"[daemon {kind}] {payload}\n")

