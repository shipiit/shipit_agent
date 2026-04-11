"""
07 — Semantic tool discovery with ToolSearchTool.

When an agent has 28+ tools attached, two things go wrong:
  1. Token bloat: every turn ships the full tool catalog to the LLM
  2. Tool hallucination: the model invents tool names that don't exist

ToolSearchTool fixes both. Given a plain-language query, it returns a
ranked shortlist of the most relevant currently-registered tools.

This example shows tool_search in two modes:
  A) Standalone — call it directly to see how ranking works
  B) In a loop — let the agent use it before committing to a tool call

Run:
    python examples/07_tool_search.py
"""

from __future__ import annotations

from shipit_agent import Agent, ToolSearchTool, get_builtin_tools
from shipit_agent.tools.base import ToolContext

from examples.run_multi_tool_agent import build_llm_from_env


def standalone_demo() -> None:
    """Call tool_search directly without an LLM in the loop."""
    print("─" * 60)
    print("  A) Standalone tool_search — no LLM involved")
    print("─" * 60)

    tools = get_builtin_tools(llm=None)
    available = [
        {
            "name": t.name,
            "description": getattr(t, "description", ""),
            "prompt_instructions": getattr(t, "prompt_instructions", ""),
        }
        for t in tools
    ]
    print(f"\n  {len(available)} tools registered\n")

    search = ToolSearchTool()
    context = ToolContext(prompt="", state={"available_tools": available})

    queries = [
        "find live information from the web",
        "execute python code",
        "ask the user a clarifying question",
        "remember a fact for later",
        "wait for human approval before doing something risky",
    ]

    for query in queries:
        print(f"  query: {query!r}")
        result = search.run(context, query=query, limit=3)
        # Just show the first 3 ranked tool names + scores
        for match in result.metadata["matches"]:
            print(f"    → {match['name']:25s} score={match['score']}")
        print()


def llm_demo() -> None:
    """Let an actual agent use tool_search to discover tools mid-loop."""
    print("─" * 60)
    print("  B) Agent uses tool_search in its own loop")
    print("─" * 60)

    llm = build_llm_from_env()

    agent = Agent.with_builtins(
        llm=llm,
        web_search_provider="duckduckgo",
    )

    prompt = (
        "I need to fetch a specific URL and extract the page title. "
        "Step 1: call `tool_search` to find the right tool. "
        "Step 2: call that tool on https://www.python.org/. "
        "Step 3: return only the page title."
    )

    print(f"\n  prompt: {prompt}\n")

    result = agent.run(prompt)

    print(f"  Agent answer:\n  {result.output}\n")
    print("  Tools called in order:")
    for i, tool_result in enumerate(result.tool_results, start=1):
        print(f"    {i}. {tool_result.name}")


def main() -> None:
    standalone_demo()
    llm_demo()


if __name__ == "__main__":
    main()
