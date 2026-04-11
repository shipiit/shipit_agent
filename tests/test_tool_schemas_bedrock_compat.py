"""Regression test: every built-in tool produces a Bedrock-compatible schema.

Bedrock's Converse API rejects tool schemas with empty ``name`` or
``description`` and requires the OpenAI/LiteLLM-style wrapped shape::

    {"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}

Tools that return a flat ``{"name": ..., "description": ..., "parameters": ...}``
dict get treated as if their top-level ``name`` and ``description`` were
empty by LiteLLM's Bedrock adapter, which is the bug this test prevents
from regressing.
"""
from __future__ import annotations

import re

from shipit_agent import Agent
from shipit_agent.builtins import get_builtin_tools
from shipit_agent.deep import DeepAgent
from shipit_agent.deep.deep_agent.delegation import AgentDelegationTool
from shipit_agent.llms import SimpleEchoLLM
from shipit_agent.rag import RAG, HashingEmbedder


_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _assert_bedrock_compatible(tool, *, label: str) -> None:
    schema = tool.schema()
    assert isinstance(schema, dict), f"{label}.schema() must return a dict"

    # Wrapped function-call shape
    assert schema.get("type") == "function", (
        f"{label}.schema() must use the {{'type': 'function', 'function': ...}} "
        f"wrapper that LiteLLM/Bedrock expects (got top-level keys: {list(schema.keys())})"
    )
    fn = schema.get("function")
    assert isinstance(fn, dict), f"{label}.schema() function block must be a dict"

    name = fn.get("name", "")
    description = fn.get("description", "")

    assert name, f"{label}: function name must be non-empty (Bedrock rejects empty names)"
    assert _NAME_RE.fullmatch(name), (
        f"{label}: function name {name!r} must match [a-zA-Z0-9_-]+ "
        "(Bedrock's regex constraint)"
    )
    assert description, (
        f"{label}: function description must be non-empty (Bedrock rejects empty)"
    )

    parameters = fn.get("parameters")
    assert isinstance(parameters, dict), (
        f"{label}: parameters block must be present (got {type(parameters).__name__})"
    )
    assert parameters.get("type") == "object", (
        f"{label}: parameters.type must be 'object'"
    )


def test_all_builtin_tools_are_bedrock_compatible():
    llm = SimpleEchoLLM()
    tools = get_builtin_tools(llm=llm, workspace_root=".tmp_workspace")
    assert tools, "expected at least one built-in tool"
    for tool in tools:
        label = f"builtin tool {getattr(tool, 'name', tool.__class__.__name__)}"
        _assert_bedrock_compatible(tool, label=label)


def test_rag_tools_are_bedrock_compatible():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("hello", document_id="d1")
    for tool in rag.as_tools():
        _assert_bedrock_compatible(tool, label=f"rag tool {tool.name}")


def test_delegation_tool_is_bedrock_compatible():
    inner = Agent(llm=SimpleEchoLLM(), name="alpha", description="alpha agent")
    tool = AgentDelegationTool(agents={"alpha": inner})
    _assert_bedrock_compatible(tool, label="delegate_to_agent")


def test_deep_agent_full_toolset_is_bedrock_compatible():
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("hi", document_id="d1")
    agent = DeepAgent.with_builtins(
        llm=SimpleEchoLLM(),
        rag=rag,
        agents={"helper": Agent(llm=SimpleEchoLLM(), name="helper", description="h")},
    )
    for tool in agent.tools:
        _assert_bedrock_compatible(
            tool, label=f"deep tool {getattr(tool, 'name', tool.__class__.__name__)}"
        )


def test_no_tool_schema_has_empty_top_level_keys():
    """The original Bedrock failure was empty top-level name/description."""
    llm = SimpleEchoLLM()
    rag = RAG.default(embedder=HashingEmbedder(dimension=64))
    rag.index_text("hi", document_id="d1")
    agent = DeepAgent.with_builtins(llm=llm, rag=rag)

    for tool in agent.tools:
        schema = tool.schema()
        # No tool should have top-level 'name' or 'description' as empty
        # strings — the wrapper must contain them under 'function'.
        if "name" in schema:
            assert schema["name"], (
                f"{tool.__class__.__name__} has empty top-level 'name' key — "
                "this triggers the Bedrock validation error"
            )
        if "description" in schema:
            assert schema["description"], (
                f"{tool.__class__.__name__} has empty top-level 'description' key"
            )
