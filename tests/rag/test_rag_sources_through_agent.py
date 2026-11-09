"""Sources and citation numbers through a real Agent run.

The agent loop runs on a worker thread, so anything the RAG tracks per run
must reach that thread; and the [N] a tool shows the model must be the
number the run's rag_sources gives the same chunk.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from shipit_agent.agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.rag.embedder import HashingEmbedder
from shipit_agent.rag.rag import RAG


class _ScriptedLLM:
    model = "scripted"

    def __init__(self, *responses: LLMResponse) -> None:
        self.responses = list(responses)
        self.calls: list[list[Any]] = []

    def complete(self, *, messages: list[Any], **kwargs: Any) -> LLMResponse:
        self.calls.append(messages)
        return self.responses.pop(0)


def _search(query: str, top_k: int = 1) -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(name="rag_search", arguments={"query": query, "top_k": top_k})])


def _rag() -> RAG:
    rag = RAG.default(embedder=HashingEmbedder(dimension=256))
    rag.index_text("Python is a programming language.", document_id="py", source="python.md")
    rag.index_text("Rust is a systems language.", document_id="rs", source="rust.md")
    return rag


def test_run_reports_the_sources_its_tools_retrieved() -> None:
    llm = _ScriptedLLM(_search("python language"), LLMResponse(content="Python. [1]"))

    result = Agent(llm=llm, rag=_rag()).run("What is Python?")

    assert [s.source for s in result.rag_sources] == ["python.md"]


def test_stream_ends_with_the_sources_its_tools_retrieved() -> None:
    llm = _ScriptedLLM(_search("python language"), LLMResponse(content="Python. [1]"))

    events = list(Agent(llm=llm, rag=_rag()).stream("What is Python?"))

    sources = [e for e in events if e.type == "rag_sources"]
    assert len(sources) == 1
    assert [s["source"] for s in sources[0].payload["sources"]] == ["python.md"]


def test_citation_numbers_match_across_searches() -> None:
    llm = _ScriptedLLM(
        _search("python language"),
        _search("rust systems", top_k=2),
        LLMResponse(content="Both. [1][2]"),
    )

    result = Agent(llm=llm, rag=_rag()).run("Python and Rust?")

    shown: dict[str, str] = {}
    for message in llm.calls[-1]:
        if getattr(message, "role", "") != "tool":
            continue
        for hit in json.loads(message.content)["results"]:
            shown.setdefault(hit["chunk_id"], hit["citation"])
    numbers = {s.chunk_id: f"[{s.index}]" for s in result.rag_sources}
    assert shown == numbers
    assert sorted(numbers.values()) == ["[1]", "[2]"]


def test_a_chunk_found_again_keeps_its_first_number() -> None:
    # A different query that finds the same chunk: an identical call would be
    # answered by the runtime's repeat guard instead of running again.
    llm = _ScriptedLLM(_search("python language"), _search("programming python"), LLMResponse(content="Python. [1]"))

    result = Agent(llm=llm, rag=_rag()).run("Python?")

    second = [m for m in llm.calls[-1] if getattr(m, "role", "") == "tool"][-1]
    assert json.loads(second.content)["results"][0]["citation"] == "[1]"
    assert [s.index for s in result.rag_sources] == [1]


def test_concurrent_runs_on_one_rag_keep_their_own_sources() -> None:
    rag = _rag()
    barrier = threading.Barrier(2)
    found: dict[str, list[str]] = {}

    class _Waiting(_ScriptedLLM):
        def complete(self, *, messages: list[Any], **kwargs: Any) -> LLMResponse:
            if len(self.calls) == 1:
                barrier.wait(timeout=10)
            return super().complete(messages=messages, **kwargs)

    def ask(name: str, query: str) -> None:
        llm = _Waiting(_search(query), LLMResponse(content="Ok."))
        found[name] = [s.source for s in Agent(llm=llm, rag=rag).run(query).rag_sources]

    threads = [
        threading.Thread(target=ask, args=("py", "python language")),
        threading.Thread(target=ask, args=("rs", "rust systems")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert found == {"py": ["python.md"], "rs": ["rust.md"]}
