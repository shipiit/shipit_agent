"""
11 — Deep Agents

GoalAgent, ReflectiveAgent, Supervisor, AdaptiveAgent, Channel,
and AgentBenchmark — the features that put SHIPIT beyond LangChain.

Run:
    python examples/11_deep_agents.py
"""

from __future__ import annotations

from examples.run_multi_tool_agent import build_llm_from_env
from shipit_agent import Agent
from shipit_agent.deep import (
    GoalAgent,
    Goal,
    ReflectiveAgent,
    Supervisor,
    Worker,
    AdaptiveAgent,
    Channel,
    AgentMessage,
    AgentBenchmark,
    TestCase,
)
from shipit_agent.tools.base import ToolContext


def demo_goal_agent(llm) -> None:
    print("\n" + "=" * 60)
    print("1. GOAL AGENT — Autonomous Goal Decomposition")
    print("=" * 60 + "\n")

    agent = GoalAgent(
        llm=llm,
        goal=Goal(
            objective="Explain 3 sorting algorithms with time complexity",
            success_criteria=[
                "Covers bubble sort, merge sort, quick sort",
                "Includes Big-O",
            ],
            max_steps=3,
        ),
    )

    for event in agent.stream():
        if event.type in (
            "run_started",
            "planning_completed",
            "step_started",
            "run_completed",
        ):
            print(f"  [{event.type:22s}] {event.message[:70]}")


def demo_reflective_agent(llm) -> None:
    print("\n" + "=" * 60)
    print("2. REFLECTIVE AGENT — Self-Improvement Loop")
    print("=" * 60 + "\n")

    agent = ReflectiveAgent(
        llm=llm,
        reflection_prompt="Check accuracy, completeness, and clarity. Score 0-1.",
        max_reflections=2,
        quality_threshold=0.8,
    )

    for event in agent.stream("Explain how a hash table works"):
        if event.type == "reasoning_completed":
            print(
                f"  REFLECTION: quality={event.payload.get('quality', '?'):.2f} — {event.payload.get('feedback', '')[:60]}"
            )
        elif event.type == "run_completed":
            print(f"  DONE: {event.message}")


def demo_supervisor(llm) -> None:
    print("\n" + "=" * 60)
    print("3. SUPERVISOR — Hierarchical Agent Management")
    print("=" * 60 + "\n")

    supervisor = Supervisor(
        llm=llm,
        workers=[
            Worker(
                name="analyst",
                agent=Agent(llm=llm, prompt="You are a data analyst. Be concise."),
            ),
            Worker(
                name="writer", agent=Agent(llm=llm, prompt="You write clear summaries.")
            ),
        ],
        max_delegations=4,
    )

    for event in supervisor.stream("Analyze Python's popularity and write a summary"):
        worker = event.payload.get("worker", "supervisor")
        if event.type in ("tool_called", "tool_completed", "run_completed"):
            print(f"  [{worker:15s}] {event.message[:70]}")


def demo_adaptive_agent(llm) -> None:
    print("\n" + "=" * 60)
    print("4. ADAPTIVE AGENT — Runtime Tool Creation")
    print("=" * 60 + "\n")

    agent = AdaptiveAgent(llm=llm, can_create_tools=True)

    fib = agent.create_tool(
        "fibonacci",
        "Fibonacci calculator",
        """
    def fibonacci(n: int) -> str:
        a, b = 0, 1
        for _ in range(n):
            a, b = b, a + b
        return str(a)
    """,
    )

    print(f"  Created: {fib.name}")
    print(f"  fibonacci(10) = {fib.run(ToolContext(prompt='test'), n=10).text}")
    print(f"  fibonacci(20) = {fib.run(ToolContext(prompt='test'), n=20).text}")
    print(f"  Total tools: {len(agent.tools)}")


def demo_channel() -> None:
    print("\n" + "=" * 60)
    print("5. CHANNEL — Typed Agent Communication")
    print("=" * 60 + "\n")

    channel = Channel(name="demo-pipeline")

    channel.send(
        AgentMessage(
            from_agent="researcher",
            to_agent="writer",
            type="findings",
            data={"facts": ["Fact 1", "Fact 2"]},
            requires_ack=True,
        )
    )
    channel.send(
        AgentMessage(
            from_agent="researcher",
            to_agent="reviewer",
            type="summary",
            data={"text": "Summary here"},
        )
    )

    msg = channel.receive(agent="writer")
    print(f"  Writer got: {msg.type} from {msg.from_agent} — {msg.data}")
    channel.ack(msg)
    print(f"  Acknowledged: {msg.acknowledged}")
    print(f"  Pending for reviewer: {channel.pending(agent='reviewer')}")
    print(f"  Total messages: {len(channel.history())}")


def demo_benchmark(llm) -> None:
    print("\n" + "=" * 60)
    print("6. AGENT BENCHMARK — Systematic Testing")
    print("=" * 60 + "\n")

    agent = Agent(llm=llm, prompt="You are a helpful programming assistant.")

    report = AgentBenchmark(
        name="knowledge-eval",
        cases=[
            TestCase(
                input="What is Python?", expected_contains=["python", "programming"]
            ),
            TestCase(input="Explain REST APIs", expected_contains=["http"]),
            TestCase(input="What is Docker?", expected_contains=["container"]),
        ],
    ).run(agent)

    print(report.summary())


def main() -> None:
    llm = build_llm_from_env()
    demo_goal_agent(llm)
    demo_reflective_agent(llm)
    demo_supervisor(llm)
    demo_adaptive_agent(llm)
    demo_channel()
    demo_benchmark(llm)


if __name__ == "__main__":
    main()
