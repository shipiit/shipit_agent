"""
23 — One agent, switching Bedrock models: Gemma 4 26B ↔ gpt-oss-120B.

`BedrockChatLLM` routes each model id to the right Bedrock path for you:

    google.gemma-4-26b-a4b            → OpenAI-compatible `bedrock-mantle`
                                        endpoint (native function calling)
    bedrock/openai.gpt-oss-120b-1:0   → Converse API (via litellm)

Same agent, same tools, same run_live() — just swap the id.

Auth:
    Gemma 4 needs a Bedrock API key. Either export one:
        export AWS_BEARER_TOKEN_BEDROCK=...   AWS_REGION_NAME=us-east-1
    or just have standard AWS credentials — this script auto-generates a
    short-term token from them (pip install aws-bedrock-token-generator).
    gpt-oss uses your standard AWS credentials directly.

Run:
    python examples/23_bedrock_model_switching.py
    SHIPIT_BEDROCK_MODEL=bedrock/openai.gpt-oss-120b-1:0 \
        python examples/23_bedrock_model_switching.py   # single model
"""

from __future__ import annotations

import os

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms import BedrockChatLLM

MODELS = [
    "google.gemma-4-26b-a4b",           # Gemma 4 26B (MoE) — mantle
    "bedrock/openai.gpt-oss-120b-1:0",  # gpt-oss 120B — Converse
]


def ensure_bedrock_token() -> bool:
    """Make sure AWS_BEARER_TOKEN_BEDROCK is set (Gemma 4 / mantle auth)."""
    if os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
        return True
    try:
        from aws_bedrock_token_generator import provide_token

        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = provide_token(region="us-east-1")
        os.environ.setdefault("AWS_REGION_NAME", "us-east-1")
        print("✓ short-term Bedrock token generated from AWS credentials")
        return True
    except Exception as err:
        print(f"⚠ no Bedrock token available ({type(err).__name__}) — "
              "Gemma 4 will be skipped")
        return False


def get_time(city: str, **_):
    """Return the local time for a city (demo tool)."""
    return f"It's 3:00 PM in {city}."


def build_agent(model_id: str) -> Agent:
    """Same agent for any Bedrock model — BedrockChatLLM routes it."""
    return Agent(
        llm=BedrockChatLLM(model=model_id, region="us-east-1"),
        tools=[FunctionTool.from_callable(get_time, name="get_time")],
        auto_use_skills=False,
    )


def main() -> None:
    have_mantle = ensure_bedrock_token()
    override = os.getenv("SHIPIT_BEDROCK_MODEL")
    models = [override] if override else MODELS

    for model in models:
        if "gemma-4" in model and not have_mantle:
            continue
        print(f"\n════ {model} ════")
        agent = build_agent(model)
        answer = agent.run_live(
            "What time is it in Tokyo? Use the tool, answer in one sentence."
        )
        print(f"→ {answer}")

    print("\nSame code, both models — BedrockChatLLM routed each correctly. ✓")


if __name__ == "__main__":
    main()
