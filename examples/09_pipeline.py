"""
09 — Pipeline Composition

Chain agents and functions into deterministic workflows.
Sequential, parallel, conditional routing, and streaming.

Run:
    python examples/09_pipeline.py

Requires:
    pip install 'shipit-agent[all]'
"""

from __future__ import annotations

import time

from examples.run_multi_tool_agent import build_llm_from_env
from shipit_agent import Agent, Pipeline, step, parallel


def word_count(text: str) -> str:
    """Pure Python step — no LLM needed."""
    words = len(text.split())
    return f"[{words} words]\n\n{text}"


def main() -> None:
    llm = build_llm_from_env()

    researcher = Agent(
        llm=llm, prompt="You are a research expert. Return concise bullet points."
    )
    writer = Agent(
        llm=llm, prompt="You are a technical writer. Write clear, engaging content."
    )

    # --- Sequential pipeline ---
    print("=== Sequential Pipeline ===\n")
    pipe = Pipeline.sequential(
        step("research", agent=researcher, prompt="Find 3 key facts about {topic}"),
        step(
            "write",
            agent=writer,
            prompt="Write a short paragraph using:\n{research.output}",
        ),
        step("final", fn=word_count),
    )

    result = pipe.run(topic="Python asyncio")
    print(f"Research: {result.steps['research'].output[:100]}...")
    print(f"Final: {result.output[:200]}...")

    # --- Parallel pipeline ---
    print("\n=== Parallel Pipeline ===\n")
    pros = Agent(llm=llm, prompt="List only the pros. Be concise.")
    cons = Agent(llm=llm, prompt="List only the cons. Be concise.")

    pipe = Pipeline(
        parallel(
            step("pros", agent=pros, prompt="Pros of {topic}"),
            step("cons", agent=cons, prompt="Cons of {topic}"),
        ),
        step(
            "combine",
            agent=writer,
            prompt="Synthesize:\nPros: {pros.output}\nCons: {cons.output}",
        ),
    )

    start = time.time()
    result = pipe.run(topic="microservices")
    print(f"Completed in {time.time() - start:.1f}s")
    print(f"Output: {result.output[:200]}...")

    # --- Streaming pipeline ---
    print("\n=== Streaming Pipeline ===\n")
    pipe = Pipeline.sequential(
        step("draft", agent=writer, prompt="Write a haiku about {topic}"),
        step("stats", fn=word_count),
    )

    for event in pipe.stream(topic="coding"):
        if event.type == "step_started":
            print(f"  >> {event.payload.get('step', 'parallel')}")
        elif event.type == "tool_completed":
            print(f"  << {event.payload['step']}: {event.payload['output'][:60]}...")
        elif event.type == "run_completed":
            print("  DONE")


if __name__ == "__main__":
    main()
