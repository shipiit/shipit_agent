"""
04 — End-to-end research agent.

A realistic multi-step research workflow that uses several built-in tools
to answer a fact-based question grounded in real web sources, not LLM
prior knowledge.

What this example shows:
  - Disabling the auto-planner (it can confuse small models on research tasks)
  - Forcing tool use even with lazy models like gpt-4o-mini
  - A prompt structured to make the model do the work in the right order
  - Iteration-cap protection so the agent always returns a final answer

Run:
    python examples/04_research_agent.py "your question here"
    python examples/04_research_agent.py            # uses default question
"""
from __future__ import annotations

import sys

from shipit_agent.policies import RouterPolicy

from examples.run_multi_tool_agent import build_demo_agent, build_llm_from_env

DEFAULT_QUESTION = "What is the current price of Bitcoin in USD?"


def main() -> None:
    question = " ".join(sys.argv[1:]).strip() or DEFAULT_QUESTION

    llm = build_llm_from_env()
    agent = build_demo_agent(llm=llm)

    # The built-in `plan_task` tool injects a static "Plan: 1. Clarify…" stub
    # into the message history when the prompt looks plan-ish. Many small
    # models then *describe* the plan instead of *executing* it. For an
    # actual tool-using research run, turn the auto-planner off.
    agent.router_policy = RouterPolicy(auto_plan=False)

    # Realistic research loops need 5-6 iterations: search → open_url ×2 →
    # maybe retry → summarize. Default 4 is too tight.
    agent.max_iterations = 8

    prompt = (
        f"Research question: {question}\n\n"
        "Hard requirements you MUST follow:\n"
        "1. Call `web_search` first to find candidate sources.\n"
        "2. Call `open_url` on at least TWO different domains and extract\n"
        "   the relevant facts from each page.\n"
        "3. Do NOT answer from prior knowledge — only use what the tools\n"
        "   actually returned.\n"
        "4. After at most 6 tool calls, STOP and produce a final markdown\n"
        "   answer even if some sources failed.\n"
        "5. Final format: a markdown table of (Source, Finding, Fetched at)\n"
        "   followed by a 1-sentence summary.\n\n"
        "Begin by calling a tool. Do not describe your plan first."
    )

    print(f"\n{'═' * 60}")
    print(f"  Research: {question}")
    print(f"{'═' * 60}\n")

    result = agent.run(prompt)

    print(result.output)

    print(f"\n{'─' * 60}")
    print(f"  {len(result.tool_results)} tool calls executed")
    for i, tool_result in enumerate(result.tool_results, start=1):
        preview = tool_result.output[:80].replace("\n", " ")
        print(f"  {i}. {tool_result.name:18s} → {preview}…")


if __name__ == "__main__":
    main()
