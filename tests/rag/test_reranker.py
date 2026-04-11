from dataclasses import dataclass
from typing import Any

from shipit_agent.rag.reranker import LLMReranker, _parse_scores
from shipit_agent.rag.types import Chunk


@dataclass
class _FakeResponse:
    content: str


class _FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[Any] = []

    def complete(self, messages):
        self.calls.append(messages)
        return _FakeResponse(content=self._responses.pop(0))


def _chunk(cid: str, text: str) -> Chunk:
    return Chunk(id=cid, document_id="d1", chunk_index=0, text=text)


def test_parse_scores_extracts_json_list():
    assert _parse_scores("[10, 5, 0]", 3) == [10.0, 5.0, 0.0]


def test_parse_scores_handles_reasoning_tags():
    text = "<think>I will score carefully.</think>\nHere: [7, 2]"
    assert _parse_scores(text, 2) == [7.0, 2.0]


def test_parse_scores_pads_short_lists():
    assert _parse_scores("[8]", 3) == [8.0, 0.0, 0.0]


def test_parse_scores_trims_long_lists():
    assert _parse_scores("[1, 2, 3, 4]", 2) == [1.0, 2.0]


def test_parse_scores_fallback_on_garbage():
    assert _parse_scores("I cannot answer", 3) == [0.0, 0.0, 0.0]


def test_llm_reranker_orders_by_score():
    llm = _FakeLLM(responses=["[9, 3, 7]"])
    reranker = LLMReranker(llm=llm)
    chunks = [
        _chunk("a", "alpha"),
        _chunk("b", "beta"),
        _chunk("c", "gamma"),
    ]
    results = reranker.rerank("query", chunks, top_k=3)
    assert [c.id for c, _ in results] == ["a", "c", "b"]
    # Scores normalised to 0..1
    assert results[0][1] == 0.9
    assert results[1][1] == 0.7


def test_llm_reranker_respects_top_k():
    llm = _FakeLLM(responses=["[9, 3, 7]"])
    reranker = LLMReranker(llm=llm)
    chunks = [_chunk("a", "x"), _chunk("b", "y"), _chunk("c", "z")]
    results = reranker.rerank("query", chunks, top_k=2)
    assert len(results) == 2
    assert results[0][0].id == "a"


def test_llm_reranker_batches_requests():
    llm = _FakeLLM(responses=["[5, 5]", "[9]"])
    reranker = LLMReranker(llm=llm, batch_size=2)
    chunks = [_chunk(f"c{i}", f"t{i}") for i in range(3)]
    reranker.rerank("query", chunks, top_k=3)
    assert len(llm.calls) == 2


def test_llm_reranker_empty_chunks():
    llm = _FakeLLM(responses=[])
    reranker = LLMReranker(llm=llm)
    assert reranker.rerank("q", [], top_k=5) == []
