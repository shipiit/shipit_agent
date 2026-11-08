"""GitHub REST plumbing: base URL, requests and error output."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError

from shipit_agent.integrations import CredentialRecord
from shipit_agent.tools.base import ToolOutput

from .constants import (
    _DEFAULT_AUTH_SCHEME,
    _DEFAULT_BASE_URL,
)


class _GitHubHTTP:
    """GitHub REST plumbing: base URL, requests and error output."""

    def _ensure_base_url(self, record: CredentialRecord) -> CredentialRecord:
        """Default base_url to api.github.com and auth_scheme to Bearer."""
        if record is None:
            return record
        metadata = dict(record.metadata or {})
        if not metadata.get("base_url") and not (record.secrets or {}).get("base_url"):
            metadata["base_url"] = _DEFAULT_BASE_URL
        if not metadata.get("auth_scheme"):
            metadata["auth_scheme"] = _DEFAULT_AUTH_SCHEME
        record.metadata = metadata
        return record

    def _request_or_error(
        self,
        *,
        record: CredentialRecord,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> tuple[Any, ToolOutput | None]:
        """Call _request_json; return (payload, None) on success, (None, error_out) on failure."""
        try:
            payload = self._request_json(
                record=record, method=method, path=path, query=query, body=body
            )
            return payload, None
        except HTTPError as err:
            return None, self._http_error_output(err)
        except Exception as err:  # pragma: no cover - defensive
            return None, ToolOutput(
                text=f"GitHub request failed: {err}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "request_failed",
                    "message": str(err),
                },
            )

    def _http_error_output(self, err: HTTPError) -> ToolOutput:
        headers = getattr(err, "headers", None)
        remaining = None
        reset = None
        if headers is not None:
            try:
                remaining = headers.get("X-RateLimit-Remaining")
                reset = headers.get("X-RateLimit-Reset")
            except Exception:  # pragma: no cover - defensive
                remaining = None
                reset = None
        if err.code == 403 and remaining is not None and str(remaining) == "0":
            retry_after_epoch = 0
            try:
                retry_after_epoch = int(reset) if reset is not None else 0
            except (TypeError, ValueError):
                retry_after_epoch = 0
            return ToolOutput(
                text=(
                    "GitHub rate limit exceeded. Retry after epoch "
                    f"{retry_after_epoch}."
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "error": "rate_limited",
                    "retry_after_epoch": retry_after_epoch,
                    "status": 403,
                },
            )

        message = self._extract_error_message(err)
        return ToolOutput(
            text=f"GitHub HTTP {err.code}: {message}",
            metadata={
                "provider": self.provider,
                "connected": True,
                "error": "http_error",
                "status": int(err.code),
                "message": message,
            },
        )

    @staticmethod
    def _extract_error_message(err: HTTPError) -> str:
        try:
            raw = err.read()
            if raw:
                parsed = json.loads(raw.decode("utf-8", errors="replace"))
                msg = parsed.get("message")
                if isinstance(msg, str) and msg:
                    return msg
        except Exception:
            pass
        reason = getattr(err, "reason", None)
        return str(reason) if reason else "unknown_error"

    @staticmethod
    def _require(kwargs: dict[str, Any], *names: str) -> tuple[dict[str, Any], ToolOutput | None]:
        missing = [n for n in names if not str(kwargs.get(n, "")).strip()]
        if missing:
            return {}, ToolOutput(
                text=f"GitHub: missing required parameter(s) {', '.join(missing)}.",
                metadata={
                    "provider": "github",
                    "error": "missing_parameter",
                    "missing": missing,
                },
            )
        return {n: kwargs.get(n) for n in names}, None
