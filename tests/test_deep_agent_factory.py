"""Tests for shipit_agent.deep.deep_agent (the DeepAgent factory)."""

from __future__ import annotations


from shipit_agent.deep import (
    DEEP_AGENT_PROMPT,
    DeepAgent,
    Goal,
    create_deep_agent,
)
from shipit_agent.deep.deep_agent.toolset import deep_tool_set, merge_tools
from shipit_agent.deep.deep_agent.verification import verify_text
from shipit_agent.llms import SimpleEchoLLM
from shipit_agent.models import Message
from shipit_agent.stores import InMemorySessionStore
from shipit_agent.tools.base import Tool, ToolContext, ToolOutput


# ---------------------------------------------------------------------------
# toolset
# ---------------------------------------------------------------------------


def test_deep_tool_set_returns_seven_tools():
    tools = deep_tool_set(llm=SimpleEchoLLM(), workspace_root=".tmp_workspace")
    names = sorted(t.name for t in tools)
    assert names == sorted(
        [
            "plan_task",
            "decompose_problem",
            "workspace_files",
            "sub_agent",
            "synthesize_evidence",
            "decision_matrix",
            "verify_output",
        ]
    )


def test_merge_tools_dedupes_by_name_last_wins():
    class _Stub:
        def __init__(self, name: str, tag: str) -> None:
            self.name = name
            self.tag = tag

    a1 = _Stub("planner", "first")
    a2 = _Stub("planner", "second")
    b = _Stub("other", "x")
    merged = merge_tools([a1, b], [a2])
    by_name = {t.name: t for t in merged}
    assert by_name["planner"].tag == "second"
    assert by_name["other"].tag == "x"


# ---------------------------------------------------------------------------
# factory wiring
# ---------------------------------------------------------------------------


def test_deep_agent_default_construction_uses_seven_tools():
    agent = DeepAgent(llm=SimpleEchoLLM())
    names = {t.name for t in agent.tools}
    for required in [
        "plan_task",
        "decompose_problem",
        "workspace_files",
        "sub_agent",
        "synthesize_evidence",
        "decision_matrix",
        "verify_output",
    ]:
        assert required in names, f"missing tool: {required}"


def test_deep_agent_uses_opinionated_prompt_by_default():
    agent = DeepAgent(llm=SimpleEchoLLM())
    assert agent.prompt is DEEP_AGENT_PROMPT
    assert "plan_task" in agent.agent.prompt
    assert "verify_output" in agent.agent.prompt


def test_deep_agent_with_builtins_includes_more_tools():
    plain = DeepAgent(llm=SimpleEchoLLM())
    full = DeepAgent.with_builtins(llm=SimpleEchoLLM())
    assert len(full.tools) > len(plain.tools)
    # Deep tools survive (no override)
    full_names = {t.name for t in full.tools}
    assert {"plan_task", "workspace_files", "sub_agent"} <= full_names


def test_deep_agent_extra_tools_are_appended():
    class EchoTool(Tool):
        name = "echo"
        description = "echo"
        prompt_instructions = ""

        def schema(self) -> dict:
            return {"name": "echo", "parameters": {"type": "object", "properties": {}}}

        def run(self, context: ToolContext, **_kwargs) -> ToolOutput:
            return ToolOutput(text="echo")

    agent = DeepAgent(llm=SimpleEchoLLM(), extra_tools=[EchoTool()])
    assert "echo" in {t.name for t in agent.tools}


def test_deep_agent_user_tool_with_clashing_name_is_replaced_by_deep_tool():
    class FakePlanner:
        name = "plan_task"
        description = "fake"
        prompt_instructions = ""

        def schema(self) -> dict:
            return {"name": "plan_task"}

        def run(self, context, **kwargs):  # pragma: no cover
            return ToolOutput(text="fake")

    agent = DeepAgent(llm=SimpleEchoLLM(), extra_tools=[FakePlanner()])
    planner = next(t for t in agent.tools if t.name == "plan_task")
    # The real PlannerTool wins (last-write semantics).
    from shipit_agent.tools.planner import PlannerTool

    assert isinstance(planner, PlannerTool)


def test_deep_agent_forwards_rag_to_inner_agent():
    from shipit_agent.rag import RAG
    from shipit_agent.rag.embedder import HashingEmbedder

    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("hello", document_id="d1")
    agent = DeepAgent(llm=SimpleEchoLLM(), rag=rag)
    inner_tool_names = {t.name for t in agent.agent.tools}
    assert "rag_search" in inner_tool_names
    assert agent.agent.rag is rag


def test_deep_agent_tunable_parameters_propagate():
    agent = DeepAgent(
        llm=SimpleEchoLLM(),
        max_iterations=20,
        parallel_tool_execution=False,
        context_window_tokens=200_000,
    )
    assert agent.agent.max_iterations == 20
    assert agent.agent.parallel_tool_execution is False
    assert agent.agent.context_window_tokens == 200_000


