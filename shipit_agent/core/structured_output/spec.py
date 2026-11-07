"""StructuredOutput: the shape a run's answer must take, from a schema, a Pydantic model or examples."""

from __future__ import annotations

import json
from typing import Any, Iterator

from shipit_agent.parsers.base import ParseError
from shipit_agent.parsers.json_parser import JSONParser
from shipit_agent.parsers.pydantic_parser import PydanticParser
from shipit_agent.parsers.streaming_json import parse_partial_json

from .retry import _SENTINEL, _chunk_text, _coerce_to_text, _is_pydantic_model
from .values import StructuredOutputResult


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
    def _initial_messages(
        self, prompt: str, *, system: str | None
    ) -> list[dict[str, Any]]:
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
            raise TypeError(
                "LLM object must have .complete(messages=...) or be callable"
            )
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
