"""End-to-end smoke tests against real Bedrock.

Run with::

    python scripts/smoke_bedrock_e2e.py

Tests every public surface against a real LLM:
    1.  Plain Agent — basic run
    2.  Agent + custom FunctionTool
    3.  Agent + RAG (citations captured)
    4.  Agent.stream() — streaming events
    5.  Agent.chat_session() — multi-turn
    6.  DeepAgent — seven deep tools wired
    7.  DeepAgent + RAG (citations captured)
    8.  DeepAgent.stream()
    9.  DeepAgent with verify=True
    10. DeepAgent with goal=Goal(...)
    11. DeepAgent.chat() multi-turn
    12. DeepAgent + agents=[...] — sub-agent delegation
    13. GoalAgent
    14. ReflectiveAgent
    15. AdaptiveAgent
    16. Supervisor + workers
    17. PersistentAgent
    18. Memory — AgentMemory + memory_store=
    19. Full stack — DeepAgent(rag, memory, agents, verify)

Requires AWS credentials (AWS_REGION_NAME / AWS_PROFILE / AWS_ACCESS_KEY_ID).
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from examples.run_multi_tool_agent import build_llm_from_env  # noqa: E402

from shipit_agent import Agent, AgentMemory  # noqa: E402
from shipit_agent.deep import (  # noqa: E402
    AdaptiveAgent,
    DeepAgent,
    Goal,
    GoalAgent,
    PersistentAgent,
    ReflectiveAgent,
    Supervisor,
    create_deep_agent,
)
from shipit_agent.rag import RAG, HashingEmbedder  # noqa: E402
from shipit_agent.stores import InMemoryMemoryStore, InMemorySessionStore  # noqa: E402
from shipit_agent.tools import FunctionTool  # noqa: E402


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------


def section(title: str) -> None:
    bar = "─" * (len(title) + 4)
    print(f"\n┌{bar}┐\n│  {title}  │\n└{bar}┘")


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")


def fail(msg: str, exc: Exception | None = None) -> None:
    print(f"  ❌ {msg}")
    if exc is not None:
        print("     " + "\n     ".join(traceback.format_exc().splitlines()[-6:]))


def echo_embed(text: str) -> list[float]:
    """Stand-in embedding fn — single string in, single vector out."""
    return [float(len(text)), float(text.count(" "))] + [0.0] * 14


def _seeded_rag() -> RAG:
    rag = RAG.default(embedder=HashingEmbedder(dimension=512))
    rag.index_text(
        "Shipit supports Python 3.10 and newer.",
        document_id="readme",
        source="readme.md",
    )
    rag.index_text(
        "Shipit agents stream events in real time.",
        document_id="streaming",
        source="streaming.md",
    )
    rag.index_text(
        "DeepAgent ships seven deep tools out of the box.",
        document_id="deep",
        source="deep_agent.md",
    )
    return rag


# ----------------------------------------------------------------------------
# tests
# ----------------------------------------------------------------------------


def test_1_plain_agent(llm) -> bool:
    section("1. Plain Agent — basic run")
    try:
        agent = Agent.with_builtins(llm=llm)
        ok(f"agent built with {len(agent.tools)} tools")
        result = agent.run("Say 'hello world' and stop.")
        assert result.output, "expected non-empty output"
        ok(f"run completed — output: {result.output[:80]!r}")
        return True
    except Exception as exc:
        fail("plain Agent run failed", exc)
        return False


def test_2_agent_with_custom_tool(llm) -> bool:
    section("2. Agent + custom FunctionTool")
    try:
        def reverse_string(text: str) -> str:
            """Reverse the input string."""
            return text[::-1]

        tool = FunctionTool.from_callable(reverse_string)
        agent = Agent.with_builtins(llm=llm, tools=[tool])
        names = {t.name for t in agent.tools}
        assert "reverse_string" in names, "custom tool must be registered"
        ok("custom function tool wired")
        result = agent.run("Use the reverse_string tool to reverse 'shipit' and tell me the result.")
        ok(f"run completed — output: {result.output[:120]!r}")
        return True
    except Exception as exc:
        fail("Agent + custom tool run failed", exc)
        return False


def test_3_agent_with_rag(llm) -> bool:
    section("3. Agent + RAG — sources captured")
    try:
        rag = _seeded_rag()
        agent = Agent.with_builtins(llm=llm, rag=rag)
        tool_names = {t.name for t in agent.tools}
        assert "rag_search" in tool_names
        ok("rag_search / rag_fetch_chunk / rag_list_sources wired")
        result = agent.run(
            "Use rag_search to find what Python version Shipit supports, "
            "then state it concisely with a [1] citation."
        )
        ok(f"run completed — output: {result.output[:120]!r}")
        ok(f"rag_sources captured: {len(result.rag_sources)}")
        for src in result.rag_sources[:3]:
            print(f"     [{src.index}] {src.source} :: {src.text[:60]}")
        return True
    except Exception as exc:
        fail("Agent + RAG run failed", exc)
        return False


def test_4_agent_stream(llm) -> bool:
    section("4. Agent.stream() — streaming events")
    try:
        agent = Agent.with_builtins(llm=llm)
        events = []
        for event in agent.stream("Say 'streaming works' and stop."):
            events.append(event.type)
        ok(f"received {len(events)} events: {events[:5]}{'…' if len(events) > 5 else ''}")
        assert "run_completed" in events, "missing run_completed event"
        return True
    except Exception as exc:
        fail("Agent.stream() failed", exc)
        return False


def test_5_agent_chat_session(llm) -> bool:
    section("5. Agent.chat_session() — multi-turn")
    try:
        agent = Agent.with_builtins(
            llm=llm,
            session_store=InMemorySessionStore(),
        )
        session = agent.chat_session(session_id="smoke-1")
        r1 = session.send("Remember the codeword is 'pelican'.")
        ok(f"turn 1 → {r1.output[:80]!r}")
        r2 = session.send("What was the codeword I just told you?")
        ok(f"turn 2 → {r2.output[:80]!r}")
        history = session.history()
        ok(f"history length: {len(history)} messages")
        return True
    except Exception as exc:
        fail("Agent.chat_session() failed", exc)
        return False


def test_6_deep_agent(llm) -> bool:
    section("6. DeepAgent — seven deep tools wired")
    try:
        agent = DeepAgent.with_builtins(llm=llm)
        names = {t.name for t in agent.tools}
        for required in (
            "plan_task",
            "decompose_problem",
            "workspace_files",
            "sub_agent",
            "synthesize_evidence",
            "decision_matrix",
            "verify_output",
        ):
            assert required in names, f"missing deep tool: {required}"
        ok(f"all 7 deep tools wired ({len(agent.tools)} tools total)")
        result = agent.run("Say 'deep agent ready' and stop.")
        ok(f"run completed — output: {result.output[:80]!r}")
        return True
    except Exception as exc:
        fail("DeepAgent run failed", exc)
        return False


def test_7_deep_agent_with_rag(llm) -> bool:
    section("7. DeepAgent + RAG — full citation flow")
    try:
        rag = _seeded_rag()
        agent = DeepAgent.with_builtins(llm=llm, rag=rag)
        result = agent.run(
            "Call rag_search to find how many deep tools DeepAgent ships with, "
            "then state the number concisely with a [1] citation."
        )
        ok(f"run completed — output: {result.output[:120]!r}")
        ok(f"rag_sources captured: {len(result.rag_sources)}")
        return True
    except Exception as exc:
        fail("DeepAgent + RAG run failed", exc)
        return False


def test_8_deep_agent_stream(llm) -> bool:
    section("8. DeepAgent.stream()")
    try:
        agent = DeepAgent.with_builtins(llm=llm)
        events = []
        for event in agent.stream("Say 'deep stream works' and stop."):
            events.append(event.type)
        ok(f"received {len(events)} events: {events[:5]}{'…' if len(events) > 5 else ''}")
        assert "run_completed" in events
        return True
    except Exception as exc:
        fail("DeepAgent.stream() failed", exc)
        return False


def test_9_deep_agent_verify(llm) -> bool:
    section("9. DeepAgent verify=True")
    try:
        agent = DeepAgent.with_builtins(llm=llm, verify=True, max_iterations=3)
        result = agent.run("Say 'verified output' and stop.")
        ok(f"run completed — output: {result.output[:80]!r}")
        ok(f"verification verdict attached: {'verification' in result.metadata}")
        return True
    except Exception as exc:
        fail("DeepAgent verify=True failed", exc)
        return False


def test_10_deep_agent_goal(llm) -> bool:
    section("10. DeepAgent goal=Goal(...)")
    try:
        agent = DeepAgent.with_builtins(
            llm=llm,
            goal=Goal(
                objective="Say hello and confirm Python 3.10+ support.",
                success_criteria=["greeting", "mentions python"],
                max_steps=2,
            ),
        )
        result = agent.run()
        ok(f"goal_status: {result.goal_status}")
        ok(f"criteria_met: {result.criteria_met}")
        ok(f"steps_taken: {result.steps_taken}")
        return True
    except Exception as exc:
        fail("DeepAgent goal run failed", exc)
        return False


def test_11_deep_agent_chat(llm) -> bool:
    section("11. DeepAgent.chat() multi-turn")
    try:
        agent = DeepAgent.with_builtins(
            llm=llm,
            session_store=InMemorySessionStore(),
        )
        chat = agent.chat(session_id="smoke-deep-1")
        r1 = chat.send("Remember the secret number is 42.")
        ok(f"turn 1 → {r1.output[:80]!r}")
        r2 = chat.send("What was the secret number?")
        ok(f"turn 2 → {r2.output[:80]!r}")
        return True
    except Exception as exc:
        fail("DeepAgent.chat() failed", exc)
        return False


def test_12_deep_agent_subagents(llm) -> bool:
    section("12. DeepAgent + agents=[...] — sub-agent delegation")
    try:
        researcher = Agent.with_builtins(
            llm=llm,
            name="researcher",
            description="Researches facts thoroughly.",
        )
        writer = Agent.with_builtins(
            llm=llm,
            name="writer",
            description="Writes concise final answers.",
        )
        agent = create_deep_agent(
            llm=llm,
            agents=[researcher, writer],
            use_builtins=True,
        )
        sub_names = list(agent.sub_agents.keys())
        assert sub_names == ["researcher", "writer"]
        ok(f"sub-agents wired: {sub_names}")
        result = agent.run("Say 'delegation ready' and stop.")
        ok(f"run completed — output: {result.output[:80]!r}")
        return True
    except Exception as exc:
        fail("DeepAgent + agents= run failed", exc)
        return False


def test_13_goal_agent(llm) -> bool:
    section("13. GoalAgent")
    try:
        agent = GoalAgent.with_builtins(
            llm=llm,
            goal=Goal(
                objective="Say 'goal agent works' and stop.",
                success_criteria=["mentions goal agent"],
                max_steps=2,
            ),
        )
        result = agent.run()
        ok(f"goal_status: {result.goal_status}")
        ok(f"criteria_met: {result.criteria_met}")
        return True
    except Exception as exc:
        fail("GoalAgent run failed", exc)
        return False


def test_14_reflective_agent(llm) -> bool:
    section("14. ReflectiveAgent")
    try:
        agent = ReflectiveAgent.with_builtins(
            llm=llm,
            quality_threshold=0.5,
            max_reflections=2,
        )
        result = agent.run("Write one short sentence about Shipit and stop.")
        ok(f"final output: {result.output[:120]!r}")
        ok(f"final quality: {result.final_quality}")
        ok(f"iterations: {result.iterations}")
        return True
    except Exception as exc:
        fail("ReflectiveAgent run failed", exc)
        return False


def test_15_adaptive_agent(llm) -> bool:
    section("15. AdaptiveAgent")
    try:
        agent = AdaptiveAgent.with_builtins(llm=llm, can_create_tools=True)
        result = agent.run("Say 'adaptive ready' and stop.")
        ok(f"run completed — output: {result.output[:80]!r}")
        ok(f"created tools at runtime: {len(agent.created_tools)}")
        return True
    except Exception as exc:
        fail("AdaptiveAgent run failed", exc)
        return False


def test_16_supervisor(llm) -> bool:
    section("16. Supervisor + workers")
    try:
        supervisor = Supervisor.with_builtins(
            llm=llm,
            worker_configs=[
                {"name": "researcher", "prompt": "You research facts."},
                {"name": "writer", "prompt": "You write concise answers."},
            ],
            max_delegations=3,
        )
        ok(f"supervisor built with {len(supervisor.workers)} workers")
        result = supervisor.run("Say 'supervisor ready' and stop.")
        ok(f"final output: {str(result.output)[:120]!r}")
        return True
    except Exception as exc:
        fail("Supervisor run failed", exc)
        return False


def test_17_persistent_agent(llm) -> bool:
    section("17. PersistentAgent")
    try:
        agent = PersistentAgent(
            llm=llm,
            checkpoint_dir=".smoke_checkpoints",
            checkpoint_interval=1,
            max_steps=2,
        )
        result = agent.run("Say 'persistent done'.", agent_id="smoke-persist")
        ok(f"run completed — output: {str(result.output)[:80]!r}")
        return True
    except Exception as exc:
        fail("PersistentAgent run failed", exc)
        return False


def test_18_memory(llm) -> bool:
    section("18. Memory — AgentMemory + memory_store=")
    try:
        profile = AgentMemory.default(llm=llm, embedding_fn=echo_embed)
        profile.add_fact("user_favourite_colour=teal")
        profile.add_fact("user_timezone=Europe/Berlin")
        ok("AgentMemory pre-loaded with 2 facts")

        tool_store = InMemoryMemoryStore()
        agent = DeepAgent.with_builtins(
            llm=llm,
            memory=profile,
            memory_store=tool_store,
        )
        inner = agent.agent
        ok(f"inner.memory_store: {type(inner.memory_store).__name__}")
        tool_names = {t.name for t in inner.tools}
        assert "memory" in tool_names
        ok("runtime memory tool wired")
        result = agent.run("Say 'memory ready' and stop.")
        ok(f"run completed — output: {result.output[:80]!r}")
        return True
    except Exception as exc:
        fail("Memory run failed", exc)
        return False


def test_19_full_stack(llm) -> bool:
    section("19. Full stack — DeepAgent(rag, memory, agents, verify)")
    try:
        rag = _seeded_rag()
        profile = AgentMemory.default(llm=llm, embedding_fn=echo_embed)
        profile.add_fact("user_role=engineer")

        researcher = Agent.with_builtins(
            llm=llm,
            name="researcher",
            description="Searches RAG for facts.",
            rag=rag,
        )

        agent = DeepAgent.with_builtins(
            llm=llm,
            rag=rag,
            memory=profile,
            memory_store=InMemoryMemoryStore(),
            agents=[researcher],
            verify=True,
            max_iterations=4,
        )

        ok("DeepAgent built with rag + memory + memory_store + agents + verify")
        ok(f"  inner tools: {len(agent.tools)}")
        ok(f"  sub_agents : {list(agent.sub_agents.keys())}")
        ok(f"  rag attached: {agent.rag is not None}")
        ok(f"  verify: {agent.verify}")

        result = agent.run(
            "Use rag_search to find what Python version Shipit supports, "
            "then state it concisely with a [1] citation."
        )
        ok(f"run completed — output: {result.output[:120]!r}")
        ok(f"rag_sources: {len(result.rag_sources)}")
        ok(f"verification: {'verification' in result.metadata}")
        return True
    except Exception as exc:
        fail("Full-stack run failed", exc)
        return False


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------


def main() -> int:
    print("\n🚀 Bedrock end-to-end smoke tests")
    try:
        llm = build_llm_from_env("bedrock")
        print(f"   LLM: {llm.__class__.__name__} model={getattr(llm, 'model', '?')}")
    except Exception as exc:
        fail("could not build Bedrock LLM", exc)
        return 1

    tests = [
        test_1_plain_agent,
        test_2_agent_with_custom_tool,
        test_3_agent_with_rag,
        test_4_agent_stream,
        test_5_agent_chat_session,
        test_6_deep_agent,
        test_7_deep_agent_with_rag,
        test_8_deep_agent_stream,
        test_9_deep_agent_verify,
        test_10_deep_agent_goal,
        test_11_deep_agent_chat,
        test_12_deep_agent_subagents,
        test_13_goal_agent,
        test_14_reflective_agent,
        test_15_adaptive_agent,
        test_16_supervisor,
        test_17_persistent_agent,
        test_18_memory,
        test_19_full_stack,
    ]
    results = []
    for fn in tests:
        results.append(fn(llm))

    section("Summary")
    passed = sum(1 for r in results if r)
    print(f"  {passed}/{len(results)} tests passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
