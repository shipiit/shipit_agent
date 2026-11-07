"""Parsing and validating a model's output, and asking again with the error when it does not fit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shipit_agent.parsers.base import ParseError
from shipit_agent.parsers.json_parser import JSONParser
from shipit_agent.parsers.pydantic_parser import PydanticParser
from shipit_agent.parsers.streaming_json import parse_partial_json

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
        return (
            None,
            raw_text,
            1,
            [{"text": raw_text, "error": f"unsupported schema type: {type(schema)}"}],
        )

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
