"""Memory stores find facts by their words, not only by the exact query text.

The model searches memory with natural phrases ("deploy region"); a fact that
says "deploys from the eu-west-1 region" must be found.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shipit_agent.stores.memory import FileMemoryStore, InMemoryMemoryStore, MemoryFact

FACTS = [
    "Ada deploys from the eu-west-1 region.",
    "Ada prefers answers formatted as bullet lists.",
    "The billing service is written in Go.",
]


@pytest.fixture(params=["memory", "file"])
def store(request, tmp_path: Path):
    s = InMemoryMemoryStore() if request.param == "memory" else FileMemoryStore(tmp_path / "m.json")
    for text in FACTS:
        s.add(MemoryFact(content=text))
    return s


def contents(facts: list[MemoryFact]) -> list[str]:
    return [f.content for f in facts]


def test_a_multi_word_query_finds_facts_by_their_words(store) -> None:
    assert contents(store.search("deploy region")) == [FACTS[0]]


def test_a_natural_question_finds_the_fact(store) -> None:
    assert contents(store.search("Which region do I deploy from?"))[0] == FACTS[0]


def test_the_exact_phrase_still_matches_first(store) -> None:
    assert contents(store.search("bullet lists"))[0] == FACTS[1]


def test_facts_matching_more_words_rank_higher(store) -> None:
    found = contents(store.search("Ada answers region"))
    assert set(found[:2]) == {FACTS[0], FACTS[1]}
    assert FACTS[2] not in found


def test_nothing_matches_an_unrelated_query(store) -> None:
    assert store.search("kubernetes autoscaling") == []


def test_stopwords_alone_match_nothing(store) -> None:
    assert store.search("what is the") == []


def test_an_empty_query_returns_facts_up_to_the_limit(store) -> None:
    assert len(store.search("", limit=2)) == 2


def test_limit_caps_the_results(store) -> None:
    assert len(store.search("Ada", limit=1)) == 1
