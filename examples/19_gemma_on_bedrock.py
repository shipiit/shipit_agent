"""
19 — Google Gemma on Amazon Bedrock (Gemma 3 & Gemma 4, agentic).

Everything goes through the ONE class you already know — `BedrockChatLLM`.
Pass a Gemma model id and it routes correctly for you:

    • Gemma 4  (google.gemma-4-*)   → native function calling for agents,
                                       served via Bedrock's OpenAI-compatible
                                       `bedrock-mantle` endpoint.
    • Gemma 3  (google.gemma-3-*)   → chat/completions via the Converse API.

No new class or function to learn — `BedrockChatLLM` figures out the path.

Setup:
    Gemma 4 (agentic): create a Bedrock API key (AWS console → Amazon Bedrock →
      API keys) and export it, plus a region where Gemma 4 is available:
          export AWS_BEARER_TOKEN_BEDROCK=...        # the Bedrock API key
          export AWS_REGION_NAME=us-east-1           # or us-east-2 / us-west-2 / eu-central-1
    Gemma 3 (chat): standard AWS credentials / region (no API key needed).

Run:
    python examples/19_gemma_on_bedrock.py
"""

from __future__ import annotations

import os

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms import BedrockChatLLM

# The Gemma catalogue on Bedrock (ids as they appear in your account).
GEMMA_4 = [
    "google.gemma-4-31b",       # dense, 30.7B — best quality
    "google.gemma-4-26b-a4b",   # mixture-of-experts, fast
    "google.gemma-4-e2b",       # small, cheap
]
GEMMA_3 = [
    "google.gemma-3-27b-it",
    "google.gemma-3-12b-it",
    "google.gemma-3-4b-it",
]


def get_time(city: str, **_ignored) -> str:
    """Return the current local time for a city (demo tool)."""
    return f"It's 3:00 PM in {city}."


def _banner(title: str) -> None:
    print("\n" + "─" * 64)
    print(f"  {title}")
    print("─" * 64)


def demo_gemma4_agentic() -> None:
    """Gemma 4 with a real tool — native function calling, via BedrockChatLLM."""
    _banner("Gemma 4 — agentic (native tool use)")
    if not os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
        print("  ⚠ Set AWS_BEARER_TOKEN_BEDROCK (a Bedrock API key) to run this.")
        print("    AWS console → Amazon Bedrock → API keys → create.")
        print("  Code (works once the key is set):\n")
        print("    llm = BedrockChatLLM(model='google.gemma-4-31b')")
        print("    agent = Agent.with_builtins(llm=llm)")
        print("    agent.run('What time is it in Tokyo?')  # calls the tool")
        return

    llm = BedrockChatLLM(model="google.gemma-4-31b")  # transparently → mantle
    agent = Agent.with_builtins(
        llm=llm, tools=[FunctionTool.from_callable(get_time)]
    )
    result = agent.run("What time is it in Tokyo? Use a tool.")
    print(f"  → {result.output}")


def demo_gemma3_chat() -> None:
    """Gemma 3 — chat/completions via the Converse API (same BedrockChatLLM)."""
    _banner("Gemma 3 — chat (Converse)")
    region = os.getenv("AWS_REGION_NAME") or os.getenv("AWS_DEFAULT_REGION")
    if not region and not os.getenv("AWS_PROFILE"):
        print("  ⚠ Set AWS_REGION_NAME (+ AWS credentials) to run this.")
        print("  Code:\n    llm = BedrockChatLLM(model='bedrock/google.gemma-3-27b-it')")
        return
    llm = BedrockChatLLM(model="bedrock/google.gemma-3-27b-it")
    agent = Agent(llm=llm, auto_use_skills=False)
    print(f"  → {agent.run('In one sentence, what is Amazon Bedrock?').output}")


def main() -> None:
    print("Google Gemma on Amazon Bedrock — one class: BedrockChatLLM")
    print(f"  Gemma 4 (agentic): {', '.join(GEMMA_4)}")
    print(f"  Gemma 3 (chat):    {', '.join(GEMMA_3)}")
    demo_gemma4_agentic()
    demo_gemma3_chat()
    print("\nSame code, any Gemma — BedrockChatLLM routes it for you. ✓")


if __name__ == "__main__":
    main()
