"""Gemma on Amazon Bedrock, through Bedrock's OpenAI-compatible (Mantle) endpoint."""

from __future__ import annotations

from typing import Any

from shipit_agent.llms.openai_adapter import OpenAIChatLLM


def _bedrock_mantle_base_url(region: str) -> str:
    return f"https://bedrock-mantle.{region}.api.aws/openai/v1"


class BedrockGemmaChatLLM(OpenAIChatLLM):
    """Google **Gemma 4** on Amazon Bedrock — with native agentic tool use.

    Gemma 4 supports *native function calling for agentic workflows*, but on
    Bedrock it is served through the **OpenAI-compatible** ``bedrock-mantle``
    endpoint (not the Converse API that :class:`BedrockChatLLM` uses). So it runs
    on the OpenAI adapter — tool calls, streaming shape, and all — pointed at
    that endpoint with a **Bedrock API key**::

        # 1. Create a Bedrock API key: AWS console → Amazon Bedrock → API keys
        # 2. export AWS_BEARER_TOKEN_BEDROCK=...   (and AWS_REGION_NAME)
        from shipit_agent import Agent
        from shipit_agent.llms import BedrockGemmaChatLLM

        llm = BedrockGemmaChatLLM(model="google.gemma-4-31b", region="us-east-1")
        agent = Agent.with_builtins(llm=llm)
        print(agent.run("What's 2+2? Use a tool if it helps.").output)

    Model ids: ``google.gemma-4-31b`` (dense), ``google.gemma-4-26b-a4b`` (MoE),
    ``google.gemma-4-e2b`` (small). Regions at launch: us-east-1, us-east-2,
    us-west-2, eu-central-1. Multimodal (text + image) too.
    """

    def __init__(
        self,
        model: str = "google.gemma-4-31b",
        *,
        region: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        **client_kwargs: Any,
    ) -> None:
        import os

        resolved_region = (
            region
            or os.getenv("AWS_REGION_NAME")
            or os.getenv("AWS_DEFAULT_REGION")
            or "us-east-1"
        )
        resolved_key = api_key or os.getenv("AWS_BEARER_TOKEN_BEDROCK")
        client_kwargs.setdefault(
            "base_url", base_url or _bedrock_mantle_base_url(resolved_region)
        )
        super().__init__(model=model, api_key=resolved_key, **client_kwargs)
