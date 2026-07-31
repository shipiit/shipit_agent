"""Provider → LLM construction for the CLI."""

from __future__ import annotations

import os
from typing import Any

# Latest defaults (July 2026): Claude 5 family for Anthropic, GPT-5.5 for
# OpenAI (the current production API recommendation), Gemma 4 31B for
# Bedrock agents. Override any of these with --model / $SHIPIT_MODEL.
DEFAULT_MODELS = {
    "bedrock": "google.gemma-4-31b",
    "openai": "gpt-5.5",
    "anthropic": "claude-sonnet-5",
    "ollama": "ollama/llama3.1",
}


def build_llm(provider: str | None = None, model: str | None = None) -> Any:
    provider = (provider or os.environ.get("SHIPIT_LLM_PROVIDER") or "echo").lower()
    model = model or os.environ.get("SHIPIT_MODEL") or DEFAULT_MODELS.get(provider, "")
    if provider == "echo":
        from shipit_agent.llms import SimpleEchoLLM

        return SimpleEchoLLM()
    if provider == "bedrock":
        from shipit_agent.llms import BedrockChatLLM

        return BedrockChatLLM(
            model=model, region=os.environ.get("AWS_REGION_NAME", "us-east-1")
        )
    if provider == "openai":
        from shipit_agent.llms import OpenAIChatLLM

        return OpenAIChatLLM(model=model)
    if provider == "anthropic":
        from shipit_agent.llms import AnthropicChatLLM

        return AnthropicChatLLM(model=model)
    if provider == "ollama":
        from shipit_agent.llms import LiteLLMChatLLM

        return LiteLLMChatLLM(
            model if model.startswith("ollama/") else f"ollama/{model}"
        )
    raise SystemExit(
        f"Unknown provider '{provider}'. "
        "Choose: bedrock | openai | anthropic | ollama | echo"
    )


def build_agent(args: Any) -> Any:
    """Shared agent construction for run/serve/doctor/code."""
    from shipit_agent import Agent, Guardrails

    llm = build_llm(getattr(args, "provider", None), getattr(args, "model", None))
    guardrails = None
    mode = getattr(args, "guardrails", None)
    if mode == "strict":
        guardrails = Guardrails.strict()
    elif mode == "standard":
        guardrails = Guardrails.standard()
    role = getattr(args, "role", None)
    if role:
        return Agent.for_role(role, llm=llm, guardrails=guardrails)
    return Agent.with_builtins(
        llm=llm,
        project_root=getattr(args, "project_root", None) or os.getcwd(),
        guardrails=guardrails,
    )
