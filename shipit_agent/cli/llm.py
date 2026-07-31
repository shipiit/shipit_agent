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

# Curated latest-model catalog per provider (July 2026) — shown by
# `shipit models`. (best) marks the strongest agentic pick per provider.
MODEL_CATALOG: dict[str, list[tuple[str, str]]] = {
    "anthropic": [
        ("claude-opus-5", "most capable Claude for complex agents (best)"),
        ("claude-sonnet-5", "flagship balance of speed and intelligence"),
        ("claude-haiku-4-5-20251001", "fastest/cheapest Claude"),
    ],
    "openai": [
        ("gpt-5.6", "newest flagship family"),
        ("gpt-5.5", "current production API recommendation (best)"),
        ("gpt-5.5-2026-04-23", "pinned snapshot of gpt-5.5"),
    ],
    "bedrock": [
        ("google.gemma-4-31b", "best open-weight agentic model (best)"),
        ("google.gemma-4-26b-a4b", "fast MoE Gemma (simple tool args only)"),
        ("bedrock/openai.gpt-oss-120b-1:0", "reasoning/coding heavyweight"),
        ("bedrock/anthropic.claude-sonnet-5-v1:0", "Claude Sonnet 5 on Bedrock"),
        ("bedrock/anthropic.claude-haiku-4-5-v1:0", "Claude Haiku on Bedrock"),
    ],
    "ollama": [
        ("ollama/llama3.1", "local default"),
        ("ollama/qwen3.5", "strong local tool-caller"),
    ],
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
    mcps = []
    raw_mcp = getattr(args, "mcp", None)
    if raw_mcp:
        from shipit_agent import connect_mcp

        for name in [n.strip() for n in raw_mcp.split(",") if n.strip()]:
            mcps.append(connect_mcp(name))
    from shipit_agent.hitl import ConsoleAskUserTool

    # CLI runs have a human at the terminal: swap the event-only ask_user
    # for the variant that actually prompts and returns the answer.
    extra_tools = [ConsoleAskUserTool()]
    role = getattr(args, "role", None)
    if role:
        return Agent.for_role(role, llm=llm, guardrails=guardrails,
                              mcps=mcps, tools=extra_tools)
    return Agent.with_builtins(
        llm=llm,
        project_root=getattr(args, "project_root", None) or os.getcwd(),
        guardrails=guardrails,
        mcps=mcps,
        tools=extra_tools,
    )
