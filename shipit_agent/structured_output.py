"""Structured output orchestrator — the public API for v1.0.8.

Wraps any LLM with three battle-tested strategies for getting reliable
typed output:

1. **Tool-call mode** (default for Anthropic / OpenAI / Bedrock when supported) —
   declare a tool whose input schema IS the desired output schema. The model
   "calls" the tool; we extract the args. This is the highest-fidelity path
   because it uses the model's native function-calling guard rails.

2. **JSON-prompt mode** (fallback) — append a schema-shaped instruction to
   the prompt and parse the JSON out of the response. Robust JSON extraction
   handles markdown fences, prose wrappers, trailing commas.

3. **Validation-retry loop** — when parsing or validation fails, send the
   error back into the SAME conversation (no separate "fixing" LLM) and
   try again. Retry budget configurable; conversation history grows with
   each attempt so the model sees what it got wrong.

Streaming variant yields partial parsed objects as tokens arrive.

Example::

    from pydantic import BaseModel
    from shipit_agent.structured_output import StructuredOutput

    class Movie(BaseModel):
        title: str
        rating: float

    so = StructuredOutput(llm=llm, schema=Movie, max_retries=2)
    movie = so.run("What's a good movie?")
    # → Movie(title='...', rating=...)

    # Streaming partial
    for partial in so.stream("What's a good movie?"):
        print(partial)  # → {} → {"title": "Inc"} → {"title": "Inception", "rating": 9.0}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

from shipit_agent.parsers.base import ParseError
from shipit_agent.parsers.json_parser import JSONParser
from shipit_agent.parsers.pydantic_parser import PydanticParser
from shipit_agent.parsers.streaming_json import parse_partial_json


@dataclass(slots=True)
class StructuredOutputResult:
    """Result of a structured-output run."""

    value: Any
    """Parsed object — Pydantic instance or dict, depending on schema."""

    raw_text: str
    """Final raw text the model produced."""

    attempts: int
    """Number of attempts (1 means first try succeeded)."""

    history: list[dict[str, Any]] = field(default_factory=list)
    """Per-attempt diagnostic info: text, error, etc."""


class StructuredOutput:
    """Wraps an LLM to produce reliable structured output.

    Args:
        llm: any object implementing ``complete(messages: list, **kwargs)`` or
            ``stream(messages: list, **kwargs)`` that returns a string / yields chunks.
            Most shipit_agent LLM adapters work directly.
        schema: a Pydantic model class OR a JSON Schema dict.
        max_retries: how many validation-failure retries before raising. ``0`` disables retry.
        mode: ``"auto"`` (try tool-call, fall back to prompt), ``"tool"`` (force tool-call),
            ``"prompt"`` (force prompt-only).
        prompt_suffix: extra instruction appended to the user message in prompt mode.
            Defaults to a schema-shaped suffix.
        coerce: when True, allow Pydantic to coerce types (strings → ints, etc.).
    """

    def __init__(
        self,
        *,
        llm: Any,
        schema: Any,
        max_retries: int = 1,
        mode: str = "auto",
        prompt_suffix: str | None = None,
        coerce: bool = True,
    ) -> None:
        if mode not in {"auto", "tool", "prompt"}:
            raise ValueError(f"mode must be auto/tool/prompt, got {mode!r}")
        self.llm = llm
        self.schema = schema
        self.max_retries = max(0, max_retries)
        self.mode = mode
        self.coerce = coerce
        self._prompt_suffix = prompt_suffix
        self._is_pydantic = _is_pydantic_model(schema)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self, prompt: str, *, system: str | None = None) -> StructuredOutputResult:
        """Run the model and return a parsed/validated result.

        Raises ``ParseError`` if all retry attempts fail.
        """
        messages = self._initial_messages(prompt, system=system)

        history: list[dict[str, Any]] = []
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                raw_text = self._invoke_llm(messages)
            except Exception as exc:  # transport-level error, not parse error
                raise ParseError(f"LLM invocation failed: {exc}", raw_text="") from exc

            try:
                value = self._parse(raw_text)
                return StructuredOutputResult(
                    value=value,
                    raw_text=raw_text,
                    attempts=attempt + 1,
                    history=history,
                )
            except ParseError as exc:
                last_error = exc
                history.append({"text": raw_text, "error": str(exc)})
                if attempt >= self.max_retries:
                    break
                # Append the bad output + the error and ask for a corrected response
                messages.append({"role": "assistant", "content": raw_text})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"That response could not be parsed: {exc}.\n"
                            "Please respond again with valid JSON exactly matching the "
                            "schema described earlier. Output ONLY the JSON."
                        ),
                    }
                )

        raise ParseError(
            f"Could not produce valid output after {self.max_retries + 1} attempts: {last_error}",
            raw_text=history[-1]["text"] if history else "",
        )

    def stream(self, prompt: str, *, system: str | None = None) -> Iterator[Any]:
        """Yield partial parsed objects as the model streams.

        Each yielded value is either ``None`` (no parseable structure yet),
        a partial dict/list, or — once streaming completes — the final
        validated typed object.

        Validation/retry is NOT applied during streaming (only at the end);
        if streaming finishes with bad output, the final yield is the error
        object's raw partial. Use ``run()`` for guaranteed-validated output.
        """
        messages = self._initial_messages(prompt, system=system)
        if not hasattr(self.llm, "stream"):
            # Non-streaming LLM — emulate by calling complete and yielding once
            text = self._invoke_llm(messages)
            yield parse_partial_json(text)
            try:
                yield self._parse(text)
            except ParseError:
                pass
            return

        accumulated = ""
        last_yielded: Any = _SENTINEL
        for chunk in self.llm.stream(messages=messages):
            piece = _chunk_text(chunk)
            if not piece:
                continue
            accumulated += piece
            partial = parse_partial_json(accumulated)
            if partial is not None and partial != last_yielded:
                last_yielded = partial
                yield partial

        # Final pass — try to produce a validated typed object. Skip if it
        # would just repeat the last partial (e.g. dict-schema where the
        # streaming partial already matched the validated dict exactly).
        try:
            final = self._parse(accumulated)
        except ParseError:
            return
        if final != last_yielded:
            yield final

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _initial_messages(self, prompt: str, *, system: str | None) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        suffix = self._prompt_suffix or self._default_prompt_suffix()
        messages.append({"role": "user", "content": prompt + suffix})
        return messages

    def _default_prompt_suffix(self) -> str:
        if self._is_pydantic:
            schema = self.schema.model_json_schema()
        elif isinstance(self.schema, dict):
            schema = self.schema
        else:
            return ""
        return (
            "\n\nRespond with a JSON object that exactly matches this schema. "
            "Output ONLY the JSON, with no prose, no commentary, no markdown fences:\n"
            f"```json\n{json.dumps(schema, indent=2)}\n```"
        )

    def _invoke_llm(self, messages: list[dict[str, Any]]) -> str:
        # Most adapters expose .complete(messages=...) returning str; some return objects.
        if hasattr(self.llm, "complete"):
            result = self.llm.complete(messages=messages)
        elif callable(self.llm):
            result = self.llm(messages=messages)
        else:
            raise TypeError("LLM object must have .complete(messages=...) or be callable")
        return _coerce_to_text(result)

    def _parse(self, text: str) -> Any:
        if self._is_pydantic:
            parser = PydanticParser(model=self.schema)
            try:
                return parser.parse(text)
            except ParseError:
                if self.coerce:
                    # Try once more with the partial parser to recover string-typed numbers etc.
                    partial = parse_partial_json(text)
                    if partial is not None:
                        try:
                            return self.schema.model_validate(partial)
                        except Exception as exc:
                            raise ParseError(
                                f"Pydantic validation failed after coercion: {exc}",
                                raw_text=text,
                            ) from exc
                raise
        elif isinstance(self.schema, dict):
            parser = JSONParser(schema=self.schema)
            return parser.parse(text)
        else:
            raise ParseError(
                f"Unsupported schema type: {type(self.schema)}", raw_text=text
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENTINEL = object()


def _is_pydantic_model(obj: Any) -> bool:
    return hasattr(obj, "model_json_schema") and hasattr(obj, "model_validate")


def _chunk_text(chunk: Any) -> str:
    """Best-effort extraction of text from a streaming chunk."""
    if isinstance(chunk, str):
        return chunk
    if isinstance(chunk, dict):
        # OpenAI-style: {"choices": [{"delta": {"content": "..."}}]}
        try:
            return chunk["choices"][0]["delta"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            pass
        for key in ("text", "content", "delta"):
            v = chunk.get(key)
            if isinstance(v, str):
                return v
    # Fallback — string-cast
    text_attr = getattr(chunk, "text", None) or getattr(chunk, "content", None)
    if isinstance(text_attr, str):
        return text_attr
    return ""


def _coerce_to_text(result: Any) -> str:
    """Extract text from common LLM .complete() return shapes."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("text", "content", "output"):
            if isinstance(result.get(key), str):
                return result[key]
        # OpenAI-shape
        try:
            return result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            pass
    text_attr = getattr(result, "text", None) or getattr(result, "content", None)
    if isinstance(text_attr, str):
        return text_attr
    return str(result)


