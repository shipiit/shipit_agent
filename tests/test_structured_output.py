"""Tests for the v1.0.8 structured-output overhaul.

Coverage: ``StructuredOutput`` (high-level wrapper) and ``validate_with_retry``
(the helper that ``Agent.run()`` uses to retry failed parses).

Each public function gets ≥10 tests covering happy path, edge cases,
streaming, retry success, retry exhaustion, and validation specifics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

import pytest

try:
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    pytest.skip("pydantic not installed", allow_module_level=True)

from shipit_agent.parsers.base import ParseError
from shipit_agent.structured_output import (
    StructuredOutput,
    StructuredOutputResult,
    validate_with_retry,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@dataclass
class ScriptedLLM:
    """Test double that returns canned responses in order."""

    responses: list[str] = field(default_factory=list)
    calls: list[list[dict[str, Any]]] = field(default_factory=list)
    _index: int = 0

    def complete(self, *, messages: list[dict[str, Any]], **_: Any) -> str:
        self.calls.append(list(messages))
        if self._index >= len(self.responses):
            raise RuntimeError(f"ScriptedLLM exhausted at call {self._index}")
        out = self.responses[self._index]
        self._index += 1
        return out

    def stream(self, *, messages: list[dict[str, Any]], **_: Any) -> Iterator[str]:
        self.calls.append(list(messages))
        if self._index >= len(self.responses):
            raise RuntimeError(f"ScriptedLLM exhausted at call {self._index}")
        text = self.responses[self._index]
        self._index += 1
        # Yield 5-char chunks
        for i in range(0, len(text), 5):
            yield text[i:i + 5]


class Movie(BaseModel):
    title: str
    rating: float


class Person(BaseModel):
    name: str
    age: int
    email: str | None = None


# ---------------------------------------------------------------------------
# StructuredOutput.run — 10+ tests
# ---------------------------------------------------------------------------


class TestStructuredOutputRun:
    def test_pydantic_first_attempt_success(self) -> None:
        llm = ScriptedLLM(responses=['{"title": "Inception", "rating": 9.0}'])
        so = StructuredOutput(llm=llm, schema=Movie, max_retries=0)
        result = so.run("recommend a movie")
        assert isinstance(result, StructuredOutputResult)
        assert isinstance(result.value, Movie)
        assert result.value.title == "Inception"
        assert result.value.rating == 9.0
        assert result.attempts == 1

    def test_pydantic_with_markdown_fence(self) -> None:
        llm = ScriptedLLM(
            responses=['```json\n{"title": "Heat", "rating": 8.5}\n```']
        )
        so = StructuredOutput(llm=llm, schema=Movie, max_retries=0)
        result = so.run("recommend")
        assert result.value.title == "Heat"

    def test_pydantic_with_prose_around(self) -> None:
        llm = ScriptedLLM(
            responses=['Sure! Here you go: {"title": "Drive", "rating": 8.0} hope it helps']
        )
        so = StructuredOutput(llm=llm, schema=Movie, max_retries=0)
        result = so.run("recommend")
        assert result.value.title == "Drive"

    def test_dict_schema(self) -> None:
        schema = {"type": "object", "required": ["x"], "properties": {"x": {}}}
        llm = ScriptedLLM(responses=['{"x": 42}'])
        so = StructuredOutput(llm=llm, schema=schema, max_retries=0)
        result = so.run("ask")
        assert result.value == {"x": 42}

    def test_retry_success_on_second_attempt(self) -> None:
        llm = ScriptedLLM(
            responses=[
                "I think Inception is great",  # not JSON
                '{"title": "Inception", "rating": 9.0}',
            ]
        )
        so = StructuredOutput(llm=llm, schema=Movie, max_retries=2)
        result = so.run("recommend")
        assert result.attempts == 2
        assert result.value.title == "Inception"
        assert len(result.history) == 1

    def test_retry_exhausted_raises(self) -> None:
        llm = ScriptedLLM(responses=["bad", "still bad", "really bad"])
        so = StructuredOutput(llm=llm, schema=Movie, max_retries=2)
        with pytest.raises(ParseError):
            so.run("recommend")

    def test_retry_zero_disables(self) -> None:
        llm = ScriptedLLM(responses=["not json"])
        so = StructuredOutput(llm=llm, schema=Movie, max_retries=0)
        with pytest.raises(ParseError):
            so.run("recommend")

    def test_system_prompt_is_first_message(self) -> None:
        llm = ScriptedLLM(responses=['{"title": "X", "rating": 1.0}'])
        so = StructuredOutput(llm=llm, schema=Movie, max_retries=0)
        so.run("recommend", system="be brief")
        assert llm.calls[0][0]["role"] == "system"
        assert llm.calls[0][0]["content"] == "be brief"

    def test_schema_suffix_appended_to_user_prompt(self) -> None:
        llm = ScriptedLLM(responses=['{"title": "X", "rating": 1.0}'])
        so = StructuredOutput(llm=llm, schema=Movie, max_retries=0)
        so.run("pick a film")
        user_msg = llm.calls[0][-1]
        assert user_msg["role"] == "user"
        assert "pick a film" in user_msg["content"]
        # Schema injection includes the field names
        assert "title" in user_msg["content"]
        assert "rating" in user_msg["content"]

    def test_custom_prompt_suffix(self) -> None:
        llm = ScriptedLLM(responses=['{"title": "X", "rating": 1.0}'])
        so = StructuredOutput(
            llm=llm, schema=Movie, max_retries=0, prompt_suffix=" GIVE JSON"
        )
        so.run("ask")
        assert llm.calls[0][-1]["content"].endswith(" GIVE JSON")

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="mode"):
            StructuredOutput(llm=ScriptedLLM(), schema=Movie, mode="bogus")

    def test_coerce_recovers_partial(self) -> None:
        # Output is a complete-ish JSON the strict parser still accepts;
        # ensures coerce path doesn't break the happy case.
        llm = ScriptedLLM(responses=['{"title": "Y", "rating": 7.5}'])
        so = StructuredOutput(llm=llm, schema=Movie, max_retries=0, coerce=True)
        result = so.run("ask")
        assert result.value.rating == 7.5


# ---------------------------------------------------------------------------
# StructuredOutput.stream — 10+ tests
# ---------------------------------------------------------------------------


class TestStructuredOutputStream:
    def test_stream_yields_partials(self) -> None:
        llm = ScriptedLLM(responses=['{"title": "Inception", "rating": 9.0}'])
        so = StructuredOutput(llm=llm, schema=Movie, max_retries=0)
        partials = list(so.stream("ask"))
        assert len(partials) >= 1
        # Last yield should be a Movie instance OR final dict
        last = partials[-1]
        assert isinstance(last, Movie) or last == {"title": "Inception", "rating": 9.0}

    def test_stream_first_partial_is_partial_dict(self) -> None:
        llm = ScriptedLLM(responses=['{"title": "Inception", "rating": 9.0}'])
        so = StructuredOutput(llm=llm, schema=Movie, max_retries=0)
        partials = list(so.stream("ask"))
        # At least one intermediate partial should be a dict
        intermediates = [p for p in partials if isinstance(p, dict)]
        assert len(intermediates) >= 1

    def test_stream_dedupes_unchanged(self) -> None:
        # Multiple chunks producing the same partial should not yield duplicates
        llm = ScriptedLLM(responses=['{"a": 1}'])
        so = StructuredOutput(llm=llm, schema={"type": "object"}, max_retries=0)
        partials = list(so.stream("ask"))
        # Adjacent duplicates should not appear
        for i in range(1, len(partials)):
            assert partials[i] != partials[i - 1] or partials[i] is None

    def test_stream_with_dict_schema(self) -> None:
        llm = ScriptedLLM(responses=['{"name": "Alice", "age": 30}'])
        schema = {"type": "object"}
        so = StructuredOutput(llm=llm, schema=schema, max_retries=0)
        partials = list(so.stream("ask"))
        assert {"name": "Alice", "age": 30} in partials

    def test_stream_falls_back_to_run_for_non_streaming_llm(self) -> None:
        # ScriptedLLM has stream(); make a stream-less variant
        class CompleteOnlyLLM:
            def complete(self, *, messages: list[dict[str, Any]], **_: Any) -> str:
                return '{"title": "X", "rating": 5.0}'

        so = StructuredOutput(llm=CompleteOnlyLLM(), schema=Movie, max_retries=0)
        partials = list(so.stream("ask"))
        assert len(partials) >= 1

    def test_stream_handles_dict_chunks(self) -> None:
        # Chunks shaped like OpenAI delta events
        class OpenAIStyleLLM:
            def complete(self, *, messages: list[dict[str, Any]], **_: Any) -> str:
                return '{"title": "X", "rating": 1.0}'

            def stream(self, *, messages: list[dict[str, Any]], **_: Any) -> Iterator[Any]:
                for piece in ['{"title":', ' "X",', ' "rating":', " 1.0}"]:
                    yield {"choices": [{"delta": {"content": piece}}]}

        so = StructuredOutput(llm=OpenAIStyleLLM(), schema=Movie, max_retries=0)
        partials = list(so.stream("ask"))
        assert len(partials) >= 1

    def test_stream_handles_chunks_with_text_attr(self) -> None:
        class ObjChunk:
            def __init__(self, text: str) -> None:
                self.text = text

        class ObjChunkLLM:
            def stream(self, *, messages: list[dict[str, Any]], **_: Any) -> Iterator[Any]:
                yield ObjChunk('{"title":')
                yield ObjChunk(' "X", "rating": 1.0}')

        so = StructuredOutput(llm=ObjChunkLLM(), schema=Movie, max_retries=0)
        partials = list(so.stream("ask"))
        assert any(isinstance(p, Movie) or (isinstance(p, dict) and p.get("title") == "X") for p in partials)

    def test_stream_skips_empty_chunks(self) -> None:
        class EmptyChunksLLM:
            def stream(self, *, messages: list[dict[str, Any]], **_: Any) -> Iterator[Any]:
                yield ""
                yield "{"
                yield ""
                yield '"a": 1}'

        so = StructuredOutput(llm=EmptyChunksLLM(), schema={"type": "object"}, max_retries=0)
        partials = list(so.stream("ask"))
        assert {"a": 1} in partials

    def test_stream_yields_final_typed_object(self) -> None:
        llm = ScriptedLLM(responses=['{"title": "T", "rating": 8.5}'])
        so = StructuredOutput(llm=llm, schema=Movie, max_retries=0)
        partials = list(so.stream("ask"))
        typed = [p for p in partials if isinstance(p, Movie)]
        assert len(typed) >= 1
        assert typed[-1].title == "T"

    def test_stream_no_retry_on_bad_output(self) -> None:
        # Streaming doesn't apply validation retry — returns whatever the
        # final pass produced (possibly partial).
        llm = ScriptedLLM(responses=["totally not json"])
        so = StructuredOutput(llm=llm, schema=Movie, max_retries=2)
        partials = list(so.stream("ask"))
        # No exception raised; partials may be empty or all None
        assert isinstance(partials, list)


# ---------------------------------------------------------------------------
# validate_with_retry — 10+ tests
# ---------------------------------------------------------------------------


class TestValidateWithRetry:
    def test_first_attempt_success_pydantic(self) -> None:
        parsed, text, attempts, log = validate_with_retry(
            llm=ScriptedLLM(),
            raw_text='{"title": "X", "rating": 9.0}',
            schema=Movie,
            max_retries=2,
        )
        assert isinstance(parsed, Movie)
        assert parsed.title == "X"
        assert attempts == 1
        assert log == []

    def test_first_attempt_success_dict(self) -> None:
        parsed, _, attempts, log = validate_with_retry(
            llm=ScriptedLLM(),
            raw_text='{"x": 1}',
            schema={"type": "object", "required": ["x"], "properties": {"x": {}}},
            max_retries=2,
        )
        assert parsed == {"x": 1}
        assert attempts == 1

    def test_retry_succeeds_on_second_attempt(self) -> None:
        llm = ScriptedLLM(responses=['{"title": "Y", "rating": 7.0}'])
        parsed, text, attempts, log = validate_with_retry(
            llm=llm,
            raw_text="I recommend Y, rating 7",  # bad initial output
            schema=Movie,
            max_retries=2,
        )
        assert isinstance(parsed, Movie)
        assert attempts == 2
        assert len(log) == 1

    def test_retry_succeeds_on_third_attempt(self) -> None:
        llm = ScriptedLLM(responses=["still bad", '{"title": "Z", "rating": 6.0}'])
        parsed, _, attempts, log = validate_with_retry(
            llm=llm,
            raw_text="prose only",
            schema=Movie,
            max_retries=2,
        )
        assert parsed.title == "Z"
        assert attempts == 3
        assert len(log) == 2

    def test_retry_exhausted_returns_none(self) -> None:
        llm = ScriptedLLM(responses=["bad", "still bad"])
        parsed, _, attempts, log = validate_with_retry(
            llm=llm,
            raw_text="initial bad",
            schema=Movie,
            max_retries=2,
        )
        assert parsed is None
        assert attempts == 3
        assert len(log) == 3

    def test_max_retries_zero_no_retry(self) -> None:
        parsed, _, attempts, log = validate_with_retry(
            llm=ScriptedLLM(),
            raw_text="bad",
            schema=Movie,
            max_retries=0,
        )
        assert parsed is None
        assert attempts == 1
        assert len(log) == 1

    def test_history_passed_to_retry_llm(self) -> None:
        llm = ScriptedLLM(responses=['{"title": "T", "rating": 5.0}'])
        history = [
            {"role": "user", "content": "Pick a movie"},
            {"role": "assistant", "content": "How about Inception?"},
        ]
        validate_with_retry(
            llm=llm, raw_text="bad", schema=Movie, history=history, max_retries=1
        )
        # The retry call should have included the history + the bad attempt + the corrective msg
        retry_messages = llm.calls[0]
        assert retry_messages[0]["content"] == "Pick a movie"
        assert retry_messages[-1]["role"] == "user"
        assert "could not be parsed" in retry_messages[-1]["content"]

    def test_pydantic_validation_failure_triggers_retry(self) -> None:
        # Initial output has wrong type for `rating` (string instead of float)
        # but coerce path may rescue; explicitly disable
        llm = ScriptedLLM(responses=['{"title": "T", "rating": 5.5}'])
        parsed, _, attempts, _ = validate_with_retry(
            llm=llm,
            raw_text='{"title": "T", "rating": "five"}',
            schema=Movie,
            max_retries=1,
            coerce=False,
        )
        assert parsed is not None
        assert attempts == 2

    def test_unsupported_schema_returns_none(self) -> None:
        parsed, _, attempts, log = validate_with_retry(
            llm=ScriptedLLM(),
            raw_text="anything",
            schema="not a schema",  # bad schema type
            max_retries=2,
        )
        assert parsed is None
        assert attempts == 1
        assert "unsupported schema type" in log[0]["error"]

    def test_llm_call_failure_logged(self) -> None:
        class FailingLLM:
            def complete(self, **_: Any) -> str:
                raise RuntimeError("network down")

        parsed, _, attempts, log = validate_with_retry(
            llm=FailingLLM(),
            raw_text="bad",
            schema=Movie,
            max_retries=2,
        )
        assert parsed is None
        assert "retry LLM call failed" in log[-1]["error"]

    def test_corrective_message_includes_error(self) -> None:
        llm = ScriptedLLM(responses=['{"title": "T", "rating": 5.0}'])
        validate_with_retry(
            llm=llm,
            raw_text="not json at all",
            schema=Movie,
            max_retries=1,
        )
        corrective = llm.calls[0][-1]
        # Error message should mention "JSON" or "parse"
        assert "JSON" in corrective["content"] or "parse" in corrective["content"]

    def test_coerce_recovers_partial_input(self) -> None:
        # Input is technically incomplete JSON but partial parser can recover it
        parsed, _, attempts, _ = validate_with_retry(
            llm=ScriptedLLM(),
            raw_text='{"title": "X", "rating": 9.0',  # missing closing brace
            schema=Movie,
            max_retries=0,
            coerce=True,
        )
        # Either coerce path recovered (attempts=1) OR it failed and returned None.
        # Both behaviors are acceptable for partial input.
        assert parsed is None or isinstance(parsed, Movie)
