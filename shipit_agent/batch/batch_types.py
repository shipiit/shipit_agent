"""Batch requests and results for the batch runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

# Sensible defaults used when a :class:`BatchRequest` does not specify its own.
DEFAULT_MODEL = "claude-3-5-sonnet-latest"


DEFAULT_MAX_TOKENS = 1024


@dataclass
class BatchRequest:
    """A single request to include in a message batch.

    Attributes:
        custom_id: Caller-provided identifier, echoed back on the matching
            :class:`BatchResult`. Must be unique within a batch.
        prompt: Convenience single-turn user prompt. Used to build a
            ``messages`` payload when ``messages`` is not supplied.
        messages: Explicit list of message dicts (``{"role", "content"}``).
            Takes precedence over ``prompt`` when both are given.
        system: Optional system prompt. Omitted from the payload when ``None``.
        max_tokens: Max output tokens for this request.
        model: Model id for this request.
        metadata: Optional ``metadata`` object forwarded to the API.
    """

    custom_id: str
    prompt: Optional[str] = None
    messages: Optional[List[dict]] = None
    system: Optional[str] = None
    max_tokens: Optional[int] = None
    model: Optional[str] = None
    metadata: Optional[dict] = None

    def to_params(
        self,
        *,
        default_model: str = DEFAULT_MODEL,
        default_max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict:
        """Build the ``params`` block for the Batches ``create`` payload.

        Keys are emitted to match the Messages API ``create`` shape. Optional
        keys (``system``, ``metadata``) are only included when set, so the
        resulting dict mirrors exactly what the SDK expects.
        """
        if self.messages is not None:
            messages = self.messages
        elif self.prompt is not None:
            messages = [{"role": "user", "content": self.prompt}]
        else:
            raise ValueError(
                f"BatchRequest {self.custom_id!r} must set either 'prompt' or 'messages'"
            )

        params: dict[str, Any] = {
            "model": self.model or default_model,
            "max_tokens": self.max_tokens or default_max_tokens,
            "messages": messages,
        }
        if self.system is not None:
            params["system"] = self.system
        if self.metadata is not None:
            params["metadata"] = self.metadata
        return params

    def to_payload(
        self,
        *,
        default_model: str = DEFAULT_MODEL,
        default_max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> dict:
        """Build the full ``{"custom_id", "params"}`` entry for ``create``."""
        return {
            "custom_id": self.custom_id,
            "params": self.to_params(
                default_model=default_model,
                default_max_tokens=default_max_tokens,
            ),
        }


@dataclass
class BatchResult:
    """The outcome of a single batched request.

    Attributes:
        custom_id: The ``custom_id`` of the originating :class:`BatchRequest`.
        output: Concatenated assistant text on success, otherwise ``""``.
        usage: The message ``usage`` object on success, otherwise ``None``.
        error: Human-readable error string for ``errored`` / ``canceled`` /
            ``expired`` results (or a mapping failure), otherwise ``None``.
        result_type: Raw discriminator: ``succeeded`` / ``errored`` /
            ``canceled`` / ``expired``.
        raw: The underlying SDK result object, for callers that need full
            access (stop reason, content blocks, request id, ...).
    """

    custom_id: str
    output: str = ""
    usage: Any = None
    error: Optional[str] = None
    result_type: Optional[str] = None
    raw: Any = None

    @property
    def ok(self) -> bool:
        """True when the request succeeded (no error captured)."""
        return self.error is None and self.result_type == "succeeded"

