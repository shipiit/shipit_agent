"""
10 — Agent Team

Dynamic multi-agent collaboration with LLM-routed coordination.
The coordinator decides who works, in what order, when to loop back.

Run:
    python examples/10_agent_team.py
"""
from __future__ import annotations

from examples.run_multi_tool_agent import build_llm_from_env
from shipit_agent import Agent, AgentTeam, TeamAgent


def main() -> None:
    llm = build_llm_from_env()

    team = AgentTeam(
        name="content-team",
        coordinator=llm,
        agents=[
            TeamAgent(name="researcher", role="Finds key facts from any topic", agent=Agent(llm=llm, prompt="You are a research expert. Return concise bullet points.")),
            TeamAgent(name="writer", role="Writes clear, engaging content", agent=Agent(llm=llm, prompt="You are a skilled writer.")),
            TeamAgent(name="reviewer", role="Reviews for accuracy and quality", agent=Agent(llm=llm, prompt="You are a critical reviewer. Say APPROVED or list issues.")),
        ],
        max_rounds=6,
    )

    print("=== Streaming Team Events ===\n")
    for event in team.stream("Write a concise overview of WebAssembly"):
        agent = event.payload.get("agent", "coordinator")
        if event.type in ("run_started", "planning_started", "tool_called", "tool_completed", "run_completed"):
            print(f"  [{agent:15s}] {event.type:22s} {event.message[:70]}")


if __name__ == "__main__":
    main()