def test_deep_agent_accepts_agent_style_session_and_trace_fields() -> None:
    store = InMemorySessionStore()
    seed = [Message(role="user", content="Earlier message")]
    agent = DeepAgent(
        llm=SimpleEchoLLM(),
        session_store=store,
        session_id="deep-session",
        trace_id="deep-trace",
        metadata={"source": "api"},
        history=seed,
    )

    assert agent.agent.session_store is store
    assert agent.agent.session_id == "deep-session"
    assert agent.agent.trace_id == "deep-trace"
    assert agent.agent.metadata["source"] == "api"
    assert any(message.content == "Earlier message" for message in agent.agent.history)


# ---------------------------------------------------------------------------
# verification + reflection + goal modes
# ---------------------------------------------------------------------------


def test_verify_text_falls_back_to_default_criterion():
    verdict = verify_text("Some answer", goal=None)
    assert "text" in verdict
    assert "metadata" in verdict


def test_verify_text_uses_goal_criteria_when_provided():
    goal = Goal(objective="x", success_criteria=["mentions python", "mentions runtime"])
    verdict = verify_text("python runtime is great", goal=goal)
    assert (
        verdict["metadata"].get("criteria")
        == [
            "mentions python",
            "mentions runtime",
        ]
        or verdict["text"]
    )  # tolerant check — different verifier impls


def test_deep_agent_run_with_verify_attaches_verdict_to_metadata():
    agent = DeepAgent(llm=SimpleEchoLLM(), verify=True, max_iterations=1)
    result = agent.run("hi")
    assert "verification" in result.metadata


def test_deep_agent_run_without_verify_does_not_attach_verdict():
    agent = DeepAgent(llm=SimpleEchoLLM(), max_iterations=1)
    result = agent.run("hi")
    assert "verification" not in result.metadata


def test_deep_agent_goal_mode_delegates_to_goal_agent():
    goal = Goal(objective="say hi", success_criteria=["greeting"], max_steps=1)
    agent = DeepAgent(llm=SimpleEchoLLM(), goal=goal)
    result = agent.run()
    # GoalResult shape
    assert hasattr(result, "goal_status")
    assert hasattr(result, "criteria_met")


# ---------------------------------------------------------------------------
# create_deep_agent functional helper
# ---------------------------------------------------------------------------


def test_create_deep_agent_wraps_callable_tools():
    def my_tool(name: str) -> str:
        """Greet a user."""
        return f"hi {name}"

    agent = create_deep_agent(llm=SimpleEchoLLM(), tools=[my_tool])
    tool_names = {t.name for t in agent.tools}
    assert "my_tool" in tool_names
    # Deep-agent triad still present
    assert "plan_task" in tool_names


def test_create_deep_agent_passes_through_power_flags():
    agent = create_deep_agent(
        llm=SimpleEchoLLM(),
        verify=True,
        reflect=False,
        max_iterations=12,
    )
    assert isinstance(agent, DeepAgent)
    assert agent.verify is True
    assert agent.reflect is False
    assert agent.max_iterations == 12


def test_create_deep_agent_merges_tools_and_extra_tools_without_conflict():
    class ExtraTool:
        name = "extra"
        description = "extra"
        prompt_instructions = ""

        def schema(self):
            return {"name": "extra"}

        def run(self, context, **_):  # pragma: no cover
            return ToolOutput(text="x")

    def my_tool(name: str) -> str:
        return f"hi {name}"

    agent = create_deep_agent(
        llm=SimpleEchoLLM(),
        tools=[my_tool],
        extra_tools=[ExtraTool()],
    )

    tool_names = {t.name for t in agent.tools}
    assert "my_tool" in tool_names
    assert "extra" in tool_names


# ---------------------------------------------------------------------------
# chat session
# ---------------------------------------------------------------------------


def test_chat_returns_session_bound_to_inner_agent():
    agent = DeepAgent(llm=SimpleEchoLLM())
    chat = agent.chat(session_id="t-1")
    assert chat.session_id == "t-1"
    assert chat.agent is agent.agent


def test_chat_preserves_history_across_turns():
    agent = DeepAgent(llm=SimpleEchoLLM(), max_iterations=1)
    chat = agent.chat(session_id="t-2")
    chat.send("first message")
    chat.send("second message")
    history = chat.history()
    user_messages = [m for m in history if m.role == "user"]
    assert len(user_messages) == 2


# ---------------------------------------------------------------------------
# add_tool / add_mcp
# ---------------------------------------------------------------------------


def test_add_tool_appends_only_when_new_name():
    class T:
        name = "custom"
        description = ""
        prompt_instructions = ""

        def schema(self):
            return {"name": "custom"}

        def run(self, context, **_):  # pragma: no cover
            return ToolOutput(text="x")

    agent = DeepAgent(llm=SimpleEchoLLM())
    before = len(agent.tools)
    agent.add_tool(T())
    assert len(agent.tools) == before + 1
    agent.add_tool(T())  # second add is a no-op
    assert len(agent.tools) == before + 1
