import math

import pytest

from shipit_agent.rag.embedder import (
    CallableEmbedder,
    HashingEmbedder,
    coerce_embedder,
    cosine_similarity,
)


def test_hashing_embedder_dimension_consistency():
    emb = HashingEmbedder(dimension=64)
    vectors = emb.embed(["alpha beta", "gamma delta", "alpha beta"])
    assert all(len(v) == 64 for v in vectors)


def test_hashing_embedder_is_deterministic():
    emb = HashingEmbedder(dimension=128)
    v1 = emb.embed(["shipit agent rag"])[0]
    v2 = emb.embed(["shipit agent rag"])[0]
    assert v1 == v2


def test_hashing_embedder_similar_texts_cluster():
    emb = HashingEmbedder(dimension=512)
    a = emb.embed(["python programming language"])[0]
    b = emb.embed(["python is a programming language"])[0]
    c = emb.embed(["sailing across the atlantic ocean"])[0]
    sim_ab = cosine_similarity(a, b)
    sim_ac = cosine_similarity(a, c)
    assert sim_ab > sim_ac


def test_hashing_embedder_empty_text_is_zero():
    emb = HashingEmbedder(dimension=32)
    v = emb.embed([""])[0]
    assert len(v) == 32
    assert all(x == 0.0 for x in v)


def test_hashing_embedder_normalized_unit_length():
    emb = HashingEmbedder(dimension=128)
    v = emb.embed(["shipit"])[0]
    norm = math.sqrt(sum(x * x for x in v))
    assert norm == pytest.approx(1.0, rel=1e-6)


def test_callable_embedder_wraps_function():
    called_with: list[list[str]] = []

    def fn(texts: list[str]) -> list[list[float]]:
        called_with.append(list(texts))
        return [[float(len(t)), 0.0, 0.0] for t in texts]

    emb = CallableEmbedder(fn=fn, dimension=3)
    vectors = emb.embed(["abc", "abcd"])
    assert called_with == [["abc", "abcd"]]
    assert vectors == [[3.0, 0.0, 0.0], [4.0, 0.0, 0.0]]


def test_callable_embedder_rejects_dimension_mismatch():
    def fn(texts):
        return [[0.0, 0.0] for _ in texts]

    emb = CallableEmbedder(fn=fn, dimension=3)
    with pytest.raises(ValueError, match="dim=2"):
        emb.embed(["hi"])


def test_callable_embedder_rejects_length_mismatch():
    def fn(texts):
        return [[0.0, 0.0, 0.0]]

    emb = CallableEmbedder(fn=fn, dimension=3)
    with pytest.raises(ValueError, match="2 inputs"):
        emb.embed(["a", "b"])


def test_coerce_embedder_passthrough():
    hashing = HashingEmbedder(dimension=32)
    assert coerce_embedder(hashing) is hashing


def test_coerce_embedder_wraps_callable():
    def fn(texts):
        return [[1.0, 2.0, 3.0, 4.0] for _ in texts]

    emb = coerce_embedder(fn)
    assert isinstance(emb, CallableEmbedder)
    assert emb.dimension == 4


def test_coerce_embedder_falls_back_for_opaque_object():
    import warnings

    class Opaque:
        pass

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        emb = coerce_embedder(Opaque())
    assert isinstance(emb, HashingEmbedder)
    assert any("HashingEmbedder" in str(w.message) for w in caught)


def test_cosine_similarity_orthogonal_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_identical_is_one():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_zero_vector_returns_zero():
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_similarity_length_mismatch_raises():
    with pytest.raises(ValueError):
        cosine_similarity([1.0], [1.0, 2.0])
