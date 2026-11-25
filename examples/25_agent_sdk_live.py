"""
25 — The SDK layer, live: streaming text and tool calls, a custom tool with an
image, the one-hour prompt cache, and the run's cost per model.

Uses a real model. Set ANTHROPIC_API_KEY (or put it in .env), then:

    python examples/25_agent_sdk_live.py

The same run from the terminal, without writing code:

    shipit sdk "What is the temperature in Paris?" --model claude-haiku-5-5
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, NotRequired, TypedDict

from shipit_agent.llms.factory import load_env_file
from shipit_agent.sdk import (
    AgentOptions,
    ResultMessage,
    StreamEvent,
    ToolAnnotations,
    create_sdk_mcp_server,
    query,
    tool,
)


class Lookup(TypedDict):
    city: Annotated[str, "The city to look up"]
    units: NotRequired[Annotated[str, "celsius or fahrenheit"]]


@tool("weather", "Get the current temperature in a city", Lookup, annotations=ToolAnnotations(readOnlyHint=True))
async def weather(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"It is 21 degrees in {args['city']}."}]}


async def main() -> None:
    options = AgentOptions(
        model="claude-haiku-5-5",
        tools=[],  # only the tool below
        mcp_servers={"util": create_sdk_mcp_server("util", tools=[weather])},
        allowed_tools=["mcp__util__weather"],
        include_partial_messages=True,  # live text and tool arguments
        cache_ttl="1h",
        max_budget_usd=0.10,
    )
    async for message in query(prompt="What is the temperature in Paris?", options=options):
        if isinstance(message, StreamEvent):
            event = message.event
            if event["type"] == "content_block_start" and event["content_block"]["type"] == "tool_use":
                print(f"\n[calling {event['content_block']['name']}] ", end="", flush=True)
            elif event["type"] == "content_block_delta":
                delta = event["delta"]
                print(delta.get("text") or delta.get("partial_json") or "", end="", flush=True)
        elif isinstance(message, ResultMessage):
            print(f"\n\n{message.subtype} in {message.num_turns} turns, ${message.total_cost_usd or 0:.4f}")
            for model, usage in (message.model_usage or {}).items():
                print(f"  {model}: {usage['inputTokens']:,} in, {usage['outputTokens']:,} out, "
                      f"{usage['cacheReadInputTokens']:,} read from cache")


if __name__ == "__main__":
    load_env_file()
    asyncio.run(main())