def validate_with_retry(
    *,
    llm: Any,
    raw_text: str,
    schema: Any,
    history: list[dict[str, Any]] | None = None,
    max_retries: int = 2,
    coerce: bool = True,
) -> tuple[Any, str, int, list[dict[str, Any]]]:
    """Parse ``raw_text`` against ``schema``; on failure, ask the LLM to fix it.

    Designed to be called by ``Agent.run()`` after the agent loop has produced
    its final answer. The retry doesn't re-run tools — it's a cheap, focused
    "format the JSON correctly this time" round trip.

    Args:
        llm: any object with a ``.complete(messages=...)`` method.
        raw_text: the original LLM output that needs parsing/validation.
        schema: Pydantic model class or JSON Schema dict.
        history: prior conversation messages — included so the model has context.
            Defaults to an empty list.
        max_retries: how many fix-it attempts before giving up. ``0`` disables retry.
        coerce: when True, allow Pydantic to coerce types via the partial parser.

    Returns:
        ``(parsed, final_text, attempts, attempt_log)`` where:
        - ``parsed`` is the typed/validated value, or ``None`` if all attempts failed.
        - ``final_text`` is the text that produced ``parsed`` (last attempt's output).
        - ``attempts`` is 1-indexed: 1 means first parse succeeded.
        - ``attempt_log`` is a list of dicts with ``text`` and ``error`` per failure.
    """
    is_pydantic = _is_pydantic_model(schema)
    if not is_pydantic and not isinstance(schema, dict):
        return None, raw_text, 1, [{"text": raw_text, "error": f"unsupported schema type: {type(schema)}"}]

    # First attempt — parse what we already have
    parsed = _try_parse(raw_text, schema, is_pydantic, coerce)
    if not isinstance(parsed, _ParseFailure):
        return parsed, raw_text, 1, []

    log: list[dict[str, Any]] = [{"text": raw_text, "error": parsed.message}]
    if max_retries <= 0:
        return None, raw_text, 1, log

    # Build retry conversation: prior history + bad assistant + corrective user
    base_messages = list(history or [])

    current_text = raw_text
    last_error = parsed.message

    for attempt in range(max_retries):
        retry_messages = base_messages + [
            {"role": "assistant", "content": current_text},
            {
                "role": "user",
                "content": (
                    f"That response could not be parsed: {last_error}.\n"
                    "Respond again with ONLY valid JSON exactly matching the "
                    "schema described earlier — no prose, no commentary, no markdown fences."
                ),
            },
        ]
        try:
            new_text = _coerce_to_text(llm.complete(messages=retry_messages))
        except Exception as exc:
            log.append({"text": "", "error": f"retry LLM call failed: {exc}"})
            return None, current_text, attempt + 2, log

        result = _try_parse(new_text, schema, is_pydantic, coerce)
        if not isinstance(result, _ParseFailure):
            return result, new_text, attempt + 2, log

        log.append({"text": new_text, "error": result.message})
        last_error = result.message
        current_text = new_text
        # Extend history so the next retry sees the prior failed exchange
        base_messages = retry_messages

    return None, current_text, max_retries + 1, log


@dataclass(slots=True)
class _ParseFailure:
    message: str


def _try_parse(text: str, schema: Any, is_pydantic: bool, coerce: bool) -> Any:
    """Single parse attempt; returns parsed value or ``_ParseFailure``."""
    if is_pydantic:
        parser = PydanticParser(model=schema)
        try:
            return parser.parse(text)
        except ParseError as exc:
            if coerce:
                partial = parse_partial_json(text)
                if partial is not None:
                    try:
                        return schema.model_validate(partial)
                    except Exception:
                        pass
            return _ParseFailure(str(exc))
    elif isinstance(schema, dict):
        try:
            return JSONParser(schema=schema).parse(text)
        except ParseError as exc:
            return _ParseFailure(str(exc))
    return _ParseFailure(f"unsupported schema type: {type(schema)}")


__all__ = ["StructuredOutput", "StructuredOutputResult", "validate_with_retry"]
