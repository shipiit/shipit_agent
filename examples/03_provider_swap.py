"""
03 — Switch LLM providers without changing code.

The same agent and same prompt, run against four different providers
back-to-back. The only thing that changes is `build_llm_from_env(<name>)`.

This is the killer feature for vendor-agnostic agents: you can write your
agent once and run it against OpenAI today, Bedrock tomorrow, your own
LiteLLM proxy next week — without touching anything in the agent layer.

Run:
    # Set credentials in .env for whichever providers you want to test
    python examples/03_provider_swap.py

The example skips any provider whose credentials aren't configured, so
you can run it with just one provider set up.
"""

from __future__ import annotations

import os
import time
import traceback

from examples.run_multi_tool_agent import build_demo_agent, build_llm_from_env

PROMPT = "In one sentence: what is 17 * 23? Show the calculation."


def try_provider(name: str) -> None:
    print(f"\n{'═' * 60}")
    print(f"  Provider: {name}")
    print(f"{'═' * 60}")

    try:
        llm = build_llm_from_env(name)
    except RuntimeError as exc:
        print(f"  ⊘ skipped: {exc}")
        return

    agent = build_demo_agent(llm=llm)

    start = time.monotonic()
    try:
        result = agent.run(PROMPT)
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ failed: {exc}")
        if os.getenv("VERBOSE"):
            traceback.print_exc()
        return

    elapsed = time.monotonic() - start
    tool_count = len(result.tool_results)
    tool_names = ", ".join(t.name for t in result.tool_results) or "none"

    print(f"  ✓ {elapsed:.2f}s  ·  {tool_count} tool calls ({tool_names})")
    print(f"\n  {result.output[:300]}")
    if len(result.output) > 300:
        print("  …")


def main() -> None:
    print("Same prompt, same agent, different providers")
    print(f"Prompt: {PROMPT}")

    # Try providers in order of likelihood. Each one is independent.
    for provider in ("openai", "anthropic", "bedrock", "gemini", "groq"):
        try_provider(provider)

    print(f"\n{'═' * 60}")
    print("  Done. The agent code never changed — only the LLM did.")
    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    main()
