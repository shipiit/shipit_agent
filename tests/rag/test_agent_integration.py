"""Integration tests: RAG with Agent and deep agents."""

from __future__ import annotations

import json

from shipit_agent.agent import Agent
from shipit_agent.deep.goal_agent import Goal, GoalAgent
from shipit_agent.deep.reflective_agent import ReflectiveAgent
from shipit_agent.rag.embedder import HashingEmbedder
from shipit_agent.rag.rag import RAG


from shipit_agent.llms.base import LLMResponse


class _ScriptedLLM:
    """Minimal LLM stub returning a plain text answer (no tool calls)."""

    def complete(self, messages, **kwargs):
        return LLMResponse(
            content="Based on the sources, Shipit supports Python 3.10+. [1]",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )


def test_agent_accepts_rag_parameter():
    rag = RAG.default(embedder=HashingEmbedder(dimension=128))
    rag.index_text(
        "Shipit supports Python 3.10+.", document_id="readme", source="readme"
    )
    agent = Agent(llm=_ScriptedLLM(), rag=rag)
    tool_names = {t.name for t in agent.tools}
    assert "rag_search" in tool_names
    assert "rag_fetch_chunk" in tool_names
    assert "rag_list_sources" in tool_names
    assert "rag_search" in agent.prompt.lower()


def test_agent_rag_tools_not_duplicated_on_rebuild():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("hi", document_id="d1")
    # Pre-populate with the same-named tool; __post_init__ should not duplicate.
    existing = rag.as_tools()[0]
    agent = Agent(llm=_ScriptedLLM(), tools=[existing], rag=rag)
    names = [t.name for t in agent.tools]
    assert names.count("rag_search") == 1


def test_agent_run_attaches_rag_sources():
    rag = RAG.default(embedder=HashingEmbedder(dimension=256))
    rag.index_text(
        "Shipit supports Python 3.10+.", document_id="readme", source="readme"
    )
    agent = Agent(llm=_ScriptedLLM(), rag=rag)
    result = agent.run("What Python version?")
    # Either the LLM stub called the tool and we captured a source, or
    # the stub bypassed tools and produced 0 sources. Both are valid
    # depending on runtime tool-call parsing — what matters is the field
    # is attached (empty or not).
    assert isinstance(result.rag_sources, list)


def test_agent_run_without_rag_has_empty_sources():
    agent = Agent(llm=_ScriptedLLM())
    result = agent.run("hi")
    assert result.rag_sources == []


def test_rag_search_tool_records_source_when_called_inside_run():
    """Directly invoke the tool inside a begin/end_run window — this is
    how the runtime actually captures sources."""
    rag = RAG.default(embedder=HashingEmbedder(dimension=256))
    rag.index_text(
        "Shipit supports Python 3.10+.", document_id="readme", source="readme"
    )
    from shipit_agent.tools.base import ToolContext

    rag.begin_run()
    search_tool = rag.as_tools()[0]
    output = search_tool.run(
        ToolContext(prompt="", metadata={}, state={}),
        query="python version",
        top_k=1,
    )
    sources = rag.end_run()
    payload = json.loads(output.text)
    assert payload["total_found"] >= 1
    assert len(sources) == 1
    assert sources[0].source == "readme"
    assert sources[0].index == 1


def test_goal_agent_accepts_rag():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("Shipit supports Python 3.10+.", document_id="readme")
    goal_agent = GoalAgent(
        llm=_ScriptedLLM(),
        goal=Goal(
            objective="Find python version", success_criteria=["mentions python"]
        ),
        rag=rag,
    )
    inner = goal_agent._build_agent()
    tool_names = {t.name for t in inner.tools}
    assert "rag_search" in tool_names


def test_reflective_agent_accepts_rag_kwarg():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("content", document_id="d1")
    # ReflectiveAgent forwards unknown kwargs to the inner Agent via **agent_kwargs.
    agent = ReflectiveAgent(llm=_ScriptedLLM(), rag=rag)
    inner = agent._build_agent()
    tool_names = {t.name for t in inner.tools}
    assert "rag_search" in tool_names
